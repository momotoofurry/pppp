/* LDA main line on the board (exploratory, report 35.14; NOT the frozen firmware): rt_lda.c on the HAL board layer.
 * The PC forwards samples over USART3 at APP_RT_BAUD, the MCU does everything else. Nothing is read from or written
 * to the Flash. Defines app_rt_run(), so it takes the place of app_rt.c in a COPY of the CubeMX project built with
 * -DEMG_APP_RT=ON. warmup = 9 windows after every stream reset, so that a replayed 2 s recording gives windows
 * 9..18 as upstream (src/board_replay_lda.py compares with the PC run of the same stream).
 * Only packets are sent (no text), so the byte stream to the PC stays decodable.
 */
#include "app_rt.h"

#include "board.h"
#include "rt_lda.h"

void app_rt_run(void)
{
    const rtl_config_t cfg = {
        .tx = board_uart_tx, .now_us = board_time_us, .warmup = 9, .margin_x100 = 0, .dist2 = 0, .k = 3,
    };
    rtl_init(&cfg);
    board_set_rx_handler(rtl_rx);
    board_rx_start(APP_RT_BAUD);
    uint32_t last = board_time_us();
    for (;;) {
        rtl_idle();
        if (board_time_us() - last >= APP_RT_DIAG_US) {
            last = board_time_us();
            rtl_status(RTL_EV_DIAG_RX_HW, (int32_t)board_rx_highwater());
            rtl_status(RTL_EV_DIAG_STACK, (int32_t)board_stack_peak());
            rtl_status(RTL_EV_DIAG_RX_OVF, (int32_t)board_rx_overflow());
            rtl_status(RTL_EV_DIAG_RX_ERR, (int32_t)board_rx_errors());
        }
        board_wait();
    }
}
