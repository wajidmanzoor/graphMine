# Command-line tool

```bash
topoGPU -filename volume.raw -datatype ushort -height 512 -width 416 -depth 112 -bufSize 3000 -out result.txt
```
| Flag | Description |
|---|---|
| `-filename` | input raw file |
| `-datatype` | `uchar`, `ushort`, `int`, `float` |
| `-height -width -depth` | volume size (omit `-depth` for 2D) |
| `-bufSize` | boundary buffer per block (default 2000) |
| `-blockSize_x/_y/_z` | CUDA block size (optional) |
| `-out` | output text file, one pair per line |