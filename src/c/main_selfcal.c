/* Cortex-M7 (STM32H743) benchmark firmware for on-device self-calibration (src/c/selfcal.c).
 *
 * The one-shot model (rf_model.h, 50 pruned pre-trained + 50 calibration trees, int16) is in Flash; the
 * calibration set (cal_input.h, 60 rows, Q5.10) stands in for the user's one-shot calibration recording.
 * Rows of a "test block" are the calibration rows replayed (stand-in for live feature extraction), pushed
 * one by one with sc_push(); after SC_ROWS rows sc_end_block() runs the full self-calibration step
 * (re-label, t-SNE, K-Means, train 20 trees, replace). The DWT cycle counter is read around each call:
 * on the board g_cyc_push_max / g_cyc_block hold cycles (nothing is reported without the board).
 */
#include <stdint.h>

#include "cal_input.h"
#include "rf_model.h"
#include "selfcal.h"

#define DEMCR      (*(volatile uint32_t *)0xE000EDFCu)
#define DWT_CTRL   (*(volatile uint32_t *)0xE0001000u)
#define DWT_CYCCNT (*(volatile uint32_t *)0xE0001004u)
#define DWT_LAR    (*(volatile uint32_t *)0xE0001FB0u)
#define SC_ROWS 300

volatile int32_t g_pred;
volatile uint32_t g_cyc_push_max, g_cyc_block, g_blocks;
sc_stats_t g_st;

int main(void)
{
    const sc_model_t m = {rf_roots, rf_feat, rf_thr, rf_left, rf_right};
    DEMCR |= 1u << 24;
    DWT_LAR = 0xC5ACCE55u;
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1u;

    sc_init(&m, &cal_x[0][0], cal_y, CAL_N, 1u);
    for (;;) {
        for (int i = 0; i < SC_ROWS; i++) {
            uint32_t t0 = DWT_CYCCNT;
            g_pred = sc_push(cal_x[i % CAL_N]);
            uint32_t dt = DWT_CYCCNT - t0;
            if (dt > g_cyc_push_max)
                g_cyc_push_max = dt;
        }
        uint32_t t0 = DWT_CYCCNT;
        sc_end_block(&g_st);
        g_cyc_block = DWT_CYCCNT - t0;
        g_blocks++;
    }
}
