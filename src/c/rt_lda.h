/* Real-time loop of the LDA main line for route B (samples arrive over the serial link), portable C.
 * Exploratory (report 35.13); NOT the frozen firmware (rt.c is untouched). Same packets as rt.c (protocol.h) and
 * the same sub-command numbers where the meaning is the same, so the PC tools keep working.
 *
 * Per session (every time the sensors are put on) the user does a cued start-up sequence; its windows are labelled
 * by the cue. The MCU keeps them in a small buffer, takes the z-score statistics of the session from them, adds
 * them to the running sums of the LDA (ldacal.c) and refits. Nothing is written to Flash; nothing is learned
 * without labels.
 *   real-time context  rtl_rx(): packets -> filter + window (features.c) -> every 100 ms a feature vector ->
 *                      label mode: stored in the session buffer; run mode: z-score -> Q5.10 -> ld_scores ->
 *                      rejection (margin of the two best discriminants, optional Mahalanobis distance) ->
 *                      k-window agreement and latch (decision.c) -> command packet
 *   thread context     rtl_idle(): the fit after RTL_FIT (session statistics, RTL_LABEL_MAX x ld_add, ld_fit;
 *                      about 10 ms on the H753 for 120 windows). Windows that arrive meanwhile are not classified.
 * Control sub-commands (PK_CONTROL payload[0]):
 *   RTL_STREAM_RESET (1)              new recording / after a gap
 *   RTL_LABEL_START (2) label u8      the following windows are start-up windows of this gesture; the first one
 *                                     after a fit (or after reset) starts a new session buffer
 *   RTL_LABEL_END (3)
 *   RTL_FIT (4)                       session statistics + add the session's windows + refit, then run mode
 *   RTL_SET_REJECT (5) margin_x100 u16, dist2 u16 (0 = off), k u8
 *   RTL_SET_REPORT (6) flags u8       bit 0: PK_PRED for every classified window
 *   RTL_FORGET (11)                   drop all accumulated labels (ld_reset), e.g. after the band was moved
 * Status events (PK_STATUS): RTL_EV_FIT value = 0 or the error (-1 a gesture has no window in the sums, -2
 *   degenerate data, -3 fewer than RTL_LABEL_MIN session windows); RTL_EV_LOST packets lost; RTL_EV_LABEL_FULL
 *   session buffer full; RTL_EV_FORGOT; RTL_EV_FIT_US value = duration of the fit in microseconds (sent before
 *   RTL_EV_FIT; 0 without a time base).
 * PK_PRED / PK_COMMAND: the field that carries the vote share for rt.c carries min(65535, margin x 100) here.
 */
#pragma once
#include <stdint.h>

#include "decision.h"
#include "ldacal.h"
#include "protocol.h"

#ifndef RTL_LABEL_MAX
#define RTL_LABEL_MAX 120               /* two cued passes of 6 gestures, 10 windows each */
#endif
#define RTL_LABEL_MIN 12

enum { RTL_STREAM_RESET = 1, RTL_LABEL_START = 2, RTL_LABEL_END = 3, RTL_FIT = 4, RTL_SET_REJECT = 5,
       RTL_SET_REPORT = 6, RTL_FORGET = 11 };
enum { RTL_EV_FIT = 1, RTL_EV_LOST = 3, RTL_EV_LABEL_FULL = 4, RTL_EV_FORGOT = 16, RTL_EV_FIT_US = 17,
       /* diagnostics sent by the board main loop (app_rt_lda.c), same numbers as rt.h */
       RTL_EV_DIAG_RX_HW = 9, RTL_EV_DIAG_STACK = 10, RTL_EV_DIAG_RX_OVF = 11, RTL_EV_DIAG_RX_ERR = 12 };
enum { RTL_MODE_IDLE = 0, RTL_MODE_LABEL = 1, RTL_MODE_RUN = 2 };

typedef struct {
    void (*tx)(const uint8_t *bytes, uint32_t n);   /* send bytes to the PC */
    uint32_t (*now_us)(void);                       /* time stamp for the outgoing packets (0: none) */
    uint16_t warmup;                                /* windows ignored after a stream reset */
    uint16_t margin_x100;                           /* reject below this margin (0: accept all) */
    uint16_t dist2;                                 /* reject above this squared distance (0: off) */
    uint8_t k;
} rtl_config_t;

typedef struct {
    uint32_t windows, windows_used, classified, skipped_busy, commands, lost_packets, seq_gaps, label_windows, fits;
    int32_t fit_result;
} rtl_counters_t;

void rtl_init(const rtl_config_t *cfg);
void rtl_rx(const uint8_t *bytes, uint32_t n);      /* real-time context */
void rtl_idle(void);                                /* thread context */
int rtl_mode(void);
const rtl_counters_t *rtl_counters(void);
void rtl_status(uint8_t ev, int32_t value);     /* send a PK_STATUS (thread context: the board's diagnostics) */
unsigned rtl_static_bytes(void);
