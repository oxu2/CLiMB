export TOKENIZERS_PARALLELISM=false

python -m train.train_lowshot_multimodal --encoder_name vilt \
                        --pretrained_model_name dandelin/vilt-b32-mlm \
                        --ordered_cl_tasks vqa \
                        --cl_algorithm singletask_ft \
                        --climb_data_dir /people/cs/o/oxx220000/data/ \
            		--output_dir /people/cs/o/oxx220000/CLiMB/experiments/ \
                        --batch_size 64
