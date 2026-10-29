/* Route-B firmware for the CubeMX / HAL project (app_rt.c): the real-time loop rt.c on the board, samples from the
 * PC over USART3 (the ST-LINK virtual COM port). main.c calls app_rt_run() instead of bench_run() when the project is
 * built with -DEMG_RT (CMake option EMG_APP_RT). */
#pragma once
#include <stdint.h>

#define APP_RT_BAUD 921600u

void app_rt_run(void);                       /* never returns */

/* board_hal.c, route B only */
void board_rx_start(uint32_t baud);
uint32_t board_rx_overflow(void);
uint32_t board_rx_errors(void);
