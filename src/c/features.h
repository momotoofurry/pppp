/* Streaming EMG feature extraction for the MCU (8 channels, 2 kHz), float32, static memory only.
 *
 * Mirrors upstream main_feature_extract_arm_position.py + emg_functions.get_*:
 *   - 4th-order Butterworth band-pass 10-500 Hz per channel, as 4 biquads (scipy butter(..., output='sos'),
 *     direct form II transposed, float32), starting from a zero state like upstream lfilter(b, a, zi=None)
 *   - windows of 400 samples every 200 samples (0.2 s / 0.1 s)
 *   - per channel: RMS, WL, SSC, ZC (thresholds 0), MAV, skewness (biased), and from a Welch PSD with one
 *     400-point periodic Hamming segment zero-padded to a 512-point FFT: VCF, MDF, MNF, PKF
 *   - output: 80 values, feature-major (rms ch0..7, wl, ssc, zc, mav, skw, vcf, mdf, mnf, pkf) as pipeline.py
 * The PSD scale (1 / (fs * sum w^2), x2 for the one-sided bins) cancels in all four spectral features and
 * is not applied. The FFT is a plain radix-2 complex FFT (on the MCU it can be swapped for CMSIS-DSP).
 */
#pragma once
#include <stdint.h>

#define FE_CH 8
#define FE_WIN 400
#define FE_STEP 200
#define FE_NFFT 512
#define FE_NFEAT 10
#define FE_DIM (FE_CH * FE_NFEAT)
#define FE_FS 2000.0f

void fe_init(void);                         /* tables (window, twiddles) */
void fe_reset(void);                        /* zero filter state, empty window (start of a recording) */
/* one sample of the FE_CH channels; returns 1 when a new feature vector was written to feat */
int fe_push(const float *x, float *feat);
/* z-score with the calibration statistics, then Q5.10 int16 (round half to even, saturating) */
void fe_normalize_q16(const float *feat, const float *mu, const float *inv_sd, int16_t *out);
unsigned fe_static_bytes(void);
int fe_recording(const float *x, int n, float *out, int max_win);   /* PC check helper */
