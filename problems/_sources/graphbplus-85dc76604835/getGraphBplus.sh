#! /bin/sh

wget https://cs.txstate.edu/~burtscher/research/graphBplus/graphBplus_02.cu
wget https://cs.txstate.edu/~burtscher/research/graphBplus/graphBplus_02.cpp

nvcc -O3 -arch=sm_70 graphBplus_02.cu -o graphBplus_CUDA
g++ -O3 -march=native -fopenmp graphBplus_02.cpp -o graphBplus_OpenMP
g++ -O3 -march=native graphBplus_02.cpp -o graphBplus_SERIAL

wget https://cs.txstate.edu/~burtscher/research/graphBplus/graphBplus_mem.cu
wget https://cs.txstate.edu/~burtscher/research/graphBplus/graphBplus_mem.cpp

nvcc -O3 -arch=sm_70 graphBplus_mem.cu -o graphBplus_mem_CUDA
g++ -O3 -march=native -fopenmp graphBplus_mem.cpp -o graphBplus_mem_OpenMP

wget https://cs.txstate.edu/~burtscher/research/graphBplus/Table2_CUDA.txt
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Table2_OpenMP.txt
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Table2_SERIAL.txt

mv Table2_CUDA.txt Table2_CUDA.py
mv Table2_OpenMP.txt Table2_OpenMP.py
mv Table2_SERIAL.txt Table2_SERIAL.py

wget https://cs.txstate.edu/~burtscher/research/graphBplus/Table3_CUDA.txt
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Table3_OpenMP.txt
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Table3_SERIAL.txt

mv Table3_CUDA.txt Table3_CUDA.py
mv Table3_OpenMP.txt Table3_OpenMP.py
mv Table3_SERIAL.txt Table3_SERIAL.py

wget https://cs.txstate.edu/~burtscher/research/graphBplus/Table4_CUDA.txt
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Table4_OpenMP.txt

mv Table4_CUDA.txt Table4_CUDA.py
mv Table4_OpenMP.txt Table4_OpenMP.py

wget https://cs.txstate.edu/~burtscher/research/graphBplus/amazonMusicalInstruments_core5_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/amazonDigitalMusic_core5_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/amazonVideo_core5_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/all_wiki_edges.csv

wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Android_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Automotive_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Baby_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Books_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Electronics_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Games_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Garden_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Instruments_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Jewelry_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Music_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Outdoors_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_TV_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Video_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/Amazon_Vinyl_edges2.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/eopinion_edges.csv
wget https://cs.txstate.edu/~burtscher/research/graphBplus/slashdot_edges.csv

exit 0
