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

output_dir="output"
mkdir -p results
mkdir -p "${output_dir}"

# Loop through all .txt files in the specified input directory
for file in "$DATASET_DIR"/*; do
    # Inform the user which file is being processed
    echo -e "\nProcessing $file..."

    # Extract the base filename without extension
    filename=$(basename -- "$file")
    filename="${filename%.txt}"

    # Paths for output files
    ser_output_file="${output_dir}/${filename}_serial_result.txt"
    par_output_file="${output_dir}/${filename}_result.txt"

    # Execute serial bcc and write to output file
    bin/serial_BCC "$file" >> results/ser_out.log
    echo "Serial BCC output written to ${ser_output_file}"

    # Execute parallel bcc and write to output file
    bin/cuda_bcc -i "$file" >> results/par_out.log
    echo "Parallel BCC output written to ${par_output_file}"

    # Validate the result
    bin/explicit_bcc_checker "$ser_output_file" "$par_output_file" >> results/checker_output.log

    # Assign the exit status to res
    res=$?
    # Check the value of res
    if [ $res -eq 0 ]; then
        echo "Validation Successful for $file"
    else
        echo "Validation Failed for $file"
        cat results/checker_output.log
    fi

    echo "Processing complete."
    done

    if [ $res -eq 0 ]; then
        echo "Validation Successful for $file"
    else
        echo "Validation Failed for $file"
    fi

    echo "Processing complete."
done
