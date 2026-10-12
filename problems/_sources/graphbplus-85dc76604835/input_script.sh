#! /bin/sh

# script to convert the files
wget https://cs.txstate.edu/~burtscher/research/graphBplus/amazon_edges_users.txt
mv amazon_edges_users.txt amazon_edges_users.py
wget https://cs.txstate.edu/~burtscher/research/graphBplus/wikiRaw_edges_users.txt
mv wikiRaw_edges_users.txt wikiRaw_edges_users.py
wget https://cs.txstate.edu/~burtscher/research/graphBplus/TextToCsv.txt
mv TextToCsv.txt TextToCsv.py

pip install pandas
pip install numpy
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Books.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Apps_for_Android.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Electronics.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Movies_and_TV.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Baby.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Toys_and_Games.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Patio_Lawn_and_Garden.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Musical_Instruments.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/reviews_Musical_Instruments_5.json.gz
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Clothing_Shoes_and_Jewelry.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Digital_Music.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/reviews_Digital_Music_5.json.gz
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Sports_and_Outdoors.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Movies_and_TV.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Video_Games.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/reviews_Video_Games_5.json.gz
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_CDs_and_Vinyl.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Automotive.csv
wget http://snap.stanford.edu/data/amazon/productGraph/categoryFiles/ratings_Amazon_Instant_Video.csv

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

python3 amazon_edges_users.py ratings_Books.csv
python3 amazon_edges_users.py ratings_Apps_for_Android.csv
python3 amazon_edges_users.py ratings_Electronics.csv
python3 amazon_edges_users.py ratings_Movies_and_TV.csv
python3 amazon_edges_users.py ratings_Baby.csv
python3 amazon_edges_users.py ratings_Toys_and_Games.csv
python3 amazon_edges_users.py ratings_Patio_Lawn_and_Garden.csv
python3 amazon_edges_users.py ratings_Musical_Instruments.csv
python3 amazon_edges_users.py reviews_Musical_Instruments_5.json.gz
python3 amazon_edges_users.py ratings_Clothing_Shoes_and_Jewelry.csv
python3 amazon_edges_users.py ratings_Digital_Music.csv
python3 amazon_edges_users.py reviews_Digital_Music_5.json.gz
python3 amazon_edges_users.py ratings_Sports_and_Outdoors.csv
python3 amazon_edges_users.py ratings_Movies_and_TV.csv
python3 amazon_edges_users.py ratings_Video_Games.csv
python3 amazon_edges_users.py reviews_Video_Games_5.json.gz
python3 amazon_edges_users.py ratings_CDs_and_Vinyl.csv
python3 amazon_edges_users.py ratings_Automotive.csv
python3 amazon_edges_users.py ratings_Amazon_Instant_Video.csv
mv amazonVideoGames_core5_edges2.csv amazonVideo_core5_edges2.csv

rm -f ratings_Books.csv
rm -f ratings_Apps_for_Android.csv
rm -f ratings_Electronics.csv
rm -f ratings_Movies_and_TV.csv
rm -f ratings_Baby.csv
rm -f ratings_Toys_and_Games.csv
rm -f ratings_Patio_Lawn_and_Garden.csv
rm -f ratings_Musical_Instruments.csv
rm -f reviews_Musical_Instruments_5.json.gz
rm -f ratings_Clothing_Shoes_and_Jewelry.csv
rm -f ratings_Digital_Music.csv
rm -f reviews_Digital_Music_5.json.gz
rm -f ratings_Sports_and_Outdoors.csv
rm -f ratings_Movies_and_TV.csv
rm -f ratings_Video_Games.csv
rm -f reviews_Video_Games_5.json.gz
rm -f ratings_CDs_and_Vinyl.csv
rm -f ratings_Automotive.csv
rm -f ratings_Amazon_Instant_Video.csv
rm -f wikiElec.ElecBs3.txt
rm -f soc-sign-Slashdot090221.txt
rm -f soc-sign-epinions.txt
rm -f ratings_Movies_and_TV.csv.1

rm -f Amazon_Books_users.csv
rm -f Amazon_Android_users.csv
rm -f Amazon_Electronics_users.csv
rm -f Amazon_TV_users.csv
rm -f Amazon_Baby_users.csv
rm -f Amazon_Games_users.csv
rm -f Amazon_Garden_users.csv
rm -f Amazon_Instruments_users.csv
rm -f amazonMusicalInstruments_core5_users.csv
rm -f Amazon_Jewelry_users.csv
rm -f Amazon_Music_users.csv
rm -f amazonDigitalMusic_core5_users.csv
rm -f Amazon_Outdoors_users.csv
rm -f Amazon_TV_users.csv
rm -f Amazon_Games_users.csv
rm -f amazonVideoGames_core5_users.csv
rm -f Amazon_Vinyl_users.csv
rm -f Amazon_Automotive_users.csv
rm -f Amazon_Video_users.csv
rm -f wiki_test_users.csv

exit 0

