#! /bin/sh

input_dir=./paper_inputs
mkdir $input_dir
cd $input_dir

# get scripts to convert the files
#wget https://cs.txstate.edu/~burtscher/research/graphBplus/amazon_edges_users.txt
#mv amazon_edges_users.txt amazon_edges_users.py
# Using the provided version of ./scripts/amazon_edges_users.py
wget https://cs.txstate.edu/~burtscher/research/graphBplus/wikiRaw_edges_users.txt
mv wikiRaw_edges_users.txt wikiRaw_edges_users.py
wget https://cs.txstate.edu/~burtscher/research/graphBplus/TextToCsv.txt
mv TextToCsv.txt TextToCsv.py

pip install pandas
pip install numpy
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Books.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Electronics.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Movies_and_TV.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Baby.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Toys_and_Games.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Patio_Lawn_and_Garden.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Musical_Instruments.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Musical_Instruments_5.json.gz
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Clothing_Shoes_and_Jewelry.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Digital_Music.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Digital_Music_5.json.gz
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Sports_and_Outdoors.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Video_Games.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Video_Games_5.json.gz
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/CDs_and_Vinyl.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Automotive.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Appliances.csv
wget --no-check-certificate -nc https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Cell_Phones_and_Accessories.csv

wget https://snap.stanford.edu/data/soc-sign-epinions.txt.gz
gunzip soc-sign-epinions.txt.gz
python3 TextToCsv.py soc-sign-epinions.txt eopinion_edges.csv

wget https://snap.stanford.edu/data/soc-sign-Slashdot090221.txt.gz
gunzip soc-sign-Slashdot090221.txt.gz
python3 TextToCsv.py soc-sign-Slashdot090221.txt slashdot_edges.csv

wget https://snap.stanford.edu/data/wikiElec.ElecBs3.txt.gz
gunzip wikiElec.ElecBs3.txt.gz
python3 wikiRaw_edges_users.py
mv wiki_test_edges.csv all_wiki_edges.csv

python3 ../scripts/amazon_edges_users.py Books.csv
python3 ../scripts/amazon_edges_users.py Electronics.csv
python3 ../scripts/amazon_edges_users.py Movies_and_TV.csv
python3 ../scripts/amazon_edges_users.py Baby.csv
python3 ../scripts/amazon_edges_users.py Toys_and_Games.csv
python3 ../scripts/amazon_edges_users.py Patio_Lawn_and_Garden.csv
python3 ../scripts/amazon_edges_users.py Musical_Instruments.csv
python3 ../scripts/amazon_edges_users.py Musical_Instruments_5.json.gz
python3 ../scripts/amazon_edges_users.py Clothing_Shoes_and_Jewelry.csv
python3 ../scripts/amazon_edges_users.py Digital_Music.csv
python3 ../scripts/amazon_edges_users.py Digital_Music_5.json.gz
python3 ../scripts/amazon_edges_users.py Sports_and_Outdoors.csv
python3 ../scripts/amazon_edges_users.py Video_Games.csv
python3 ../scripts/amazon_edges_users.py Video_Games_5.json.gz
python3 ../scripts/amazon_edges_users.py CDs_and_Vinyl.csv
python3 ../scripts/amazon_edges_users.py Automotive.csv
python3 ../scripts/amazon_edges_users.py Appliances.csv
python3 ../scripts/amazon_edges_users.py Cell_Phones_and_Accessories.csv

rm -f Books.csv
rm -f Electronics.csv
rm -f Movies_and_TV.csv
rm -f Baby.csv
rm -f Toys_and_Games.csv
rm -f Patio_Lawn_and_Garden.csv
rm -f Musical_Instruments.csv
rm -f Musical_Instruments_5.json.gz
rm -f Clothing_Shoes_and_Jewelry.csv
rm -f Digital_Music.csv
rm -f Digital_Music_5.json.gz
rm -f Sports_and_Outdoors.csv
rm -f Movies_and_TV.csv
rm -f Video_Games.csv
rm -f Video_Games_5.json.gz
rm -f CDs_and_Vinyl.csv
rm -f Automotive.csv
rm -f Appliances.csv
rm -f Cell_Phones_and_Accessories.csv
rm -f wikiElec.ElecBs3.txt
rm -f soc-sign-Slashdot090221.txt
rm -f soc-sign-epinions.txt
rm -f wiki_test_users.csv

rm wikiRaw_edges_users.py
rm TextToCsv.py

exit 0

