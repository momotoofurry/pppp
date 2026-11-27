/* Real-time loop of the LDA main line. See rt_lda.h. */
#include "rt_lda.h"

#include <math.h>
#include <string.h>

#include "features.h"

/* the class of a window indexes the decision votes; the task label's valid mask is one byte (bit c = class c) */
_Static_assert(LD_CLASSES == DC_CLASSES, "build with the same -DLD_CLASSES and -DDC_CLASSES");
_Static_assert(LD_CLASSES - 1 <= 8, "RTL_TASK_LABEL's valid mask has 8 bits for the non-Rest classes");
_Static_assert(LD_DIM == FE_DIM, "build with matching -DFE_CH and -DLD_DIM");
_Static_assert(FE_CH <= PK_CH, "FE_CH must not exceed PK_CH");

static rtl_config_t s_cfg;
static pk_parser_t s_pk;
static rtl_counters_t s_cnt;
static dc_state_t s_dc;
static uint16_t s_fast_m100;                        /* 35.95: margin x100 of a 'strong' window (fast switch) */
static volatile int s_mode;
static volatile uint8_t s_fit_request;
static float s_lab_x[RTL_LABEL_MAX][FE_DIM];    /* start-up windows of this session, raw features */
static uint8_t s_lab_y[RTL_LABEL_MAX];
static int s_label = -1;
static uint8_t s_new_session = 1;
static float s_mu[FE_DIM], s_inv_sd[FE_DIM];    /* z-score of this session */
static uint16_t s_rx_seq;
static int s_have_seq;
static uint32_t s_win_since_reset;
static uint8_t s_report;
static uint16_t s_tx_seq[3];                    /* COMMAND, PRED, STATUS */
static float s_feat[FE_DIM];
static int16_t s_q[FE_DIM];
/* task labels: the current run of agreeing accepted windows, and the windows of the last command */
static int16_t s_run[RTL_CMD_MAX][FE_DIM];
static int s_run_n, s_run_cls = -1;
static int16_t s_pend[RTL_CMD_MAX][FE_DIM];
static int s_pend_n, s_pend_cls = -1;
static uint32_t s_pend_window;
static uint8_t s_pend_open, s_pend_valid;
static volatile uint8_t s_task_request;
static float s_prior[LD_CLASSES];
/* activity gate */
static float s_gate_k, s_gate_thr = -1.0f;
static uint8_t s_gate_mode;

static uint32_t now(void)
{
    return s_cfg.now_us ? s_cfg.now_us() : 0;
}
static float s_act[RTL_LABEL_MAX];
/* 35.83: ring of the last classified windows for hindsight range labels */
#define RTL_HIST_INVALID 0xFFFFFFFFu     /* 35.104: a ring slot being rewritten (seqlock) */
static int16_t s_hist_q[RTL_HIST][FE_DIM];
static uint32_t s_hist_w[RTL_HIST];
static uint8_t s_hist_g[RTL_HIST];
static uint32_t s_hist_n;                       /* windows written since the last fit (ring position) */
/* range-label queue: a single-producer / single-consumer ring, rx writes s_range_head, idle writes s_range_done */
static volatile uint32_t s_range_head, s_range_done;
static uint32_t s_range_first[RTL_RANGE_Q], s_range_last[RTL_RANGE_Q];
static uint8_t s_range_cls[RTL_RANGE_Q];

unsigned rtl_static_bytes(void)
{
    return (unsigned)(sizeof s_cfg + sizeof s_pk + sizeof s_cnt + sizeof s_dc + sizeof s_lab_x + sizeof s_lab_y +
                      sizeof s_mu + sizeof s_inv_sd + sizeof s_feat + sizeof s_q + sizeof s_tx_seq + sizeof s_run +
                      sizeof s_pend + sizeof s_prior + sizeof s_act + sizeof s_hist_q + sizeof s_hist_w +
                      sizeof s_hist_g);
}


static void put32(uint8_t *b, uint32_t v)
{
    b[0] = (uint8_t)v;
    b[1] = (uint8_t)(v >> 8);
    b[2] = (uint8_t)(v >> 16);
    b[3] = (uint8_t)(v >> 24);
}

static void send(uint8_t type, int slot, const uint8_t *payload, uint16_t len)
{
    uint8_t out[PK_OVERHEAD + 16];
    uint32_t n = pk_build(out, type, s_tx_seq[slot]++, payload, len);
    if (s_cfg.tx && n)
        s_cfg.tx(out, n);
}

static void status(uint8_t ev, int32_t value)
{
    uint8_t p[8] = {ev, 0, 0, 0};
    put32(p + 4, (uint32_t)value);
    send(PK_STATUS, 2, p, 8);
}

/* report bit 1: a PK_COMMAND with command 0 (none) and class Rest = stop (35.82; also on a stream reset, 35.85) */
static void send_stop(void)
{
    uint8_t p[12];
    put32(p, s_cnt.windows);
    put32(p + 4, now());
    p[8] = 0;
    p[9] = (uint8_t)(LD_CLASSES - 1);
    p[10] = 0;
    p[11] = 0;
    send(PK_COMMAND, 0, p, 12);
}

static void send_stop(void);

static void stream_reset(void)
{
    if (s_mode == RTL_MODE_RUN && (s_report & 2u))
        send_stop();                            /* 35.85: the latch is reset below; the arm must not keep moving */
    fe_reset();
    dc_reset(&s_dc);
    s_win_since_reset = 0;
    s_run_n = 0;
    s_run_cls = -1;
    s_pend_open = 0;                            /* the windows of the last command are kept for its label */
}

void rtl_init(const rtl_config_t *cfg)
{
    s_cfg = *cfg;
    pk_init(&s_pk);
    memset(&s_cnt, 0, sizeof s_cnt);
    memset(s_tx_seq, 0, sizeof s_tx_seq);
    dc_init(&s_dc, 500, cfg->k);                /* the votes given to dc_step are all-or-nothing, see on_window */
    fe_init();
    s_mode = RTL_MODE_IDLE;                     /* 35.85: before stream_reset, so that init never sends a stop */
    s_report = 0;
    stream_reset();
    ld_reset();
    s_mode = RTL_MODE_IDLE;
    s_fit_request = 0;
    s_label = -1;
    s_new_session = 1;
    s_have_seq = 0;
    s_report = 0;
    s_pend_valid = 0;
    s_pend_n = 0;
    s_pend_cls = -1;
    s_task_request = 0;
    s_range_head = s_range_done = 0;
    s_hist_n = 0;
    s_gate_k = 0.0f;
    s_gate_thr = -1.0f;
    s_gate_mode = 0;
    ld_set_active(0xFFFFFFFFu);
}

static float activity(const float *feat)
{
    float a = 0.0f;
    for (int ch = 0; ch < FE_CH; ch++)
        a += feat[RTL_MAV0 + ch];
    return a;
}

/* median of the activity of the cued windows of class c (numpy.median: mean of the two middle values) */
static float class_median(int n, int c)
{
    int m = 0;
    for (int i = 0; i < n; i++) {
        if (s_lab_y[i] != c)
            continue;
        float v = activity(s_lab_x[i]);
        int j = m++;
        while (j > 0 && s_act[j - 1] > v) {
            s_act[j] = s_act[j - 1];
            j--;
        }
        s_act[j] = v;
    }
    if (!m)
        return -1.0f;
    return (m & 1) ? s_act[m / 2] : 0.5f * (s_act[m / 2 - 1] + s_act[m / 2]);
}

/* median activity of all the cued windows of the active non-Rest classes (mode 2) */
static float pooled_median(int n)
{
    int m = 0;
    for (int i = 0; i < n; i++) {
        if (s_lab_y[i] == LD_CLASSES - 1 || !ld_is_active(s_lab_y[i]))
            continue;
        float v = activity(s_lab_x[i]);
        int j = m++;
        while (j > 0 && s_act[j - 1] > v) {
            s_act[j] = s_act[j - 1];
            j--;
        }
        s_act[j] = v;
    }
    if (!m)
        return -1.0f;
    return (m & 1) ? s_act[m / 2] : 0.5f * (s_act[m / 2 - 1] + s_act[m / 2]);
}

static float gate_threshold(int n)
{
    if (s_gate_mode == 2)
        return pooled_median(n);
    float rest = class_median(n, LD_CLASSES - 1), lo = -1.0f;
    for (int c = 0; c < LD_CLASSES - 1; c++) {
        if (!ld_is_active(c))
            continue;
        float v = class_median(n, c);
        if (v < 0.0f)
            return -1.0f;
        if (lo < 0.0f || v < lo)
            lo = v;
    }
    return rest < 0.0f ? -1.0f : sqrtf(rest * lo);
}

/* one 100 ms feature vector (real-time context) */
static void on_window(void)
{
    s_cnt.windows++;
    if (s_win_since_reset++ < s_cfg.warmup)
        return;
    s_cnt.windows_used++;
    if (s_fit_request || s_task_request || s_range_head != s_range_done) {   /* the fit owns the buffers and the model */
        s_cnt.skipped_busy++;
        return;
    }
    if (s_mode == RTL_MODE_LABEL) {
        if (s_label >= 0 && (int)s_cnt.label_windows < RTL_LABEL_MAX) {
            memcpy(s_lab_x[s_cnt.label_windows], s_feat, sizeof s_feat);
            s_lab_y[s_cnt.label_windows++] = (uint8_t)s_label;
            if (s_cnt.label_windows == RTL_LABEL_MAX)
                status(RTL_EV_LABEL_FULL, RTL_LABEL_MAX);
        }
        return;
    }
    if (s_mode != RTL_MODE_RUN)
        return;
    float sc[LD_CLASSES];
    fe_normalize_q16(s_feat, s_mu, s_inv_sd, s_q);
    int top = ld_scores(s_q, sc);
    float second = -INFINITY;
    for (int c = 0; c < LD_CLASSES; c++)
        if (c != top && sc[c] > second)
            second = sc[c];
    float m100 = (sc[top] - second) * 100.0f;
    uint16_t margin = m100 >= 65535.0f ? 65535u : (uint16_t)m100;
    int accepted = margin >= s_cfg.margin_x100;
    if (accepted && s_cfg.dist2)
        accepted = ld_dist2(s_q, top) <= (float)s_cfg.dist2;
    s_cnt.classified++;
    uint8_t gated = 0;
    if (s_gate_k > 0.0f && s_gate_thr > 0.0f && activity(s_feat) < s_gate_k * s_gate_thr) {
        gated = 1;                              /* not contracting: Rest, whatever the LDA says */
        top = LD_CLASSES - 1;
        accepted = 1;
        s_cnt.gated++;
    }
    {                                           /* 35.83: keep the window for hindsight range labels */
        const uint32_t h = s_hist_n++ % RTL_HIST;
        /* 35.104 seqlock (writer): invalid while the slot is rewritten, the window number last */
        __atomic_store_n(&s_hist_w[h], RTL_HIST_INVALID, __ATOMIC_RELAXED);
        __atomic_signal_fence(__ATOMIC_SEQ_CST);
        memcpy(s_hist_q[h], s_q, sizeof s_q);
        s_hist_g[h] = gated;
        __atomic_store_n(&s_hist_w[h], s_cnt.windows, __ATOMIC_RELEASE);
    }
    /* windows for the task label: the run of agreeing accepted windows; after a command, further windows of the
     * same class are added to that command's windows until the class changes */
    if (accepted) {
        if (top != s_run_cls) {
            s_run_cls = top;
            s_run_n = 0;
        }
        if (s_run_n < RTL_CMD_MAX)
            memcpy(s_run[s_run_n++], s_q, sizeof s_q);
    } else {
        s_run_n = 0;
        s_run_cls = -1;
    }
    if (s_pend_open) {
        if (accepted && top == s_pend_cls) {
            if (s_pend_n < RTL_CMD_MAX)
                memcpy(s_pend[s_pend_n++], s_q, sizeof s_q);
        } else {
            s_pend_open = 0;
        }
    }
    /* decision.c: k-window agreement and latch; an accepted window gives all the votes to its class, a rejected
     * one gives none (share 0 < 0.5: rejected, the run is broken) */
    uint16_t votes[DC_CLASSES] = {0};
    if (accepted)
        votes[top] = 1000;
    dc_out_t o;
    int cmd = dc_step_m(&s_dc, votes, 1000, accepted && margin >= s_fast_m100, &o);   /* 35.95 */
    uint32_t t = now();
    if (s_report & 1u) {
        uint8_t p[14];
        put32(p, s_cnt.windows);
        put32(p + 4, t);
        p[8] = (uint8_t)top;
        p[9] = (uint8_t)accepted;
        p[10] = (uint8_t)margin;
        p[11] = (uint8_t)(margin >> 8);
        p[12] = gated;
        p[13] = 0;
        send(PK_PRED, 1, p, 14);
    }
    if (cmd == DC_NONE && o.established == LD_CLASSES - 1 && (s_report & 2u)) {
        uint8_t p[12];                          /* 35.82: Rest established = stop (command 0) */
        put32(p, s_cnt.windows);
        put32(p + 4, t);
        p[8] = 0;
        p[9] = (uint8_t)(LD_CLASSES - 1);
        p[10] = (uint8_t)margin;
        p[11] = (uint8_t)(margin >> 8);
        send(PK_COMMAND, 0, p, 12);
    }
    if (cmd != DC_NONE) {
        uint8_t p[12];
        put32(p, s_cnt.windows);
        put32(p + 4, t);
        p[8] = (uint8_t)cmd;
        p[9] = (uint8_t)top;
        p[10] = (uint8_t)margin;
        p[11] = (uint8_t)(margin >> 8);
        send(PK_COMMAND, 0, p, 12);
        s_cnt.commands++;
        memcpy(s_pend, s_run, (size_t)s_run_n * sizeof s_run[0]);
        s_pend_n = s_run_n;
        s_pend_cls = top;
        s_pend_window = s_cnt.windows;
        s_pend_open = 1;
        s_pend_valid = 1;
    }
}

static void on_samples(uint16_t seq, const uint8_t *p, uint16_t len)
{
    if (s_have_seq && seq != s_rx_seq) {        /* packets lost: the stream has a gap */
        uint16_t lost = (uint16_t)(seq - s_rx_seq);
        s_cnt.lost_packets += lost;
        s_cnt.seq_gaps++;
        status(RTL_EV_LOST, lost);
        stream_reset();
    }
    s_have_seq = 1;
    s_rx_seq = (uint16_t)(seq + 1);
    float x[PK_CH];
    for (uint16_t f = 0; f + 2 * PK_CH <= len; f += 2 * PK_CH) {
        for (int ch = 0; ch < PK_CH; ch++)
            x[ch] = (float)(int16_t)(p[f + 2 * ch] | (p[f + 2 * ch + 1] << 8)) * PK_LSB_VOLT;
        if (fe_push(x, s_feat))
            on_window();
    }
}

static void on_control(const uint8_t *p, uint16_t len)
{
    if (len < 1)
        return;
    switch (p[0]) {
    case RTL_STREAM_RESET:
        stream_reset();
        break;
    case RTL_LABEL_START:
        if (len >= 2 && p[1] < LD_CLASSES && !s_fit_request) {
            if (s_new_session) {
                s_cnt.label_windows = 0;
                s_new_session = 0;
            }
            s_mode = RTL_MODE_LABEL;
            s_label = p[1];
        }
        break;
    case RTL_LABEL_END:
        s_label = -1;
        break;
    case RTL_FIT:
        if (s_mode == RTL_MODE_LABEL)
            s_fit_request = 1;
        break;
    case RTL_SET_REJECT:
        if (len >= 6) {
            s_cfg.margin_x100 = (uint16_t)(p[1] | (p[2] << 8));
            s_cfg.dist2 = (uint16_t)(p[3] | (p[4] << 8));
            s_cfg.k = p[5];
            dc_init(&s_dc, 500, p[5]);
            dc_set_rest_k(&s_dc, len >= 7 ? p[6] : 0);
            dc_set_fast(&s_dc, len >= 10 ? p[7] : 0);                  /* 35.95: fast switch, off by default */
            s_fast_m100 = len >= 10 ? (uint16_t)(p[8] | (p[9] << 8)) : 0;
        }
        break;
    case RTL_SET_REPORT:
        if (len >= 2)
            s_report = p[1];
        break;
    case RTL_FORGET:
        if (!s_fit_request && !s_task_request) {
            ld_reset();
            s_mode = RTL_MODE_IDLE;
            s_new_session = 1;
            s_pend_valid = 0;
            s_gate_thr = -1.0f;
            status(RTL_EV_FORGOT, 0);
        }
        break;
    case RTL_SET_GATE:
        if (len >= 4) {
            s_gate_k = (float)(p[1] | (p[2] << 8)) / 100.0f;
            s_gate_mode = p[3];
        }
        break;
    case RTL_SET_CLASSES:
        if (len >= 3 && !s_fit_request && !s_task_request)
            ld_set_active((uint32_t)(p[1] | (p[2] << 8)));
        break;
    case RTL_LABEL_RANGE:
        if (len < 10 || s_fit_request || s_task_request)
            break;
        if (p[9] >= LD_CLASSES || !ld_is_active(p[9]) || s_mode != RTL_MODE_RUN) {
            status(RTL_EV_RANGE, -4);
            break;
        }
        if (s_range_head - s_range_done >= RTL_RANGE_Q) {
            status(RTL_EV_RANGE, -3);
            break;
        }
        {
            const uint32_t i = s_range_head % RTL_RANGE_Q;
            s_range_first[i] = (uint32_t)p[1] | ((uint32_t)p[2] << 8) | ((uint32_t)p[3] << 16) | ((uint32_t)p[4] << 24);
            s_range_last[i] = (uint32_t)p[5] | ((uint32_t)p[6] << 8) | ((uint32_t)p[7] << 16) | ((uint32_t)p[8] << 24);
            s_range_cls[i] = p[9];
            s_range_head++;                     /* published after the entry is written */
        }
        break;
    case RTL_TASK_LABEL:
        if (len < 3 || s_fit_request || s_task_request || s_range_head != s_range_done)
            break;
        if (p[1] >= LD_CLASSES - 1 || !ld_is_active(p[1])) {
            status(RTL_EV_TASK, -4);
            break;
        }
        if (!s_pend_valid || s_mode != RTL_MODE_RUN || s_pend_n < 1) {
            status(RTL_EV_TASK, -1);
            break;
        }
        if (len >= 7 && (uint32_t)(p[3] | (p[4] << 8) | ((uint32_t)p[5] << 16) | ((uint32_t)p[6] << 24)) != s_pend_window) {
            status(RTL_EV_TASK, -5);
            break;
        }
        {
            const int e = p[1];
            int others = 0;
            for (int c = 0; c < LD_CLASSES - 1; c++)
                others += c != e && ((p[2] >> c) & 1u) && ld_is_active(c);
            for (int c = 0; c < LD_CLASSES; c++)
                s_prior[c] = RTL_P_INVALID;
            s_prior[e] = others ? 1.0f - RTL_EPS : 1.0f - RTL_P0;
            for (int c = 0; c < LD_CLASSES - 1; c++)
                if (c != e && ((p[2] >> c) & 1u) && ld_is_active(c))
                    s_prior[c] = RTL_EPS / (float)others;
            s_prior[LD_CLASSES - 1] = RTL_P0;
            s_pend_open = 0;
            s_task_request = 1;
        }
        break;
    }
}

static void on_packet(void *ctx, uint8_t type, uint16_t seq, const uint8_t *payload, uint16_t len)
{
    (void)ctx;
    if (type == PK_SAMPLES)
        on_samples(seq, payload, len);
    else if (type == PK_CONTROL)
        on_control(payload, len);
}

void rtl_rx(const uint8_t *bytes, uint32_t n)
{
    pk_feed(&s_pk, bytes, n, on_packet, 0);
}

static void task_update(void)
{
    const uint32_t t0 = now();
    float q[LD_CLASSES];
    const int a = ld_soft_q(s_pend[0], s_pend_n, s_prior, RTL_BETA, q);
    ld_decay(RTL_DECAY);
    for (int i = 0; i < s_pend_n; i++)
        ld_add_soft(s_pend[i], q);
    const int r = ld_fit();
    s_pend_valid = 0;
    s_cnt.task_labels++;
    status(RTL_EV_TASK_US, (int32_t)(now() - t0));
    status(RTL_EV_TASK, r == 0 ? a * 1000 + (int32_t)(q[a] * 999.0f) : r);
    s_task_request = 0;
}

/* 35.83: hard labels for the buffered windows of every queued range (a direction skips gated windows), one refit */
static void range_update(void)
{
    const uint32_t n = s_hist_n < RTL_HIST ? s_hist_n : RTL_HIST;
    const uint32_t d0 = s_range_done, q = s_range_head - d0;   /* the labels queued so far; later ones wait */
    int added[RTL_RANGE_Q], total = 0;
    for (uint32_t k = 0; k < q; k++) {
        const uint32_t e = (d0 + k) % RTL_RANGE_Q;
        added[k] = 0;
        for (uint32_t i = 0; i < n; i++) {
            /* 35.104 seqlock (reader): rtl_rx may overwrite slot i while this copies it (it preempts rtl_idle);
             * keep the copy only if the slot held the same window before and after */
            const uint32_t w = __atomic_load_n(&s_hist_w[i], __ATOMIC_ACQUIRE);
            if (w == RTL_HIST_INVALID || w < s_range_first[e] || w > s_range_last[e])
                continue;
            int16_t q[FE_DIM];
            memcpy(q, s_hist_q[i], sizeof q);
            const uint8_t g = s_hist_g[i];
            __atomic_signal_fence(__ATOMIC_SEQ_CST);
            if (__atomic_load_n(&s_hist_w[i], __ATOMIC_ACQUIRE) != w)
                continue;                       /* overwritten meanwhile: that window is gone */
            if (s_range_cls[e] != LD_CLASSES - 1 && g)
                continue;
            ld_add(q, s_range_cls[e]);
            added[k]++;
        }
        total += added[k];
    }
    const int r = total ? ld_fit() : 0;
    for (uint32_t k = 0; k < q; k++) {
        if (r == 0 && added[k]) {
            s_cnt.range_labels++;
            s_cnt.range_windows += (uint32_t)added[k];
        }
        status(RTL_EV_RANGE, !added[k] ? -1 : r == 0 ? added[k] : r);
    }
    s_range_done = d0 + q;
}

void rtl_idle(void)
{
    if (s_task_request) {
        task_update();
        return;
    }
    if (s_range_head != s_range_done) {
        range_update();
        return;
    }
    if (!s_fit_request)
        return;
    /* the cued windows of inactive classes are dropped from the session buffer (kept in order) */
    int n = 0;
    for (int i = 0; i < (int)s_cnt.label_windows; i++) {
        if (!ld_is_active(s_lab_y[i]))
            continue;
        if (n != i) {
            memcpy(s_lab_x[n], s_lab_x[i], sizeof s_lab_x[0]);
            s_lab_y[n] = s_lab_y[i];
        }
        n++;
    }
    int r = -3;
    const uint32_t t0 = now();
    if (n >= RTL_LABEL_MIN) {
        /* z-score of the session = mean and (population) standard deviation of its start-up windows */
        for (int j = 0; j < FE_DIM; j++) {
            double m = 0.0, v = 0.0;
            for (int i = 0; i < n; i++)
                m += s_lab_x[i][j];
            m /= n;
            for (int i = 0; i < n; i++) {
                double d = s_lab_x[i][j] - m;
                v += d * d;
            }
            v = sqrt(v / n);
            s_mu[j] = (float)m;
            s_inv_sd[j] = v > 0.0 ? (float)(1.0 / v) : 0.0f;
        }
        for (int i = 0; i < n; i++) {
            fe_normalize_q16(s_lab_x[i], s_mu, s_inv_sd, s_q);
            ld_add(s_q, s_lab_y[i]);
        }
        r = ld_fit();
        if (r == 0 && (s_gate_thr < 0.0f || s_gate_mode >= 1)) {
            const float t = gate_threshold(n);
            if (t > 0.0f)
                s_gate_thr = t;
            status(RTL_EV_GATE_THR, t > 0.0f ? (int32_t)(t * 1e9f + 0.5f) : -1);
        }
    }
    s_cnt.fit_result = r;
    s_cnt.fits++;
    s_hist_n = 0;                               /* a new session's z-score: the old windows do not match it */
    s_label = -1;
    s_new_session = 1;
    dc_reset(&s_dc);
    s_mode = r == 0 ? RTL_MODE_RUN : RTL_MODE_IDLE;
    s_fit_request = 0;
    status(RTL_EV_FIT_US, (int32_t)(now() - t0));
    status(RTL_EV_FIT, r);
}

void rtl_status(uint8_t ev, int32_t value)
{
    status(ev, value);
}

int rtl_mode(void)
{
    return s_mode;
}

const rtl_counters_t *rtl_counters(void)
{
    return &s_cnt;
}
