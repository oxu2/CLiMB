from tqdm import tqdm
import pdb
import csv
import glob
import json
import logging
import os
import numpy as np
import sys



logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class DataProcessor(object):
    """Base class for data converters for multiple choice data sets."""
    def __init__(self):
        label_list = self._set_label_list()
        self.label_map = {label: i for i, label in enumerate(label_list)}

    def get_train_examples(self, data_dir):
        raise NotImplementedError()

    def get_dev_examples(self, data_dir):
        raise NotImplementedError()

    def get_test_examples(self, data_dir):
        raise NotImplementedError()

    @classmethod
    def _to_example(self, example_id, text_a=None, text_b=None, text_c=None, label=None, desc=None):
        merged_text = [f'{text_a} [SEP] {t_b}' for t_b in text_b] #TODO: text_c
        return {
            "example_id": example_id,
            "text_a": text_a,
            "text_b": text_b,
            "text_c": text_c,
            "merged_text": merged_text,
            "label": label,
            "description": desc
        }

    @classmethod
    def _read_csv(self, input_file):
        with open(input_file, "r", encoding="utf-8") as f:
            return list(csv.reader(f))

    @classmethod
    def _read_tsv(cls, input_file, quotechar=None):
        """Reads a tab separated value file."""
        with open(input_file, "r", encoding="utf-8-sig") as f:
            return list(csv.reader(f, delimiter="\t", quotechar=quotechar))

    @classmethod
    def _read_jsonl(cls, input_file):
        data = []
        with open(input_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                line = line.strip()
                line = json.loads(line)
                data.append(line)
        return data


def split_train_dev(data, seed=2022, dev_ratio=0.3):
    n_labeled_data = len(data)
    np.random.seed(seed)
    dev_ids = set(np.random.choice(n_labeled_data, int(n_labeled_data*dev_ratio), replace=False))
    train_data, dev_data = [], []
    for i, dt in enumerate(data):
        if i in dev_ids:
            dev_data.append(dt)
        else:
            train_data.append(dt)

    return train_data, dev_data, dev_ids


class HellaSwagProcessor(DataProcessor):
    def get_train_examples(self, data_dir):
        path = os.path.join(data_dir, "hellaswag_train.jsonl")
        logger.info("Loading Training set from {}".format(path))
        labeled_data = self._create_examples(self._read_jsonl(path))
        train_data, _, self.dev_ids = split_train_dev(labeled_data)
        return train_data

    def get_dev_examples(self, data_dir):
        path = os.path.join(data_dir, "hellaswag_train.jsonl")
        logger.info("Loading Dev set split from the original Training set from {}".format(path))
        labeled_data = self._create_examples(self._read_jsonl(path))
        _, dev_data, self.dev_ids = split_train_dev(labeled_data)
        return dev_data

    def get_test_examples(self, data_dir):
        path = os.path.join(data_dir, "hellaswag_val.jsonl")
        logger.info("Loading the original Dev set as the Test set from {}".format(path))
        return self._create_examples(self._read_jsonl(path))

    def _set_label_list(self):
        return [0, 1, 2, 3]

    def _create_examples(self, data, has_label=True):
        examples = []
        for idx, dt in enumerate(data):
            examples.append(
                self._to_example(
                    example_id = idx,
                    text_a = dt["ctx"],
                    text_b = dt["endings"],
                    label = self.label_map[dt["label"]] if has_label else None,
                    desc = "Multiple-Choice; text_a: Ctx; text_b: ending"
                )
            )
        return examples


class PIQAProcessor(DataProcessor):
    def get_train_examples(self, data_dir):
        path = os.path.join(data_dir, "train.jsonl")
        label_path = os.path.join(data_dir, "train-labels.lst")
        logger.info("Loading Training set from {}".format(path))
        labeled_data = self._create_examples(self._read_jsonl(path), label_path)
        train_data, _, self.dev_ids = split_train_dev(labeled_data)
        return train_data

    def get_dev_examples(self, data_dir):
        path = os.path.join(data_dir, "train.jsonl")
        label_path = os.path.join(data_dir, "train-labels.lst")
        logger.info("Loading Dev set split from the original Training set from {}".format(path))
        labeled_data = self._create_examples(self._read_jsonl(path), label_path)
        _, dev_data, self.dev_ids = split_train_dev(labeled_data)
        return dev_data

    def get_test_examples(self, data_dir):
        path = os.path.join(data_dir, "valid.jsonl")
        label_path = os.path.join(data_dir, "valid-labels.lst")
        logger.info("Loading the original Dev set as the Test set from {}".format(path))
        return self._create_examples(self._read_jsonl(path), label_path)

    def _set_label_list(self):
        return ["0", "1"]

    def _create_examples(self, data, label_path, has_label=True):
        if has_label:
            labels = open(label_path, encoding="utf-8").read().splitlines()
        else:
            labels = np.zeros(len(data)) #dummy, not used

        examples = [
            self._to_example(
                example_id = idx,
                text_a = dt["goal"],
                text_b = [dt["sol1"], dt["sol2"]],
                label = self.label_map[lb] if has_label else None,
                desc = "Multiple-Choice; text_a: Ctx; text_b: Ans"
            )
            for idx, (dt, lb) in enumerate(zip(data, labels))
        ]
        return examples


class CommonsenseQAProcessor(DataProcessor):
    def get_train_examples(self, data_dir):
        path = os.path.join(data_dir, "train_rand_split.jsonl")
        logger.info("Loading Training set from {}".format(path))
        labeled_data = self._create_examples(self._read_jsonl(path))
        train_data, _, self.dev_ids = split_train_dev(labeled_data)
        return train_data

    def get_dev_examples(self, data_dir):
        path = os.path.join(data_dir, "train_rand_split.jsonl")
        logger.info("Loading Dev set split from the original Training set from {}".format(path))
        labeled_data = self._create_examples(self._read_jsonl(path))
        _, dev_data, self.dev_ids = split_train_dev(labeled_data)
        return dev_data

    def get_test_examples(self, data_dir):
        path = os.path.join(data_dir, "dev_rand_split.jsonl")
        logger.info("Loading the original Dev set as the Test set from {}".format(path))
        return self._create_examples(self._read_jsonl(path))

    def _set_label_list(self):
        return ["A", "B", "C", "D", "E"]

    def _create_examples(self, data, has_label=True):
        examples = [
            self._to_example(
                example_id = idx,
                text_a = dt['question']['stem'],
                text_b = [ch['text'] for ch in dt['question']['choices']],
                label = self.label_map[dt["answerKey"]] if has_label else None,
                desc = "Multiple-Choice; text_a: Ctx; text_b: Ans"
            )
            for idx, dt in enumerate(data)
        ]
        return examples


class COSMOSQAProcessor(DataProcessor):
    def get_train_examples(self, data_dir):
        path = os.path.join(data_dir, "train.csv")
        logger.info("Loading Training set from {}".format(path))
        labeled_data = self._create_examples(self._read_csv(path))
        train_data, _, self.dev_ids = split_train_dev(labeled_data)
        return train_data

    def get_dev_examples(self, data_dir):
        path = os.path.join(data_dir, "train.csv")
        logger.info("Loading Dev set split from the original Training set from {}".format(path))
        labeled_data = self._create_examples(self._read_csv(path))
        _, dev_data, self.dev_ids = split_train_dev(labeled_data)
        return dev_data

    def get_test_examples(self, data_dir):
        path = os.path.join(data_dir, "valid.csv")
        logger.info("Loading the original Dev set as the Test set from {}".format(path))
        return self._create_examples(self._read_csv(path))

    def _set_label_list(self):
        return ['0', '1', '2', '3']

    def _create_examples(self, data, has_label=True):
        examples = [
            self._to_example(
                example_id = line[0],
                text_a = line[1],
                text_b = [line[3], line[4], line[5], line[6]],
                text_c = line[2],
                label = self.label_map[line[7]] if has_label else None,
                desc = "Multiple-Choice; text_a: Ctx; text_b: Ans; text_c: Ques"
            )
            for line in data[1:]  # we skip the line with the column names
        ]

        return examples
    

class IMDBProcessor():
    def __init__(self, cache_dir='cache_imdb'):
        from datasets import load_dataset
        dataset = load_dataset("imdb", cache_dir=cache_dir)
        self.train_data, self.dev_data, self.dev_ids = split_train_dev(dataset['train'])
        self.test_data = dataset['test']

    def get_train_examples(self, data_dir=None):
        return self.train_data

    def get_dev_examples(self, data_dir=None):
        return self.dev_data

    def get_test_examples(self, data_dir=None):
        return self.test_data


class GLUEProcessor():
    def __init__(self, task='sst2', cache_dir='cache_glue'):
        from datasets import load_dataset
        dataset = load_dataset('glue', task, cache_dir=cache_dir)
        self.train_data, self.dev_data, self.dev_ids = split_train_dev(dataset['train'])
        self.test_data = dataset['validation']

    def get_train_examples(self, data_dir=None):
        return self.train_data

    def get_dev_examples(self, data_dir=None):
        return self.dev_data

    def get_test_examples(self, data_dir=None):
        return self.test_data

'''
if __name__ == "__main__":
    assert len(sys.argv) == 2, "input task name"
    task_name = sys.argv[1]

    processor_map = {'piqa': PIQAProcessor, 'hellaswag': HellaSwagProcessor, 'cosmosqa': COSMOSQAProcessor, 
        'commonsenseqa': CommonsenseQAProcessor, 'imdb': IMDBProcessor, 'sst2': GLUEProcessor} 
    processor = processor_map[task_name]()
    
    if task_name in ['sst2', 'imdb']:
        data_dir = None
    else:
        data_dir = f'/data/datasets/MCL/{task_name}'

    data = processor.get_train_examples(data_dir) # type: list
    all_length = np.zeros(len(data), int)
    for i, example in enumerate(data):
        if task_name == 'sst2':
            text = example['sentence']
        elif task_name == 'imdb':
            text = example['text']
        elif task_name == 'cosmosqa':
            text = example['text_a'] + " " + example['text_c']
            longest_bi = np.argmax(np.array([len(s.split()) for s in example['text_b']]))
            text += " " + example['text_b'][longest_bi]
        else:
            text = example['text_a']
            assert len(example['text_b'])==5
            longest_bi = np.argmax(np.array([len(s.split()) for s in example['text_b']]))
            text += " " + example['text_b'][longest_bi]
        all_length[i] = len(text.split())

    print(f'{task_name}: {all_length.mean():.1f} ±{all_length.std():.1f}, max: {all_length.max()}')
'''
