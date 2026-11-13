#!/bin/bash
# board build of the MLP vs LDA bench (report 35.39): emg_lda_soft's board layer + build/mlp_bench (check_mlp_bench.py)
B=/c/Users/kirit/AppData/Local/stm32cube/bundles
export PATH="$B/gnu-tools-for-stm32/14.3.1+st.2/bin:$B/cmake/4.4.0+st.1/bin:$B/ninja/1.13.2+st.1/bin:$PATH"
cd /d/stm32/blink_leaf || exit 1
[ -d emg_leaf ] && { echo "emg_leaf already exists, stop"; exit 1; }
rm -rf emg_mlp && mkdir emg_mlp
cp emg_lda_soft/board_hal.c emg_lda_soft/bench.h emg_lda_soft/board.h emg_lda_soft/app_rt.h emg_mlp/
for f in mlp_bench.c mlp.c mlp.h ldacal.c ldacal.h mlp_rows.h mlp_weights.h; do
  MSYS_NO_PATHCONV=1 wsl -- cp /home/momo1234/model-leaf/build/mlp_bench/$f /mnt/d/stm32/blink_leaf/emg_mlp/$f
done
grep -c "LD_CLASSES 8" emg_mlp/ldacal.h
mv emg emg_leaf && mv emg_mlp emg
rm -rf build/mlp
cmake -S . -B build/mlp -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/gcc-arm-none-eabi.cmake -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -1
cmake --build build/mlp 2>&1 | grep -iE "warning|error|RAM:|FLASH:|DTCM" | head -20
mv emg emg_mlp && mv emg_leaf emg
ls emg | head -2
arm-none-eabi-size build/mlp/blink.elf
