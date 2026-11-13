#!/bin/bash
# FreeRTOS build of the LDA main line (report 35.36): emg_rtl_task (the 35.33 sources) with app_rt_rtos.c in place of
# app_rt_lda.c, plus the FreeRTOS V10.6.2 kernel of STM32CubeH7 V1.13.0 (ARM_CM4F port, no heap file: static only).
B=/c/Users/kirit/AppData/Local/stm32cube/bundles
export PATH="$B/gnu-tools-for-stm32/14.3.1+st.2/bin:$B/cmake/4.4.0+st.1/bin:$B/ninja/1.13.2+st.1/bin:$PATH"
F=/c/Users/kirit/STM32Cube/Repository/STM32Cube_FW_H7_V1.13.0/Middlewares/Third_Party/FreeRTOS/Source
cd /d/stm32/blink_leaf || exit 1
[ -d emg_leaf ] && { echo "emg_leaf already exists, stop"; exit 1; }
rm -rf emg_rtos && cp -r emg_rtl_task emg_rtos && rm emg_rtos/app_rt_lda.c
cp emg_rtos_src/app_rt_rtos.c emg_rtos_src/FreeRTOSConfig.h emg_rtos/
cp $F/tasks.c $F/list.c $F/queue.c $F/stream_buffer.c $F/include/*.h emg_rtos/
cp $F/portable/GCC/ARM_CM4F/port.c emg_rtos/port.c
cp $F/portable/GCC/ARM_CM4F/portmacro.h emg_rtos/
mv emg emg_leaf && mv emg_rtos emg
rm -rf build/rtos
cmake -S . -B build/rtos -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/gcc-arm-none-eabi.cmake -DCMAKE_BUILD_TYPE=Release -DEMG_APP_RT=ON 2>&1 | tail -1
cmake --build build/rtos 2>&1 | grep -iE "warning|error|RAM:|FLASH:|DTCM" | head -30
mv emg emg_rtos && mv emg_leaf emg
ls emg | head -2
arm-none-eabi-size build/rtos/blink.elf
