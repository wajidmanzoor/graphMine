#!/usr/bin/env bash

DATASET_DIR="/home/abhijeet/datasets/medium_datasets/ecl_graphs"
OUT_LOG="out.log"

K_START=4
K_STEP=2
K_MAX=256   # safety cap

for file in "$DATASET_DIR"/*; do
    echo "======================================" | tee -a "$OUT_LOG"
    echo "Running on: $file" | tee -a "$OUT_LOG"

    k=$K_START

    while true; do
        echo "Trying k=$k" | tee -a "$OUT_LOG"

        output=$(bin/main "$file" "$k" 2>&1)
        echo "$output" >> "$OUT_LOG"

        if echo "$output" | grep -q "sampled graph is disconnected"; then
            echo "Disconnected for k=$k" | tee -a "$OUT_LOG"
            k=$((k + K_STEP))

            if [ "$k" -gt "$K_MAX" ]; then
                echo "❌ Reached max k=$K_MAX, giving up on $file" | tee -a "$OUT_LOG"
                break
            fi
        else
            echo " Connected graph achieved with k=$k" | tee -a "$OUT_LOG"
            break
        fi
    done
done

