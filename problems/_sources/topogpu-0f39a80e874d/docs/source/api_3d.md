# 3D API

## `topogpu.create3D(imgSize_x, imgSize_y, imgSize_z, dtype, bndmat_num=2000, bx=0, by=0, bz=0, deviceID=-1, debug=False, verbose=False)`

Creates a TopoGPU object for single 3D volumes.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `imgSize_x` | int | – | volume height |
| `imgSize_y` | int | – | volume width |
| `imgSize_z` | int | – | volume depth |
| `dtype` | str | – | element type of the input: `'uchar'`/`'uint8'`, `'ushort'`/`'uint16'`, `'int'`/`'int32'`, `'float'`/`'float32'` |
| `bndmat_num` | int | 2000 | boundary-relation buffer per GPU block; increase if `Error: boundary matrix buffer limit reached` |
| `bx`, `by`, `bz` | int | 0 | CUDA block size per axis; 0 = chosen automatically |
| `deviceID` | int | -1 | CUDA device index; -1 = chosen automatically |
| `debug` | bool | False | print debug information |
| `verbose` | bool | False | print chunk/block/memory information |

Raises `TypeError` for an unsupported `dtype`.

### `configure(imgX, imgY, imgZ)`
Sets the size of the next input volume and uploads chunk/block tables to the GPU. Call before every compute. `imgY` may not exceed the `imgSize_y` given at creation.

### `compute_PH_from_file(filename, datatype)`
Loads a raw binary volume and computes persistent homology.

| Parameter | Type | Description |
|---|---|---|
| `filename` | str | path to the raw file |
| `datatype` | str | element type stored in the file (`'uchar'`, `'ushort'`, `'int'`, `'float'`) |

### `compute_PH_from_array(arr)`

| Parameter | Type | Description |
|---|---|---|
| `arr` | ndarray `(depth, height, width)` | input volume in raw-file memory order; converted to the backend dtype (`uint16` for `'uchar'`, `int32` for `'ushort'`/`'int'`, `float32` for `'float'`) and made C-contiguous if necessary |

### `reset()`
Frees the results of the last computation. Call after reading the results.

### `get_pairNum()`
Returns the number of persistence pairs of the last computation (int, includes the essential pair).

### `get_results()`
Returns a float32 array of shape `(N, 9)`: `dim, birth, death, birth_z, birth_y, birth_x, death_z, death_y, death_x`. The array is a view into internal memory — call `.copy()` before `reset()` or the next compute.

### `get_blockDims()`
Returns `(bx, by, bz)`, the CUDA block size in use.

### `get_chunkDims()`
Returns `(chunk_height, chunk_width, chunk_depth)`, the chunk size used for streaming.

---

## `topogpu.create3D_batch(batchSize, imgSize_x, imgSize_y, imgSize_z, dtype, bndmat_num=2000, bx=0, by=0, bz=0, deviceID=-1, debug=False, verbose=False)`

Creates a TopoGPU object that processes up to `batchSize` same-sized 3D volumes per call.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `batchSize` | int | – | maximum number of volumes per compute call |
| `imgSize_x`, `imgSize_y`, `imgSize_z` | int | – | volume height, width, depth (fixed for the object) |
| `dtype` | str | – | as in `create3D` |
| `bndmat_num` | int | 2000 | as in `create3D` |
| `bx`, `by`, `bz` | int | 0 | as in `create3D` |
| `deviceID` | int | -1 | as in `create3D` |
| `debug`, `verbose` | bool | False | as in `create3D` |

### `compute_PH_from_files(filenames, datatype)`

| Parameter | Type | Description |
|---|---|---|
| `filenames` | list of str | at most `batchSize` raw volume files, all of the creation size |
| `datatype` | str | element type stored in the files |

### `compute_PH_from_array(arr)`

| Parameter | Type | Description |
|---|---|---|
| `arr` | ndarray `(B, depth, height, width)` | `B ≤ batchSize` volumes in raw-file memory order; converted to the backend dtype and made C-contiguous if necessary |

Raises `ValueError` if `arr.ndim != 4`.

### `reset()`
Frees the results of the last computation. Also done automatically at the start of the next compute.

### `get_fileNum()`
Returns the number of volumes processed by the last compute (int).

### `get_pairNum(fileIdx)`
Returns the number of persistence pairs of volume `fileIdx` (0-based, int).

### `get_results(fileIdx=None)`
`fileIdx` given → float32 array `(N, 9)` for that volume, columns as in `create3D`. `fileIdx=None` → list of such arrays for all volumes, in input order. Returned arrays are copies.

### `get_blockDims()`
Returns `(bx, by, bz)`.

### `get_chunkDims()`
Returns `(chunk_height, chunk_width, chunk_depth)`.