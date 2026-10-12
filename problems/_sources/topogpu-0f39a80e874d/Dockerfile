# One-stop build+dev image: CUDA 12.6 toolchain, GCC 12, Python 3.10–3.13 (via uv),
# build tools, auditwheel, Jupyter. manylinux_2_28-compatible base (glibc 2.28).
FROM nvidia/cuda:12.6.3-devel-rockylinux8

ENV PATH=/root/.local/bin:/opt/rh/gcc-toolset-12/root/usr/bin:/opt/python/cpython-3.12.15-linux-x86_64-gnu/bin:$PATH \
    LD_LIBRARY_PATH=/opt/rh/gcc-toolset-12/root/usr/lib64:/usr/local/cuda/lib64 \
    CC=gcc CXX=g++ \
    PIP_NO_CACHE_DIR=1 \
    UV_PYTHON_INSTALL_DIR=/opt/python

# System toolchain and libraries
RUN dnf -y install epel-release \
 && dnf -y install gcc-toolset-12 git which wget curl tar xz zip unzip \
        libgomp zlib-devel openssl-devel libffi-devel bzip2-devel \
 && dnf clean all

# uv + all target CPython interpreters
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
 && uv python install 3.10 3.11 3.12 3.13

# Build tools in every interpreter (Cython, numpy, build, wheel, setuptools, auditwheel)
RUN for v in 3.10 3.11 3.12 3.13; do \
      uv pip install --python "$v" --system --break-system-packages \
        "cython>=3.0.11" "numpy>=2.1" setuptools wheel build auditwheel ; \
    done

# Default interpreter for interactive use (Jupyter + test deps), Python 3.12
RUN uv pip install --python 3.12 --system --break-system-packages notebook pillow matplotlib cripser patchelf \
 && ln -sf "$(uv python find 3.12)" /usr/local/bin/python3 \
 && ln -sf "$(uv python find 3.12)" /usr/local/bin/python

WORKDIR /workspace
EXPOSE 8888
CMD ["bash"]