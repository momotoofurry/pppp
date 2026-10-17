#include "rf_predict.h"

#include <math.h>

int rf_predict(const rf_value_t *x)
{
    uint16_t votes[RF_N_CLASSES] = {0};
    for (int t = 0; t < RF_N_TREES; t++) {
        const uint32_t root = rf_roots[t];
        int cls;
        if (root & 0x80000000u) {
            cls = (int)(root & 0xffu);
        } else {
            const uint8_t *feat = rf_feat + root;
            const rf_value_t *thr = rf_thr + root;
            const uint16_t *left = rf_left + root;
            const uint16_t *right = rf_right + root;
            uint16_t n = 0;
            for (;;) {
                const uint16_t c = (x[feat[n]] < thr[n]) ? left[n] : right[n];
                if (c & 0x8000u) {
                    cls = c & 0x7fff;
                    break;
                }
                n = c;
            }
        }
        votes[cls]++;
    }
    int best = 0;
    for (int k = 1; k < RF_N_CLASSES; k++)
        if (votes[k] > votes[best])
            best = k;
    return best;
}

#if RF_INT16
void rf_quantize(const float *in, int16_t *out, int n)
{
    for (int i = 0; i < n; i++) {
        /* scaling by 2^RF_Q_SHIFT is exact in float; rintf rounds half to even like numpy */
        float q = rintf(in[i] * (float)(1 << RF_Q_SHIFT));
        if (q > 32767.0f) q = 32767.0f;
        if (q < -32768.0f) q = -32768.0f;
        out[i] = (int16_t)q;
    }
}
#endif
