/* One-shot calibration on the MCU (Cortex-M7): a new user records one trial per gesture, and the MCU builds the
 * one-shot model itself (upstream main_replay_arm_position.py, before the first test block):
 *   1. z-score statistics: mean and population std of every feature over the calibration rows
 *      (pipeline.load_subject), then the rows as Q5.10 int16
 *   2. prune the SC_N_PRE pre-trained trees (depth 10, const in Flash) with the calibration rows: upstream
 *      emg_functions.prune, decision for decision (see oneshot.c), kept as an overlay (bitmap + sorted list of
 *      "internal node g is now a leaf with label c"), the pre-trained table is never copied or changed
 *   3. train SC_N_APP trees on the calibration rows (rf_train.c, depth 10, no leaf limit in practice:
 *      OS_MAX_LEAVES >= the number of rows)
 *   4. stream everything into a one-shot image written once to Flash through os_writer_t (append-only,
 *      each byte written once; the hardware writer is in the board layer, the PC check uses a RAM array)
 * Image layout: [header (padded to 32 B)] [prune list] [app tree nodes (sc_node_t)] [prune bitmap];
 * the header is written last. os_model() turns an image (+ the pre-trained table) into an sc_model_t.
 * All working memory is borrowed from the t-SNE workspace (tsne_scratch): one-shot calibration runs before
 * self-calibration starts, so the two never run at the same time.
 */
#pragma once
#include <stdint.h>

#include "selfcal.h"

#define OS_MAGIC 0x4F53484Fu         /* "OSHO" */
#define OS_VERSION 1u
#define OS_CAL_MAX SC_CAL_MAX         /* calibration rows */
#define OS_MAX_DEPTH SC_MAX_DEPTH
#define OS_MAX_LEAVES 64              /* one-shot trees: <= number of distinct rows (60) */
#define OS_MAX_FEATURES 8             /* sklearn max_features='sqrt' of 80 */
#define OS_TREE_INT_MAX 1023          /* internal nodes of one depth-10 tree */
#define OS_PRE_INT_MAX 65535u         /* prune list uses 16-bit node indices */
#define OS_ALIGN 32u                  /* STM32H7 Flash word */

/* the SC_N_PRE pre-trained trees, our table format (rf_predict.h), const in Flash */
typedef struct {
    const uint32_t *roots;
    const uint8_t *feat;
    const int16_t *thr;
    const uint16_t *left, *right;
    uint32_t n_internal;              /* total internal nodes of the table */
} os_table_t;

typedef struct {
    uint32_t magic, version, bytes;   /* bytes: size of the whole image */
    uint32_t n_cal, n_prune, n_nodes; /* rows used, prune entries, app tree nodes */
    uint32_t off_prune, off_nodes, off_bits, bits_bytes;
    uint32_t app_roots[SC_N_APP];
    float mu[SC_DIM], inv_sd[SC_DIM]; /* z-score: q = round((x - mu) * inv_sd * 1024) */
} os_header_t;

/* append-only writer (Flash): write n bytes at byte offset off of the image; returns 0 on success */
typedef struct {
    int (*write)(void *ctx, uint32_t off, const void *src, uint32_t n);
    void *ctx;
    uint32_t capacity;                /* bytes available (one Flash sector: 128 KB) */
} os_writer_t;

typedef struct {
    int n_pruned_nodes;               /* pruned leaves over all pre-trained trees */
    int app_nodes;                    /* internal nodes of the app trees */
    int app_leaves_max;
    uint32_t image_bytes;
    uint32_t scratch_bytes;           /* borrowed from the t-SNE workspace */
} os_stats_t;

/* buffer for the raw (not normalised) calibration features, OS_CAL_MAX x SC_DIM float: fill it, then calibrate */
float *os_feature_buffer(void);
/* rows 0..n-1 of os_feature_buffer() with labels y (0..SC_CLASSES-1). cal_q receives the n rows as Q5.10
 * (for sc_init). Returns 0, or a negative error (-1 sizes, -2 scratch too small, -3 writer, -4 image full). */
int os_calibrate(const os_table_t *pre, const uint8_t *y, int n, uint32_t seed, const os_writer_t *w, int16_t *cal_q,
                 os_stats_t *st);
/* the Q5.10 calibration rows of the last os_calibrate() (valid until the first t-SNE runs: pass them to sc_init) */
const int16_t *os_cal_rows(void);
/* z-score + Q5.10 of one feature vector with the statistics of an image (as fe_normalize_q16) */
void os_normalize(const os_header_t *h, const float *feat, int16_t *out);
/* sc_model_t of an image; returns 0, or -1 if the image is not valid */
int os_model(const void *image, const os_table_t *pre, sc_model_t *m);
/* pruning only (PC check): prune the pre-trained trees with Q5.10 rows; out receives the sorted prune list
 * (at most max_out entries). Returns the number of entries, or a negative error. */
int os_prune(const os_table_t *pre, const int16_t *rows_q, const uint8_t *y, int n, sc_prune_t *out, int max_out);
