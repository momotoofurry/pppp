/* On-board timing: the small MLP of nn_compare.py against the shrinkage LDA, same rows, same MCU (report 35.39;
 * exploratory, NOT the frozen firmware). Takes the place of bench.c in a COPY of the CubeMX project, as lda_bench.c;
 * never touches the Flash. Data (mlp_rows.h, src/check_mlp_bench.py): NinaPro DB6 subject 1, 8 classes, first
 * electrode ring, day-1 z-score, Q5.10: the 960 day-1 rows (D1T1, 12 repetitions), the 80 cued-pass rows of the next
 * session (D1T2, repetition 1) and its 480 probe rows (repetitions 7-12). mlp_weights.h: the day-1 network trained in
 * float64 by the script (seed 0), rounded to float32. ldacal.c is compiled here with LD_CLASSES 8 (a copy).
 *   LDA  day 1: 960 x ld_add, ld_fit, 480 x ld_predict; cue: per class ld_decay(0.97) + 10 x ld_add, ld_fit (as
 *        db6_sim cue1), 480 x ld_predict
 *   MLP  day 1: 480 x mlp_predict; cue: 30 epochs of Adam over the 80 rows (batch 16, lr 1e-3, L2 1e-4, rows in
 *        stored order), 480 x mlp_predict
 * Each call timed with bench_cycles(); predictions hashed. The PC run (bench_pc.c) prints the same lines with zero
 * timings; float32 on both sides, the ARM build may contract a*b+c into FMA, so a few predictions can differ.
 */
#include "bench.h"

#include <stdio.h>
#include <string.h>

#include "ldacal.h"
#include "mlp.h"
#include "mlp_rows.h"
#include "mlp_weights.h"

typedef struct {
    uint32_t n, max;
    uint64_t sum;
} stage_t;

static uint32_t s_hz;
static char s_line[220];

static void add(stage_t *s, uint32_t c)
{
    s->n++;
    s->sum += c;
    if (c > s->max)
        s->max = c;
}

static unsigned long tenth_us(uint64_t cycles)
{
    return s_hz ? (unsigned long)(cycles * 10u / (s_hz / 1000000u)) : 0ul;
}

static void report(const char *name, const stage_t *s)
{
    uint64_t mean = s->n ? s->sum / s->n : 0;
    unsigned long m = tenth_us(mean), x = tenth_us(s->max), tot = tenth_us(s->sum);
    snprintf(s_line, sizeof s_line, "  %-14s n=%4lu  mean %8lu.%lu us   max %8lu.%lu us   total %9lu.%lu us\r\n", name,
             (unsigned long)s->n, m / 10, m % 10, x / 10, x % 10, tot / 10, tot % 10);
    bench_print(s_line);
}

static void probe(const char *name, int (*pred)(const int16_t *), stage_t *st)
{
    uint32_t h = 2166136261u;
    unsigned correct = 0;
    for (int i = 0; i < MR_NP; i++) {
        uint32_t t0 = bench_cycles();
        int p = pred(mr_probe[i]);
        add(st, bench_cycles() - t0);
        h = (h ^ (uint32_t)p) * 16777619u;
        correct += p == mr_probe_y[i];
    }
    snprintf(s_line, sizeof s_line, "%s: correct %u of %d, hash %08lx\r\n", name, correct, MR_NP, (unsigned long)h);
    bench_print(s_line);
}

void bench_run(uint32_t cpu_hz)
{
    s_hz = cpu_hz;
    snprintf(s_line, sizeof s_line, "\r\n=== MLP vs LDA bench ===\r\n%s\r\nldacal static %u B (%d classes); mlp static %u B, "
             "%d parameters (%u B float32)\r\n", bench_platform(), ld_static_bytes(), LD_CLASSES, mlp_static_bytes(),
             MLP_NPARAM, (unsigned)(MLP_NPARAM * 4));
    bench_print(s_line);
    /* ---- LDA */
    stage_t a = {0}, f = {0}, p = {0}, cu = {0}, p2 = {0};
    ld_reset();
    for (int i = 0; i < MR_N1; i++) {
        uint32_t t0 = bench_cycles();
        ld_add(mr_day1[i], mr_day1_y[i]);
        add(&a, bench_cycles() - t0);
    }
    uint32_t t0 = bench_cycles();
    int r = ld_fit();
    add(&f, bench_cycles() - t0);
    snprintf(s_line, sizeof s_line, "lda day-1 fit %d\r\n", r);
    bench_print(s_line);
    probe("lda day-1", ld_predict, &p);
    t0 = bench_cycles();
    for (int c = 0; c < LD_CLASSES; c++) {
        ld_decay(0.97f);
        for (int i = 0; i < MR_NC; i++)
            if (mr_cue_y[i] == c)
                ld_add(mr_cue[i], c);
    }
    r = ld_fit();
    add(&cu, bench_cycles() - t0);
    snprintf(s_line, sizeof s_line, "lda cue fit %d\r\n", r);
    bench_print(s_line);
    probe("lda cue", ld_predict, &p2);
    report("ld_add", &a);
    report("ld_fit", &f);
    report("ld_predict", &p);
    report("lda cue update", &cu);
    /* ---- MLP */
    stage_t mp = {0}, ep = {0}, ft = {0}, mp2 = {0};
    mlp_load(mw_params);
    probe("mlp day-1", mlp_predict, &mp);
    uint32_t tf = bench_cycles();
    for (int e = 0; e < MW_EPOCHS; e++) {
        uint32_t te = bench_cycles();
        mlp_train_epoch(mr_cue, mr_cue_y, MR_NC, MW_BATCH, MW_LR, MW_L2);
        add(&ep, bench_cycles() - te);
    }
    add(&ft, bench_cycles() - tf);
    probe("mlp fine-tuned", mlp_predict, &mp2);
    uint32_t hp = 2166136261u;
    const float *pp = mlp_params();
    for (int i = 0; i < MLP_NPARAM; i++) {
        int32_t qv = (int32_t)(pp[i] * 1000.0f);          /* weights to 1e-3: robust to last-bit differences */
        hp = (hp ^ (uint32_t)qv) * 16777619u;
    }
    snprintf(s_line, sizeof s_line, "mlp weights after fine-tuning, hash of round-to-1e-3 %08lx\r\n", (unsigned long)hp);
    bench_print(s_line);
    report("mlp_predict", &mp);
    report("mlp epoch", &ep);
    report("mlp fine-tune", &ft);
    bench_print("=== done ===\r\n");
}
