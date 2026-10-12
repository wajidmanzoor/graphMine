# HB-Geo

This folder provides a reference implementation of paper -- HB-Geo: A Street-Level IP Geolocation Method Based on Hop-Constrained Subgraphs and Binary Gates(CyberSecurity).


## Basic Usage

### Requirements

The code was tested with `python 3.10.14`, `pytorch 2.2.0+cu118`,  `cudatoolkit 11.8.0`, and `cudnn 8.7.0`. Install the dependencies via [Anaconda](https://www.anaconda.com/):

```shell
# create virtual environment
conda create --name HB_Geo python=3.10.14

# activate environment
conda activate HB_Geo

# install pytorch & cudatoolkit & dgl
conda install pytorch torchvision torchaudio dgl cudatoolkit=11.8 -c pytorch -c conda-forge
# install other requirements
conda install numpy pandas
pip install scikit-learn
```

### Run the code

```shell
# Open the "HB-Geo" folder
cd HB-Geo

#HB-Geo contains multiple cities, each stored in a separate folder. We provide the HB-Geo_Osaka, HB-Geo_Seoul, and HB-Geo_Shanghai folders. We use HB-Geo_Shanghai as an example.
cd HB-Geo_Shanghai

# run the preprocessing module
python preprocess.py

# run the model HB-Geo
python main.py  --lr 0.002 --device cuda:0 --dim_in 9  --num_hidden 64  --num_heads 2,2,2

```

## The description of hyperparameters used in main.py

| Hyperparameter   | Description                                                  |
| :--------------- | ------------------------------------------------------------ |
| dim_in           | the dimension of input features                              |
| lr               | learning rate                                                |
| num_hidden       | the node embedding dimension                                 |
| num_heads        | the number of Transformer's heads                            |
| device           | the GPU index                                                |



## Folder Structure

```tex
└── HB-Geo
	├── HB-Geo_Osaka # HB-Geo used for geolocating target IPs in Osaka city
	├── HB-Geo_Seoul # HB-Geo used for geolocating target IPs in Seoul city
	├── HB-Geo_Shanghai # HB-Geo used for geolocating target IPs in Shanghai city
	└── README.md

└── HB-Geo_Osaka/HB-Geo_Seoul/HB-Geo_Shanghai
	├── asset # Record data during model execution and store intermediate model states
	├── datasets # Store the dataset
	│    |── Shanghai # Street-level IP geolocation dataset collected from Shanghai City
	├── lib # Store model and utility files
	│    |── model.py # Our proposed HB-Geo model
	│    |── utils.py # Required utility file	
	├── output # Store the output results
	├── main.py # Run model for training and test
	└── preprocess.py # The preprocessing file
```

## Dataset Information

The "datasets" folder contains three subfolders corresponding to three real-world street-level IP geolocation datasets collected from Osaka City, Seoul and Shanghai. There are six files in each subfolder:

- data.csv    *# All landmarks for Osaka/Seoul/Shanghai* 
- data_train.csv    *# Training set for Osaka/Seoul/Shanghai*
- data_val.csv   *# Validation set for Osaka/Seoul/Shanghai*
- data_test.csv   *# Testing set for Osaka/Seoul/Shanghai*
- IP.csv   *# IPs in the Osaka/Seoul/Shanghai dataset*
- last_traceroute.csv   *# Last few hops information from traceroute in the Osaka/Seoul/Shanghai dataset*

