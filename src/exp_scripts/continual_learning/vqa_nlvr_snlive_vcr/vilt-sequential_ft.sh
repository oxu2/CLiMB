export TOKENIZERS_PARALLELISM=false

python -m train.train_upstream_continual_learning --encoder_name vilt \
                        --pretrained_model_name dandelin/vilt-b32-mlm \
                        --ordered_cl_tasks vqa,nlvr2,snli-ve,vcr \
                        --cl_algorithm sequential_ft \
                        --climb_data_dir /people/cs/o/oxx220000/data/ \
                        --do_train \
			--do_eval \
                        --output_dir /people/cs/o/oxx220000/CLiMB/experiments/ \
                        --do_wandb_logging \
                        --batch_size 64
