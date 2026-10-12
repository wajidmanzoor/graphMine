# Third-Party Licenses

TopoGPU is released under the MIT License (see `LICENSE`). It incorporates the following third-party components, which are distributed under their own licenses. Copies of the license texts are included in the repository at the paths listed.

| Component | Version | License | Source | License file |
|---|---|---|---|---|
| PHAT – Persistent Homology Algorithms Toolbox | 1.7 | LGPL-3.0 | https://bitbucket.org/phat-code/phat | `third_party/phat/LICENSE` |
| CTPL – C++ Thread Pool Library | 0.0.2 | Apache-2.0 | https://github.com/vit-vit/CTPL | `third_party/CTPL_LICENSE` |
| stb_image | 2.30 | MIT / Public Domain (dual) | https://github.com/nothings/stb | `third_party/stb_LICENSE` |
| NVIDIA CUDA Toolkit (cudart, Thrust/CCCL) | 12.x | NVIDIA CUDA EULA; CCCL: Apache-2.0 with LLVM exception | https://developer.nvidia.com/cuda-toolkit | not redistributed in this repository |

## Notes

- **PHAT (LGPL-3.0).** PHAT is a header-only template library; its code is compiled into the TopoGPU binary and Python extension. In accordance with LGPL-3.0 §3, this notice identifies the use of PHAT, and the LGPL-3.0 text is provided at `third_party/phat/LICENSE`. PHAT is used unmodified. Users may obtain the PHAT source from the link above.
- **CTPL (Apache-2.0).** Used unmodified; the Apache-2.0 license and NOTICE requirements are satisfied by the included license file.
- **stb_image (MIT / Public Domain).** Used unmodified under the MIT option.
- **CUDA runtime.** The pip wheels do not bundle `libcudart`; it is installed from the `nvidia-cuda-runtime-cu12` package under NVIDIA's EULA. The Docker image is built on the `nvidia/cuda` base image and is subject to NVIDIA's container license terms.

## Reference

If you use TopoGPU, please cite:

F. Wang, H. Wagner, R. Chowdhury, and C. Chen, "GPU-Accelerated Computation of Persistent Homology for Topological Analysis of Image Data," *IEEE Transactions on Pattern Analysis and Machine Intelligence*, 2026. doi:10.1109/TPAMI.2026.3741473