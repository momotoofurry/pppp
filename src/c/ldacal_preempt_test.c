/* report 35.103: does a reader that preempts ld_fit see a whole model?
 * The classifier (rtl_rx: TIM6 interrupt on bare metal, the higher-priority task on FreeRTOS) can run in the middle
 * of ld_fit (rtl_idle: task labels, range labels). Here LD_TEST_HOOK(point) runs the readers at points inside ld_fit
 * (after the covariance, every 16 Cholesky rows, before the weights, after each class's weights, after publishing)
 * and checks every score / distance equals either the whole OLD model or, after publishing, the whole NEW model.
 * Also: a failed fit (-2) must leave the old model, including the factor ld_dist2 uses, untouched.
 *   gcc -O2 -DLD_CLASSES=9 -DLD_TEST_HOOK=hook -include hook.h ldacal.c ldacal_preempt_test.c -lm */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "ldacal.h"

#define NT 40                                     /* test windows read at every hook */
static int16_t s_test[NT][LD_DIM];
static float s_ref_old[NT][LD_CLASSES], s_ref_new[NT][LD_CLASSES], s_d_old[NT], s_d_new[NT];
static int s_phase;                               /* 0: no checks, 1: inside the fit under test */
static int s_hooks, s_bad_before, s_bad_after, s_seen_new;
static uint32_t s_rng = 12345u;

static int rnd(int a)
{
    s_rng = s_rng * 1664525u + 1013904223u;
    return (int)((s_rng >> 8) % (uint32_t)(2 * a + 1)) - a;
}

static void window(int c, int16_t *x, int shift)
{
    for (int i = 0; i < LD_DIM; i++)
        x[i] = (int16_t)(((i % LD_CLASSES) == c ? 900 : 0) + (i == c + shift ? 600 : 0) + rnd(700));
}

static void snapshot(float sc[NT][LD_CLASSES], float *d)
{
    for (int t = 0; t < NT; t++) {
        ld_scores(s_test[t], sc[t]);
        d[t] = ld_dist2(s_test[t], t % LD_CLASSES);
    }
}

static int same(float sc[NT][LD_CLASSES], const float *d, float ref[NT][LD_CLASSES], const float *dref)
{
    for (int t = 0; t < NT; t++) {
        if (d[t] != dref[t])
            return 0;
        for (int c = 0; c < LD_CLASSES; c++)
            if (sc[t][c] != ref[t][c])
                return 0;
    }
    return 1;
}

void hook(int point)
{
    if (!s_phase)
        return;
    s_hooks++;
    float sc[NT][LD_CLASSES], d[NT];
    snapshot(sc, d);
    if (point < 4) {
        if (!same(sc, d, s_ref_old, s_d_old))
            s_bad_before++;
    } else {
        s_seen_new = 1;
        if (!same(sc, d, s_ref_new, s_d_new))
            s_bad_after++;
    }
}

int main(void)
{
    int ok = 1;
    int16_t x[LD_DIM];
    for (int t = 0; t < NT; t++)
        window(t % LD_CLASSES, s_test[t], 0);
    /* the new model's reference: day 1 + day 2 sums, fitted without any reader in between */
    ld_reset();
    for (int r = 0; r < 60; r++)
        for (int c = 0; c < LD_CLASSES; c++) { window(c, x, 0); ld_add(x, c); }
    uint32_t keep = s_rng;
    for (int r = 0; r < 30; r++)
        for (int c = 0; c < LD_CLASSES; c++) { window(c, x, 3); ld_add(x, c); }
    if (ld_fit() != 0) { printf("FAIL reference fit\n"); return 1; }
    snapshot(s_ref_new, s_d_new);
    /* the old model: day 1 only */
    s_rng = 12345u;
    for (int t = 0; t < NT; t++)
        window(t % LD_CLASSES, s_test[t], 0);
    ld_reset();
    for (int r = 0; r < 60; r++)
        for (int c = 0; c < LD_CLASSES; c++) { window(c, x, 0); ld_add(x, c); }
    if (ld_fit() != 0) { printf("FAIL old fit\n"); return 1; }
    snapshot(s_ref_old, s_d_old);
    /* day 2 arrives (the same windows as for the reference), then the fit under test with readers inside it */
    s_rng = keep;
    for (int r = 0; r < 30; r++)
        for (int c = 0; c < LD_CLASSES; c++) { window(c, x, 3); ld_add(x, c); }
    s_phase = 1;
    const int r = ld_fit();
    s_phase = 0;
    float sc[NT][LD_CLASSES], d[NT];
    snapshot(sc, d);
    printf("fit %d; readers ran at %d points inside it\n", r, s_hooks);
    printf("%s readers before the publish saw the whole OLD model (%d mismatches)\n", s_bad_before ? "FAIL" : "ok  ",
           s_bad_before);
    printf("%s readers after the publish saw the whole NEW model (%d mismatches)\n",
           (s_bad_after || !s_seen_new) ? "FAIL" : "ok  ", s_bad_after);
    printf("%s after the fit: scores and distances = the reference new model, bit for bit\n",
           same(sc, d, s_ref_new, s_d_new) ? "ok  " : "FAIL");
    ok &= !s_bad_before && !s_bad_after && s_seen_new && same(sc, d, s_ref_new, s_d_new) && r == 0 && s_hooks >= 10;
    /* a failed fit: identical windows for one class make the shrunk covariance degenerate -> -2 */
    float before[NT][LD_CLASSES], db[NT];
    snapshot(before, db);
    ld_reset();
    for (int c = 0; c < LD_CLASSES; c++) {
        memset(x, 0, sizeof x);
        for (int k = 0; k < 5; k++)
            ld_add(x, c);
    }
    const int rf = ld_fit();
    snapshot(sc, d);
    const int kept = same(sc, d, before, db);
    printf("%s a failed fit (%d) leaves the model in use (weights AND the factor of ld_dist2) untouched\n",
           (rf != 0 && kept) ? "ok  " : "FAIL", rf);
    ok &= rf != 0 && kept;
    printf("%s\n", ok ? "ALL OK" : "SOME FAILED");
    return ok ? 0 : 1;
}
