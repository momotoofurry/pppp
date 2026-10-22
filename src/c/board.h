/* Board layer (STM32H7) used by the portable firmware. The real implementation is board_h7.c (hardware layer,
 * needs the CMSIS device headers); board_stub.c only lets the firmware link without it. */
#pragma once
#include <stdint.h>

/* Program n bytes at Flash address addr (inside an erased sector). The caller writes each byte once, in
 * increasing address order, except for a final write at a lower address (the one-shot header): the
 * implementation buffers 32-byte Flash words and pads the last one with 0xFF. Returns 0 on success. */
int board_flash_write(uint32_t addr, const void *src, uint32_t n);
/* finish pending Flash words (call after the last board_flash_write of an image); returns 0 on success */
int board_flash_flush(void);
/* erase the 128 KB sector that contains addr; returns 0 on success */
int board_flash_erase_sector(uint32_t addr);

/* clocks, caches, MPU, the time base and the UART to the PC */
void board_init(void);
/* microseconds since board_init() (wraps after ~71 min) */
uint32_t board_time_us(void);
/* send bytes to the PC (blocking or queued) */
void board_uart_tx(const uint8_t *p, uint32_t n);
/* h is called with the bytes received from the PC, from interrupt context (UART / DMA) */
void board_set_rx_handler(void (*h)(const uint8_t *p, uint32_t n));
/* sleep until the next interrupt */
void board_wait(void);
