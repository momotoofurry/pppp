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
 * (the earlier firmware). The alignment needs >= RT_ALIGN_MIN windows (about 6 s, several gestures: with fewer
 * windows or one gesture the estimate is often wrong, report 20); with fewer the rotation is left unchanged and
 * RT_EV_ALIGN_SHORT is sent instead of RT_EV_ALIGNED.
 * RT_RESCALE (default 1, report 20 'R3'): at the end of a block the z-score statistics are updated first, the
 * buffer and the calibration rows are mapped to the new statistics (sc_rescale), then the new trees are trained,
 * so that buffer, calibration rows and new trees share the statistics of the next block. RT_RESCALE = 0: firmware
 * v2 order (sc_end_block, then ad_end_block, no mapping).
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
 *   RT_LOAD                    restore the day-1 state from the one-shot image in Flash (model, z-score, calibration
 *                              rows, alignment profile; adaptation starts again): after a reboot, or to start a
 *                              study condition from the same initial model. Adapted trees are never written to Flash.
 *   RT_SET_ADAPT on u8          1 (default after reset): full system; 0: fixed day-1 model, windows are classified but
 *                              never buffered, so there is no z-score update, no self-calibration and no alignment
 * Status events (PK_STATUS): RT_EV_CALIBRATED value = os_calibrate() result, RT_EV_SELFCAL value = blocks done,
 *   RT_EV_LOST value = packets lost in the last gap, RT_EV_CAL_FULL value = calibration windows kept,
 *   RT_EV_ALIGNED value = estimated rotation (-3..4), RT_EV_ALIGN_SHORT value = alignment windows received,
 *   RT_EV_SC_BEGIN value = windows so far when a self-calibration starts, RT_EV_SC_END value = its duration (us);
 *   the PRED packets between the two are the windows classified while it ran (test A, VALIDATION_PLAN.md);
 *   RT_EV_SC_SKIP value = predicted classes in the block, when the update was skipped (RT_MIN_CLASSES),
 *   RT_EV_LOADED value = calibration rows restored by RT_LOAD (> 0), or -1 no valid image / -5 bad model.
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
#ifndef RT_RESCALE
#define RT_RESCALE 1
#endif
#define RT_ALIGN_MIN 60                 /* windows (6 s of continuous stream) */
#ifndef RT_MIN_CLASSES
#define RT_MIN_CLASSES 5                /* skip a block's update when fewer predicted classes have >= AD_MIN_CLASS
                                           windows (report 22: only Rest + 2 gestures made self-calibration -6.4 points);
                                           0 = never skip */
#endif

enum { RT_STREAM_RESET = 1, RT_CAL_START = 2, RT_CAL_END = 3, RT_CALIBRATE = 4, RT_SET_DECISION = 5, RT_SET_REPORT = 6,
       RT_ALIGN_START = 7, RT_ALIGN_END = 8, RT_LOAD = 9, RT_SET_ADAPT = 10 };
enum { RT_EV_CALIBRATED = 1, RT_EV_SELFCAL = 2, RT_EV_LOST = 3, RT_EV_CAL_FULL = 4, RT_EV_ALIGNED = 5,
       RT_EV_ALIGN_SHORT = 6, RT_EV_SC_BEGIN = 7, RT_EV_SC_END = 8,
       /* diagnostics sent by the board main loop (app_rt.c), not by rt.c */
       RT_EV_DIAG_RX_HW = 9, RT_EV_DIAG_STACK = 10, RT_EV_DIAG_RX_OVF = 11, RT_EV_DIAG_RX_ERR = 12,
       RT_EV_SC_SKIP = 13, RT_EV_LOADED = 14 };
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
void rt_status(uint8_t ev, int32_t value);       /* send a PK_STATUS (thread context: the board's diagnostics) */
const pk_parser_t *rt_parser(void);
