#!/bin/bash
# Build the STM32H753 firmware (NUCLEO-H753ZI) from the repo's src/c (report 35.102).
#
#   bash firmware/build_fw.sh <src/c directory> <output directory> [preset]
#
# Runs in Git Bash on Windows with STM32CubeCLT / the VS Code STM32 extension's bundles (gnu-tools-for-stm32 14.3.1,
# cmake, ninja). Set STM32_BUNDLES if they are not in the default place.
# The board project (CubeMX: clocks, UART, HAL; CMake) is firmware/stm32h753/; this script copies it to a temporary
# folder, puts the EMG sources into its emg/ folder (CMakeLists.txt compiles emg/*.c), builds, and writes
# blink.elf / blink.map / blink.bin (the flash image, objcopy -O binary) and its md5 to the output directory.
#
# presets
#   s7     (default) the real-time LDA loop with 9 classes as on the board for the S7 self-test:
#          -DEMG_APP_RT=ON, -DLD_CLASSES=9 -DDC_CLASSES=9 -DRTL_LABEL_MAX=810, Release (-Os -g)
#   s7_4ch native 4-channel (40-dim) build of the same loop (-DFE_CH=4 -DLD_DIM=40; PK_CH stays 8 so
#          TrignoBridge and recorded 8-col streams work unchanged, using ch0..3 only)
#
# The frozen board firmware rtl_task_s7f is the git tag rtl_task_s7f (commit 37ac42a); its image md5 is
# 4d60a4f38b54c83d341f5f33c355bd9e (26056 bytes). To rebuild it exactly:
#   git worktree add ../s7f rtl_task_s7f            (or: git archive rtl_task_s7f src/c | tar -x -C <dir>)
#   bash firmware/build_fw.sh ../s7f/src/c out_s7f
set -e
SRC=$1
OUT=$2
PRESET=${3:-s7}
[ -d "$SRC" ] && [ -n "$OUT" ] || { echo "usage: bash firmware/build_fw.sh <src/c directory> <output directory> [s7|s7_4ch]"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
B=${STM32_BUNDLES:-/c/Users/$USERNAME/AppData/Local/stm32cube/bundles}
GCC=$(ls -d "$B"/gnu-tools-for-stm32/*/bin 2>/dev/null | sort | tail -1)
CMK=$(ls -d "$B"/cmake/*/bin 2>/dev/null | sort | tail -1)
NIN=$(ls -d "$B"/ninja/*/bin 2>/dev/null | sort | tail -1)
[ -n "$GCC" ] && [ -n "$CMK" ] && [ -n "$NIN" ] || { echo "STM32 bundles not found under $B (set STM32_BUNDLES)"; exit 1; }
export PATH="$GCC:$CMK:$NIN:$PATH"
echo "toolchain: $(arm-none-eabi-gcc --version | head -1)"

# the EMG sources of the real-time LDA loop (the files of the board's emg_rtl_task folder)
FILES="app_rt.h app_rt_lda.c bench.h board.h board_hal.c decision.c decision.h features.c features.h ldacal.c ldacal.h
protocol.c protocol.h rt_lda.c rt_lda.h"
case $PRESET in
  s7) FLAGS="-DRTL_LABEL_MAX=810 -DLD_CLASSES=9 -DDC_CLASSES=9" ;;
  s7_4ch) FLAGS="-DFE_CH=4 -DLD_DIM=40 -DRTL_LABEL_MAX=810 -DLD_CLASSES=9 -DDC_CLASSES=9" ;;
  *) echo "unknown preset $PRESET"; exit 1 ;;
esac

W=$(mktemp -d)
cp -r "$HERE/stm32h753/." "$W/"
mkdir -p "$W/emg"
for f in $FILES; do cp "$SRC/$f" "$W/emg/"; done
cd "$W"
cmake -S . -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/gcc-arm-none-eabi.cmake -DCMAKE_BUILD_TYPE=Release \
  -DEMG_APP_RT=ON "-DCMAKE_C_FLAGS=$FLAGS" > cmake_configure.log 2>&1 || { cat cmake_configure.log; exit 1; }
cmake --build build 2>&1 | grep -iE "warning|error|RAM:|FLASH:|DTCM" | head -30 || true
[ -f build/blink.elf ] || { echo "build failed"; exit 1; }
cd - > /dev/null
mkdir -p "$OUT"
cp "$W/build/blink.elf" "$W/build/blink.map" "$OUT/"
arm-none-eabi-objcopy -O binary "$OUT/blink.elf" "$OUT/blink.bin"
arm-none-eabi-size "$OUT/blink.elf"
echo "image: $(stat -c %s "$OUT/blink.bin") bytes, md5 $(md5sum < "$OUT/blink.bin" | cut -d' ' -f1)"
rm -rf "$W"
