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
 * With -DWITH_ONESHOT (and WITH_FEATURES) the one-shot model is built on the MCU instead of coming from the PC:
 * only the 50 pre-trained trees are in Flash (pre_model.h); the 60 calibration feature vectors (cal_feat.h,
 * stand-in for the features of the user's calibration recording) go through os_calibrate(), which writes the
 * one-shot image into the reserved Flash sector (board_flash_write, board layer); the z-score statistics of
 * the image are then used for every live feature vector. g_cyc_oneshot holds the cycles of os_calibrate().
 */
#include <stdint.h>

#include "selfcal.h"
#ifdef WITH_ONESHOT
#include "board.h"
#include "cal_feat.h"
#include "oneshot.h"
#include "pre_model.h"
extern const uint8_t _oneshot_image[], _oneshot_bytes[];
volatile int32_t g_os_status = 1;
volatile uint32_t g_cyc_oneshot;
os_stats_t g_os;

static int flash_writer(void *ctx, uint32_t off, const void *src, uint32_t n)
{
    (void)ctx;
    return board_flash_write((uint32_t)_oneshot_image + off, src, n);
}
#else
#include "cal_input.h"
#include "rf_model.h"
#endif
#ifdef WITH_FEATURES
#include "features.h"
#include "raw_input.h"
#ifndef WITH_ONESHOT
float g_mu[FE_DIM], g_inv_sd[FE_DIM];     /* placeholder statistics (the PC-built model has its own) */
#endif
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
    DEMCR |= 1u << 24;
    DWT_LAR = 0xC5ACCE55u;
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1u;

#ifdef WITH_ONESHOT
    const os_table_t pre = {pre_roots, pre_feat, pre_thr, pre_left, pre_right, PRE_N_INTERNAL};
    const os_writer_t w = {flash_writer, 0, (uint32_t)_oneshot_bytes};
    sc_model_t m;
    float *fb = os_feature_buffer();
    for (int i = 0; i < CAL_N * FE_DIM; i++)
        fb[i] = cal_feat[i / FE_DIM][i % FE_DIM];
    uint32_t c0 = DWT_CYCCNT;
    g_os_status = board_flash_erase_sector((uint32_t)_oneshot_image);
    if (g_os_status == 0)
        g_os_status = os_calibrate(&pre, cal_y, CAL_N, 1u, &w, 0, &g_os);
    if (g_os_status == 0)
        g_os_status = board_flash_flush();
    g_cyc_oneshot = DWT_CYCCNT - c0;
    if (g_os_status != 0 || os_model(_oneshot_image, &pre, &m) != 0)
        for (;;) {                            /* no one-shot model: stop here (g_os_status says why) */
        }
    sc_init(&m, os_cal_rows(), cal_y, CAL_N, 1u);
    const os_header_t *hdr = (const os_header_t *)_oneshot_image;
#else
    const sc_model_t m = {rf_roots, rf_feat, rf_thr, rf_left, rf_right};
    sc_init(&m, &cal_x[0][0], cal_y, CAL_N, 1u);
#endif
#ifdef WITH_FEATURES
    fe_init();
#ifndef WITH_ONESHOT
    for (int i = 0; i < FE_DIM; i++) {
        g_mu[i] = 0.0f;
        g_inv_sd[i] = 1.0f;
    }
#endif
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
#ifdef WITH_ONESHOT
            os_normalize(hdr, feat, q);
#else
            fe_normalize_q16(feat, g_mu, g_inv_sd, q);
#endif
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
