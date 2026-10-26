/* On-device self-calibration of the RF (Cortex-M7), static memory only: the whole upstream loop of
 * main_replay_arm_position.py for one user after one-shot calibration.
 *
 * Model: the one-shot model (SC_N_PRE pruned pre-trained trees + SC_N_APP trees trained on the calibration
 * data) is written to Flash once per calibration session and never rewritten. Self-calibration keeps
 * SC_N_APP replaceable slots: each slot uses either its original one-shot tree (Flash) or a new tree in RAM
 * (<= SC_MAX_LEAVES leaves). Inference = majority vote of the SC_N_PRE + SC_N_APP trees.
 *
 * Per test block, rows are streamed in with sc_push() (no block buffer in RAM) and sc_end_block() then does
 * what upstream does after each block:
 *   1. (sc_push) predict each row with the self-calibrated model, put row + prediction into the buffer
 *      (upstream buffer_update: new rows go to the front; when full, each new row evicts the last row of the
 *      most frequent (pseudo-)label)
 *   2. re-label the whole buffer with the ORIGINAL one-shot model (as upstream manifold_clustering)
 *   3. if every class has >= SC_MIN_CLASS rows: take the first m rows of each class (m = smallest count),
 *      K-Means initialised at the class centres -> cluster = pseudo-label; otherwise class-balanced rows with
 *      the model labels. SC_EMBED selects what K-Means runs on:
 *        0 (default)  the 80 int16 features of the rows themselves (upstream embedding=None). At the MCU buffer
 *                     size this is as accurate as t-SNE (results/embed_sweep_summary.csv: 83.21 vs 83.23%,
 *                     p = 0.65) and needs no t-SNE module (tsne.c is not linked)
 *        1            t-SNE (3-D, perplexity 10, SC_TSNE_ITER iterations) -> standardise (the earlier firmware)
 *   4. train SC_N_UPD trees (depth SC_MAX_DEPTH, <= SC_MAX_LEAVES leaves) on these rows + the calibration
 *      set, and put them into SC_N_UPD randomly chosen slots
 * Features are int16 Q5.10 throughout (buffer, calibration set, trees).
 */
#pragma once
#include <stdint.h>

#ifndef SC_BUF
#define SC_BUF 375
#endif
#define SC_CAL_MAX 60
#define SC_DIM 80
#define SC_CLASSES 6
#define SC_N_PRE 50
#define SC_N_APP 50
#define SC_N_UPD 20             /* round(0.4 * SC_N_APP), as upstream (80 of 200) */
#define SC_MIN_CLASS 10
#define SC_MAX_DEPTH 10
#define SC_MAX_LEAVES 32
#ifndef SC_EMBED
#define SC_EMBED 0
#endif
#ifndef SC_TSNE_ITER
#define SC_TSNE_ITER 500
#endif
#define SC_PERPLEXITY 10.0f
#ifndef SC_BLOCK_MAX
#define SC_BLOCK_MAX 4096       /* most rows per block (keys reserved per block; 300 in the data set) */
#endif

/* node of a tree stored as an array of structs (one-shot trees in the Flash image, oneshot.h) */
typedef struct {
    uint8_t feat;
    uint8_t pad;
    int16_t thr;                /* go left if x < thr (Q5.10) */
    uint16_t left, right;       /* bit 15 set -> leaf (low bits = class), else node index within the tree */
} sc_node_t;

/* pruned node of a pre-trained tree: internal node `idx` (global index into the table arrays) is a leaf */
typedef struct {
    uint16_t idx;
    uint8_t label;
    uint8_t pad;
} sc_prune_t;

/* one-shot model: SC_N_PRE + SC_N_APP trees.
 * roots/feat/thr/left/right: our table format (rf_predict.h). Without app_nodes the table holds all
 * SC_N_PRE + SC_N_APP trees (one-shot model built on the PC). With on-device one-shot calibration (oneshot.c)
 * the table holds the SC_N_PRE pre-trained trees (const, Flash), pruned through prune_bits / prune (bit g
 * set: internal node g is now a leaf, label in the sorted list prune[0..n_prune)), and the SC_N_APP
 * calibration trees are app_nodes / app_roots (root: bit 31 set -> single leaf, else node offset). */
typedef struct {
    const uint32_t *roots;
    const uint8_t *feat;
    const int16_t *thr;
    const uint16_t *left, *right;
    const uint8_t *prune_bits;          /* 0: no pruning overlay */
    const sc_prune_t *prune;
    int n_prune;
    const sc_node_t *app_nodes;         /* 0: the app trees are trees SC_N_PRE.. of the table */
    const uint32_t *app_roots;
} sc_model_t;

typedef struct {
    int buffer_n;               /* rows in the buffer */
    int n_selected;             /* rows used for pseudo-labelling */
    int clustered;              /* 1: K-Means (after t-SNE if SC_EMBED) ran; 0: model labels */
    int tsne_cells_max;         /* 0 without t-SNE */
    int ram_trees;              /* slots holding a RAM tree */
    int new_nodes_max;          /* internal nodes of the largest new tree */
} sc_stats_t;

void sc_init(const sc_model_t *m, const int16_t *cal, const uint8_t *cal_y, int n_cal, uint32_t seed);
int sc_predict(const int16_t *x);                    /* self-calibrated model */
int sc_predict_oneshot(const int16_t *x);            /* original one-shot model */
/* as above, with the votes of the SC_N_PRE + SC_N_APP trees per class (votes: SC_CLASSES entries) */
int sc_votes_oneshot(const int16_t *x, uint16_t *votes);
/* one row of the current block (SC_DIM int16): returns the self-calibrated prediction, buffers the row */
int sc_push(const int16_t *x);
int sc_push_votes(const int16_t *x, uint16_t *votes);   /* same, also returns the votes per class */
/* classify only (no buffering): for windows that arrive while sc_end_block() runs in the background */
int sc_votes(const int16_t *x, uint16_t *votes);
/* end of block: pseudo-label the buffer, train SC_N_UPD trees, replace slots */
void sc_end_block(sc_stats_t *st);
unsigned sc_static_bytes(void);
