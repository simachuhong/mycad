# T2 aarch64 QEMU regression prep image (todo 15).
# Base ubuntu:24.04 = glibc 2.39 — the lowest glibc the pinned PySide6
# 6.12.0 aarch64 wheel accepts (manylinux_2_39); bookworm (2.36) is a
# documented failing probe. GL/xkb/glib libs serve the offscreen Qt lane.
FROM docker.m.daocloud.io/library/ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      libgl1 libegl1 libxkbcommon0 libglib2.0-0 libfreetype6 libfontconfig1 libdbus-1-3 libgl1-mesa-dri libegl-mesa0 python3 python3-pip python3.12-venv git \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --quiet --break-system-packages uv
