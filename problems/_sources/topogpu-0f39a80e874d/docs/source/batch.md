# Batch mode

Process many **same-sized** images per call; GPU work on one half of the batch overlaps
the CPU boundary-matrix reduction of the other half.

```python
tg = topogpu.create2D_batch(32, 512, 512, "uchar", bndmat_num=700)

tg.compute_PH_from_array(imgs)          # imgs: (B, H, W), C-contiguous, B <= 32
results = tg.get_results()              # list of B arrays, each (N_b, 7)

tg.compute_PH_from_files(paths, "uchar")  # list of <= 32 .jpg/.png/.raw paths
```
Results are valid until the next `compute_*` call; `get_results()` returns copies.
For volumes use `create3D_batch(B, X, Y, Z, dtype)` with a `(B, X, Y, Z)` array.