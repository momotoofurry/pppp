# Reproducible Linux environment for the whole project (stages 1-4).
#
# Ubuntu 22.04 gives the same toolchains as the WSL2 distro used for the first ARM build:
#   gcc 11.4 (PC C check), arm-none-eabi-gcc 10.3.1 + newlib-nano (Cortex-M7 build).
# Python 3.12.3 (same release as the Windows venv, conda-forge build) is installed by uv into /opt/venv.
#
# Build from the repo root:  docker/run.sh build
# The image holds only tools; code, upstream data and results are bind-mounted at /work.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates git gcc libc6-dev make \
      gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONDONTWRITEBYTECODE=1
RUN uv venv --python 3.12.3 /opt/venv \
 && chmod -R a+rX /opt/python /opt/venv
COPY docker/requirements.txt /tmp/requirements.txt
RUN uv pip install --python /opt/venv/bin/python --no-cache -r /tmp/requirements.txt

WORKDIR /work
CMD ["bash"]
