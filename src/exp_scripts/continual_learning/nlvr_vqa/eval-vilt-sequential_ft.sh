export TOKENIZERS_PARALLELISM=false

python -m train.train_upstream_continual_learning --encoder_name vilt \
                        --pretrained_model_name dandelin/vilt-b32-mlm \
                        --ordered_cl_tasks nlvr2,vqa \
                        --cl_algorithm sequential_ft \
			--do_eval \
                        --output_dir /people/cs/o/oxx220000/CLiMB/experiments/ \
                        --do_wandb_logging \
                        --batch_size 32
