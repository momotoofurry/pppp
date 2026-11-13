/* Small MLP for the MCU (report 35.39): see mlp.h. */
#include "mlp.h"

#include <math.h>
#include <string.h>

#define OFF_W1 0
#define OFF_B1 (OFF_W1 + MLP_IN * MLP_H1)
#define OFF_W2 (OFF_B1 + MLP_H1)
#define OFF_B2 (OFF_W2 + MLP_H1 * MLP_H2)
#define OFF_W3 (OFF_B2 + MLP_H2)
#define OFF_B3 (OFF_W3 + MLP_H2 * MLP_K)

static float s_p[MLP_NPARAM];          /* parameters */
static float s_g[MLP_NPARAM];          /* gradient of the current mini-batch */
static float s_m[MLP_NPARAM];          /* Adam first moment */
static float s_v[MLP_NPARAM];          /* Adam second moment */
static float s_b1t, s_b2t;             /* beta1^t, beta2^t */
static float s_x[MLP_IN], s_h1[MLP_H1], s_h2[MLP_H2], s_z[MLP_K];
static float s_d2[MLP_H2], s_d1[MLP_H1];

void mlp_adam_reset(void)
{
    memset(s_m, 0, sizeof s_m);
    memset(s_v, 0, sizeof s_v);
    s_b1t = 1.0f;
    s_b2t = 1.0f;
}

void mlp_load(const float *params)
{
    memcpy(s_p, params, sizeof s_p);
    mlp_adam_reset();
}

const float *mlp_params(void)
{
    return s_p;
}

unsigned mlp_static_bytes(void)
{
    return (unsigned)(sizeof s_p + sizeof s_g + sizeof s_m + sizeof s_v + sizeof s_x + sizeof s_h1 + sizeof s_h2 +
                      sizeof s_z + sizeof s_d2 + sizeof s_d1);
}

static void layer(const float *in, int n_in, const float *w, const float *b, float *out, int n_out, int relu)
{
    for (int j = 0; j < n_out; j++)
        out[j] = b[j];
    for (int i = 0; i < n_in; i++) {
        const float xi = in[i];
        if (xi == 0.0f)
            continue;
        const float *wi = w + i * n_out;
        for (int j = 0; j < n_out; j++)
            out[j] += xi * wi[j];
    }
    if (relu)
        for (int j = 0; j < n_out; j++)
            if (out[j] < 0.0f)
                out[j] = 0.0f;
}

static void forward(const int16_t *x)
{
    for (int i = 0; i < MLP_IN; i++)
        s_x[i] = (float)x[i] * (1.0f / 1024.0f);
    layer(s_x, MLP_IN, s_p + OFF_W1, s_p + OFF_B1, s_h1, MLP_H1, 1);
    layer(s_h1, MLP_H1, s_p + OFF_W2, s_p + OFF_B2, s_h2, MLP_H2, 1);
    layer(s_h2, MLP_H2, s_p + OFF_W3, s_p + OFF_B3, s_z, MLP_K, 0);
}

int mlp_scores(const int16_t *x, float *scores)
{
    forward(x);
    int best = 0;
    for (int k = 0; k < MLP_K; k++) {
        scores[k] = s_z[k];
        if (s_z[k] > s_z[best])
            best = k;
    }
    return best;
}

int mlp_predict(const int16_t *x)
{
    float sc[MLP_K];
    return mlp_scores(x, sc);
}

/* forward + backward of one sample, gradient added to s_g */
static void accumulate(const int16_t *x, int y)
{
    forward(x);
    float mx = s_z[0];
    for (int k = 1; k < MLP_K; k++)
        if (s_z[k] > mx)
            mx = s_z[k];
    float d3[MLP_K], sum = 0.0f;
    for (int k = 0; k < MLP_K; k++) {
        d3[k] = expf(s_z[k] - mx);
        sum += d3[k];
    }
    for (int k = 0; k < MLP_K; k++)
        d3[k] = d3[k] / sum - (k == y ? 1.0f : 0.0f);
    /* layer 3 */
    for (int i = 0; i < MLP_H2; i++) {
        float *g = s_g + OFF_W3 + i * MLP_K;
        const float *w = s_p + OFF_W3 + i * MLP_K;
        float d = 0.0f;
        for (int k = 0; k < MLP_K; k++) {
            g[k] += s_h2[i] * d3[k];
            d += w[k] * d3[k];
        }
        s_d2[i] = s_h2[i] > 0.0f ? d : 0.0f;
    }
    for (int k = 0; k < MLP_K; k++)
        s_g[OFF_B3 + k] += d3[k];
    /* layer 2 */
    for (int i = 0; i < MLP_H1; i++) {
        float *g = s_g + OFF_W2 + i * MLP_H2;
        const float *w = s_p + OFF_W2 + i * MLP_H2;
        float d = 0.0f;
        for (int j = 0; j < MLP_H2; j++) {
            g[j] += s_h1[i] * s_d2[j];
            d += w[j] * s_d2[j];
        }
        s_d1[i] = s_h1[i] > 0.0f ? d : 0.0f;
    }
    for (int j = 0; j < MLP_H2; j++)
        s_g[OFF_B2 + j] += s_d2[j];
    /* layer 1 */
    for (int i = 0; i < MLP_IN; i++) {
        float *g = s_g + OFF_W1 + i * MLP_H1;
        const float xi = s_x[i];
        if (xi == 0.0f)
            continue;
        for (int j = 0; j < MLP_H1; j++)
            g[j] += xi * s_d1[j];
    }
    for (int j = 0; j < MLP_H1; j++)
        s_g[OFF_B1 + j] += s_d1[j];
}

static int is_weight(int i)
{
    return (i < OFF_B1) || (i >= OFF_W2 && i < OFF_B2) || (i >= OFF_W3 && i < OFF_B3);
}

static void adam_step(int nb, float lr, float l2)
{
    const float b1 = 0.9f, b2 = 0.999f, eps = 1e-8f;
    s_b1t *= b1;
    s_b2t *= b2;
    const float c1 = 1.0f / (1.0f - s_b1t), c2 = 1.0f / (1.0f - s_b2t), inv = 1.0f / (float)nb;
    for (int i = 0; i < MLP_NPARAM; i++) {
        float g = s_g[i] * inv;
        if (is_weight(i))
            g += l2 * s_p[i];
        s_m[i] = b1 * s_m[i] + (1.0f - b1) * g;
        s_v[i] = b2 * s_v[i] + (1.0f - b2) * g * g;
        s_p[i] -= lr * (s_m[i] * c1) / (sqrtf(s_v[i] * c2) + eps);
    }
}

void mlp_train_epoch(const int16_t (*x)[MLP_IN], const uint8_t *y, int n, int batch, float lr, float l2)
{
    for (int s = 0; s < n; s += batch) {
        int e = s + batch < n ? s + batch : n;
        memset(s_g, 0, sizeof s_g);
        for (int r = s; r < e; r++)
            accumulate(x[r], y[r]);
        adam_step(e - s, lr, l2);
    }
}
