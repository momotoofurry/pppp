/* Energy measurement firmware (report 35.33; exploratory, NOT the frozen firmware). Takes the place of bench.c in a
 * COPY of the CubeMX project (as lda_bench.c), uses bench.h plus the HAL for the tick, WFI and the LEDs; never
 * touches the Flash. For a multimeter in series with the IDD jumper (MCU supply only): the board holds one load for
 * HOLD_MS, then the next, and cycles through the states forever, so a slow meter can settle on each.
 *
 * At start: one timing pass (DWT cycles) of every unit of work. Then the states, each announced on the virtual COM
 * port and by LD1 (green) blinking the state number BEFORE the hold starts (the LED is off during the hold):
 *   1 spin      CPU busy-waiting on the tick (active, no work)            -> the "awake doing nothing" current
 *   2 wfi       __WFI() until the next 1 kHz SysTick                       -> the "sleeping between work" current
 *   3 fit       ld_fit() back to back (one LDA solve, 80 features)
 *   4 update    one soft task-label update back to back: ld_soft_q over 10 rows, ld_decay(0.97), 10 x ld_add_soft,
 *               ld_fit (the 4.66 ms update of report 35.23)
 *   5 window    one 100 ms window back to back: 200 samples x 8 channels through fe_push (filters, and at the window
 *               end the features), fe_normalize_q16, ld_predict
 *   6 realtime  the real-time duty cycle: every 1 ms tick 2 samples x 8 channels (2 kHz), the window work when a
 *               window completes (10 per second), __WFI() in between
 *   7 rt+upd    as 6, plus one soft update every 2 s (one robot command every 2 s)
 * At the end of every state: how many units ran and the units per second, so that
 *   energy per unit  ~ (I_state - I_wfi) x 3.3 V / (units per second)      (marginal, over sleeping)
 *   average power of the real-time loop = I_realtime x 3.3 V
 * The input is pseudo-random noise (the work does not depend on the values, except the FFT on denormals, which
 * the noise amplitude avoids); the LDA is fitted once from the 60 labelled rows of leaf_rows.h.
 */
#include "bench.h"

#include <stdio.h>
#include <string.h>

#include "features.h"
#include "ldacal.h"
#include "leaf_rows.h"
#include "main.h"
#include "stm32h7xx_hal.h"

#ifndef HOLD_MS
#define HOLD_MS 30000u
#endif
#define UPDATE_EVERY_MS 2000u

static uint32_t s_hz;
static char s_line[220];
static uint32_t s_rng = 12345u;
static float s_x[FE_CH], s_feat[FE_DIM], s_mu[FE_DIM], s_isd[FE_DIM];
static int16_t s_q[FE_DIM];
static float s_prior[LD_CLASSES], s_qq[LD_CLASSES];
static volatile uint32_t s_sink;
static int s_cmd;

static float noise(void)
{
    s_rng = s_rng * 1664525u + 1013904223u;
    return (float)((int32_t)s_rng >> 8) * (1.0f / 8388608.0f);       /* uniform in [-1, 1) */
}

static void samples(int n)
{
    for (int i = 0; i < n; i++) {
        for (int c = 0; c < FE_CH; c++)
            s_x[c] = noise();
        if (fe_push(s_x, s_feat)) {
            fe_normalize_q16(s_feat, s_mu, s_isd, s_q);
            s_sink += (uint32_t)ld_predict(s_q);
        }
    }
}

static void window(void)
{
    samples(FE_STEP);
}

static void update(void)
{
    const int k = (s_cmd * 10) % (LR_NU - 10 + 1);
    const int e = lr_use_y[k];
    s_cmd++;
    for (int c = 0; c < LD_CLASSES; c++)
        s_prior[c] = 0.01f;
    s_prior[e] = 0.85f;
    s_prior[(e + 1) % 5] = 0.05f;
    s_prior[(e + 2) % 5] = 0.05f;
    s_prior[5] = 0.05f;
    s_sink += (uint32_t)ld_soft_q(lr_use[k], 10, s_prior, 0.3f, s_qq);
    ld_decay(0.97f);
    for (int r = 0; r < 10; r++)
        ld_add_soft(lr_use[k + r], s_qq);
    s_sink += (uint32_t)ld_fit();
}

static void fit(void)
{
    s_sink += (uint32_t)ld_fit();
}

static unsigned long tenth_us(uint64_t cycles)
{
    return (unsigned long)(cycles * 10u / (s_hz / 1000000u));
}

static void time_unit(const char *name, void (*f)(void), int n)
{
    uint64_t sum = 0;
    uint32_t mx = 0;
    for (int i = 0; i < n; i++) {
        uint32_t t0 = bench_cycles();
        f();
        uint32_t c = bench_cycles() - t0;
        sum += c;
        if (c > mx)
            mx = c;
    }
    unsigned long m = tenth_us(sum / (uint64_t)n), x = tenth_us(mx);
    snprintf(s_line, sizeof s_line, "  %-8s n=%4d  mean %6lu.%lu us   max %6lu.%lu us\r\n", name, n, m / 10, m % 10, x / 10,
             x % 10);
    bench_print(s_line);
}

static void led(int on)
{
    HAL_GPIO_WritePin(ld1_GPIO_Port, ld1_Pin, on ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static void blink(int n)
{
    for (int i = 0; i < n; i++) {
        led(1);
        HAL_Delay(200);
        led(0);
        HAL_Delay(300);
    }
    HAL_Delay(1000);
}

static void hold(int id, const char *name, const char *unit)
{
    snprintf(s_line, sizeof s_line, "state %d %-8s start (hold %lu s)\r\n", id, name, (unsigned long)(HOLD_MS / 1000u));
    bench_print(s_line);
    blink(id);
    uint32_t t0 = HAL_GetTick(), units = 0, next_upd = t0 + UPDATE_EVERY_MS, last = t0;
    while (HAL_GetTick() - t0 < HOLD_MS) {
        switch (id) {
        case 1:
            __NOP();
            break;
        case 2:
            __WFI();
            break;
        case 3:
            fit();
            units++;
            break;
        case 4:
            update();
            units++;
            break;
        case 5:
            window();
            units++;
            break;
        default: {                                       /* 6, 7: one 1 ms tick = 2 samples per channel */
            uint32_t now = HAL_GetTick();
            if (now != last) {
                while (last != now) {                    /* catch up: no 1 ms batch of samples is ever skipped */
                    last++;
                    samples(2);
                    units++;
                }
                if (id == 7 && (int32_t)(now - next_upd) >= 0) {
                    next_upd += UPDATE_EVERY_MS;
                    update();
                }
            } else {
                __WFI();
            }
        }
        }
    }
    uint32_t ms = HAL_GetTick() - t0;
    unsigned long per_s100 = (unsigned long)((uint64_t)units * 100000u / ms);
    snprintf(s_line, sizeof s_line, "state %d %-8s end: %lu %s in %lu ms = %lu.%02lu per s\r\n", id, name,
             (unsigned long)units, unit, (unsigned long)ms, per_s100 / 100, per_s100 % 100);
    bench_print(s_line);
}

void bench_run(uint32_t cpu_hz)
{
    s_hz = cpu_hz;
    led(0);
    fe_init();
    fe_reset();
    for (int i = 0; i < FE_DIM; i++)
        s_mu[i] = 0.0f, s_isd[i] = 1.0f;
    ld_reset();
    for (int i = 0; i < LR_NA; i++)
        ld_add(lr_anchor[i], lr_anchor_y[i]);
    int r = ld_fit();
    snprintf(s_line, sizeof s_line, "\r\n=== energy states ===\r\n%s\r\nfirst fit %d, hold %lu ms per state, update every %lu ms "
             "in state 7\r\nunit timings:\r\n", bench_platform(), r, (unsigned long)HOLD_MS, (unsigned long)UPDATE_EVERY_MS);
    bench_print(s_line);
    time_unit("fit", fit, 50);
    time_unit("update", update, 50);
    time_unit("window", window, 50);
    for (int cycle = 1;; cycle++) {
        snprintf(s_line, sizeof s_line, "--- cycle %d ---\r\n", cycle);
        bench_print(s_line);
        hold(1, "spin", "-");
        hold(2, "wfi", "-");
        hold(3, "fit", "fits");
        hold(4, "update", "updates");
        hold(5, "window", "windows");
        hold(6, "realtime", "ticks");
        hold(7, "rt+upd", "ticks");
        if (cycle == 1)
            bench_print("=== done ===\r\n");
    }
}
