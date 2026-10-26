/* Real-time loop of the MCU for route B (samples arrive over the serial link), portable C.
 *
 * Two execution contexts:
 *   real-time context  rt_rx(): called with the bytes received from the UART (from the UART / DMA interrupt or a
 *                      periodic low-priority interrupt that drains the DMA ring). It parses packets, and for every
 *                      sample frame: filter + window (features.c); every 200 samples (100 ms) a feature vector ->
 *                      z-score -> Q5.10 -> RF votes -> rejection / k-window agreement (decision.c) -> command
 *                      packet. It never runs anything long.
 *   thread context     rt_idle(): called from the main loop. Runs the long jobs: building the one-shot model
 *                      (os_calibrate, after the calibration recordings) and self-calibration (sc_end_block, every
 *                      RT_BLOCK windows). It must run at lower priority than rt_rx().
 * While self-calibration runs, new windows are still classified (sc_votes) but not put into the buffer: the
 * buffer is being read by the pseudo-labelling / tree training. Trees are replaced slot by slot with the slot falling back to
 * its Flash tree while it is rewritten (selfcal.c), so classification never sees a half-written tree.
 * After a stream reset (gap, lost packets, new recording) the first `warmup` windows only fill the filter
 * and the window (the band-pass starts from a zero state, as upstream) and are not used.
 *
 * RT_ADAPT (default 1): input adaptation (adapt.h). After one-shot calibration the z-score statistics start from the
 * one-shot image; every pushed window is added to its predicted class and the statistics are updated after each
 * self-calibration block (class-balanced, rate AD_RATE). On a later session (sensors re-donned) RT_ALIGN_START ..
 * RT_ALIGN_END collects windows of any gestures (not classified) and estimates the ring rotation; from then on
 * every feature vector is re-ordered before the z-score. RT_ADAPT = 0: the one-shot statistics only, no alignment
 * (the earlier firmware).
 *
 * Control sub-commands (PK_CONTROL payload[0], arguments follow):
 *   RT_STREAM_RESET            new recording / after a gap
 *   RT_CAL_START  label u8     the following windows are calibration windows of this gesture (0..5)
 *   RT_CAL_END                 stop collecting calibration windows
 *   RT_CALIBRATE               build the one-shot model from the collected windows (thread context)
 *   RT_SET_DECISION tau u16 k u8
 *   RT_SET_REPORT flags u8     bit 0: send PK_PRED for every classified window
 *   RT_ALIGN_START             (RT_ADAPT, after calibration) the following windows are alignment windows
 *   RT_ALIGN_END               estimate the rotation from them, back to classification
 * Status events (PK_STATUS): RT_EV_CALIBRATED value = os_calibrate() result, RT_EV_SELFCAL value = blocks done,
 *   RT_EV_LOST value = packets lost in the last gap, RT_EV_CAL_FULL value = calibration windows kept,
 *   RT_EV_ALIGNED value = estimated rotation (-3..4).
 */
#pragma once
#include <stdint.h>

#include "decision.h"
#include "oneshot.h"
#include "protocol.h"
#include "selfcal.h"

#define RT_BLOCK 300                    /* windows per self-calibration block (30 trials x 10 windows upstream) */

#ifndef RT_ADAPT
#define RT_ADAPT 1
#endif

enum { RT_STREAM_RESET = 1, RT_CAL_START = 2, RT_CAL_END = 3, RT_CALIBRATE = 4, RT_SET_DECISION = 5, RT_SET_REPORT = 6,
       RT_ALIGN_START = 7, RT_ALIGN_END = 8 };
enum { RT_EV_CALIBRATED = 1, RT_EV_SELFCAL = 2, RT_EV_LOST = 3, RT_EV_CAL_FULL = 4, RT_EV_ALIGNED = 5 };
enum { RT_MODE_IDLE = 0, RT_MODE_CAL = 1, RT_MODE_RUN = 2, RT_MODE_ALIGN = 3 };

typedef struct {
    const os_table_t *pre;              /* pre-trained trees (Flash) */
    const os_writer_t *writer;          /* one-shot image writer (Flash sector) */
    const void *image;                  /* where the image can be read back (the Flash sector) */
    int (*flash_erase)(void);           /* erase the image sector before writing (0: nothing to do) */
    int (*flash_flush)(void);           /* after the last write (0: nothing to do) */
    void (*tx)(const uint8_t *bytes, uint32_t n);   /* send bytes to the PC */
    uint32_t (*now_us)(void);           /* time stamp for the outgoing packets */
    uint16_t warmup;                    /* windows ignored after a stream reset */
    uint16_t tau_permille;
    uint8_t k;
    uint32_t seed;
} rt_config_t;

typedef struct {
    uint32_t windows, windows_used, pushed, classified_only, commands, lost_packets, seq_gaps, cal_windows;
    uint32_t selfcal_blocks;
    int32_t calibrate_result;
} rt_counters_t;

void rt_init(const rt_config_t *cfg);
void rt_rx(const uint8_t *bytes, uint32_t n);    /* real-time context */
void rt_idle(void);                              /* thread context */
int rt_mode(void);
const rt_counters_t *rt_counters(void);
const pk_parser_t *rt_parser(void);
