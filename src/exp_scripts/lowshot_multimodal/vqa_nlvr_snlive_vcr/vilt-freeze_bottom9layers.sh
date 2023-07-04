export TOKENIZERS_PARALLELISM=false

python -m train.train_lowshot_multimodal --encoder_name vilt \
                        --pretrained_model_name dandelin/vilt-b32-mlm \
                        --ordered_cl_tasks vqa,nlvr2,snli-ve,vcr \
                        --cl_algorithm freeze_bottom_k_layers \
			--layers_to_freeze 9 \
                        --climb_data_dir /people/cs/o/oxx220000/data/ \
                        --output_dir /people/cs/o/oxx220000/CLiMB/experiments/ \
                        --batch_size 64
