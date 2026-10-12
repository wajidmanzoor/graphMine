# Preprocess ECLgraph CSR graphs

This code takes a CSR graph and outputs a preprocessed CSR graph. This is optional and provided for reproducibility.

**Effects**:

* Removes all nodes not in the largest Connected Component
* If edge weights exist, divides them by EXISTING_WEIGHT_DIVISION_FACTOR (default=3)
* If no edge weights exist, adds random weights generated from NEW_WEIGHT_MIN to NEW_WEIGHT_MAX (default=100 to 10000)

The default values were used for the paper to avoid 32-bit integer overflow. This code has only been tested on undirected graphs; do not use this preprocessor on converted DIMACS graphs.

**To compile:**

    make

**To run:**

    ./preprocess <input_graph> <output_graph> <old_source(optional)> <old_sink(optional)> 

If <old_source> or <old_sink> are specified, the code will print what their new indices are in the output_graph.

