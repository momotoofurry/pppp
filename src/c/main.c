/* Minimal Cortex-M7 (STM32H743) program: one feature vector -> rf_predict().
 *
 * g_features stands in for the output of on-device feature extraction (a RAM buffer).
 * The DWT cycle counter is read around the prediction; on real hardware g_cycles holds the
 * inference time in core clock cycles.
 * Build with -DUSE_EMLEARN to call emlearn's rfmodel_predict() instead of our table runtime.
 */
#include <stdint.h>
#include <string.h>

#include "sample_input.h"
#ifdef USE_EMLEARN
#include "emlearn_model.h"
#else
#include "rf_predict.h"
#endif

#define DEMCR      (*(volatile uint32_t *)0xE000EDFCu)
#define DWT_CTRL   (*(volatile uint32_t *)0xE0001000u)
#define DWT_CYCCNT (*(volatile uint32_t *)0xE0001004u)
#define DWT_LAR    (*(volatile uint32_t *)0xE0001FB0u)

float g_features[80];          /* feature buffer filled by feature extraction */
volatile int32_t g_pred = -1;
volatile uint32_t g_cycles;

#if defined(FEATURES_INT16)
static int16_t g_features_q[80];
static void quantize(const float *in, int16_t *out)
{
    for (int i = 0; i < 80; i++) {
        float q = __builtin_rintf(in[i] * 1024.0f);
        if (q > 32767.0f) q = 32767.0f;
        if (q < -32768.0f) q = -32768.0f;
        out[i] = (int16_t)q;
    }
}
#endif

int main(void)
{
    memcpy(g_features, sample_features, sizeof g_features);

    DEMCR |= 1u << 24;          /* TRCENA */
    DWT_LAR = 0xC5ACCE55u;      /* unlock DWT (needed on Cortex-M7) */
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1u;             /* CYCCNTENA */

    const uint32_t t0 = DWT_CYCCNT;
#if defined(FEATURES_INT16)
    quantize(g_features, g_features_q);
#ifdef USE_EMLEARN
    g_pred = rfmodel_predict(g_features_q, 80);
#else
    g_pred = rf_predict(g_features_q);
#endif
#else
#ifdef USE_EMLEARN
    g_pred = rfmodel_predict(g_features, 80);
#else
    g_pred = rf_predict(g_features);
#endif
#endif
    g_cycles = DWT_CYCCNT - t0;

    for (;;) {
    }
}
