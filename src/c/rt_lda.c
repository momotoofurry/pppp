/* Real-time loop of the LDA main line. See rt_lda.h. */
#include "rt_lda.h"

#include <math.h>
#include <string.h>

#include "features.h"

static rtl_config_t s_cfg;
static pk_parser_t s_pk;
static rtl_counters_t s_cnt;
static dc_state_t s_dc;
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

unsigned rtl_static_bytes(void)
{
    return (unsigned)(sizeof s_cfg + sizeof s_pk + sizeof s_cnt + sizeof s_dc + sizeof s_lab_x + sizeof s_lab_y +
                      sizeof s_mu + sizeof s_inv_sd + sizeof s_feat + sizeof s_q + sizeof s_tx_seq);
}

static uint32_t now(void)
{
    return s_cfg.now_us ? s_cfg.now_us() : 0;
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

static void stream_reset(void)
{
    fe_reset();
    dc_reset(&s_dc);
    s_win_since_reset = 0;
}

void rtl_init(const rtl_config_t *cfg)
{
    s_cfg = *cfg;
    pk_init(&s_pk);
    memset(&s_cnt, 0, sizeof s_cnt);
    memset(s_tx_seq, 0, sizeof s_tx_seq);
    dc_init(&s_dc, 500, cfg->k);                /* the votes given to dc_step are all-or-nothing, see on_window */
    fe_init();
    stream_reset();
    ld_reset();
    s_mode = RTL_MODE_IDLE;
    s_fit_request = 0;
    s_label = -1;
    s_new_session = 1;
    s_have_seq = 0;
    s_report = 0;
}

/* one 100 ms feature vector (real-time context) */
static void on_window(void)
{
    s_cnt.windows++;
    if (s_win_since_reset++ < s_cfg.warmup)
        return;
    s_cnt.windows_used++;
    if (s_fit_request) {                        /* the fit owns the session buffer and the model */
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
    /* decision.c: k-window agreement and latch; an accepted window gives all the votes to its class, a rejected
     * one gives none (share 0 < 0.5: rejected, the run is broken) */
    uint16_t votes[DC_CLASSES] = {0};
    if (accepted)
        votes[top] = 1000;
    dc_out_t o;
    int cmd = dc_step(&s_dc, votes, 1000, &o);
    uint32_t t = now();
    if (s_report & 1u) {
        uint8_t p[14];
        put32(p, s_cnt.windows);
        put32(p + 4, t);
        p[8] = (uint8_t)top;
        p[9] = (uint8_t)accepted;
        p[10] = (uint8_t)margin;
        p[11] = (uint8_t)(margin >> 8);
        p[12] = 0;
        p[13] = 0;
        send(PK_PRED, 1, p, 14);
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
        }
        break;
    case RTL_SET_REPORT:
        if (len >= 2)
            s_report = p[1];
        break;
    case RTL_FORGET:
        if (!s_fit_request) {
            ld_reset();
            s_mode = RTL_MODE_IDLE;
            s_new_session = 1;
            status(RTL_EV_FORGOT, 0);
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

void rtl_idle(void)
{
    if (!s_fit_request)
        return;
    const int n = (int)s_cnt.label_windows;
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
    }
    s_cnt.fit_result = r;
    s_cnt.fits++;
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
