#!/bin/bash
# FreeRTOS build of the LDA main line (report 35.36): emg_rtl_task (the 35.33 sources) with app_rt_rtos.c in place of
# app_rt_lda.c, plus the FreeRTOS V10.6.2 kernel of STM32CubeH7 V1.13.0 (ARM_CM4F port, no heap file: static only).
# STRESS=1 bash build_rtos_stm32.sh -> build/rtos_stress with RTOS_STRESS (the learn task saturates the CPU, report 35.37)
OUT=rtos; [ "${STRESS:-0}" = 1 ] && OUT=rtos_stress
B=/c/Users/kirit/AppData/Local/stm32cube/bundles
export PATH="$B/gnu-tools-for-stm32/14.3.1+st.2/bin:$B/cmake/4.4.0+st.1/bin:$B/ninja/1.13.2+st.1/bin:$PATH"
F=/c/Users/kirit/STM32Cube/Repository/STM32Cube_FW_H7_V1.13.0/Middlewares/Third_Party/FreeRTOS/Source
cd /d/stm32/blink_leaf || exit 1
[ -d emg_leaf ] && { echo "emg_leaf already exists, stop"; exit 1; }
rm -rf emg_rtos && cp -r emg_rtl_task emg_rtos && rm emg_rtos/app_rt_lda.c
cp emg_rtos_src/app_rt_rtos.c emg_rtos_src/FreeRTOSConfig.h emg_rtos/
[ "$OUT" = rtos_stress ] && sed -i '1i #define RTOS_STRESS 1' emg_rtos/app_rt_rtos.c
cp $F/tasks.c $F/list.c $F/queue.c $F/stream_buffer.c $F/include/*.h emg_rtos/
cp $F/portable/GCC/ARM_CM4F/port.c emg_rtos/port.c
cp $F/portable/GCC/ARM_CM4F/portmacro.h emg_rtos/
mv emg emg_leaf && mv emg_rtos emg
rm -rf build/$OUT
cmake -S . -B build/$OUT -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/gcc-arm-none-eabi.cmake -DCMAKE_BUILD_TYPE=Release -DEMG_APP_RT=ON 2>&1 | tail -1
cmake --build build/$OUT 2>&1 | grep -iE "warning|error|RAM:|FLASH:|DTCM" | head -30
mv emg emg_rtos && mv emg_leaf emg
ls emg | head -2
arm-none-eabi-size build/$OUT/blink.elf
