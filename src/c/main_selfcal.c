/* Cortex-M7 (STM32H743) benchmark firmware for on-device self-calibration (src/c/selfcal.c).
 *
 * The one-shot model (rf_model.h, 50 pruned pre-trained + 50 calibration trees, int16) is in Flash; the
 * calibration set (cal_input.h, 60 rows, Q5.10) stands in for the user's one-shot calibration recording.
 * Rows of a "test block" are the calibration rows replayed (stand-in for live feature extraction), pushed
 * one by one with sc_push(); after SC_ROWS rows sc_end_block() runs the full self-calibration step
 * (re-label, t-SNE, K-Means, train 20 trees, replace). The DWT cycle counter is read around each call:
 * on the board g_cyc_push_max / g_cyc_block hold cycles (nothing is reported without the board).
 * With -DWITH_FEATURES the whole chain runs instead: raw samples (raw_input.h, one recorded calibration
 * trial as int16, stand-in for the ADC) -> fe_push() (filter + 80 features, src/c/features.c) -> z-score with
 * the calibration statistics -> Q5.10 -> sc_push(); g_cyc_fe_max holds the cycles of the slowest fe_push().
 */
#include <stdint.h>

#include "cal_input.h"
#include "rf_model.h"
#include "selfcal.h"
#ifdef WITH_FEATURES
#include "features.h"
#include "raw_input.h"
float g_mu[FE_DIM], g_inv_sd[FE_DIM];     /* calibration statistics (computed at one-shot calibration) */
volatile uint32_t g_cyc_fe_max;
#endif

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
#ifdef WITH_FEATURES
    fe_init();
    for (int i = 0; i < FE_DIM; i++) {
        g_mu[i] = 0.0f;
        g_inv_sd[i] = 1.0f;
    }
    long smp = 0;
#endif
    for (;;) {
        for (int i = 0; i < SC_ROWS; i++) {
#ifdef WITH_FEATURES
            float x[FE_CH], feat[FE_DIM];
            int16_t q[FE_DIM];
            for (;;) {                        /* samples until the next feature vector */
                if (smp % RAW_N == 0)
                    fe_reset();               /* recordings are filtered from a zero state, as upstream */
                for (int ch = 0; ch < FE_CH; ch++)
                    x[ch] = raw_x[smp % RAW_N][ch] * RAW_SCALE;
                smp++;
                uint32_t t0 = DWT_CYCCNT;
                int ready = fe_push(x, feat);
                uint32_t dt = DWT_CYCCNT - t0;
                if (dt > g_cyc_fe_max)
                    g_cyc_fe_max = dt;
                if (ready)
                    break;
            }
            fe_normalize_q16(feat, g_mu, g_inv_sd, q);
            const int16_t *row = q;
#else
            const int16_t *row = cal_x[i % CAL_N];
#endif
            uint32_t t0 = DWT_CYCCNT;
            g_pred = sc_push(row);
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
