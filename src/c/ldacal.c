/* Per-session LDA re-calibration, static memory only. See ldacal.h. */
#include "ldacal.h"

#include <math.h>
#include <string.h>

#define TRI(i, j) ((i) * ((i) + 1) / 2 + (j))   /* packed lower triangle, j <= i */

static float s_g[LD_TRI];                       /* sum of x x^T over all labelled windows */
static float s_sum[LD_CLASSES][LD_DIM];
static uint32_t s_n[LD_CLASSES];
static float s_l[LD_TRI];                       /* work: covariance, then its Cholesky factor */
static float s_w[LD_CLASSES][LD_DIM];
static float s_b[LD_CLASSES];
static float s_rho;
static float s_x[LD_DIM];

unsigned ld_static_bytes(void)
{
    return (unsigned)(sizeof s_g + sizeof s_sum + sizeof s_n + sizeof s_l + sizeof s_w + sizeof s_b + sizeof s_rho +
                      sizeof s_x);
}

void ld_reset(void)
{
    memset(s_g, 0, sizeof s_g);
    memset(s_sum, 0, sizeof s_sum);
    memset(s_n, 0, sizeof s_n);
}

void ld_add(const int16_t *x, int label)
{
    if (label < 0 || label >= LD_CLASSES)
        return;
    for (int i = 0; i < LD_DIM; i++)
        s_x[i] = (float)x[i] / LD_Q;
    float *g = s_g;
    for (int i = 0; i < LD_DIM; i++) {
        const float xi = s_x[i];
        for (int j = 0; j <= i; j++)
            *g++ += xi * s_x[j];
        s_sum[label][i] += xi;
    }
    s_n[label]++;
}

float ld_shrinkage(void)
{
    return s_rho;
}

int ld_fit(void)
{
    uint32_t n_all = 0;
    for (int c = 0; c < LD_CLASSES; c++) {
        if (!s_n[c])
            return -1;
        n_all += s_n[c];
    }
    const float inv_n = 1.0f / (float)n_all;
    /* S = (G - sum_c s_c s_c^T / n_c) / N */
    for (int i = 0; i < LD_DIM; i++)
        for (int j = 0; j <= i; j++) {
            float v = s_g[TRI(i, j)];
            for (int c = 0; c < LD_CLASSES; c++)
                v -= s_sum[c][i] * s_sum[c][j] / (float)s_n[c];
            s_l[TRI(i, j)] = v * inv_n;
        }
    /* OAS shrinkage */
    float tr = 0.0f, sq = 0.0f;
    for (int i = 0; i < LD_DIM; i++) {
        tr += s_l[TRI(i, i)];
        for (int j = 0; j < i; j++)
            sq += 2.0f * s_l[TRI(i, j)] * s_l[TRI(i, j)];
        sq += s_l[TRI(i, i)] * s_l[TRI(i, i)];
    }
    const float mu = tr / LD_DIM, alpha = sq / (float)(LD_DIM * LD_DIM);
    /* degenerate data (e.g. identical rows): the within-class variance is only rounding noise of G - s s^T / n,
     * which can come out slightly positive and pass the Cholesky. Compare it with the total second moment. */
    float tot = 0.0f;
    for (int i = 0; i < LD_DIM; i++)
        tot += s_g[TRI(i, i)];
    if (!(mu > 1e-5f * tot * inv_n / LD_DIM))
        return -2;
    const float num = alpha + mu * mu, den = ((float)n_all + 1.0f) * (alpha - mu * mu / LD_DIM);
    float rho = (den == 0.0f || num / den > 1.0f) ? 1.0f : num / den;
    for (int k = 0; k < LD_TRI; k++)
        s_l[k] *= 1.0f - rho;
    for (int i = 0; i < LD_DIM; i++)
        s_l[TRI(i, i)] += rho * mu;
    /* Cholesky in place: C = L L^T */
    for (int i = 0; i < LD_DIM; i++)
        for (int j = 0; j <= i; j++) {
            float v = s_l[TRI(i, j)];
            for (int k = 0; k < j; k++)
                v -= s_l[TRI(i, k)] * s_l[TRI(j, k)];
            if (i == j) {
                if (!(v > 0.0f))
                    return -2;
                s_l[TRI(i, i)] = sqrtf(v);
            } else {
                s_l[TRI(i, j)] = v / s_l[TRI(j, j)];
            }
        }
    /* w_c = C^-1 m_c, b_c = -m_c.w_c / 2 */
    for (int c = 0; c < LD_CLASSES; c++) {
        float *w = s_w[c];
        const float inv = 1.0f / (float)s_n[c];
        for (int i = 0; i < LD_DIM; i++) {      /* L y = m */
            float v = s_sum[c][i] * inv;
            for (int k = 0; k < i; k++)
                v -= s_l[TRI(i, k)] * w[k];
            w[i] = v / s_l[TRI(i, i)];
        }
        for (int i = LD_DIM - 1; i >= 0; i--) { /* L^T w = y */
            float v = w[i];
            for (int k = i + 1; k < LD_DIM; k++)
                v -= s_l[TRI(k, i)] * w[k];
            w[i] = v / s_l[TRI(i, i)];
        }
        float d = 0.0f;
        for (int i = 0; i < LD_DIM; i++)
            d += s_sum[c][i] * inv * w[i];
        s_b[c] = -0.5f * d;
    }
    s_rho = rho;
    return 0;
}

int ld_scores(const int16_t *x, float *scores)
{
    int best = 0;
    for (int c = 0; c < LD_CLASSES; c++) {
        float v = 0.0f;
        for (int i = 0; i < LD_DIM; i++)
            v += (float)x[i] * s_w[c][i];
        scores[c] = v / LD_Q + s_b[c];
        if (scores[c] > scores[best])
            best = c;
    }
    return best;
}

int ld_predict(const int16_t *x)
{
    float s[LD_CLASSES];
    return ld_scores(x, s);
}
