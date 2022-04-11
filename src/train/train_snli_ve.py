import argparse
import datetime
import json
import logging
import os
import random
import sys
import time
import math
import shutil
import pickle as pkl
import copy
import pdb
from tqdm import tqdm
import wandb

sys.path.insert(0, '.')

import numpy as np
import torch
from torch import nn
from torch.optim import AdamW
from transformers import get_polynomial_decay_schedule_with_warmup

from data.image_datasets.flickr30kimages_dataset import Flickr30KImagesDataset
from data.visionlanguage_datasets.snli_ve_dataset import build_snli_ve_dataloader

logger = logging.getLogger(__name__)
logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        datefmt='%m/%d/%Y %H:%M:%S',
        level=logging.INFO)

def train_snli_ve(args, encoder, task_configs, model_config, tokenizer, device):

    snli_ve_config = task_configs['snli-ve']
    data_dir = snli_ve_config['data_dir']
    num_labels = snli_ve_config['num_labels']

    # Load Flickr30K Images dataset for image data backbone
    images_source = snli_ve_config['images_source']
    flickr30k_config = task_configs[images_source]
    images_dataset = Flickr30KImagesDataset(flickr30k_config['data_dir'])

    # Create model
    encoder_dim = model_config['encoder_dim']
    visual_mode = model_config['visual_mode']
    classifier_class = model_config['classifier_class']
    model = classifier_class(encoder=encoder, 
                             encoder_dim=encoder_dim, 
                             num_labels=num_labels)
    batch2inputs_converter = model_config['batch2inputs_converter']
    model.to(device)

    # Create dataloaders for training and validation
    snli_ve_train_dataloader = build_snli_ve_dataloader(args=args,
                                                        data_dir=data_dir,
                                                        images_dataset=images_dataset,
                                                        split='train',
                                                        tokenizer=tokenizer,
                                                        visual_mode=visual_mode)

    snli_ve_dev_dataloader = build_snli_ve_dataloader(args=args,
                                              data_dir=data_dir,
                                              images_dataset=images_dataset,
                                              split='dev',
                                              tokenizer=tokenizer,
                                              visual_mode=visual_mode)

    # Training hyperparameters
    num_epochs = snli_ve_config['num_epochs']
    lr = snli_ve_config['lr']
    adam_epsilon = snli_ve_config['adam_epsilon']
    weight_decay = snli_ve_config['weight_decay']

    # Create optimizer
    loss_criterion = nn.CrossEntropyLoss(reduction='mean')
    no_decay = ['bias', 'LayerNorm.weight']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)], 'weight_decay': weight_decay},
        {'params': [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
        ]
    # https://github.com/dandelin/ViLT/blob/master/vilt/modules/vilt_utils.py#L236
    optimizer = AdamW(optimizer_grouped_parameters, lr=lr, eps=adam_epsilon, betas=(0.9, 0.98))
    # Create Scheduler
    # https://github.com/dandelin/ViLT/blob/master/vilt/modules/vilt_utils.py#L263
    max_steps = len(snli_ve_train_dataloader) * num_epochs
    warmup_ratio = 0.1 # TODO remove hard code
    scheduler = get_polynomial_decay_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(max_steps * warmup_ratio),
        num_training_steps=max_steps,
        lr_end=0,
        power=1,
    )

    best_score = 0
    best_model = {
        'epoch': 0,
        'model': copy.deepcopy(model), #model.state_dict(),
        'optimizer_state': optimizer.state_dict()
    }

    model.zero_grad()
    model.train()
    for epoch in range(num_epochs):
        # Training loop for epoch
        for step, batch in enumerate(tqdm(snli_ve_train_dataloader, desc='Training epoch {}'.format(epoch+1))):
            inputs = batch2inputs_converter(batch)
            labels = batch['labels'].to(device)

            #output = model(images=images, texts=texts)      # TODO: Create abstraction that can convert batch keys into model input keys for all models
            output = model(**inputs)
            logits = output[1]
            # https://github.com/dandelin/ViLT/blob/master/vilt/modules/objectives.py#L317
            loss = loss_criterion(logits, labels)

            loss.backward()

            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

            if (step + 1) % 100 == 0:
                wandb.log({'snli-ve': {'loss': loss.item()}})

        # Do evaluation after epoch
        eval_score = eval_snli_ve(args, model, snli_ve_dev_dataloader, device, batch2inputs_converter)
        logger.info("Evaluation after epoch {}: {:.2f}".format(epoch+1, eval_score))
        wandb.log({'snli-ve': {'dev_score': eval_score}})
        if eval_score > best_score:
            logger.info("New best evaluation score: {:.2f}".format(eval_score))
            best_score = eval_score
            best_model['epoch'] = epoch
            best_model['model'] = copy.deepcopy(model)

    return best_score, best_model

def eval_snli_ve(args, model, snli_ve_dev_dataloader, device, batch2inputs_converter):

    model.eval()
    eval_correct = 0

    for step, batch in enumerate(tqdm(snli_ve_dev_dataloader, desc='Evaluating on SNLI-VE dev set')):
        inputs = batch2inputs_converter(batch)
        labels = batch['labels'].to(device)

        #output = model(images=images, texts=texts)      # TODO: Create abstraction that can convert batch keys into model input keys for all models
        with torch.no_grad():
            output = model(**inputs)
        logits = output[1]

        batch_scores = (logits.argmax(-1).cpu() == batch['labels'])
        eval_correct += batch_scores.sum().item()

    eval_acc = eval_correct/len(snli_ve_dev_dataloader.dataset)*100.0

    model.train()
    return eval_acc

def eval_snli_ve_forgetting(args, encoder, model_path, encoder_path, task_configs, model_config, tokenizer, device):

    snli_ve_config = task_configs['snli-ve']
    data_dir = snli_ve_config['data_dir']
    num_labels = snli_ve_config['num_labels']

    # Load Flickr30K Images dataset for image data backbone
    images_source = snli_ve_config['images_source']
    flickr30k_config = task_configs[images_source]
    images_dataset = Flickr30KImagesDataset(flickr30k_config['data_dir'])

    # Create model
    encoder_dim = model_config['encoder_dim']
    visual_mode = model_config['visual_mode']
    classifier_class = model_config['classifier_class']
    model = classifier_class(encoder=encoder, 
                             encoder_dim=encoder_dim, 
                             num_labels=num_labels)
    batch2inputs_converter = model_config['batch2inputs_converter']
    model.to(device)

    snli_ve_dev_dataloader = build_snli_ve_dataloader(args=args,
                                              data_dir=data_dir,
                                              images_dataset=images_dataset,
                                              split='dev',
                                              tokenizer=tokenizer,
                                              visual_mode=visual_mode)

    # Load model with encoder weights from encoder_path, and classifier weights from model_path
    model.load_state_dict(torch.load(model_path))

    # Load encoder weights from encoder checkpoint
    ckpt_encoder_dict = torch.load(encoder_path)
    model_encoder_dict = model.get_encoder().state_dict()

    for k in ckpt_encoder_dict.keys():
        if model_encoder_dict[k].shape == ckpt_encoder_dict[k].shape:
            model_encoder_dict[k].copy_(ckpt_encoder_dict[k])

    return eval_snli_ve(args, model, snli_ve_dev_dataloader, device, batch2inputs_converter)
