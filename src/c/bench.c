/* First on-board timing of the firmware v2 chain, the same steps as rt.c in the order a user goes through them:
 *   1. one-shot calibration on the MCU: the 60 calibration feature vectors (cal_feat.h, subject 0, stand-in for the
 *      user's calibration recording) -> os_calibrate (z-score, prune the 50 pre-trained trees of pre_model.h, train
 *      50 trees) -> one-shot image in Flash (board_flash_*) -> os_model
 *   2. start-up alignment: BENCH_ALIGN windows -> ad_align_push / ad_align_finish
 *   3. BENCH_BLOCKS blocks of BENCH_ROWS windows (300 per block in the data set): per window
 *        fe_push of the 200 new samples (raw_bench.h, src/check_bench.py: subject 0, testing_block0, one 2 s trial
 *        of each of the 6 gestures, int16 x RAW_SCALE, stand-in for the ADC / UART samples; the trials are
 *        replayed in turn, each from a zero filter state, as upstream filters recordings)
 *        -> ad_map + ad_normalize -> sc_push_votes -> ad_observe;
 *      after each block sc_end_block (pseudo-labels, 20 new trees) and ad_end_block (z-score update)
 * Every call is timed with bench_cycles(). The fe_push call that completes a window does the window's features
 * (FFT, Welch PSD, 10 features x 8 channels); the other 199 only filter one sample.
 * All 6 gestures are in the stream, so the buffer holds every class and sc_end_block takes its K-Means path (the
 * expensive one). The same 6 trials are replayed over and over, so the accuracy printed is a sanity check only.
 * Predictions are hashed (with the one-shot image) so that the board output can be compared with the PC run
 * (bench_pc.c): the same numbers mean the board computed the same thing.
 */
#include "bench.h"

#include <stdio.h>
#include <string.h>

#include "adapt.h"
#include "board.h"
#include "cal_feat.h"
#include "features.h"
#include "oneshot.h"
#include "pre_model.h"
#include "raw_bench.h"
#include "selfcal.h"

#define BENCH_BLOCKS 3
#define BENCH_ROWS 300
#define BENCH_ALIGN 50

typedef struct {
    const char *name;
    uint32_t n, max;
    uint64_t sum;
} stage_t;

static stage_t s_fe_win = {"features (window)"}, s_fe_smp = {"filter (1 sample)"}, s_norm = {"map+normalize"},
               s_push = {"sc_push_votes"}, s_obs = {"ad_observe"}, s_end = {"sc_end_block"},
               s_adend = {"ad_end_block"}, s_os = {"os_calibrate+flash"}, s_align = {"ad_align_finish"};
static uint32_t s_hz;
static long s_smp;                                     /* samples streamed so far */
static int s_label;                                    /* gesture of the trial being streamed */
static char s_line[160];

static void add(stage_t *s, uint32_t c)
{
    s->n++;
    s->sum += c;
    if (c > s->max)
        s->max = c;
}

static uint32_t us(uint64_t cycles)
{
    return s_hz ? (uint32_t)(cycles / (s_hz / 1000000u)) : 0u;
}

static void say(void)
{
    bench_print(s_line);
}

static void report(const stage_t *s)
{
    uint64_t mean = s->n ? s->sum / s->n : 0;
    snprintf(s_line, sizeof s_line, "%-20s n=%5lu  mean %9lu cyc %8lu us   max %9lu cyc %8lu us\r\n", s->name,
             (unsigned long)s->n, (unsigned long)mean, (unsigned long)us(mean), (unsigned long)s->max,
             (unsigned long)us(s->max));
    say();
}

/* next raw feature vector of the replayed recording */
static void next_window(float *feat)
{
    float x[FE_CH];
    for (;;) {
        int t = (int)(s_smp / RAW_N % RAW_T), i = (int)(s_smp % RAW_N);
        if (i == 0)
            fe_reset();
        s_label = raw_y[t];
        for (int ch = 0; ch < FE_CH; ch++)
            x[ch] = raw_x[t][i][ch] * RAW_SCALE;
        s_smp++;
        uint32_t t0 = bench_cycles();
        int ready = fe_push(x, feat);
        uint32_t dt = bench_cycles() - t0;
        add(ready ? &s_fe_win : &s_fe_smp, dt);
        if (ready)
            return;
    }
}

static uint32_t hash(uint32_t h, const void *p, uint32_t n)
{
    const uint8_t *b = p;
    while (n--)
        h = (h ^ *b++) * 16777619u;                      /* FNV-1a */
    return h;
}

static int flash_write(void *ctx, uint32_t off, const void *src, uint32_t n)
{
    (void)ctx;
    return board_flash_write(BENCH_IMAGE_BASE + off, src, n);
}

void bench_run(uint32_t cpu_hz)
{
    s_hz = cpu_hz;
    snprintf(s_line, sizeof s_line, "\r\n=== bench v2 (%s) ===\r\n", bench_platform());
    say();
    const uint8_t *img = bench_image();
    if (!img) {
        bench_print("no image area (program overlaps Flash bank 2 sector 7?): stop\r\n");
        return;
    }

    /* 1. one-shot calibration */
    const os_table_t pre = {pre_roots, pre_feat, pre_thr, pre_left, pre_right, PRE_N_INTERNAL};
    const os_writer_t w = {flash_write, 0, BENCH_IMAGE_BYTES};
    os_stats_t ost;
    sc_model_t m;
    float *fb = os_feature_buffer();
    memcpy(fb, cal_feat, sizeof cal_feat);
    uint32_t t0 = bench_cycles();
    int r = board_flash_erase_sector(BENCH_IMAGE_BASE);
    if (r == 0)
        r = os_calibrate(&pre, cal_y, CAL_N, 1u, &w, 0, &ost);
    if (r == 0)
        r = board_flash_flush();
    add(&s_os, bench_cycles() - t0);
    if (r != 0 || os_model(img, &pre, &m) != 0) {
        snprintf(s_line, sizeof s_line, "one-shot calibration failed (%d): stop\r\n", r);
        say();
        return;
    }
    const os_header_t *hdr = (const os_header_t *)img;
    uint32_t h_img = hash(2166136261u, img, ost.image_bytes);
    snprintf(s_line, sizeof s_line, "one-shot: image %lu B, pruned leaves %d, app nodes %d, hash %08lx\r\n",
             (unsigned long)ost.image_bytes, ost.n_pruned_nodes, ost.app_nodes, (unsigned long)h_img);
    say();
    sc_init(&m, os_cal_rows(), cal_y, CAL_N, 1u);
    ad_init(hdr->mu, hdr->inv_sd, &cal_feat[0][0], CAL_N);
    fe_init();

    /* 2. start-up alignment */
    float feat[FE_DIM], al[FE_DIM];
    int16_t q[FE_DIM];
    uint16_t votes[SC_CLASSES];
    ad_align_reset();
    for (int i = 0; i < BENCH_ALIGN; i++) {
        next_window(feat);
        ad_align_push(feat);
    }
    t0 = bench_cycles();
    int k = ad_align_finish();
    add(&s_align, bench_cycles() - t0);

    /* 3. blocks */
    uint32_t h_pred = 2166136261u, cls[SC_CLASSES] = {0}, correct = 0;
    sc_stats_t st = {0};
    ad_stats_t ast = {0};
    for (int b = 0; b < BENCH_BLOCKS; b++) {
        for (int i = 0; i < BENCH_ROWS; i++) {
            next_window(feat);
            t0 = bench_cycles();
            ad_map(feat, al);
            ad_normalize(al, q);
            uint32_t t1 = bench_cycles();
            int pred = sc_push_votes(q, votes);
            uint32_t t2 = bench_cycles();
            ad_observe(al, pred);
            uint32_t t3 = bench_cycles();
            add(&s_norm, t1 - t0);
            add(&s_push, t2 - t1);
            add(&s_obs, t3 - t2);
            h_pred = hash(h_pred, votes, sizeof votes);
            cls[pred]++;
            correct += pred == s_label;
        }
        t0 = bench_cycles();
        sc_end_block(&st);
        add(&s_end, bench_cycles() - t0);
        t0 = bench_cycles();
        ad_end_block(&ast);
        add(&s_adend, bench_cycles() - t0);
        snprintf(s_line, sizeof s_line, "block %d: clustered %d, selected %d, new nodes max %d, z-score updated %d\r\n",
                 b, st.clustered, st.n_selected, st.new_nodes_max, ast.updated);
        say();
    }

    /* results */
    snprintf(s_line, sizeof s_line, "rotation k %d; predictions %lu %lu %lu %lu %lu %lu; votes hash %08lx\r\n", k,
             (unsigned long)cls[0], (unsigned long)cls[1], (unsigned long)cls[2], (unsigned long)cls[3],
             (unsigned long)cls[4], (unsigned long)cls[5], (unsigned long)h_pred);
    say();
    snprintf(s_line, sizeof s_line, "replayed windows correct %lu / %d (sanity only: 6 trials repeated)\r\n",
             (unsigned long)correct, BENCH_BLOCKS * BENCH_ROWS);
    say();
    const stage_t *all[] = {&s_os, &s_align, &s_fe_smp, &s_fe_win, &s_norm, &s_push, &s_obs, &s_end, &s_adend};
    for (unsigned i = 0; i < sizeof all / sizeof all[0]; i++)
        report(all[i]);
    /* one 100 ms window on the device = 200 filtered samples (the last one also computes the features) + the rest */
    uint64_t per_win = s_fe_win.sum / s_fe_win.n + (uint64_t)(FE_STEP - 1) * (s_fe_smp.sum / s_fe_smp.n) +
                       s_norm.sum / s_norm.n + s_push.sum / s_push.n + s_obs.sum / s_obs.n;
    snprintf(s_line, sizeof s_line, "per 100 ms window (mean): %lu cyc = %lu us\r\n=== done ===\r\n",
             (unsigned long)per_win, (unsigned long)us(per_win));
    say();
}
