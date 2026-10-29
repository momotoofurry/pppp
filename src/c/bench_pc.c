/* PC run of bench.c: the board layer with the Flash sector as a RAM array (erase = 0xFF, programming can only
 * clear bits, as on Flash) and stdout; no cycle counter. The board prints the same one-shot hash, predictions and
 * votes hash when it computed the same thing (src/check_bench.py builds and runs this in the container).
 * Build: gcc -O2 -std=gnu11 -I<data headers> bench_pc.c bench.c selfcal.c kmeans.c rf_train.c features.c adapt.c
 *        oneshot.c -lm */
#include <stdio.h>
#include <string.h>

#include "bench.h"
#include "board.h"

static uint8_t s_flash[BENCH_IMAGE_BYTES];

int board_flash_erase_sector(uint32_t addr)
{
    if (addr != BENCH_IMAGE_BASE)
        return -1;
    memset(s_flash, 0xFF, sizeof s_flash);
    return 0;
}

int board_flash_write(uint32_t addr, const void *src, uint32_t n)
{
    if (addr < BENCH_IMAGE_BASE || addr - BENCH_IMAGE_BASE + n > BENCH_IMAGE_BYTES)
        return -1;
    const uint8_t *p = src;
    for (uint32_t i = 0; i < n; i++)
        s_flash[addr - BENCH_IMAGE_BASE + i] &= p[i];
    return 0;
}

int board_flash_flush(void)
{
    return 0;
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
    fwrite(p, 1, n, stdout);
}

void board_set_rx_handler(void (*h)(const uint8_t *p, uint32_t n))
{
    (void)h;
}

void board_wait(void)
{
}

const uint8_t *bench_image(void)
{
    return s_flash;
}

uint32_t bench_cycles(void)
{
    return 0;
}

void bench_print(const char *s)
{
    fputs(s, stdout);
}

const char *bench_platform(void)
{
    return "PC";
}

int main(int argc, char **argv)
{
    bench_run(0);
    if (argc > 1) {                          /* bench_pc <file>: the one-shot image (to compare with the board's) */
        FILE *f = fopen(argv[1], "wb");
        if (!f)
            return 1;
        fwrite(s_flash, 1, sizeof s_flash, f);
        fclose(f);
    }
    return 0;
}
