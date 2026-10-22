/* Placeholder board layer: links the firmware without the hardware layer. Every call fails (-1), so a
 * firmware built with it never believes it has written Flash. Replaced by board_h7.c on the board. */
#include "board.h"

int board_flash_write(uint32_t addr, const void *src, uint32_t n)
{
    (void)addr;
    (void)src;
    (void)n;
    return -1;
}

int board_flash_flush(void)
{
    return -1;
}

int board_flash_erase_sector(uint32_t addr)
{
    (void)addr;
    return -1;
}

void board_init(void)
{
}

uint32_t board_time_us(void)
{
    return 0;
}

void board_uart_tx(const uint8_t *p, uint32_t n)
{
    (void)p;
    (void)n;
}

void board_set_rx_handler(void (*h)(const uint8_t *p, uint32_t n))
{
    (void)h;
}

void board_wait(void)
{
}
