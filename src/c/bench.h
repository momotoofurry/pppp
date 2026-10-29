/* First on-board timing of the firmware v2 chain (bench.c), portable: the platform layer is board_hal.c on the
 * NUCLEO-H753ZI (CubeMX / HAL project) or bench_pc.c on the PC (same output, for the checksum comparison).
 * The one-shot image lives at BENCH_IMAGE_BASE: Flash bank 2, sector 7 (the last 128 KB of the 2 MB part), written
 * through board_flash_write(), which takes absolute addresses there (the PC layer maps them onto a RAM array). */
#pragma once
#include <stdint.h>

#define BENCH_IMAGE_BASE 0x081E0000u
#define BENCH_IMAGE_BYTES (128u * 1024u)

/* the readable one-shot image (BENCH_IMAGE_BASE on the board), or 0 if the platform cannot provide it (e.g. the
 * program would overlap the sector) */
const uint8_t *bench_image(void);
uint32_t bench_cycles(void);                 /* free-running cycle counter (DWT on the board, 0 on the PC) */
void bench_print(const char *s);             /* text to the PC (UART on the board, stdout on the PC) */
const char *bench_platform(void);            /* one line: what the platform is (clock, caches) */

/* runs the whole bench once and prints the results; cpu_hz converts cycles to microseconds (0: no timing) */
void bench_run(uint32_t cpu_hz);
