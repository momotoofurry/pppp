/* Route-B firmware on the board (as main_rt.c, on the HAL board layer): the PC forwards samples over USART3 at
 * APP_RT_BAUD, the MCU does everything else (rt.c). Flash: the 50 pre-trained trees (pre_model.h) and, after the
 * one-shot calibration, the image in bank 2 sector 7 (BENCH_IMAGE_BASE, as the bench).
 * warmup = 9 windows after every stream reset, so that a replayed 2 s recording gives windows 9..18 as upstream
 * (src/board_replay.py compares with the PC run of the same stream); live use takes 2 (main_rt.c).
 * Only packets are sent (no text), so the byte stream to the PC stays decodable.
 */
#include "app_rt.h"

#include "bench.h"
#include "board.h"
#include "pre_model.h"
#include "rt.h"

static int flash_write(void *ctx, uint32_t off, const void *src, uint32_t n)
{
    (void)ctx;
    return board_flash_write(BENCH_IMAGE_BASE + off, src, n);
}

static int flash_erase(void)
{
    return board_flash_erase_sector(BENCH_IMAGE_BASE);
}

static const os_table_t s_pre = {pre_roots, pre_feat, pre_thr, pre_left, pre_right, PRE_N_INTERNAL};

void app_rt_run(void)
{
    static os_writer_t writer;
    writer.write = flash_write;
    writer.ctx = 0;
    writer.capacity = BENCH_IMAGE_BYTES;
    const rt_config_t cfg = {
        .pre = &s_pre, .writer = &writer, .image = (const void *)BENCH_IMAGE_BASE, .flash_erase = flash_erase,
        .flash_flush = board_flash_flush, .tx = board_uart_tx, .now_us = board_time_us,
        .warmup = 9, .tau_permille = 600, .k = 3, .seed = 0x2545F491u,
    };
    rt_init(&cfg);
    board_set_rx_handler(rt_rx);
    board_rx_start(APP_RT_BAUD);
    uint32_t last = board_time_us();
    for (;;) {
        rt_idle();
        if (board_time_us() - last >= APP_RT_DIAG_US) {     /* test A (VALIDATION_PLAN.md): buffer, stack, UART */
            last = board_time_us();
            rt_status(RT_EV_DIAG_RX_HW, (int32_t)board_rx_highwater());
            rt_status(RT_EV_DIAG_STACK, (int32_t)board_stack_peak());
            rt_status(RT_EV_DIAG_RX_OVF, (int32_t)board_rx_overflow());
            rt_status(RT_EV_DIAG_RX_ERR, (int32_t)board_rx_errors());
        }
        board_wait();
    }
}
