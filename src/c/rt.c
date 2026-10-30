/* Real-time loop for route B. See rt.h. */
#include "rt.h"

#include <string.h>

#include "features.h"
#if RT_ADAPT
#include "adapt.h"
#endif

static rt_config_t s_cfg;
static pk_parser_t s_pk;
static rt_counters_t s_cnt;
static dc_state_t s_dc;
static volatile int s_mode;
static volatile uint8_t s_sc_request, s_sc_running, s_cal_request;
static uint8_t s_cal_y[OS_CAL_MAX];
static int s_cal_label = -1;
static uint16_t s_rx_seq;
static int s_have_seq;
static uint32_t s_win_since_reset, s_in_block;
static uint8_t s_report;
static const os_header_t *s_hdr;
static uint16_t s_tx_seq[3];                    /* COMMAND, PRED, STATUS */
static float s_feat[FE_DIM];
static int16_t s_q[FE_DIM];
#if RT_ADAPT
static float s_al[FE_DIM];                      /* feature vector after the channel alignment */
#if RT_RESCALE
static float s_map_scale[SC_DIM], s_map_offset[SC_DIM];
#endif
#endif

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

void rt_init(const rt_config_t *cfg)
{
    s_cfg = *cfg;
    pk_init(&s_pk);
    memset(&s_cnt, 0, sizeof s_cnt);
    memset(s_tx_seq, 0, sizeof s_tx_seq);
    dc_init(&s_dc, cfg->tau_permille, cfg->k);
    fe_init();
    stream_reset();
    s_mode = RT_MODE_IDLE;
    s_sc_request = s_sc_running = s_cal_request = 0;
    s_cal_label = -1;
    s_have_seq = 0;
    s_in_block = 0;
    s_report = 0;
    s_hdr = 0;
}

/* one 100 ms feature vector (real-time context) */
static void on_window(void)
{
    s_cnt.windows++;
    if (s_win_since_reset++ < s_cfg.warmup)
        return;
    s_cnt.windows_used++;
    if (s_mode == RT_MODE_CAL) {
        if (s_cal_label >= 0 && (int)s_cnt.cal_windows < OS_CAL_MAX && !s_cal_request) {
            float *fb = os_feature_buffer();
            memcpy(fb + s_cnt.cal_windows * FE_DIM, s_feat, sizeof s_feat);
            s_cal_y[s_cnt.cal_windows++] = (uint8_t)s_cal_label;
            if (s_cnt.cal_windows == OS_CAL_MAX)
                status(RT_EV_CAL_FULL, (int32_t)s_cnt.cal_windows);
        }
        return;
    }
#if RT_ADAPT
    if (s_mode == RT_MODE_ALIGN) {
        ad_align_push(s_feat);
        return;
    }
#endif
    if (s_mode != RT_MODE_RUN)
        return;
    uint16_t votes[SC_CLASSES];
    int pushed = 0;
#if RT_ADAPT
    ad_map(s_feat, s_al);
    ad_normalize(s_al, s_q);
#else
    os_normalize(s_hdr, s_feat, s_q);
#endif
    if (!s_sc_request && !s_sc_running) {
        int lab = sc_push_votes(s_q, votes);
#if RT_ADAPT
        ad_observe(s_al, lab);                  /* not while self-calibration runs: ad_end_block() follows it */
#else
        (void)lab;
#endif
        pushed = 1;
        s_cnt.pushed++;
        if (++s_in_block == RT_BLOCK) {
            s_in_block = 0;
            s_sc_request = 1;                   /* rt_idle() runs sc_end_block() */
        }
    } else {
        sc_votes(s_q, votes);
        s_cnt.classified_only++;
    }
    dc_out_t o;
    int cmd = dc_step(&s_dc, votes, SC_N_PRE + SC_N_APP, &o);
    uint32_t t = now();
    if (s_report & 1u) {
        uint8_t p[14];
        put32(p, s_cnt.windows);
        put32(p + 4, t);
        p[8] = (uint8_t)o.top;
        p[9] = o.accepted;
        p[10] = (uint8_t)o.ratio_permille;
        p[11] = (uint8_t)(o.ratio_permille >> 8);
        p[12] = (uint8_t)pushed;
        p[13] = 0;
        send(PK_PRED, 1, p, 14);
    }
    if (cmd != DC_NONE) {
        uint8_t p[12];
        put32(p, s_cnt.windows);
        put32(p + 4, t);
        p[8] = (uint8_t)cmd;
        p[9] = (uint8_t)o.top;
        p[10] = (uint8_t)o.ratio_permille;
        p[11] = (uint8_t)(o.ratio_permille >> 8);
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
        status(RT_EV_LOST, lost);
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
    case RT_STREAM_RESET:
        stream_reset();
        break;
    case RT_CAL_START:
        if (len >= 2 && p[1] < SC_CLASSES && !s_sc_running && !s_sc_request) {
            if (s_mode != RT_MODE_CAL)
                s_cnt.cal_windows = 0;          /* a new calibration session */
            s_mode = RT_MODE_CAL;
            s_cal_label = p[1];
        }
        break;
    case RT_CAL_END:
        s_cal_label = -1;
        break;
    case RT_CALIBRATE:
        if (s_mode == RT_MODE_CAL)
            s_cal_request = 1;
        break;
    case RT_SET_DECISION:
        if (len >= 4)
            dc_init(&s_dc, (uint16_t)(p[1] | (p[2] << 8)), p[3]);
        break;
    case RT_SET_REPORT:
        if (len >= 2)
            s_report = p[1];
        break;
#if RT_ADAPT
    case RT_ALIGN_START:
        if (s_mode == RT_MODE_RUN && !s_sc_running && !s_sc_request) {
            ad_align_reset();
            s_mode = RT_MODE_ALIGN;
        }
        break;
    case RT_ALIGN_END:
        if (s_mode == RT_MODE_ALIGN) {
            int n = ad_align_count();
            s_mode = RT_MODE_RUN;
            if (n < RT_ALIGN_MIN)
                status(RT_EV_ALIGN_SHORT, n);   /* rotation unchanged */
            else
                status(RT_EV_ALIGNED, ad_align_finish());
        }
        break;
#endif
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

void rt_rx(const uint8_t *bytes, uint32_t n)
{
    pk_feed(&s_pk, bytes, n, on_packet, 0);
}

void rt_idle(void)
{
    if (s_cal_request) {
        int r = -1;
        sc_model_t m;
        if (!s_cfg.flash_erase || s_cfg.flash_erase() == 0)
            r = os_calibrate(s_cfg.pre, s_cal_y, (int)s_cnt.cal_windows, s_cfg.seed, s_cfg.writer, 0,
                             &(os_stats_t){0});
        if (r == 0 && s_cfg.flash_flush && s_cfg.flash_flush() != 0)
            r = -3;
        if (r == 0 && os_model(s_cfg.image, s_cfg.pre, &m) != 0)
            r = -5;
        if (r == 0) {
            sc_init(&m, os_cal_rows(), s_cal_y, (int)s_cnt.cal_windows, s_cfg.seed + 1u);
            s_hdr = (const os_header_t *)s_cfg.image;
#if RT_ADAPT
            ad_init(s_hdr->mu, s_hdr->inv_sd, os_feature_buffer(), (int)s_cnt.cal_windows);
#endif
            s_in_block = 0;
            s_mode = RT_MODE_RUN;
        }
        s_cnt.calibrate_result = r;
        s_cal_request = 0;
        status(RT_EV_CALIBRATED, r);
    }
    if (s_sc_request) {
        sc_stats_t st;
        s_sc_running = 1;
        s_sc_request = 0;
        uint32_t t0 = now();
        status(RT_EV_SC_BEGIN, (int32_t)s_cnt.windows);
#if RT_ADAPT
        ad_stats_t ast;                       /* the real-time context may read the statistics meanwhile: a
                                                   window then mixes old and new values of a few features */
#if RT_RESCALE
        ad_end_block_map(&ast, s_map_scale, s_map_offset);
        if (ast.updated)
            sc_rescale(s_map_scale, s_map_offset, 1);   /* buffer + calibration rows; sc_votes() reads neither */
        sc_end_block(&st);
#else
        sc_end_block(&st);
        ad_end_block(&ast);
#endif
#else
        sc_end_block(&st);
#endif
        s_sc_running = 0;
        status(RT_EV_SC_END, (int32_t)(now() - t0));
        s_cnt.selfcal_blocks++;
        status(RT_EV_SELFCAL, (int32_t)s_cnt.selfcal_blocks);
    }
}

void rt_status(uint8_t ev, int32_t value)
{
    status(ev, value);
}

int rt_mode(void)
{
    return s_mode;
}

const rt_counters_t *rt_counters(void)
{
    return &s_cnt;
}

const pk_parser_t *rt_parser(void)
{
    return &s_pk;
}
