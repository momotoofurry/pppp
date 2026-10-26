/* Label-free input adaptation on the MCU, static memory only: start-up channel alignment and the class-balanced
 * online update of the z-score statistics. Both work on the raw (not normalised) feature vectors of features.c
 * (SC_DIM = 10 features x 8 channels, column = feature * 8 + channel).
 *
 * Start-up alignment (python: shift_sweep.estimate_rotation): the electrode ring may be rotated by k positions on
 * a later day. Profile = per feature in {RMS, MAV, WL} and channel: mean of log(max(x, 1e-12)) over the windows,
 * standardised over the 8 channels (population std). k = argmax_k sum q[f][c] * p[f][(c - k) mod 8] over the
 * 8 candidates (first maximum; returned in -3..4), q = calibration profile, p = profile of the alignment windows.
 * ad_map() then reads model channel c from recorded channel (c + k) mod 8. With k = 0 ad_map() is a copy.
 *
 * z-score update (python: zscore_sweep.py, zs = bal0.3): during a block every pushed window is added to the
 * running mean / M2 of its predicted class (Welford, float32). At the end of the block, the classes with
 * >= AD_MIN_CLASS windows give the equal-weight mixture: mean = mean of the class means, var = mean of the class
 * variances + variance of the class means (population); with >= 2 such classes the statistics move by AD_RATE:
 * mu <- (1 - a) mu + a mean, var <- (1 - a) var + a var. ad_normalize() uses the current statistics.
 * The block statistics never use labels: the classes are the self-calibrated model's predictions.
 * results/zscore_sweep_summary_bal.csv: with Rest as half of the windows 84.17% (no update 83.23%).
 */
#pragma once
#include <stdint.h>

#include "selfcal.h"

#ifndef AD_RATE
#define AD_RATE 0.3f
#endif
#define AD_MIN_CLASS 5
#define AD_CH 8

typedef struct {
    int classes_used;           /* classes with >= AD_MIN_CLASS windows in the last block (update if >= 2) */
    int updated;                /* 1: the statistics were updated */
} ad_stats_t;

/* mu / inv_sd: the one-shot z-score (os_header_t); cal: n_cal x SC_DIM raw calibration features (profile) */
void ad_init(const float *mu, const float *inv_sd, const float *cal, int n_cal);
/* start-up alignment: windows of a short recording (any gestures), then the rotation estimate */
void ad_align_reset(void);
void ad_align_push(const float *raw);
int ad_align_finish(void);      /* sets and returns k (-3..4); 0 if no window was pushed */
int ad_rotation(void);
void ad_set_rotation(int k);
/* raw -> aligned raw (out may not alias raw) */
void ad_map(const float *raw, float *out);
/* z-score with the current statistics + Q5.10 (as os_normalize) */
void ad_normalize(const float *x, int16_t *q);
/* aligned raw features of a pushed window and its predicted class */
void ad_observe(const float *x, int cls);
/* end of block: update the statistics; resets the class accumulators */
void ad_end_block(ad_stats_t *st);
const float *ad_mean(void);     /* current statistics (for the PC check) */
const float *ad_var(void);
unsigned ad_static_bytes(void);
