# GT-Geo

This folder provides a reference implementation of paper -- Sparsity is Not an Obstacle: An Accurate and Efficient IP Geolocation Framework Based on Graph Transformer(Computer Networks).


## Basic Usage

### Requirements

The code was tested with `python 3.10.14`, `pytorch 2.2.0+cu118`,  `cudatoolkit 11.8.0`, and `cudnn 8.7.0`. Install the dependencies via [Anaconda](https://www.anaconda.com/):

```shell
# create virtual environment
conda create --name GT_Geo python=3.10.14

# activate environment
conda activate GT_Geo

# install pytorch & cudatoolkit & dgl
conda install pytorch torchvision torchaudio dgl cudatoolkit=11.8 -c pytorch -c conda-forge
# install other requirements
conda install numpy pandas
pip install scikit-learn
```

### Run the code

```shell
# Open the "GT-Geo" folder
cd GT-Geo

#GT-Geo consists of three variants: the 1GT folder contains the GT-Geo model with one GT layer, the 2GT folder contains the GT-Geo model with two GT layers, and the 3GT folder contains the GT-Geo model with three GT layers. We take 1GT as an example.
cd 1GT

# run the model GT-Geo
python main_split_version.py --backbone mpnn --epochs 4000 --lr 0.01 --hidden_channels 80  --ours_layers 1  --use_graph  --graph_weight 0.95 --ours_dropout 0.1 --ours_use_residual  --alpha 0.5  --ours_use_weight  --ours_use_act  --num_heads 1 --edge_hidden_size 80 --num_step_message_passing 2 --seed 123  --device 0 

```

## The description of hyperparameters used in main_split_version.py

| Hyperparameter   | Description                                                  |
| :--------------- | ------------------------------------------------------------ |
| seed             | the random number seed used for parameter initialization during training |
| epochs       	   | the number of training epochs                                |
| backbone         | the name of GNN model                                        |
| lr               | learning rate                                                |
| hidden_channels  | the node embedding dimension                                 |
| ours_layers      | the number of Transformer layers                             |
| use_graph        | whether use position embeddings or not                       |
| graph_weight     | the proportion of the GNN component                          |
| ours_dropout     | the Transformer component's dropout                          |
| ours_use_residual| whether to use residual connections                          |
| alpha            | the weight for residual link                                 |
| ours_use_weight  | whether to use weight for Transformer convolution            |
| ours_use_act     | when predicting if use collaborative_mlp or not              |
| num_heads        | the number of Transformer's heads                            |
| edge_hidden_size | the edge embedding dimension                                 |
| num_step_message_passing| the number of GNN layers                              |
| device           | the GPU index                                                |



## Folder Structure

```tex
└── GT-Geo
	├── datasets # Contains three real-world street-level IP geolocation datasets.
	│	|── New_York # Street-level IP geolocation dataset collected from New York City
	│	|── Los_Angeles # Street-level IP geolocation dataset collected from Los Angeles
	│	|── Shanghai # Street-level IP geolocation dataset collected from Shanghai
	├── 1GT # the GT-Geo model with one GT layer
	├── 2GT # the GT-Geo model with two GT layers
	├── 3GT # the GT-Geo model with three GT layers
	└── README.md

└── 1GT/2GT/3GT
	├── city_data # Store the dataset for one city.
	├── output_result # Store the output results
	├── main_split_version.py # Run model for training and test
	├── models.py # Our proposed GNN component
	├── ours.py # Our proposed GT-Geo model
	└── parse.py # Get the input parameters
```

## Dataset Information

The "datasets" folder contains three subfolders corresponding to three real-world street-level IP geolocation    datasets collected from New York City, Los Angeles and Shanghai. There are six files in each subfolder:

- ny(los/sh)_dstip_id_allinfo_sim.txt    *# All landmarks for New York/Shanghai/Los Angeles* 
- ny(los/sh)_dstip_id_allinfo_sim_train_0.1.txt    *# Training set for New York/Shanghai/Los Angeles*
- ny(los/sh)_dstip_id_allinfo_sim_val_0.2.txt   *# Validation set for New York/Shanghai/Los Angeles*
- ny(los/sh)_dstip_id_allinfo_sim_test_0.7.txt   *# Testing set for New York/Shanghai/Los Angeles*
- ny(los/sh)_edge_feature_sim.txt   *# Edge features in the New York/Shanghai/Los Angeles dataset*
- ny(los/sh)_ip_feature_sim.txt   *# Node features in the New York/Shanghai/Los Angeles dataset*


