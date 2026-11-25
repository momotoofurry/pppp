/* Per-session LDA re-calibration, static memory only. See ldacal.h. */
#include "ldacal.h"

#include <math.h>
#include <string.h>

#define TRI(i, j) ((i) * ((i) + 1) / 2 + (j))   /* packed lower triangle, j <= i */

static float s_g[LD_TRI];                       /* sum of x x^T over all labelled windows */
static float s_sum[LD_CLASSES][LD_DIM];
static float s_n[LD_CLASSES];                   /* weight per class (a count with hard labels) */
/* 35.103: the fitted model, twice. ld_fit writes the spare copy and publishes it with one index store, so a reader
 * that preempts ld_fit (rtl_rx in the TIM6 interrupt / the higher-priority task) always sees a whole model: the old
 * one until the store, the new one after it. A failed fit publishes nothing (the factor of the model in use stays
 * intact). Single writer (ld_fit, never re-entered), readers only take the index. */
typedef struct {
    float l[LD_TRI];                            /* covariance, then its Cholesky factor */
    float w[LD_CLASSES][LD_DIM];
    float b[LD_CLASSES];
    float m[LD_CLASSES][LD_DIM];                /* the class means the model was fitted with (ld_dist2) */
    float rho;
} ld_model_t;
static ld_model_t s_mod[2];
static volatile uint32_t s_cur;                 /* index of the published model */
static float s_x[LD_DIM];                       /* scratch of the writer side (ld_add, ld_add_soft) only */
#ifndef LD_TEST_HOOK
#define LD_TEST_HOOK(point) ((void)0)
#endif

static inline const ld_model_t *published(void)
{
    return &s_mod[__atomic_load_n(&s_cur, __ATOMIC_ACQUIRE)];
}
#define LD_ALL ((1u << LD_CLASSES) - 1u)
static uint32_t s_active = LD_ALL;

unsigned ld_static_bytes(void)
{
    return (unsigned)(sizeof s_g + sizeof s_sum + sizeof s_n + sizeof s_mod + sizeof s_cur + sizeof s_x +
                      sizeof s_active);
}

void ld_set_active(uint32_t mask)
{
    s_active = (mask & LD_ALL) | (1u << (LD_CLASSES - 1));
}

int ld_is_active(int c)
{
    return c >= 0 && c < LD_CLASSES && ((s_active >> c) & 1u);
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
    s_n[label] += 1.0f;
}

float ld_shrinkage(void)
{
    return published()->rho;
}

int ld_fit(void)
{
    const uint32_t nxt = 1u - s_cur;
    ld_model_t *const md = &s_mod[nxt];         /* the spare copy: nobody reads it until it is published */
    float *const s_l = md->l;
    float n_all = 0.0f;
    for (int c = 0; c < LD_CLASSES; c++) {
        if (!ld_is_active(c))
            continue;
        if (!(s_n[c] > 0.0f))
            return -1;
        n_all += s_n[c];
    }
    const float inv_n = 1.0f / n_all;
    /* S = (G - sum_c s_c s_c^T / n_c) / N */
    for (int i = 0; i < LD_DIM; i++)
        for (int j = 0; j <= i; j++) {
            float v = s_g[TRI(i, j)];
            for (int c = 0; c < LD_CLASSES; c++)
                if (ld_is_active(c))
                    v -= s_sum[c][i] * s_sum[c][j] / s_n[c];
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
    const float num = alpha + mu * mu, den = (n_all + 1.0f) * (alpha - mu * mu / LD_DIM);
    float rho = (den == 0.0f || num / den > 1.0f) ? 1.0f : num / den;
    for (int k = 0; k < LD_TRI; k++)
        s_l[k] *= 1.0f - rho;
    for (int i = 0; i < LD_DIM; i++)
        s_l[TRI(i, i)] += rho * mu;
    LD_TEST_HOOK(0);
    /* Cholesky in place: C = L L^T */
    for (int i = 0; i < LD_DIM; i++) {
        if (i % 16 == 0)
            LD_TEST_HOOK(1);
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
    }
    /* w_c = C^-1 m_c, b_c = -m_c.w_c / 2 */
    LD_TEST_HOOK(2);
    for (int c = 0; c < LD_CLASSES; c++) {
        if (!ld_is_active(c))
            continue;                           /* scored -INFINITY by ld_scores */
        float *w = md->w[c];
        const float inv = 1.0f / s_n[c];
        for (int i = 0; i < LD_DIM; i++)
            md->m[c][i] = s_sum[c][i] * inv;
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
        md->b[c] = -0.5f * d;
        LD_TEST_HOOK(3);
    }
    md->rho = rho;
    __atomic_store_n(&s_cur, nxt, __ATOMIC_RELEASE);   /* publish: one aligned 32-bit store */
    LD_TEST_HOOK(4);
    return 0;
}

int ld_scores(const int16_t *x, float *scores)
{
    const ld_model_t *md = published();
    int best = -1;                              /* the first active class wins ties, as before the mask */
    for (int c = 0; c < LD_CLASSES; c++) {
        if (!ld_is_active(c)) {
            scores[c] = -INFINITY;
            continue;
        }
        float v = 0.0f;
        for (int i = 0; i < LD_DIM; i++)
            v += (float)x[i] * md->w[c][i];
        scores[c] = v / LD_Q + md->b[c];
        if (best < 0 || scores[c] > scores[best])
            best = c;
    }
    return best;
}

float ld_dist2(const int16_t *x, int c)
{
    const ld_model_t *md = published();
    float z[LD_DIM];                            /* 35.103: own scratch (s_x belongs to the writer side) */
    float d = 0.0f;
    for (int i = 0; i < LD_DIM; i++) {          /* L z = x - m_c */
        float v = (float)x[i] / LD_Q - md->m[c][i];
        for (int k = 0; k < i; k++)
            v -= md->l[TRI(i, k)] * z[k];
        z[i] = v / md->l[TRI(i, i)];
        d += z[i] * z[i];
    }
    return d;
}

int ld_predict(const int16_t *x)
{
    float s[LD_CLASSES];
    return ld_scores(x, s);
}

void ld_add_soft(const int16_t *x, const float *q)
{
    for (int i = 0; i < LD_DIM; i++)
        s_x[i] = (float)x[i] / LD_Q;
    float *g = s_g;
    for (int i = 0; i < LD_DIM; i++) {
        const float xi = s_x[i];
        for (int j = 0; j <= i; j++)
            *g++ += xi * s_x[j];
    }
    for (int c = 0; c < LD_CLASSES; c++) {
        if (q[c] == 0.0f)
            continue;
        for (int i = 0; i < LD_DIM; i++)
            s_sum[c][i] += q[c] * s_x[i];
        s_n[c] += q[c];
    }
}

void ld_decay(float f)
{
    for (int k = 0; k < LD_TRI; k++)
        s_g[k] *= f;
    for (int c = 0; c < LD_CLASSES; c++) {
        for (int i = 0; i < LD_DIM; i++)
            s_sum[c][i] *= f;
        s_n[c] *= f;
    }
}

int ld_soft_q(const int16_t *rows, int nrows, const float *prior, float beta, float *q)
{
    float m[LD_CLASSES] = {0}, s[LD_CLASSES];
    for (int r = 0; r < nrows; r++) {
        ld_scores(rows + r * LD_DIM, s);
        for (int c = 0; c < LD_CLASSES; c++)
            m[c] += s[c];
    }
    float top = m[0] / (float)nrows;
    for (int c = 0; c < LD_CLASSES; c++) {
        m[c] /= (float)nrows;
        if (m[c] > top)
            top = m[c];
    }
    float tot = 0.0f;
    int best = 0;
    for (int c = 0; c < LD_CLASSES; c++) {
        q[c] = prior[c] * expf(beta * (m[c] - top));
        tot += q[c];
    }
    for (int c = 0; c < LD_CLASSES; c++) {
        q[c] /= tot;
        if (q[c] > q[best])
            best = c;
    }
    return best;
}
