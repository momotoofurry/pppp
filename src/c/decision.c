/* Low-confidence rejection + k-window agreement. See decision.h. */
#include "decision.h"

/* Power, Lateral, Tripod, Pointer, Open, Rest */
const uint8_t dc_class_command[DC_CLASSES] = {DC_POSE_A, DC_NONE, DC_GRIP, DC_POSE_B, DC_RELEASE, DC_NONE};

void dc_init(dc_state_t *s, uint16_t tau_permille, uint8_t k)
{
    s->tau_permille = tau_permille;
    s->k = k ? k : 1;
    dc_reset(s);
}

void dc_reset(dc_state_t *s)
{
    s->last = -1;
    s->run = 0;
    s->latched = -1;
}

int dc_step(dc_state_t *s, const uint16_t *votes, int total, dc_out_t *out)
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
        return DC_NONE;
    }
    if (top == s->last) {
        if (s->run < s->k)
            s->run++;
    } else {
        s->last = (int8_t)top;
        s->run = 1;
    }
    if (s->run < s->k || top == s->latched)
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
