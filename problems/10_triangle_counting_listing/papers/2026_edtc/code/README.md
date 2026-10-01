
# EDTC: Exact triangle counting system for GPU dynamic graphs based on updated edges
Welcome to the EDTC project!
## Dependency:
```
CUDA Toolkit == 12.2
g++ == 9.4.0
```

## Build
```
cd EDTC
make
./tricount -f [original path] [batchSize] [batchNum] [gpuid] -Stream [batch path]
```

## Datasets
```
Available in [数据集](https://1drv.ms/f/s!AqB2dG2VW7jra9NhLE7G1o_DwnM?e=DGW1uh)
```

## Batch
```python
#  shuflle data
shuf graph.snap -o graph_shuf.snap
# Obtain partial rows of data.
head -n 10000000 graph_shuf.snap > head_graph.snap
tail -n 10000000 graph_shuf.snap > tail_graph.snap
# Generate DelBatch
sed -e 's/^/d\t/' head_graph.snap > deletions.stream
# Generate AddBatch
sed -e 's/^/a\t/' tail_graph.snap > additions.stream
# Generate StreamBatch
paste -d "\n" deletions.stream additions.stream > update.stream
```
