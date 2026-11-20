/* float32 accumulation precision of ldacal.c over many sessions (report 35.73).
 *
 * The same int16 Q5.10 windows go into three builds of the same source:
 *   ld_  ldacal.c as on the board (float32 throughout);
 *   lr_  reference: float -> double everywhere;
 *   lm_  candidate fix: only the running sums (s_g, s_sum, s_n) and G - s s^T / n in double, the fit in float32.
 * After chosen days all three are fitted; we compare predictions on fresh test windows, accuracies, shrinkage and
 * the discriminant values. Only the arithmetic differs, so every gap is rounding.
 *
 * Synthetic data, built to stress the sums rather than to look like one person:
 *   40 base features with correlated noise, 9 classes, class-mean scale SEP (sets the difficulty);
 *   DUP = 1: duplicated to 80 like the board (4 sensors copied to 8 channels), DUP = 0: 40 independent + 40 more
 *   independent noisy copies (no exact duplicates);
 *   every day a new gain and offset per feature (electrode shift); per-day z-score from that day's cue windows
 *   (as on the board); per day 540 cue windows (2 rounds x 30 x 9) + TASK task windows with their true class;
 *   OFF: a residual mean of +OFF sd on every feature after the z-score (a poor z-score anchor);
 *   K: ld_decay(0.97) after every K windows (0 = none: plain cross-day accumulation).
 * Usage: ldacal_precision <days> <task/day> <OFF> <K> <seed> <SEP> <DUP>
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ldacal.h"
#include "ldacal_mix.h"
#include "ldacal_ref.h"

#define NB 40
#define NCUE 30
#define NTEST 4000

static uint64_t rs = 88172645463325252ULL;
static double urand(void)
{
    rs ^= rs << 13;
    rs ^= rs >> 7;
    rs ^= rs << 17;
    return ((rs >> 11) + 0.5) * (1.0 / 9007199254740992.0);
}
static double nrand(void)
{
    return sqrt(-2.0 * log(urand())) * cos(6.283185307179586 * urand());
}

static double A[NB][NB], MU[LD_CLASSES][NB], gain[LD_DIM], off[LD_DIM], zm[LD_DIM], zs[LD_DIM];
static double OFF;
static int DUP;

static void raw(int c, double *x)
{
    double z[NB];
    for (int i = 0; i < NB; i++)
        z[i] = nrand();
    for (int i = 0; i < NB; i++) {
        double v = MU[c][i];
        for (int k = 0; k < NB; k++)
            v += A[i][k] * z[k];
        x[i] = v;
        x[i + NB] = DUP ? v : v + nrand() * 0.5;     /* DUP 0: a second, noisy view of the same feature */
    }
    for (int i = 0; i < LD_DIM; i++)
        x[i] = x[i] * gain[i] + off[i];
    if (DUP)
        for (int i = 0; i < NB; i++)
            x[i + NB] = x[i];
}

static void quant(const double *x, int16_t *q)
{
    for (int i = 0; i < LD_DIM; i++) {
        double v = ((x[i] - zm[i]) / zs[i] + OFF) * LD_Q;
        v = v > 32767 ? 32767 : v < -32768 ? -32768 : v;
        q[i] = (int16_t)lrint(v);
    }
}

static int nadd, K;
static void add(const int16_t *q, int c)
{
    ld_add(q, c);
    lr_add(q, c);
    lm_add(q, c);
    if (K && ++nadd % K == 0) {
        ld_decay(0.97f);
        lr_decay(0.97);
        lm_decay(0.97f);
    }
}

int main(int argc, char **argv)
{
    int days = argc > 1 ? atoi(argv[1]) : 365, task = argc > 2 ? atoi(argv[2]) : 1500;
    OFF = argc > 3 ? atof(argv[3]) : 0.0;
    K = argc > 4 ? atoi(argv[4]) : 0;
    rs ^= (uint64_t)(argc > 5 ? atoi(argv[5]) : 1) * 0x9E3779B97F4A7C15ULL;
    double sep = argc > 6 ? atof(argv[6]) : 0.35;
    DUP = argc > 7 ? atoi(argv[7]) : 1;
    for (int i = 0; i < NB; i++)
        for (int k = 0; k < NB; k++)
            A[i][k] = (i == k ? 0.7 : 0.0) + nrand() * 0.7 / sqrt((double)NB);
    for (int c = 0; c < LD_CLASSES; c++)
        for (int i = 0; i < NB; i++)
            MU[c][i] = nrand() * sep;
    static const int chk[] = {1, 2, 5, 10, 20, 30, 50, 100, 200, 365, 730};
    int ci = 0;
    long nwin = 0;
    for (int d = 1; d <= days; d++) {
        for (int i = 0; i < LD_DIM; i++) {
            gain[i] = exp(nrand() * 0.2);
            off[i] = nrand() * 0.5;
        }
        if (DUP)
            for (int i = 0; i < NB; i++) {
                gain[i + NB] = gain[i];
                off[i + NB] = off[i];
            }
        static double cue[LD_CLASSES * NCUE * 2][LD_DIM];
        int n = 0;
        for (int r = 0; r < 2; r++)
            for (int c = 0; c < LD_CLASSES; c++)
                for (int k = 0; k < NCUE; k++)
                    raw(c, cue[n++]);
        for (int i = 0; i < LD_DIM; i++) {
            double s = 0, s2 = 0;
            for (int k = 0; k < n; k++) {
                s += cue[k][i];
                s2 += cue[k][i] * cue[k][i];
            }
            zm[i] = s / n;
            zs[i] = sqrt(s2 / n - zm[i] * zm[i]);
        }
        int16_t q[LD_DIM];
        for (int k = 0; k < n; k++) {
            quant(cue[k], q);
            add(q, (k / NCUE) % LD_CLASSES);
        }
        double x[LD_DIM];
        for (int t = 0; t < task; t++) {
            int c = (int)(urand() * LD_CLASSES);
            raw(c, x);
            quant(x, q);
            add(q, c);
        }
        nwin += n + task;
        if (ci < (int)(sizeof chk / sizeof chk[0]) && d == chk[ci]) {
            ci++;
            int f32 = ld_fit(), f64 = lr_fit(), fm = lm_fit();
            int ok32 = 0, ok64 = 0, okm = 0, ag32 = 0, agm = 0;
            double e32 = 0, em = 0, smax = 0;
            float s32[LD_CLASSES], sm[LD_CLASSES];
            double s64[LD_CLASSES];
            for (int t = 0; t < NTEST; t++) {
                int c = t % LD_CLASSES;
                raw(c, x);
                quant(x, q);
                int p32 = ld_scores(q, s32), p64 = lr_scores(q, s64), pm = lm_scores(q, sm);
                ok32 += p32 == c;
                ok64 += p64 == c;
                okm += pm == c;
                ag32 += p32 == p64;
                agm += pm == p64;
                for (int k = 0; k < LD_CLASSES; k++) {
                    e32 = fmax(e32, fabs(s32[k] - s64[k]));
                    em = fmax(em, fabs(sm[k] - s64[k]));
                    smax = fmax(smax, fabs(s64[k]));
                }
            }
            printf("%d,%ld,%.4f,%.4f,%.4f,%.5f,%.5f,%.3e,%.3e,%.3e,%.3e,%d,%d,%d\n", d, nwin, ok32 / (double)NTEST,
                   ok64 / (double)NTEST, okm / (double)NTEST, ag32 / (double)NTEST, agm / (double)NTEST,
                   e32 / smax, em / smax, ld_shrinkage(), lr_shrinkage(), f32, f64, fm);
        }
    }
    return 0;
}
