nsys profile -o GAP-road --stats=true ./cuda_bcc /raid/graphwork/new/modified/GAP-road.txt

#!/bin/bash

# Path to the input files and output directory
input_path="datasets"
# input_path="/home/graphwork/cs22s501/datasets/txt/medium_graphs"
# input_path="/home/graphwork/cs22s501/datasets/txt/new_graphs/modified"
mkdir -p profiling_results

# Loop through all .txt files in the specified input directory
for file in "${input_path}"/*.txt; do
    # Inform the user which file is being processed
    echo -e "\nProcessing $file..."

    # Extract the base filename without extension
    filename=$(basename -- "$file")
    
    # Execute the parallel bcc
    nsys profile -o $filename --stats=true ./cuda_bcc "$file" >> "profiling_results/${filename}.log"

    # Assign the exit status to res
    res=$?

    # Check the value of res
    if [ $res -eq 0 ]; then
        echo "Validation Successful for $file"
    else
        echo "Validation Failed for $file"
    fi

    # echo "Processing complete."
done
