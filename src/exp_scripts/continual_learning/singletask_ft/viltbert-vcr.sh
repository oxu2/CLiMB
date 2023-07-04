export TOKENIZERS_PARALLELISM=false

python -m train.train_upstream_continual_learning --encoder_name viltbert \
                        --pretrained_model_name dandelin/vilt-b32-mlm \
                        --ordered_cl_tasks vcr \
                        --cl_algorithm singletask_ft \
                        --climb_data_dir /people/cs/o/oxx220000/data/ \
            		--do_train \
                        --output_dir /people/cs/o/oxx220000/CLiMB/experiments/ \
                        --do_wandb_logging \
                        --batch_size 64
