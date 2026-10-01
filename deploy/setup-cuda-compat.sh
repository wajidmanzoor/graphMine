#!/usr/bin/env bash
set -euo pipefail

# vLLM 0.30's PyPI wheel is built with CUDA 13.0. This pinned NVIDIA
# forward-compatibility package lets a supported professional GPU host with a
# CUDA 12.x driver run that userspace without replacing the kernel driver.
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${repo_dir}/.cuda-compat-13-0"
compat_dir="${target}/usr/local/cuda-13.0/compat"
package="cuda-compat-13-0_580.178.04-1ubuntu1_amd64.deb"
package_url="https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/${package}"
package_sha256="f7e29a545c1334bb5ca4b054213de9c9ceb70f8bf561aa214075020c4e0b60cf"

if [[ "$(uname -m)" != "x86_64" ]] || ! grep -q '^ID=ubuntu$' /etc/os-release; then
  echo "Automatic local CUDA compatibility setup supports x86_64 Ubuntu only." >&2
  echo "Install NVIDIA's cuda-compat-13-0 package for this host instead." >&2
  exit 1
fi
if [[ -f "${compat_dir}/libcuda.so.580.178.04" ]]; then
  echo "CUDA 13.0 forward-compatibility libraries are already available at ${compat_dir}"
  exit 0
fi

download_dir="$(mktemp -d)"
trap 'rm -rf "${download_dir}"' EXIT
curl --fail --location --output "${download_dir}/${package}" "${package_url}"
printf '%s  %s\n' "${package_sha256}" "${download_dir}/${package}" | sha256sum --check
mkdir -p "${target}"
dpkg-deb --extract "${download_dir}/${package}" "${target}"
echo "Installed local CUDA compatibility libraries at ${compat_dir}"
