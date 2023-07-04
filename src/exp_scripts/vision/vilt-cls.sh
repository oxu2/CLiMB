export TOKENIZERS_PARALLELISM=false

task_arr=("inat2019" "places365" "imagenet")
nshot_arr=(16 32)
subseed_arr=(10)
ckpt_arr=(
    "dandelin/vilt-b32-mlm" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-singletask_ft-task0_vqa/checkpoints/task0_vqa/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-sequential_ft-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task1_nlvr2/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-sequential_ft-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task2_snli-ve/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-experience_replay-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task1_nlvr2/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-experience_replay-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task2_snli-ve/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-freeze_bottom9layers-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task0_vqa/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-freeze_bottom9layers-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task1_nlvr2/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-freeze_bottom9layers-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task2_snli-ve/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-ewc-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task1_nlvr2/encoder" \
    "/people/cs/o/oxx220000/CLiMB/experiments/vilt-ewc-task0_vqa-task1_nlvr2-task2_snli-ve-task3_vcr/checkpoints/task2_snli-ve/encoder" \
    )

for t in ${task_arr[@]}
do
    for s in ${subseed_arr[@]}
    do
        for n in ${nshot_arr[@]}
        do
            for c in ${ckpt_arr[@]}
            do
                echo "ckpt: $c, n-shot: $n, sample_seed: $s"
                python -m train.train_vision --encoder_name vilt \
                                        --checkpoint_name $c \
                                        --task_name $t \
                                        --output_dir /people/cs/o/oxx220000/CLiMB/experiments/vision_only \
                                        --batch_size 32 \
                                        --model_catog vilt-v-cls \
                                        --num_shot $n \
                                        --subsample_seed $s
            done
        done
    done
done
