#!/bin/bash

NUM=1 #number of time to run to calucalte average execution time!

#! SRCNAME="gpuSteiner3_sk2_new0_2Dpull2 gpuSteiner3_sk2_new0_2Dpull3 gpuSteiner3_sk2_new0_2Dpull3_sh gpuSteiner6-oddAgain"
SRCNAME="gpuSteiner6-oddAgainWithKtimer2Sh3" #32
TIMEOUT="timeout 30m"
INPUTDIR="tcSelected" #tcSelected tcScaleW tcScaleWND

for SRC in $SRCNAME
do
  FOL=`date +'%m%d%H%m%S'`
  mkdir $FOL
  NAME=$SRCNAME
  #! NAME=$(echo $SRC | awk -F "gpuSteiner" '{print $2}')
  nvcc -o "$SRC.out" "$SRC.cu" -Wno-deprecated-gpu-targets -std=c++11
  echo "Filename, GPU Time(ms), -- compiled! "
  echo $SRC $NAME
  for file in $INPUTDIR/*.txt  #
  do
    SUM=0
    for i in {1..$NUM} #change to run multiple times
    do
      #! fileName=$(echo $file | awk -F'/' '{print $(NF)}' | cut -f1 -d.)
      fileName=`echo $file | cut -d'/' -f2 | cut -d'.' -f1` #may need to change it to awk
      $TIMEOUT ./$SRC.out 64 < $file > $FOL/$fileName.output
      sleep 1
      echo $fileName $(cat $FOL/$NUM/$fileName.output)
    done
  done
  mv $FOL $FOL$NAME
done

SRCNAME="2approxCpu2"
for SRC in $SRCNAME
do
  FOL=`date +'%m%d%H%m%S'`
  mkdir -p $FOL/{1..$NUM}
  NAME=$SRCNAME
  #! NAME=$(echo $SRC | awk -F "gpuSteiner" '{print $2}')
  g++ -O3 -o "$SRC.out" "$SRC.cpp"
  echo "Filename, GPU Time(ms), -- compiled! "
  echo $SRC $NAME
  for file in $INPUTDIR/*.gr
  do
    SUM=0
    for i in {1..$NUM} #change to run multiple times
    do
      fileName=$(echo $file | awk -F'/' '{print $(NF)}' | cut -f1 -d.)
      fileName=`echo $file | cut -d'/' -f2 | cut -d'.' -f1` #may need to change it to awk
      $TIMEOUT ./$SRC.out < $file > $FOL/$NUM/$fileName.output
      sleep 1
      echo $fileName $(cat $FOL/$NUM/$fileName.output)
    done
    #echo $fileName $(cat $FOL/$fileName.output)
  done
  mv $FOL $FOL$NAME
done
