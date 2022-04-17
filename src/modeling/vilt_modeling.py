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
from transformers import ViltProcessor, ViltModel

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
        args:
        processor - instance of ViltProcessor
        vilt - instance of ViltModel class
        '''

        super().__init__()
        self.processor = processor
        self.vilt = vilt
        self.device = device

    def process_inputs(self, images, texts):
        encodings = self.processor(images=images, text=texts, 
            padding=True, truncation=True, return_tensors='pt').to(self.device)

        #debug(self.processor, encodings)
        return encodings

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
            self.expand_modality_type_embeddings()

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

    def expand_modality_type_embeddings(self, type_vocab_size=3):
        self.vilt_encoder.vilt.config.modality_type_vocab_size = type_vocab_size
        #https://github.com/dandelin/ViLT/blob/762fd3975c180db6fc88f577cf39549983fa373a/vilt/modules/vilt_module.py#L85
        emb_data = self.vilt_encoder.vilt.embeddings.token_type_embeddings.weight.data
        self.vilt_encoder.vilt.embeddings.token_type_embeddings = nn.Embedding(type_vocab_size, self.encoder_dim)
        self.vilt_encoder.vilt.embeddings.token_type_embeddings.weight.data[0, :] = emb_data[0, :]
        self.vilt_encoder.vilt.embeddings.token_type_embeddings.weight.data[1, :] = emb_data[1, :]
        self.vilt_encoder.vilt.embeddings.token_type_embeddings.weight.data[2, :] = emb_data[1, :]

    def get_encoder(self):

        return self.vilt_encoder

def load_vilt_encoder(pretrained_vilt_name, device):

    logger.info("-"*100)
    logger.info("Loading pretrained ViLT model: {}".format(pretrained_vilt_name))
    vilt_processor = ViltProcessor.from_pretrained(pretrained_vilt_name)
    vilt = ViltModel.from_pretrained(pretrained_vilt_name)
    vilt_encoder = ViltEncoderWrapper(vilt_processor, vilt, device)
    logger.info("Successfully loaded pretrained ViLT model")
    return vilt_encoder

def convert_batch_to_model_input_dict(batch):

    return {'images': batch['images'],
            'texts': batch['raw_texts']}
