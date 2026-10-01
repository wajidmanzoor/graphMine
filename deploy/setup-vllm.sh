#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m venv "${repo_dir}/.venv-vllm"
"${repo_dir}/.venv-vllm/bin/python" -m pip install --upgrade pip
"${repo_dir}/.venv-vllm/bin/pip" install -r "${repo_dir}/deploy/requirements-vllm.txt"
"${repo_dir}/.venv-vllm/bin/vllm" --version

if ! "${repo_dir}/.venv-vllm/bin/python" -c \
  'import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))'; then
  echo "The vLLM CUDA runtime is newer than the installed driver; setting up local forward compatibility."
  "${repo_dir}/deploy/setup-cuda-compat.sh"
  compat_dir="${repo_dir}/.cuda-compat-13-0/usr/local/cuda-13.0/compat"
  LD_LIBRARY_PATH="${compat_dir}" \
    "${repo_dir}/.venv-vllm/bin/python" -c \
    'import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))'
fi
