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

class SNLIVETrainer:

    def __init__(self, args, task_configs, model_config, tokenizer, device):

        self.args = args
        self.tokenizer = tokenizer
        self.device = device

        self.snli_ve_config = task_configs['snli-ve']
        self.data_dir = os.path.join(args.mcl_data_dir, self.snli_ve_config['data_dir'])

        # Load Flickr30K Images dataset for image data backbone
        images_source = self.snli_ve_config['images_source']
        flickr30k_config = task_configs[images_source]
        images_dataset = Flickr30KImagesDataset(os.path.join(args.mcl_data_dir, flickr30k_config['data_dir']))

        # Model-specific stuff
        self.visual_mode = model_config['visual_mode']
        self.batch2inputs_converter = model_config['batch2inputs_converter']

        # Create dataloaders for training and validation
        self.snli_ve_train_dataloader = build_snli_ve_dataloader(args=args,
                                                                 data_dir=self.data_dir,
                                                                 images_dataset=images_dataset,
                                                                 split='train',
                                                                 tokenizer=self.tokenizer,
                                                                 visual_mode=self.visual_mode)

        self.snli_ve_dev_dataloader = build_snli_ve_dataloader(args=args,
                                                               data_dir=self.data_dir,
                                                               images_dataset=images_dataset,
                                                               split='dev',
                                                               tokenizer=tokenizer,
                                                               visual_mode=self.visual_mode)

        # Training hyperparameters
        self.num_epochs = self.snli_ve_config['num_epochs']
        self.lr = self.snli_ve_config['lr']
        self.adam_epsilon = self.snli_ve_config['adam_epsilon']
        self.weight_decay = self.snli_ve_config['weight_decay']
        self.loss_criterion = nn.CrossEntropyLoss()
        self.max_steps = len(self.snli_ve_train_dataloader) * self.num_epochs
        self.warmup_ratio = 0.1 # TODO remove hard code

    def get_train_dataloader(self):
        return self.snli_ve_train_dataloader

    def get_collate_fn(self):
        return self.snli_ve_train_dataloader.collate_fn

    def forward_pass(self, model, batch, do_eval=False):

        inputs = self.batch2inputs_converter(batch)
        if do_eval is True:
            with torch.no_grad():
                output = model(task_key='snli-ve', **inputs)
        else:
            output = model(task_key='snli-ve', **inputs)
        return output


    def train_step(self, model, batch, optimizer, scheduler=None):

        output = self.forward_pass(model, batch)
        logits = output[1]
        target = batch['labels'].to(self.device)
        loss = self.loss_criterion(logits, target)
        loss.backward()

        optimizer.step()
        if scheduler is not None:
            scheduler.step()
        optimizer.zero_grad()

        return loss, output

    def create_optimizer(self, model):

        no_decay = ['bias', 'LayerNorm.weight']
        optimizer_grouped_parameters = [
            {'params': [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)], 'weight_decay': self.weight_decay},
            {'params': [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
            ]
        optimizer = AdamW(optimizer_grouped_parameters, lr=self.lr, eps=self.adam_epsilon, betas=(0.9, 0.98))
        return optimizer

    def train(self, model, replay_memory=None):

        model.to(self.device)
        if self.args.cl_algorithm == 'adapter':
            model.set_active_adapters("snli-ve")

        if self.args.cl_algorithm == 'experience_replay':
            assert replay_memory is not None
            do_replay = replay_memory.do_replay()

        # Create optimizer
        optimizer = self.create_optimizer(model)
        # Create Scheduler
        scheduler = get_polynomial_decay_schedule_with_warmup(
            optimizer,
            num_warmup_steps=int(self.max_steps * self.warmup_ratio),
            num_training_steps=self.max_steps,
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
        for epoch in range(self.num_epochs):
            # Training loop for epoch

            model.train()
            for step, batch in enumerate(tqdm(self.snli_ve_train_dataloader, desc='Training epoch {}'.format(epoch+1))):

                loss, output = self.train_step(model, batch, optimizer, scheduler)

                if (step + 1) % 100 == 0:
                    wandb.log({'snli-ve': {'loss': loss.item()}})

                if self.args.cl_algorithm == 'experience_replay' and do_replay is True:
                    if (step + 1) % self.args.replay_frequency == 0:
                        sampled_replay_task = replay_memory.sample_replay_task()
                        replay_loss = replay_memory.run_replay_step(task_key=sampled_replay_task, model=model)

            # Do evaluation after epoch
            eval_score = self.eval(model)
            logger.info("Evaluation after epoch {}: {:.2f}".format(epoch+1, eval_score))
            wandb.log({'snli-ve': {'dev_score': eval_score}})
            if eval_score > best_score:
                logger.info("New best evaluation score: {:.2f}".format(eval_score))
                best_score = eval_score
                best_model['epoch'] = epoch
                best_model['model'] = copy.deepcopy(model)

        return best_score, best_model

    def eval(self, model):

        model.eval()
        eval_score = 0

        for step, batch in enumerate(tqdm(self.snli_ve_dev_dataloader, desc='Evaluating on SNLI-VE val set')):
            output = self.forward_pass(model, batch, do_eval=True)

            logits = output[1]
            batch_scores = (logits.argmax(-1).cpu() == batch['labels'])
            eval_score += batch_scores.sum().item()

        eval_score = eval_score/len(self.snli_ve_dev_dataloader.dataset)*100.0

        model.train()
        return eval_score

    def eval_forgetting(self, model, model_path):

        model.to(self.device)
        if self.args.cl_algorithm == 'adapter':
            model.set_active_adapters("snli-ve")

        # Load model with encoder weights from encoder_path, and classifier weights from model_path
        model.load_state_dict(torch.load(model_path))
        logger.info("Loaded model checkpoint from {}".format(model_path))

        return self.eval(model)

