# 2D API

## `topogpu.create2D(imgSize_x, imgSize_y, dtype, bndmat_num=2000, bx=0, by=0, deviceID=-1, debug=False, verbose=False)`

Creates a TopoGPU object for single 2D images.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `imgSize_x` | int | – | image height |
| `imgSize_y` | int | – | image width |
| `dtype` | str | – | element type of the input: `'uchar'`/`'uint8'`, `'ushort'`/`'uint16'`, `'int'`/`'int32'`, `'float'`/`'float32'` |
| `bndmat_num` | int | 2000 | boundary-relation buffer per GPU block; increase if `Error: boundary matrix buffer limit reached` |
| `bx`, `by` | int | 0 | CUDA block width / height; 0 = chosen automatically |
| `deviceID` | int | -1 | CUDA device index; -1 = chosen automatically |
| `debug` | bool | False | print debug information |
| `verbose` | bool | False | print chunk/block/memory information |

Raises `TypeError` for an unsupported `dtype`.

### `configure(imgX, imgY)`
Sets the size of the next input image and uploads chunk/block tables to the GPU. Call before every compute. `imgY` may not exceed the `imgSize_y` given at creation.

### `compute_PH_from_file(filename, datatype)`
Loads a `.jpg`/`.png` image or a raw binary file and computes persistent homology.

| Parameter | Type | Description |
|---|---|---|
| `filename` | str | path to the file |
| `datatype` | str | element type stored in the file (`'uchar'`, `'ushort'`, `'int'`, `'float'`); use `'uchar'` for jpg/png |

### `compute_PH_from_array(arr)`
Computes persistent homology from a NumPy array.

| Parameter | Type | Description |
|---|---|---|
| `arr` | ndarray `(H, W)` | input image; converted to the backend dtype (`uint16` for `'uchar'`, `int32` for `'ushort'`/`'int'`, `float32` for `'float'`) and made C-contiguous if necessary |

### `reset()`
Frees the results of the last computation. Call after reading the results.

### `get_pairNum()`
Returns the number of persistence pairs of the last computation (int, includes the essential pair).

### `get_results()`
Returns a float32 array of shape `(N, 7)`: `dim, birth, death, birth_y, birth_x, death_y, death_x`. The array is a view into internal memory — call `.copy()` before `reset()` or the next compute.

### `get_blockDims()`
Returns `(bx, by)`, the CUDA block size in use.

### `get_chunkDims()`
Returns `(chunk_height, chunk_width)`, the chunk size used for streaming.

---

## `topogpu.create2D_batch(batchSize, imgSize_x, imgSize_y, dtype, bndmat_num=2000, bx=0, by=0, deviceID=-1, debug=False, verbose=False)`

Creates a TopoGPU object that processes up to `batchSize` same-sized 2D images per call.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `batchSize` | int | – | maximum number of images per compute call |
| `imgSize_x` | int | – | image height (fixed for the object) |
| `imgSize_y` | int | – | image width (fixed for the object) |
| `dtype` | str | – | as in `create2D` |
| `bndmat_num` | int | 2000 | as in `create2D` |
| `bx`, `by` | int | 0 | as in `create2D` |
| `deviceID` | int | -1 | as in `create2D` |
| `debug`, `verbose` | bool | False | as in `create2D` |

### `compute_PH_from_files(filenames, datatype)`
Computes persistent homology of several image files.

| Parameter | Type | Description |
|---|---|---|
| `filenames` | list of str | at most `batchSize` paths (`.jpg`, `.png` or raw binary), all of the creation size |
| `datatype` | str | element type stored in the files |

### `compute_PH_from_array(arr)`

| Parameter | Type | Description |
|---|---|---|
| `arr` | ndarray `(B, H, W)` | `B ≤ batchSize` images; converted to the backend dtype and made C-contiguous if necessary |

Raises `ValueError` if `arr.ndim != 3`.

### `reset()`
Frees the results of the last computation. Also done automatically at the start of the next compute.

### `get_fileNum()`
Returns the number of images processed by the last compute (int).

### `get_pairNum(fileIdx)`
Returns the number of persistence pairs of image `fileIdx` (0-based, int).

### `get_results(fileIdx=None)`
`fileIdx` given → float32 array `(N, 7)` for that image, columns as in `create2D`. `fileIdx=None` → list of such arrays for all images, in input order. Returned arrays are copies.

### `get_blockDims()`
Returns `(bx, by)`.

### `get_chunkDims()`
Returns `(chunk_height, chunk_width)`.