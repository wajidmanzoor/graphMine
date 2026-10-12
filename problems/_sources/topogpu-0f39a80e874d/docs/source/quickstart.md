# Quick start

## A 2D image
```python
import numpy as np, topogpu
from PIL import Image

img = np.asarray(Image.open("scan.jpg").convert("L"))     # (H, W) uint8
tg  = topogpu.create2D(img.shape[0], img.shape[1], "uchar")
tg.configure(img.shape[0], img.shape[1])
tg.compute_PH_from_array(img)
diag = tg.get_results().copy()                              # (N, 7) float32
tg.reset()
```

## A 3D volume from a raw file
```python
tg = topogpu.create3D(256, 256, 256, "uchar", bndmat_num=2000)
tg.configure(256, 256, 256)
tg.compute_PH_from_file("aneurism_256x256x256_uint8.raw", "uchar")
diag = tg.get_results().copy()                              # (N, 9) float32
tg.reset()
```

## Result format
| Column | 2D `(N, 7)` | 3D `(N, 9)` |
|---|---|---|
| 0 | dim | dim |
| 1 | birth | birth |
| 2 | death | death |
| 3.. | birth_y, birth_x, death_y, death_x | birth_z, birth_y, birth_x, death_z, death_y, death_x |

The last row is the essential H0 pair `[0, min_value, inf, 0, …]`.
Pairs with `birth == death` are omitted.