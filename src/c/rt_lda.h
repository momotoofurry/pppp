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
 *   RTL_SET_REJECT (5) margin_x100 u16, dist2 u16 (0 = off), k u8 [, k_rest u8]
 *                                     k_rest (report 35.79): windows that establish Rest (stop); 0 or absent = k
 *   RTL_SET_REPORT (6) flags u8       bit 0: PK_PRED for every classified window
 *                                     bit 1 (report 35.82): a PK_COMMAND with command 0 (none) and class Rest every
 *                                     time Rest is established (k_rest agreeing Rest / gated windows): the 'stop' of
 *                                     continuous arm control (hold = move, relax = stop). Not a command: no task-label
 *                                     windows, not counted in commands. Off by default.
 *   RTL_FORGET (11)                   drop all accumulated labels (ld_reset), e.g. after the band was moved
 *   RTL_TASK_LABEL (12) expected u8, valid u8 [, window u32]
 *                                     task label for the last command (report 35.18, 35.24): the robot side
 *                                     tells which gesture the task expected (class 0-4) and which other gestures
 *                                     were valid commands at that moment (bit c = class c). The MCU kept the
 *                                     windows that made the command (the agreeing run, then further windows of
 *                                     the same class, at most RTL_CMD_MAX). In thread context it builds the
 *                                     prior (expected 1 - RTL_EPS, the other valid ones share RTL_EPS, Rest
 *                                     RTL_P0, the rest RTL_P_INVALID; 1 - RTL_P0 if no other is valid), computes
 *                                     the soft label q (ld_soft_q, beta RTL_BETA), forgets (ld_decay RTL_DECAY),
 *                                     adds the windows with q (ld_add_soft) and refits. One label per command.
 *                                     With the optional window (the window number of the COMMAND packet the
 *                                     label is for), a label for an older command than the one kept is refused
 *                                     (-5), so a late label never lands on the windows of a newer command.
 *   RTL_SET_GATE (13) k_x100 u16, mode u8
 *                                     activity gate (report 35.18, 35.21, 35.28): activity of a window = sum of
 *                                     the 8 raw MAV features; below k x threshold the window is Rest whatever the
 *                                     LDA says (no command, no task-label window). threshold = sqrt(median
 *                                     activity of the Rest windows x smallest median of a gesture) over the cued
 *                                     windows of a fit: mode 0 the first fit after init / RTL_FORGET (day 1), mode
 *                                     1 every fit. k_x100 = 0: off (default). PK_PRED byte 12 = 1 for a gated window.
 *                                     mode 2 (report 35.78): threshold = median activity of ALL the cued windows of
 *                                     the active non-Rest classes, new at every fit (k 0.5 = half a typical
 *                                     gesture; the cued Rest is not used, it can carry mains noise).
 *   RTL_SET_CLASSES (14) mask u16     active classes (report 35.78): bit c = class c (Rest always on; default all).
 *                                     Inactive classes are never predicted; at the next RTL_FIT their cued windows
 *                                     are left out of the z-score, the sums and the gate threshold, and their task
 *                                     labels are refused (-4). E.g. S7 of the 9-class build = 0x1CF (no index
 *                                     point, no thumb up). Not while a fit or task update is pending.
 *   RTL_LABEL_RANGE (15) first u32, last u32, class u8   (report 35.83)
 *                                     hindsight label from the robot side (labeler.py: confirmed when an object is
 *                                     put down, up to 20 s later): the classified windows numbered first..last
 *                                     (PK_PRED / PK_COMMAND window numbers) that are still in the ring of the last
 *                                     RTL_HIST windows are added to the running sums with this hard label (ld_add;
 *                                     a non-Rest class skips the windows the activity gate made Rest), then refit, in
 *                                     thread context like RTL_TASK_LABEL. No forgetting. Status RTL_EV_RANGE, one per
 *                                     label. Labels arriving before rtl_idle ran queue up (RTL_RANGE_Q; the board test
 *                                     of 35.83 lost the second of two back-to-back labels without it) and are applied
 *                                     together with one refit; a full queue answers -3.
 * Status events (PK_STATUS): RTL_EV_FIT value = 0 or the error (-1 a gesture has no window in the sums, -2
 *   degenerate data, -3 fewer than RTL_LABEL_MIN session windows); RTL_EV_LOST packets lost; RTL_EV_LABEL_FULL
 *   session buffer full; RTL_EV_FORGOT; RTL_EV_FIT_US value = duration of the fit in microseconds (sent before
 *   RTL_EV_FIT; 0 without a time base). RTL_EV_TASK value = class x 1000 + floor(999 q[class]) of the soft
 *   label's argmax after a task update, or < 0: -1 no command waiting for a label, -2 degenerate data, -4 bad
 *   expected class, -5 the label is for an older command; RTL_EV_RANGE = windows a range label added, or < 0: -1
 *   none of them in the ring, -2 degenerate data (old model kept), -3 queue full, -4 bad or inactive class;
 *   RTL_EV_GATE_THR = the gate threshold in nV after a
 *   fit that set it (-1: a gesture without cued windows); RTL_EV_TASK_US = duration of the task update in microseconds (sent before RTL_EV_TASK).
 * PK_PRED / PK_COMMAND: the field that carries the vote share for rt.c carries min(65535, margin x 100) here.
 */
#pragma once
#include <stdint.h>

#include "decision.h"
#include "features.h"
#include "ldacal.h"
#include "protocol.h"

#ifndef RTL_LABEL_MAX
#define RTL_LABEL_MAX 120               /* two cued passes of 6 gestures, 10 windows each */
#endif
#define RTL_LABEL_MIN 12
#ifndef RTL_CMD_MAX
#define RTL_CMD_MAX 16                  /* windows kept per command for its task label */
#endif
#define RTL_EPS 0.15f
#define RTL_P0 0.05f
#define RTL_P_INVALID 0.01f
#define RTL_BETA 0.3f
#define RTL_DECAY 0.97f
#define RTL_MAV0 (4 * FE_CH)              /* first MAV feature (feature-major, features.h) */
#ifndef RTL_HIST
#define RTL_HIST 256                    /* classified windows kept for hindsight labels (35.83): 25.6 s, 42 KB */
#endif
#define RTL_RANGE_Q 16                  /* range labels waiting for rtl_idle (one put-down sends several) */

enum { RTL_STREAM_RESET = 1, RTL_LABEL_START = 2, RTL_LABEL_END = 3, RTL_FIT = 4, RTL_SET_REJECT = 5,
       RTL_SET_REPORT = 6, RTL_FORGET = 11, RTL_TASK_LABEL = 12, RTL_SET_GATE = 13, RTL_SET_CLASSES = 14,
       RTL_LABEL_RANGE = 15 };
enum { RTL_EV_FIT = 1, RTL_EV_LOST = 3, RTL_EV_LABEL_FULL = 4, RTL_EV_FORGOT = 16, RTL_EV_FIT_US = 17,
       RTL_EV_TASK = 18, RTL_EV_TASK_US = 19, RTL_EV_GATE_THR = 20, RTL_EV_RANGE = 21,
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
} rtl_config_t;                                     /* k_rest starts equal to k (RTL_SET_REJECT sets it) */

typedef struct {
    uint32_t windows, windows_used, classified, skipped_busy, commands, lost_packets, seq_gaps, label_windows, fits;
    int32_t fit_result;
    uint32_t task_labels;                           /* task updates done */
    uint32_t gated;                                 /* windows the activity gate made Rest */
    uint32_t range_labels, range_windows;           /* 35.83: range labels applied, windows they added */
} rtl_counters_t;

void rtl_init(const rtl_config_t *cfg);
void rtl_rx(const uint8_t *bytes, uint32_t n);      /* real-time context */
void rtl_idle(void);                                /* thread context */
int rtl_mode(void);
const rtl_counters_t *rtl_counters(void);
void rtl_status(uint8_t ev, int32_t value);     /* send a PK_STATUS (thread context: the board's diagnostics) */
unsigned rtl_static_bytes(void);
