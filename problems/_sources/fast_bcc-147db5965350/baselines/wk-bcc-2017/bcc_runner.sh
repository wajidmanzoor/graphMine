#!/usr/bin/env bash

if [[ -z "$1" ]]; then
    echo "Usage: $0 <path-to-dataset-directory>"
    exit 1
fi

DATASET_DIR="$1"

if [[ ! -d "$DATASET_DIR" ]]; then
    echo "Error: Directory '$DATASET_DIR' does not exist."
    exit 1
fi

# Optional: clear log before starting
> out.log

for file in "$DATASET_DIR"/*; do
    if [[ -f "$file" ]]; then
        printf "Processing: %s\n" "$file"
        bin/cuda_bcc -i "$file" >> out.log 2>&1 || {
            echo "Error processing $file" | tee -a out.log
        }
    fi
done

echo "All files processed!" | tee -a out.log