for file in ibm01.hgr ibm02.hgr ibm03.hgr ibm04.hgr ibm05.hgr ibm06.hgr ibm07.hgr ibm08.hgr ibm09.hgr ibm10.hgr ibm11.hgr ibm12.hgr ibm13.hgr ibm14.hgr ibm15.hgr ibm16.hgr ibm17.hgr ibm18.hgr
do
    python test.py --filename $file --modelname model.pt --use_sketch
done