/* Start-up channel alignment and class-balanced z-score update, static memory only. See adapt.h. */
#include "adapt.h"

#include <math.h>
#include <string.h>

#define AMP_N 3
static const uint8_t AMP[AMP_N] = {0, 4, 1};    /* rms, mav, wl in the upstream feature order (pipeline.FEATS) */

/* ---- state ---- */
static float s_mu[SC_DIM], s_var[SC_DIM], s_inv[SC_DIM];
static float s_cal_prof[AMP_N][AD_CH];
static double s_al_sum[AMP_N][AD_CH];
static int s_al_n;
static int s_k;
/* ---- per-block class accumulators (Welford) ---- */
static float s_cm[SC_CLASSES][SC_DIM], s_cm2[SC_CLASSES][SC_DIM];
static int s_cn[SC_CLASSES];

unsigned ad_static_bytes(void)
{
    return (unsigned)(sizeof s_mu + sizeof s_var + sizeof s_inv + sizeof s_cal_prof + sizeof s_al_sum + sizeof s_al_n +
                      sizeof s_k + sizeof s_cm + sizeof s_cm2 + sizeof s_cn);
}

static void refresh_inv(void)
{
    for (int j = 0; j < SC_DIM; j++)
        s_inv[j] = s_var[j] > 0.0f ? 1.0f / sqrtf(s_var[j]) : 0.0f;
}

static void standardise_channels(double p[AMP_N][AD_CH], float out[AMP_N][AD_CH])
{
    for (int a = 0; a < AMP_N; a++) {
        double m = 0.0, s = 0.0;
        for (int c = 0; c < AD_CH; c++)
            m += p[a][c];
        m /= AD_CH;
        for (int c = 0; c < AD_CH; c++)
            s += (p[a][c] - m) * (p[a][c] - m);
        s = sqrt(s / AD_CH);
        for (int c = 0; c < AD_CH; c++)
            out[a][c] = (float)(s > 0.0 ? (p[a][c] - m) / s : 0.0);
    }
}

static double logf_clip(float x)
{
    return log(x > 1e-12f ? (double)x : 1e-12);
}

void ad_init(const float *mu, const float *inv_sd, const float *cal, int n_cal)
{
    for (int j = 0; j < SC_DIM; j++) {
        s_mu[j] = mu[j];
        s_var[j] = inv_sd[j] > 0.0f ? 1.0f / (inv_sd[j] * inv_sd[j]) : 0.0f;
        s_inv[j] = inv_sd[j];
    }
    double p[AMP_N][AD_CH] = {{0}};
    for (int i = 0; i < n_cal; i++)
        for (int a = 0; a < AMP_N; a++)
            for (int c = 0; c < AD_CH; c++)
                p[a][c] += logf_clip(cal[i * SC_DIM + AMP[a] * AD_CH + c]);
    for (int a = 0; a < AMP_N; a++)
        for (int c = 0; c < AD_CH; c++)
            p[a][c] /= n_cal > 0 ? n_cal : 1;
    standardise_channels(p, s_cal_prof);
    s_k = 0;
    ad_align_reset();
    memset(s_cn, 0, sizeof s_cn);               /* all three: a re-calibration may come in the middle of a block */
    memset(s_cm, 0, sizeof s_cm);
    memset(s_cm2, 0, sizeof s_cm2);
}

void ad_align_reset(void)
{
    memset(s_al_sum, 0, sizeof s_al_sum);
    s_al_n = 0;
}

void ad_align_push(const float *raw)
{
    for (int a = 0; a < AMP_N; a++)
        for (int c = 0; c < AD_CH; c++)
            s_al_sum[a][c] += logf_clip(raw[AMP[a] * AD_CH + c]);
    s_al_n++;
}

int ad_align_count(void)
{
    return s_al_n;
}

int ad_align_finish(void)
{
    if (s_al_n == 0)
        return s_k = 0;
    double p[AMP_N][AD_CH];
    float q[AMP_N][AD_CH];
    for (int a = 0; a < AMP_N; a++)
        for (int c = 0; c < AD_CH; c++)
            p[a][c] = s_al_sum[a][c] / s_al_n;
    standardise_channels(p, q);
    int best = 0;
    double best_s = -1e300;
    for (int k = 0; k < AD_CH; k++) {           /* np.roll(p, k)[c] = p[c - k] */
        double s = 0.0;
        for (int a = 0; a < AMP_N; a++)
            for (int c = 0; c < AD_CH; c++)
                s += (double)s_cal_prof[a][c] * q[a][(c - k + AD_CH) % AD_CH];
        if (s > best_s) {                       /* first maximum, as np.argmax */
            best_s = s;
            best = k;
        }
    }
    return s_k = best < 4 ? best : best - AD_CH;
}

int ad_rotation(void)
{
    return s_k;
}

void ad_set_rotation(int k)
{
    s_k = k;
}

void ad_map(const float *raw, float *out)
{
    /* model channel c <- recorded channel (c + k) mod 8 is the recording rotated by k; undoing an estimated
     * rotation k means column c <- column (c - k) mod 8 (python: rotate(X, -k)) */
    for (int f = 0; f < SC_DIM / AD_CH; f++)
        for (int c = 0; c < AD_CH; c++)
            out[f * AD_CH + c] = raw[f * AD_CH + ((c - s_k) % AD_CH + AD_CH) % AD_CH];
}

void ad_normalize(const float *x, int16_t *q)
{
    for (int j = 0; j < SC_DIM; j++) {
        float v = rintf((x[j] - s_mu[j]) * s_inv[j] * 1024.0f);   /* half to even, as os_normalize / numpy */
        q[j] = (int16_t)(v > 32767.0f ? 32767 : v < -32768.0f ? -32768 : v);
    }
}

void ad_observe(const float *x, int cls)
{
    if (cls < 0 || cls >= SC_CLASSES)
        return;
    int n = ++s_cn[cls];
    for (int j = 0; j < SC_DIM; j++) {
        float d = x[j] - s_cm[cls][j];
        s_cm[cls][j] += d / (float)n;
        s_cm2[cls][j] += d * (x[j] - s_cm[cls][j]);
    }
}

void ad_end_block(ad_stats_t *st)
{
    ad_end_block_map(st, 0, 0);
}

void ad_end_block_map(ad_stats_t *st, float *scale, float *offset)
{
    int used = 0;
    for (int k = 0; k < SC_CLASSES; k++)
        used += s_cn[k] >= AD_MIN_CLASS;
    st->classes_used = used;
    st->updated = 0;
    if (used >= 2) {
        for (int j = 0; j < SC_DIM; j++) {
            double m = 0.0, v = 0.0, m2 = 0.0;
            for (int k = 0; k < SC_CLASSES; k++)
                if (s_cn[k] >= AD_MIN_CLASS) {
                    m += s_cm[k][j];
                    m2 += (double)s_cm[k][j] * s_cm[k][j];
                    v += s_cm2[k][j] / s_cn[k];
                }
            m /= used;
            v = v / used + (m2 / used - m * m);  /* mean of class variances + variance of class means */
            float mu_old = s_mu[j], inv_old = s_inv[j];
            s_mu[j] = (1.0f - AD_RATE) * s_mu[j] + AD_RATE * (float)m;
            s_var[j] = (1.0f - AD_RATE) * s_var[j] + AD_RATE * (float)(v > 0.0 ? v : 0.0);
            if (scale) {                        /* q_old -> q_new of the same raw value, Q5.10 */
                float inv_new = s_var[j] > 0.0f ? 1.0f / sqrtf(s_var[j]) : 0.0f;
                scale[j] = inv_old > 0.0f ? inv_new / inv_old : 0.0f;
                offset[j] = 1024.0f * (mu_old - s_mu[j]) * inv_new;
            }
        }
        refresh_inv();
        st->updated = 1;
    }
    memset(s_cn, 0, sizeof s_cn);
    memset(s_cm, 0, sizeof s_cm);
    memset(s_cm2, 0, sizeof s_cm2);
}

#if SC_ROLLBACK
static float s_mu_bak[SC_DIM], s_var_bak[SC_DIM];

void ad_save(void)
{
    memcpy(s_mu_bak, s_mu, sizeof s_mu);
    memcpy(s_var_bak, s_var, sizeof s_var);
}

void ad_skip_block(void)
{
    memset(s_cn, 0, sizeof s_cn);
    memset(s_cm, 0, sizeof s_cm);
    memset(s_cm2, 0, sizeof s_cm2);
}

void ad_restore(void)
{
    memcpy(s_mu, s_mu_bak, sizeof s_mu);
    memcpy(s_var, s_var_bak, sizeof s_var);
    refresh_inv();
}
#endif

const float *ad_mean(void)
{
    return s_mu;
}

const float *ad_var(void)
{
    return s_var;
}
