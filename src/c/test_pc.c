/* PC correctness harness: read float32 features (n x 80), predict each row, write int32 labels.
 *
 *   build with -DUSE_EMLEARN to call emlearn's generated rfmodel_predict() (emlearn_model.h),
 *   otherwise our table runtime rf_predict() (rf_model.h + rf_predict.c).
 *   Define FEATURES_INT16 for models whose features are Q5.10 int16.
 *
 * usage: test_pc <test_X.bin> <out_pred.bin>
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <math.h>

#define N_FEAT 80

#ifdef USE_EMLEARN
#include "emlearn_model.h"
#else
#include "rf_predict.h"
#endif

#ifdef FEATURES_INT16
static void quantize(const float *in, int16_t *out)
{
#ifdef USE_EMLEARN
    for (int i = 0; i < N_FEAT; i++) {
        float q = rintf(ldexpf(in[i], 10));
        if (q > 32767.0f) q = 32767.0f;
        if (q < -32768.0f) q = -32768.0f;
        out[i] = (int16_t)q;
    }
#else
    rf_quantize(in, out, N_FEAT);
#endif
}
#endif

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: %s test_X.bin out_pred.bin\n", argv[0]);
        return 2;
    }
    FILE *fi = fopen(argv[1], "rb"), *fo = fopen(argv[2], "wb");
    if (!fi || !fo) {
        perror("fopen");
        return 1;
    }
    float x[N_FEAT];
    long n = 0;
    while (fread(x, sizeof(float), N_FEAT, fi) == N_FEAT) {
        int32_t y;
#ifdef FEATURES_INT16
        int16_t xq[N_FEAT];
        quantize(x, xq);
#ifdef USE_EMLEARN
        y = rfmodel_predict(xq, N_FEAT);
#else
        y = rf_predict(xq);
#endif
#else
#ifdef USE_EMLEARN
        y = rfmodel_predict(x, N_FEAT);
#else
        y = rf_predict(x);
#endif
#endif
        fwrite(&y, sizeof y, 1, fo);
        n++;
    }
    fclose(fi);
    fclose(fo);
    fprintf(stderr, "%ld samples\n", n);
    return 0;
}
