export TOKENIZERS_PARALLELISM=false

python -m train.train_lowshot_multimodal --encoder_name vilt \
                        --pretrained_model_name dandelin/vilt-b32-mlm \
                        --ordered_cl_tasks vqa,nlvr2,snli-ve,vcr \
                        --cl_algorithm experience_replay \
                        --memory_percentage 0.01 \
			--memory_sampling_strategy random \
			--replay_frequency 100 \
			--climb_data_dir /people/cs/o/oxx220000/data/ \
                        --output_dir /people/cs/o/oxx220000/CLiMB/experiments/ \
                        --batch_size 64
