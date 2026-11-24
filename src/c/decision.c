/* Low-confidence rejection + k-window agreement. See decision.h. */
#include "decision.h"

#if DC_CLASSES == 6
/* Power, Lateral, Tripod, Pointer, Open, Rest (pilot-freeze-5: Lateral = home, PROTOCOL.md 5) */
const uint8_t dc_class_command[DC_CLASSES] = {DC_POSE_A, DC_HOME, DC_GRIP, DC_POSE_B, DC_RELEASE, DC_NONE};
#elif DC_CLASSES == 9
/* wrist ext, wrist flex, radial dev, ulnar dev, index point, thumb up, hand open, fist, Rest (decision.h) */
const uint8_t dc_class_command[DC_CLASSES] = {DC9_UP, DC9_DOWN, DC9_LEFT, DC9_RIGHT, DC9_FORWARD, DC9_BACK,
                                              DC9_GRIP_OPEN, DC9_GRIP_CLOSE, DC_NONE};
#else
#error "DC_CLASSES: 6 or 9"
#endif

void dc_init(dc_state_t *s, uint16_t tau_permille, uint8_t k)
{
    s->tau_permille = tau_permille;
    s->k = k ? k : 1;
    s->k_rest = s->k;
    s->k_fast = 0;
    dc_reset(s);
}

void dc_set_rest_k(dc_state_t *s, uint8_t k_rest)
{
    s->k_rest = k_rest ? k_rest : s->k;
}

void dc_set_fast(dc_state_t *s, uint8_t k_fast)
{
    s->k_fast = k_fast;
}

void dc_reset(dc_state_t *s)
{
    s->last = -1;
    s->run = 0;
    s->latched = -1;
    s->fast_run = 0;
}

int dc_step(dc_state_t *s, const uint16_t *votes, int total, dc_out_t *out)
{
    return dc_step_m(s, votes, total, 0, out);
}

int dc_step_m(dc_state_t *s, const uint16_t *votes, int total, int strong, dc_out_t *out)
{
    int top = 0;
    for (int c = 1; c < DC_CLASSES; c++)
        if (votes[c] > votes[top])
            top = c;
    out->top = (int8_t)top;
    out->ratio_permille = (uint16_t)(total > 0 ? (uint32_t)votes[top] * 1000u / (uint32_t)total : 0);
    out->accepted = (uint8_t)((uint32_t)votes[top] * 1000u >= (uint32_t)s->tau_permille * (uint32_t)total);
    out->established = -1;
    if (!out->accepted) {
        s->last = -1;
        s->run = 0;
        s->fast_run = 0;
        return DC_NONE;
    }
    const uint8_t need = top == DC_CLASSES - 1 ? s->k_rest : s->k;
    const uint8_t cap = s->k > s->k_rest ? s->k : s->k_rest;
    if (top == s->last) {
        if (s->run < cap)
            s->run++;
        s->fast_run = strong ? (uint8_t)(s->fast_run < 255 ? s->fast_run + 1 : 255) : 0;
    } else {
        s->last = (int8_t)top;
        s->run = 1;
        s->fast_run = strong ? 1 : 0;
    }
    const int fast = s->k_fast && top != DC_CLASSES - 1 && s->fast_run >= s->k_fast;   /* 35.95 */
    if ((s->run < need && !fast) || top == s->latched)
        return DC_NONE;
    s->latched = (int8_t)top;
    out->established = (int8_t)top;
    return dc_class_command[top];
}

/* PC check helper: replay n windows (votes n x DC_CLASSES), dc_reset() whenever seg[i] != seg[i - 1].
 * cmd[i]: command sent at window i; acc[i]: window accepted; est[i]: class established (-1 none).
 * Not used on the MCU (removed by --gc-sections). */
void dc_replay(const uint16_t *votes, const int32_t *seg, int n, int total, uint16_t tau_permille, uint8_t k,
               int8_t *cmd, int8_t *acc, int8_t *est)
{
    dc_state_t s;
    dc_out_t o;
    dc_init(&s, tau_permille, k);
    for (int i = 0; i < n; i++) {
        if (i > 0 && seg[i] != seg[i - 1])
            dc_reset(&s);
        cmd[i] = (int8_t)dc_step(&s, votes + i * DC_CLASSES, total, &o);
        acc[i] = (int8_t)o.accepted;
        est[i] = o.established;
    }
}
