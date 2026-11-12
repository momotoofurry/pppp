/* On-board timing of the LDA re-calibration (ldacal.c; exploratory, report 35.10 - NOT the frozen firmware).
 * As leaf_bench.c: takes the place of bench.c in a COPY of the CubeMX project, uses only bench.h, never touches
 * the Flash. Data: leaf_rows.h (src/check_leaf_bench.py): 60 labelled start-up rows and 240 test rows of subject 0,
 * testing_block0, Q5.10.
 *   pass 1  ld_reset, 60 x ld_add, ld_fit, 240 x ld_predict          (a new LDA from one start-up sequence)
 *   pass 2  the same 60 rows added again (120 in the sums), ld_fit, 240 x ld_predict   (accumulating)
 * Each call is timed with bench_cycles(). Predictions are hashed; the PC run (bench_pc.c + this file) prints the
 * same lines with zero timings. float32 on both sides, but the ARM build may contract a*b+c into FMA, so the
 * discriminant values can differ in the last bits; the prediction counts are what must agree.
 */
#include "bench.h"

#include <stdio.h>
#include <string.h>

#include "ldacal.h"
#include "leaf_rows.h"

typedef struct {
    uint32_t n, max;
    uint64_t sum;
} stage_t;

static uint32_t s_hz;
static char s_line[200];

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
    snprintf(s_line, sizeof s_line, "  %-12s n=%4lu  mean %8lu cyc %6lu.%lu us   max %8lu cyc %6lu.%lu us   total %8lu.%lu us\r\n",
             name, (unsigned long)s->n, (unsigned long)mean, m / 10, m % 10, (unsigned long)s->max, x / 10, x % 10,
             tot / 10, tot % 10);
    bench_print(s_line);
}

static void pass(const char *name)
{
    stage_t s_add = {0}, s_fit = {0}, s_pred = {0};
    for (int i = 0; i < LR_NA; i++) {
        uint32_t t0 = bench_cycles();
        ld_add(lr_anchor[i], lr_anchor_y[i]);
        add(&s_add, bench_cycles() - t0);
    }
    uint32_t t0 = bench_cycles();
    int r = ld_fit();
    add(&s_fit, bench_cycles() - t0);
    uint32_t h = 2166136261u;
    unsigned correct = 0, cls[LD_CLASSES] = {0};
    for (int i = 0; i < LR_NU; i++) {
        t0 = bench_cycles();
        int p = ld_predict(lr_use[i]);
        add(&s_pred, bench_cycles() - t0);
        h = (h ^ (uint32_t)p) * 16777619u;
        cls[p]++;
        correct += p == lr_use_y[i];
    }
    snprintf(s_line, sizeof s_line, "%s: fit %d, rho x 1e6 %ld, correct %u of %d, predictions %u %u %u %u %u %u, hash %08lx\r\n",
             name, r, (long)(ld_shrinkage() * 1e6f), correct, LR_NU, cls[0], cls[1], cls[2], cls[3], cls[4], cls[5],
             (unsigned long)h);
    bench_print(s_line);
    report("ld_add", &s_add);
    report("ld_fit", &s_fit);
    report("ld_predict", &s_pred);
}

void bench_run(uint32_t cpu_hz)
{
    s_hz = cpu_hz;
    snprintf(s_line, sizeof s_line, "\r\n=== LDA re-calibration bench ===\r\n%s\r\nldacal static %u B, %d features, %d classes, "
             "%d labelled rows, %d test rows\r\n", bench_platform(), ld_static_bytes(), LD_DIM, LD_CLASSES, LR_NA, LR_NU);
    bench_print(s_line);
    ld_reset();
    pass("new LDA from 60 rows");
    pass("60 more rows (120)");
    bench_print("=== done ===\r\n");
}
