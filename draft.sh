conda activate climb


FileNotFoundError: [Errno 2] No such file or directory: '/data/datasets/MCL/iNat2019/train2019.json'

https://ml-inat-competition-datasets.s3.amazonaws.com/2019/train_val2019.tar.gz

# bash exp_scripts/vision/vilt-cls.sh

bash src/exp_scripts/vision/vilt-cls.sh

# bash code: extract iNat2019/test2019.tar.gz  to iNat2019/ directory
tar -xvf iNat2019/test_val2019.tar.gz --directory iNat2019/
tar -xvf iNat2019/test2019.tar.gz --directory iNat2019/
tar -xvf iNat2019/val2019.tar.gz --directory iNat2019/

# move /people/cs/o/oxx220000/data/train_val2019 to /people/cs/o/oxx220000/data/iNat2019/
mv /people/cs/o/oxx220000/data/train_val2019 /people/cs/o/oxx220000/data/iNat2019/

# replace /data/datasets/MCL with /people/cs/o/oxx220000/data
# replace /data/experiments/MCL with /people/cs/o/oxx220000/CLiMB/experiments
