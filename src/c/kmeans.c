/* K-Means (Lloyd) on the standardised t-SNE embedding, static memory only. See kmeans.h. */
#include "kmeans.h"

#include <float.h>
#include <string.h>

static uint8_t s_old[KM_NMAX];

unsigned km_static_bytes(void)
{
    return (unsigned)sizeof s_old;
}

static int assign(const float *x, int n, const float *ctr, int k, uint8_t *lab, float *dist)
{
    int changed = 0;
    for (int i = 0; i < n; i++) {
        float best = FLT_MAX;
        int b = 0;
        for (int c = 0; c < k; c++) {
            float d = 0.0f;
            for (int a = 0; a < KM_DIM; a++) {
                float t = x[i * KM_DIM + a] - ctr[c * KM_DIM + a];
                d += t * t;
            }
            if (d < best) {              /* ties -> lowest cluster, as sklearn */
                best = d;
                b = c;
            }
        }
        if (dist)
            dist[i] = best;
        changed |= lab[i] != b;
        lab[i] = (uint8_t)b;
    }
    return changed;
}

int km_fit(const float *x, int n, int k, float *ctr, int max_iter, float tol_rel, uint8_t *lab)
{
    if (n > KM_NMAX || k > KM_KMAX || n < k)
        return -1;
    /* sklearn: tol = tol_rel * mean over dimensions of the data variance */
    double var = 0.0;
    for (int a = 0; a < KM_DIM; a++) {
        double m = 0.0, s = 0.0;
        for (int i = 0; i < n; i++)
            m += x[i * KM_DIM + a];
        m /= n;
        for (int i = 0; i < n; i++)
            s += (x[i * KM_DIM + a] - m) * (x[i * KM_DIM + a] - m);
        var += s / n;
    }
    const double tol = tol_rel * var / KM_DIM;
    int it, strict = 0;
    memset(s_old, 0xFF, n);
    for (it = 0; it < max_iter; it++) {
        static float dist[KM_NMAX];
        assign(x, n, ctr, k, lab, dist);
        /* M-step */
        float sum[KM_KMAX * KM_DIM] = {0};
        int cnt[KM_KMAX] = {0};
        for (int i = 0; i < n; i++) {
            cnt[lab[i]]++;
            for (int a = 0; a < KM_DIM; a++)
                sum[lab[i] * KM_DIM + a] += x[i * KM_DIM + a];
        }
        /* empty cluster: take the point farthest from its centre (sklearn relocates the farthest points) */
        for (int c = 0; c < k; c++) {
            if (cnt[c])
                continue;
            int far = 0;
            for (int i = 1; i < n; i++)
                if (dist[i] > dist[far] && cnt[lab[i]] > 1)
                    far = i;
            int o = lab[far];
            cnt[o]--;
            for (int a = 0; a < KM_DIM; a++) {
                sum[o * KM_DIM + a] -= x[far * KM_DIM + a];
                sum[c * KM_DIM + a] = x[far * KM_DIM + a];
            }
            cnt[c] = 1;
            dist[far] = 0.0f;
            lab[far] = (uint8_t)c;
        }
        double shift = 0.0;
        for (int c = 0; c < k; c++)
            for (int a = 0; a < KM_DIM; a++) {
                float v = sum[c * KM_DIM + a] / cnt[c];
                double d = v - ctr[c * KM_DIM + a];
                shift += d * d;
                ctr[c * KM_DIM + a] = v;
            }
        if (memcmp(lab, s_old, n) == 0) {
            strict = 1;
            break;
        }
        if (shift <= tol)
            break;
        memcpy(s_old, lab, n);
    }
    if (!strict)
        assign(x, n, ctr, k, lab, 0);   /* labels consistent with the final centres */
    return it;
}

void standardize(float *x, int n)
{
    for (int a = 0; a < KM_DIM; a++) {
        double m = 0.0, s = 0.0;
        for (int i = 0; i < n; i++)
            m += x[i * KM_DIM + a];
        m /= n;
        for (int i = 0; i < n; i++)
            s += (x[i * KM_DIM + a] - m) * (x[i * KM_DIM + a] - m);
        s = s > 0 ? 1.0 / __builtin_sqrt(s / n) : 1.0;   /* sklearn StandardScaler: population std */
        for (int i = 0; i < n; i++)
            x[i * KM_DIM + a] = (float)((x[i * KM_DIM + a] - m) * s);
    }
}

void group_centres(const float *x, int n, const uint8_t *lab, int k, float *ctr)
{
    int cnt[KM_KMAX] = {0};
    memset(ctr, 0, sizeof(float) * k * KM_DIM);
    for (int i = 0; i < n; i++) {
        cnt[lab[i]]++;
        for (int a = 0; a < KM_DIM; a++)
            ctr[lab[i] * KM_DIM + a] += x[i * KM_DIM + a];
    }
    for (int c = 0; c < k; c++)
        for (int a = 0; a < KM_DIM; a++)
            ctr[c * KM_DIM + a] /= cnt[c] ? cnt[c] : 1;
}
