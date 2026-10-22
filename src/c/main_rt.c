/* Firmware for route B (STM32H7): the PC forwards Trigno samples over the UART, the MCU does everything else.
 *
 * Flash: the 50 pre-trained trees (pre_model.h) and, after the user's one-shot calibration, the one-shot image in
 * the reserved last sector (oneshot.c). The board layer (board.h: board_h7.c on the board, board_stub.c to link
 * without it) calls rt_rx() from its UART receive interrupt; the main loop runs rt_idle() (one-shot calibration,
 * self-calibration) and sleeps. See rt.h for the protocol and the two execution contexts.
 */
#include <stdint.h>

#include "board.h"
#include "pre_model.h"
#include "rt.h"

extern const uint8_t _oneshot_image[], _oneshot_bytes[];

static int flash_write(void *ctx, uint32_t off, const void *src, uint32_t n)
{
    (void)ctx;
    return board_flash_write((uint32_t)_oneshot_image + off, src, n);
}

static int flash_erase(void)
{
    return board_flash_erase_sector((uint32_t)_oneshot_image);
}

static const os_table_t s_pre = {pre_roots, pre_feat, pre_thr, pre_left, pre_right, PRE_N_INTERNAL};

int main(void)
{
    static os_writer_t writer;
    writer.write = flash_write;
    writer.ctx = 0;
    writer.capacity = (uint32_t)_oneshot_bytes;
    board_init();
    const rt_config_t cfg = {
        .pre = &s_pre, .writer = &writer, .image = _oneshot_image, .flash_erase = flash_erase,
        .flash_flush = board_flash_flush, .tx = board_uart_tx, .now_us = board_time_us,
        .warmup = 2,                /* 200 ms after a gap: the band-pass settles (upstream skips 9 windows per 2 s trial) */
        .tau_permille = 600, .k = 3,  /* placeholder until set from day-1 data (RT_SET_DECISION) */
        .seed = 0x2545F491u,
    };
    rt_init(&cfg);
    board_set_rx_handler(rt_rx);
    for (;;) {
        rt_idle();
        board_wait();
    }
}
