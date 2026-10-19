/* Streaming EMG feature extraction, float32, static memory only. See features.h. */
#include "features.h"

#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* scipy.signal.butter(4, (10 * 2 / 2000, 500 * 2 / 2000), btype='bandpass', output='sos'): b0 b1 b2 a0 a1 a2 */
static const float SOS[4][6] = {
    {0.08820249967393601f, 0.17640499934787202f, 0.08820249967393601f, 1.0f, -0.02843462790167564f, 0.04224752573740011f},
    {1.0f, 2.0f, 1.0f, 1.0f, -0.006379783291503074f, 0.45728100305990194f},
    {1.0f, -2.0f, 1.0f, 1.0f, -1.9413512087108937f, 0.9423633968801141f},
    {1.0f, -2.0f, 1.0f, 1.0f, -1.9757901498887869f, 0.9767741445262733f},
};

static float s_z[FE_CH][4][2];              /* biquad states */
static float s_ring[FE_CH][FE_WIN];         /* filtered samples, ring */
static uint32_t s_count;                    /* samples since reset */
static float s_hamm[FE_WIN];
static float s_cos[FE_NFFT / 2], s_sin[FE_NFFT / 2];
static float s_re[FE_NFFT], s_im[FE_NFFT];  /* FFT work, also holds the linearised window */

unsigned fe_static_bytes(void)
{
    return (unsigned)(sizeof s_z + sizeof s_ring + sizeof s_count + sizeof s_hamm + sizeof s_cos + sizeof s_sin +
                      sizeof s_re + sizeof s_im);
}

void fe_init(void)
{
    for (int n = 0; n < FE_WIN; n++)        /* periodic Hamming (scipy get_window('hamming', 400)) */
        s_hamm[n] = (float)(0.54 - 0.46 * cos(2.0 * M_PI * n / FE_WIN));
    for (int k = 0; k < FE_NFFT / 2; k++) {
        s_cos[k] = (float)cos(2.0 * M_PI * k / FE_NFFT);
        s_sin[k] = (float)sin(2.0 * M_PI * k / FE_NFFT);
    }
    fe_reset();
}

void fe_reset(void)
{
    memset(s_z, 0, sizeof s_z);
    memset(s_ring, 0, sizeof s_ring);
    s_count = 0;
}

static void fft(float *re, float *im)
{
    for (int i = 1, j = 0; i < FE_NFFT; i++) {     /* bit reversal */
        int bit = FE_NFFT >> 1;
        for (; j & bit; bit >>= 1)
            j ^= bit;
        j ^= bit;
        if (i < j) {
            float t = re[i]; re[i] = re[j]; re[j] = t;
            t = im[i]; im[i] = im[j]; im[j] = t;
        }
    }
    for (int len = 2; len <= FE_NFFT; len <<= 1) {
        int step = FE_NFFT / len;
        for (int i = 0; i < FE_NFFT; i += len)
            for (int k = 0; k < len / 2; k++) {
                float wr = s_cos[k * step], wi = -s_sin[k * step];
                float *ar = re + i + k, *ai = im + i + k, *br = re + i + k + len / 2, *bi = im + i + k + len / 2;
                float tr = *br * wr - *bi * wi, ti = *br * wi + *bi * wr;
                *br = *ar - tr;
                *bi = *ai - ti;
                *ar += tr;
                *ai += ti;
            }
    }
}

static void channel_features(int ch, float *feat)
{
    float *x = s_re;                            /* window in time order */
    int start = (int)(s_count % FE_WIN);        /* oldest sample */
    for (int n = 0; n < FE_WIN; n++)
        x[n] = s_ring[ch][(start + n) % FE_WIN];
    float s2 = 0, sa = 0, wl = 0, mean = 0;
    int zc = 0, ssc = 0;
    for (int n = 0; n < FE_WIN; n++) {
        s2 += x[n] * x[n];
        sa += fabsf(x[n]);
        mean += x[n];
    }
    for (int n = 0; n + 1 < FE_WIN; n++) {
        float d = x[n + 1] - x[n];
        wl += fabsf(d);
        if (signbit(x[n]) != signbit(x[n + 1]) && fabsf(d) > 0.0f)
            zc++;
        if (n + 2 < FE_WIN) {
            float d2 = x[n + 2] - x[n + 1];
            if (signbit(d) != signbit(d2) && fmaxf(fabsf(d), fabsf(d2)) > 0.0f)
                ssc++;
        }
    }
    mean /= FE_WIN;
    float m2 = 0, m3 = 0;
    for (int n = 0; n < FE_WIN; n++) {
        float c = x[n] - mean;
        m2 += c * c;
        m3 += c * c * c;
    }
    m2 /= FE_WIN;
    m3 /= FE_WIN;
    /* PSD of the Hamming-windowed segment, zero-padded to FE_NFFT */
    for (int n = 0; n < FE_WIN; n++)
        x[n] *= s_hamm[n];
    for (int n = FE_WIN; n < FE_NFFT; n++)
        x[n] = 0.0f;
    memset(s_im, 0, sizeof s_im);
    fft(s_re, s_im);
    const int nb = FE_NFFT / 2 + 1;
    const float df = FE_FS / FE_NFFT;
    float sm0 = 0, sm1 = 0, sm2 = 0, pmax = -1.0f;
    int kmax = 0;
    for (int k = 0; k < nb; k++) {              /* power, one-sided: x2 except DC and Nyquist */
        float p = s_re[k] * s_re[k] + s_im[k] * s_im[k];
        if (k > 0 && k < nb - 1)
            p *= 2.0f;
        s_im[k] = p;                            /* keep the PSD for the median */
        float f = k * df;
        sm0 += p;
        sm1 += p * f;
        sm2 += p * f * f;
        if (p > pmax) {
            pmax = p;
            kmax = k;
        }
    }
    float half = 0.5f * sm0, cum = 0, best = INFINITY;
    int kmed = 0;
    for (int k = 0; k < nb; k++) {
        cum += s_im[k];
        float e = fabsf(cum - half);
        if (e < best) {
            best = e;
            kmed = k;
        }
    }
    float mnf = sm1 / sm0;
    feat[0 * FE_CH + ch] = sqrtf(s2 / FE_WIN);
    feat[1 * FE_CH + ch] = wl;
    feat[2 * FE_CH + ch] = (float)ssc;
    feat[3 * FE_CH + ch] = (float)zc;
    feat[4 * FE_CH + ch] = sa / FE_WIN;
    feat[5 * FE_CH + ch] = m3 / (m2 * sqrtf(m2));
    feat[6 * FE_CH + ch] = sm2 / sm0 - mnf * mnf;
    feat[7 * FE_CH + ch] = kmed * df;
    feat[8 * FE_CH + ch] = mnf;
    feat[9 * FE_CH + ch] = kmax * df;
}

int fe_push(const float *x, float *feat)
{
    int pos = (int)(s_count % FE_WIN);
    for (int ch = 0; ch < FE_CH; ch++) {
        float v = x[ch];
        for (int s = 0; s < 4; s++) {           /* direct form II transposed */
            const float *c = SOS[s];
            float y = c[0] * v + s_z[ch][s][0];
            s_z[ch][s][0] = c[1] * v - c[4] * y + s_z[ch][s][1];
            s_z[ch][s][1] = c[2] * v - c[5] * y;
            v = y;
        }
        s_ring[ch][pos] = v;
    }
    s_count++;
    if (s_count < FE_WIN || (s_count - FE_WIN) % FE_STEP != 0)
        return 0;
    for (int ch = 0; ch < FE_CH; ch++)
        channel_features(ch, feat);
    return 1;
}

void fe_normalize_q16(const float *feat, const float *mu, const float *inv_sd, int16_t *out)
{
    for (int i = 0; i < FE_DIM; i++) {
        float q = rintf((feat[i] - mu[i]) * inv_sd[i] * 1024.0f);
        if (q > 32767.0f) q = 32767.0f;
        if (q < -32768.0f) q = -32768.0f;
        out[i] = (int16_t)q;
    }
}

/* PC check helper: one recording, channel-major (FE_CH x n); writes every feature vector (nwin x FE_DIM).
 * Returns the number of windows. Not used on the MCU (removed by --gc-sections). */
int fe_recording(const float *x, int n, float *out, int max_win)
{
    float smp[FE_CH];
    int w = 0;
    fe_reset();
    for (int i = 0; i < n; i++) {
        for (int ch = 0; ch < FE_CH; ch++)
            smp[ch] = x[ch * n + i];
        if (fe_push(smp, out + w * FE_DIM) && ++w == max_win)
            break;
    }
    return w;
}
