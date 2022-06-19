import sys
import os
import time
import jsonlines
import logging
import glob
from tqdm import tqdm
import pickle
import pdb
from PIL import Image
import numpy as np
import torch
from torch.utils.data import Dataset
import random

from PIL import Image
from torchvision import transforms as T

logger = logging.getLogger(__name__)
logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        datefmt='%m/%d/%Y %H:%M:%S',
        level=logging.INFO)

class NLVR2Dataset(Dataset):

    def __init__(self, data_dir, split, visual_input_type):
        # TODO
        if visual_input_type != "pil-image":
            raise NotImplementedError("Have not implemented other inputs for NLVR2 images!")

        self.data_dir = data_dir
        self.num_labels = 2
        self.visual_input_typel = visual_input_type
        self.split = split

        rename_split = {'train': 'train', 'val': 'dev', 'test': 'test1'}
        _split = rename_split[split]
        self.image_dir = os.path.join(data_dir, 'images', _split)

        # Load if cached data exist
        self.cached_data_file = os.path.join(data_dir, 'cached_nlvr2_data', f'{_split}.pkl')
        if os.path.isfile(self.cached_data_file):
            with open(self.cached_data_file, 'rb') as f:
                self.data = pickle.load(open(self.cached_data_file, 'rb'))
        else:
            annotations_file = os.path.join(data_dir, 'data', f'{_split}.json')

            self.data = []
            # https://github.com/facebookresearch/vilbert-multi-task/blob/main/vilbert/datasets/nlvr2_dataset.py
            with jsonlines.open(annotations_file) as reader:
                for annotation in reader:
                    # logger.info(annotation)
                    example = {}
                    example["id"] = annotation["identifier"]
                    example["image_id_0"] = os.path.join(self.image_dir, (
                        "-".join(annotation["identifier"].split("-")[:-1]) + "-img0.png"
                    ))
                    example["image_id_1"] = os.path.join(self.image_dir, (
                        "-".join(annotation["identifier"].split("-")[:-1]) + "-img1.png"
                    ))
                    example["sentence"] = str(annotation["sentence"])
                    example["labels"] = 0 if str(annotation["label"]) == "False" else 1
                    ''' # debug
                    try: 
                        assert os.path.exists(example["image_id_0"]), "img1 not exists" 
                        assert os.path.exists(example["image_id_1"]), "img2 not exists" 
                        img1 = self.get_pil_image(example["image_id_0"])
                        img2 = self.get_pil_image(example["image_id_1"])
                    except:
                        logger.info(annotation)
                        continue
                    '''
                    self.data.append(example)

            with open(self.cached_data_file, 'wb') as f:
                pickle.dump(self.data, f)

        self.n_examples = len(self.data)
        logger.info("Loaded NLVRv2 {} dataset, with {} examples".format(split, self.n_examples))
        self.pil_transform = T.Resize(size=384, max_size=640)

    def get_pil_image(self, image_fn):
        image = Image.open(image_fn)
        image = image.convert('RGB')
        if min(list(image.size)) > 384:
            image = self.pil_transform(image)
        return image

    def __len__(self):
        return self.n_examples

    #TODO: implement visual_input_type = faster-RCNN 
    def __getitem__(self, index):
        example = self.data[index]
        img1 = self.get_pil_image(example["image_id_0"])
        img2 = self.get_pil_image(example["image_id_1"])
        image_tensor = [img1, img2]

        return example["sentence"], image_tensor, example["labels"]

    def convert_to_low_shot(self, num_shots_per_class):

        assert self.split == 'train'
        logger.info("Converting NLVR2 train split into low-shot dataset, with {} examples per class...".format(num_shots_per_class))
        new_data = []
        for i in range(self.num_labels):
            i_examples = [d for d in self.data if d['labels'] == i]
            low_shot_examples = random.sample(i_examples, num_shots_per_class)
            new_data.extend(low_shot_examples)
        self.data = new_data
        self.n_examples = len(self.data)

        logger.info("Converted into low-shot dataset, with {} examples".format(self.n_examples))

#TODO: implement visual_input_type = faster-RCNN 
def nlvr2_batch_collate(batch, visual_input_type):
    raw_texts, pil_objs, labels = zip(*batch)
    return {'raw_texts': list(raw_texts), 
            'images': pil_objs, 
            'labels': torch.LongTensor(labels)}
    

def build_nlvr2_dataloader(args, data_dir, split, visual_input_type):
    logger.info("Creating NLVRv2 {} dataloader with batch size of {}".format(split, int(args.batch_size/2)))

    dataset = NLVR2Dataset(data_dir, split, visual_input_type)
    dataloader = torch.utils.data.DataLoader(
        dataset,
        num_workers = args.num_workers,
        batch_size = int(args.batch_size/2),
        shuffle = (split=='train'),
        collate_fn = lambda x: nlvr2_batch_collate(x, visual_input_type)
        )
    return dataloader

'''
if __name__ == '__main__':
    data_dir = '/data/datasets/MCL/nlvr2/'
    class Args:
        def __init__(self):
            self.batch_size = 4 
            self.num_workers = 0
    args = Args()

    nlvr2_dataloader = build_nlvr2_dataloader(args, data_dir, 'train', 'pil-image')

    for batch in tqdm(nlvr2_dataloader):
        print(batch['raw_texts'])
        print(batch['images'])
        print(batch['labels'])
        pdb.set_trace() 
'''
