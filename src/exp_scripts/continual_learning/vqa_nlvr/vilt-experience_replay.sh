export TOKENIZERS_PARALLELISM=false

python -m train.train_upstream_continual_learning --encoder_name vilt \
                        --pretrained_model_name dandelin/vilt-b32-mlm \
                        --ordered_cl_tasks vqa,nlvr2 \
                        --cl_algorithm experience_replay \
			--memory_percentage 0.01 \
			--memory_sampling_strategy random \
			--replay_frequency 100 \
			--do_train \
                        --output_dir /people/cs/o/oxx220000/CLiMB/experiments/ \
                        --do_wandb_logging \
                        --batch_size 16
