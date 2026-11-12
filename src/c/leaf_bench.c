/* On-board timing of the leaf counters (leafcal.c; exploratory, report 35 - NOT the frozen firmware).
 * Takes the place of bench.c in a COPY of the CubeMX project: it defines bench_run(), uses only bench.h
 * (cycle counter, print) and never touches the Flash, so the one-shot image stored by the firmware stays as it is.
 *
 * Data (src/check_leaf_bench.py): the one-shot model of subject 0 built on the PC (leaf_model.h, leafcal.h
 * tables) and Q5.10 rows of testing_block0 (leaf_rows.h): the 60 labelled start-up rows and the other rows.
 * For each configuration (which trees keep counters):
 *   1. lc_votes on every test row            (the model as after one-shot)
 *   2. lc_learn on the 60 labelled rows      (the whole per-session update)
 *   3. lc_votes on every test row again      (with the counters in use)
 * Each call is timed with bench_cycles(). The votes are hashed, so the PC run (bench_pc.c + this file) must
 * print the same hashes and counts.
 */
#include "bench.h"

#include <stdio.h>
#include <string.h>

#include "leaf_model.h"
#include "leaf_rows.h"
#include "leafcal.h"

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

static uint32_t hash(uint32_t h, const void *p, unsigned n)     /* FNV-1a */
{
    const uint8_t *b = p;
    while (n--)
        h = (h ^ *b++) * 16777619u;
    return h;
}

static unsigned long tenth_us(uint64_t cycles)                  /* 0.1 us units */
{
    return s_hz ? (unsigned long)(cycles * 10u / (s_hz / 1000000u)) : 0ul;
}

static void report(const char *name, const stage_t *s)
{
    uint64_t mean = s->n ? s->sum / s->n : 0;
    unsigned long m = tenth_us(mean), x = tenth_us(s->max), tot = tenth_us(s->sum);
    snprintf(s_line, sizeof s_line, "  %-22s n=%4lu  mean %7lu cyc %5lu.%lu us   max %7lu cyc %5lu.%lu us   total %7lu.%lu us\r\n",
             name, (unsigned long)s->n, (unsigned long)mean, m / 10, m % 10, (unsigned long)s->max, x / 10, x % 10,
             tot / 10, tot % 10);
    bench_print(s_line);
}

static void pass(stage_t *st, uint32_t *h, unsigned *correct)
{
    uint16_t v[LC_CLASSES];
    *h = 2166136261u;
    *correct = 0;
    for (int i = 0; i < LR_NU; i++) {
        uint32_t t0 = bench_cycles();
        int p = lc_votes(lr_use[i], v);
        add(st, bench_cycles() - t0);
        *h = hash(*h, v, sizeof v);
        *correct += p == lr_use_y[i];
    }
}

static void run(const char *name, const uint16_t *base)
{
    lc_model_t m = {lm_roots, lm_feat, lm_thr, lm_left, lm_right, base};
    stage_t before = {0}, learn = {0}, after = {0};
    uint32_t h0, h1;
    unsigned c0, c1;
    if (lc_init(&m)) {
        snprintf(s_line, sizeof s_line, "%s: lc_init failed (needs %u counter rows)\r\n", name, base[LC_N_TREES]);
        bench_print(s_line);
        return;
    }
    pass(&before, &h0, &c0);
    for (int i = 0; i < LR_NA; i++) {
        uint32_t t0 = bench_cycles();
        lc_learn(lr_anchor[i], lr_anchor_y[i]);
        add(&learn, bench_cycles() - t0);
    }
    pass(&after, &h1, &c1);
    snprintf(s_line, sizeof s_line, "%s: counter rows %u (%u B); correct %u -> %u of %d; votes hash %08lx -> %08lx\r\n",
             name, base[LC_N_TREES], base[LC_N_TREES] * LC_CLASSES, c0, c1, LR_NU, (unsigned long)h0,
             (unsigned long)h1);
    bench_print(s_line);
    report("lc_votes (one-shot)", &before);
    report("lc_learn (1 window)", &learn);
    report("lc_votes (counters)", &after);
}

void bench_run(uint32_t cpu_hz)
{
    s_hz = cpu_hz;
    snprintf(s_line, sizeof s_line, "\r\n=== leaf counter bench ===\r\n%s\r\nleafcal static %u B, %d trees, %d internal nodes, "
             "%d labelled rows, %d test rows\r\n", bench_platform(), lc_static_bytes(), LC_N_TREES, LM_N_INTERNAL, LR_NA, LR_NU);
    bench_print(s_line);
    run("no counters", lm_base_none);
    run("appended trees (k 0)", lm_base_k0);
    run("+ 10 pre-trained", lm_base_k10);
    run("+ 25 pre-trained", lm_base_k25);
    run("all 100 trees", lm_base_k50);
    bench_print("=== done ===\r\n");
}
