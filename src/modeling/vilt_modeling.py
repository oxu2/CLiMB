import os
import sys
import logging
import itertools
import pdb
import numpy as np
import torch
import time
import torch.nn as nn
import torch.nn.functional as F

from transformers import BertConfig, BertTokenizer, BertModel
from transformers import ViltConfig, ViltProcessor, ViltModel
from transformers import BertTokenizerFast

logger = logging.getLogger(__name__)
logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        datefmt='%m/%d/%Y %H:%M:%S',
        level=logging.INFO)

def debug(processor, encodings, n=4):
    from torchvision.utils import save_image
    def denorm(x):
        """Convert the range from [-1, 1] to [0, 1]."""
        out = (x + 1) / 2
        return out.clamp_(0, 1)

    imgs = denorm(encodings['pixel_values'][: n*2].cpu())
    texts = processor.batch_decode(encodings['input_ids'][:n])
    save_image(imgs, 'debug_img.png', nrow=2, padding=0)
    print(texts)
    pdb.set_trace()


class ViltEncoderWrapper(nn.Module):

    def __init__(self, processor, vilt, device):
        '''
        Wrapper around Vilt model from huggingface library
        this is the class that gets saved during checkpointing for continual learning
        '''

        super().__init__()
        self.processor = processor
        self.vilt = vilt
        self.device = device
        self.processor.tokenizer = BertTokenizerFast.from_pretrained("bert-base-uncased")
        self.max_text_length = self.vilt.config.max_position_embeddings
        self.encoder_dim = self.vilt.config.hidden_size

    def reset_processor(self, max_text_length, img_size):
        self.max_text_length = max_text_length
        self.processor.feature_extractor.size = img_size

    def reallocate_text_image(self, pretrained_pos_emb, max_len, img_size):
        vilt_config = self.vilt.config
        assert max_len % vilt_config.max_position_embeddings == 0

        self.reset_processor(max_len, img_size)

        # copy the pretrained positional embeddings to support texts with longer max_len 
        extended_pos_emb = torch.cat([pretrained_pos_emb \
            for _ in range(0, max_len, vilt_config.max_position_embeddings)], 0)
        # extend & re-init Embedding
        self.vilt.embeddings.text_embeddings.position_embeddings = \
            nn.Embedding(max_len, vilt_config.hidden_size).from_pretrained(extended_pos_emb, freeze=False)

        # extend self.position_ids
        # https://github.com/huggingface/transformers/blob/main/src/transformers/models/vilt/modeling_vilt.py#L274
        self.vilt.embeddings.text_embeddings.\
            register_buffer("position_ids", torch.arange(max_len).expand((1, -1)))

    def process_inputs(self, images, texts):
        encodings = self.processor(images=images, text=texts, max_length=self.max_text_length,
            padding=True, truncation=True, return_tensors='pt').to(self.device)

        #debug(self.processor, encodings)
        return encodings

    def expand_modality_type_embeddings(self, type_vocab_size=3):
        self.vilt.config.modality_type_vocab_size = type_vocab_size
        #https://github.com/dandelin/ViLT/blob/762fd3975c180db6fc88f577cf39549983fa373a/vilt/modules/vilt_module.py#L85
        emb_data = self.vilt.embeddings.token_type_embeddings.weight.data
        self.vilt.embeddings.token_type_embeddings = nn.Embedding(type_vocab_size, self.encoder_dim)
        self.vilt.embeddings.token_type_embeddings.weight.data[0, :] = emb_data[0, :]
        self.vilt.embeddings.token_type_embeddings.weight.data[1, :] = emb_data[1, :]
        self.vilt.embeddings.token_type_embeddings.weight.data[2, :] = emb_data[1, :]

    def forward(self, **encodings):

        output = self.vilt(**encodings)
        return output.pooler_output


class ViltContinualLearner(nn.Module):

    def __init__(self, ordered_cl_tasks, encoder, encoder_dim, task_configs):

        '''
        encoder - instance of ViltEncoderWrapper class
        encoder_dim - output dimension of vilt encoder
        num_labels - number of labels for classification task
        '''

        super().__init__()
        self.encoder_dim = encoder_dim
        self.vilt_encoder = encoder
        self.ordered_cl_tasks = ordered_cl_tasks
        self.task_configs = task_configs

        self.task_layer_dict = {}
        for task_key in ordered_cl_tasks:
            self.add_task_layer(task_key, task_configs[task_key])
        self.task_layer = nn.ModuleDict(self.task_layer_dict)

        if 'nlvr2' in ordered_cl_tasks:
            self.vilt_encoder.expand_modality_type_embeddings()

    def add_task_layer(self, task_key, task_config):

        num_images = task_config['num_images']
        num_labels = task_config['num_labels']
        if task_config['model_type'] == 'classification':
            clf_layer = nn.Sequential(
                            nn.Linear(self.encoder_dim*num_images, self.encoder_dim*2),
                            nn.LayerNorm(self.encoder_dim*2),
                            nn.GELU(),
                            nn.Linear(self.encoder_dim*2, num_labels)
                        )
            self.task_layer_dict[task_key] = clf_layer

    def forward(self, task_key, images, texts):

        if self.task_configs[task_key]['num_images'] == 1:
            return self.forward_single_image(task_key, images, texts)
        else:
            return self.forward_multi_images(task_key, images, texts, self.task_configs[task_key]['num_images'])

    def forward_single_image(self, task_key, images, texts):

        encodings = self.vilt_encoder.process_inputs(images, texts)

        encoder_output = self.vilt_encoder(**encodings)

        output_logits = self.task_layer[task_key](encoder_output)
        return encoder_output, output_logits

    def forward_multi_images(self, task_key, images, texts, num_images=2):

        flat_images_list = list(itertools.chain(*images))
        encodings = self.vilt_encoder.process_inputs(flat_images_list, texts)

        input_ids, attention_mask, token_type_ids = \
            encodings['input_ids'], encodings['attention_mask'], encodings['token_type_ids']
        # reshape
        bs = len(input_ids)
        pixel_values = encodings['pixel_values'].view(bs, num_images, *encodings["pixel_values"].shape[-3:])
        pixel_mask = encodings['pixel_mask'].view(bs, num_images, *encodings["pixel_mask"].shape[-2:])

        # https://github.com/huggingface/transformers/blob/v4.16.2/src/transformers/models/vilt/modeling_vilt.py#L1351
        pooler_outputs = []
        for i in range(num_images):
            # forward every image through the model
            encodings = {
                'input_ids': input_ids,
                'attention_mask': attention_mask,
                'token_type_ids': token_type_ids,
                'pixel_values': pixel_values[:, i, :, :, :],
                'pixel_mask': pixel_mask[:, i, :, :],
                'image_token_type_idx': i + 1,
            }
            pooled_out = self.vilt_encoder(**encodings)
            pooler_outputs.append(pooled_out)
        pooled_output = torch.cat(pooler_outputs, dim=-1) # [bs, 1536]

        output_logits = self.task_layer[task_key](pooled_output)
        return pooled_output, output_logits


    def get_encoder(self):

        return self.vilt_encoder


class ViltForImageClassification(nn.Module):

    def __init__(self, encoder, encoder_dim, num_labels):

        super().__init__()
        self.encoder_dim = encoder_dim
        self.vilt_encoder = encoder
        self.clf_layer = nn.Sequential(
                            nn.Linear(encoder_dim, encoder_dim*2),
                            nn.LayerNorm(encoder_dim*2),
                            nn.GELU(),
                            nn.Linear(encoder_dim*2, num_labels)
                        )

    def forward(self, images, texts):
        encodings = self.vilt_encoder.process_inputs(images, texts)
        encoder_output = self.vilt_encoder(**encodings)

        output_logits = self.clf_layer(encoder_output)
        return output_logits


class ViltForSequenceClassification(nn.Module):

    def __init__(self, encoder, encoder_dim, num_labels):

        super().__init__()
        self.encoder_dim = encoder_dim
        self.vilt_encoder = encoder
        self.clf_layer = nn.Sequential(
                            nn.Linear(encoder_dim, encoder_dim*2),
                            nn.LayerNorm(encoder_dim*2),
                            nn.GELU(),
                            nn.Linear(encoder_dim*2, num_labels)
                        )


    def forward(self, images, texts):

        encodings = self.vilt_encoder.process_inputs(images, texts)
        # expand to batch size
        bs = len(encodings['input_ids'])
        encodings['pixel_values'] = encodings['pixel_values'].expand([bs, *encodings['pixel_values'].shape[1:]])
        encodings['pixel_mask'] = encodings['pixel_mask'].expand([bs, *encodings['pixel_mask'].shape[1:]])
        encoder_output = self.vilt_encoder(**encodings)

        output_logits = self.clf_layer(encoder_output)
        return output_logits


class ViltBertForSequenceClassification(nn.Module):

    def __init__(self, encoder, encoder_dim, num_labels):

        super().__init__()
        self.encoder_dim = encoder_dim
        self.vilt_encoder = encoder
        self.clf_layer = nn.Sequential(
                            nn.Linear(encoder_dim, encoder_dim*2),
                            nn.LayerNorm(encoder_dim*2),
                            nn.GELU(),
                            nn.Linear(encoder_dim*2, num_labels)
                        )

        self.bert = BertModel.from_pretrained('bert-base-uncased')

    @torch.no_grad()
    def get_bert_outputs(self, encodings):
        outputs = self.bert(encodings['input_ids'],
            attention_mask=encodings['attention_mask'], 
            token_type_ids=encodings['token_type_ids'])
        return outputs.last_hidden_state #[bs, max_seq_len, hidden_size]

    def forward(self, images, texts):

        encodings = self.vilt_encoder.process_inputs(images, texts)
        # expand to batch size
        bs = len(encodings['input_ids'])
        encodings['pixel_values'] = encodings['pixel_values'].expand([bs, *encodings['pixel_values'].shape[1:]])
        encodings['pixel_mask'] = encodings['pixel_mask'].expand([bs, *encodings['pixel_mask'].shape[1:]])

        encodings['inputs_embeds'] = self.get_bert_outputs(encodings)
        encodings['input_ids'] = None

        encoder_output = self.vilt_encoder(**encodings)

        output_logits = self.clf_layer(encoder_output)
        return output_logits


class ViltForMultipleChoice(nn.Module):

    def __init__(self, encoder, encoder_dim, num_labels):

        super().__init__()
        self.encoder_dim = encoder_dim
        self.num_labels = num_labels
        self.vilt_encoder = encoder
        self.clf_layer = nn.Sequential(
                            nn.Dropout(0.1),
                            nn.Linear(encoder_dim, 1)
                        )

    def forward(self, images, texts):
        encodings = self.vilt_encoder.process_inputs(images, texts)
        # unflat_input_ids = encodings['input_ids'].view(self.num_labels, 32, -1).transpose(0, 1)
        bs = len(encodings['input_ids'])
        encodings['pixel_values'] = encodings['pixel_values'].expand([bs, *encodings['pixel_values'].shape[1:]])
        encodings['pixel_mask'] = encodings['pixel_mask'].expand([bs, *encodings['pixel_mask'].shape[1:]])
        encoder_output = self.vilt_encoder(**encodings)
        reshape_output = encoder_output.view(self.num_labels, -1, self.encoder_dim).transpose(0, 1).contiguous()

        output_logits = self.clf_layer(reshape_output).squeeze()
        return output_logits


class ViltBertForMultipleChoice(nn.Module):

    def __init__(self, encoder, encoder_dim, num_labels):

        super().__init__()
        self.encoder_dim = encoder_dim
        self.num_labels = num_labels
        self.vilt_encoder = encoder
        self.clf_layer = nn.Sequential(
                            nn.Dropout(0.1),
                            nn.Linear(encoder_dim, 1)
                        )

        self.bert = BertModel.from_pretrained('bert-base-uncased')

    @torch.no_grad()
    def get_bert_outputs(self, encodings):
        outputs = self.bert(encodings['input_ids'],
            attention_mask=encodings['attention_mask'], 
            token_type_ids=encodings['token_type_ids'])
        return outputs.last_hidden_state #[bs, max_seq_len, hidden_size]

    def forward(self, images, texts):
        encodings = self.vilt_encoder.process_inputs(images, texts)
        # unflat_input_ids = encodings['input_ids'].view(self.num_labels, 32, -1).transpose(0, 1)
        bs = len(texts)
        encodings['pixel_values'] = encodings['pixel_values'].expand([bs, *encodings['pixel_values'].shape[1:]])
        encodings['pixel_mask'] = encodings['pixel_mask'].expand([bs, *encodings['pixel_mask'].shape[1:]])

        encodings['inputs_embeds'] = self.get_bert_outputs(encodings)
        encodings['input_ids'] = None

        encoder_output = self.vilt_encoder(**encodings)
        reshape_output = encoder_output.view(self.num_labels, -1, self.encoder_dim).transpose(0, 1).contiguous()

        output_logits = self.clf_layer(reshape_output).squeeze()
        return output_logits


# for debugging
class BertForMultipleChoice(nn.Module):
    def __init__(self, encoder, encoder_dim, num_labels):

        super().__init__()
        self.encoder_dim = encoder_dim
        self.num_labels = num_labels
        self.bert = BertModel.from_pretrained('bert-base-uncased')
        self.clf_layer = nn.Sequential(
                            nn.Dropout(0.1),
                            nn.Linear(encoder_dim, 1)
                        )
        self.device = torch.device("cuda")
        self.processor = ViltProcessor.from_pretrained("dandelin/vilt-b32-mlm")
        self.processor.tokenizer = BertTokenizerFast.from_pretrained("bert-base-uncased")
        self.processor.feature_extractor.size = 128

    def forward(self, images, texts):
        encodings = self.processor(images=images, text=texts, max_length=80,
            padding=True, truncation=True, return_tensors='pt').to(self.device)

        # unflat_input_ids = encodings['input_ids'].view(self.num_labels, 32, -1).transpose(0, 1)
        outputs = self.bert(encodings['input_ids'], 
                                    attention_mask=encodings['attention_mask'],
                                    token_type_ids=encodings['token_type_ids'])
        encoder_output = outputs[1]
        reshape_output = encoder_output.view(self.num_labels, -1, self.encoder_dim).transpose(0, 1).contiguous()

        output_logits = self.clf_layer(reshape_output).squeeze()
        return output_logits


def load_vilt_encoder(loaded_encoder_name, device, pretrained_vilt_name="dandelin/vilt-b32-mlm"):

    logger.info("-"*100)
    logger.info("Loading ViLT encoder model: {}".format(loaded_encoder_name))
    vilt_processor = ViltProcessor.from_pretrained(pretrained_vilt_name)

    if loaded_encoder_name == pretrained_vilt_name: # load pretrained encoder
        vilt = ViltModel.from_pretrained(pretrained_vilt_name)
        vilt_encoder = ViltEncoderWrapper(vilt_processor, vilt, device)

    else: # load pre-finetuned encoder
        config = ViltConfig.from_pretrained(pretrained_vilt_name)
        vilt = ViltModel(config) # random init.
        vilt_encoder = ViltEncoderWrapper(vilt_processor, vilt, device)
        if 'nlvr2' in loaded_encoder_name:
            vilt_encoder.expand_modality_type_embeddings()
        vilt_encoder.load_state_dict(torch.load(loaded_encoder_name)) # loaded

    logger.info("Successfully loaded pretrained ViLT model")
    return vilt_encoder

def convert_batch_to_model_input_dict(batch):

    return {'images': batch['images'],
            'texts': batch['raw_texts']}

def convert_seq_batch_to_model_input_dict(batch, mean_image):

    return {'images': [mean_image],
            'texts': list(batch[0])}

def convert_mc_batch_to_model_input_dict(batch, mean_image):
    texts_a, texts_b = batch[0], batch[1]
    bs = len(texts_a)

    texts_b = list(itertools.chain(*texts_b)) #texts_b (n_choice, bs) -> (n_choice*bs,)
    text_pairs = [[texts_a[i%bs], tb] for i, tb in enumerate(texts_b)] # extend text_a & pair w/ text_b

    return {'images': [mean_image],
            'texts': text_pairs}
