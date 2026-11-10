/* Leaf counters: labelled windows of a start-up sequence update the forest without retraining (exploratory,
 * report 35; NOT part of the frozen firmware). Static memory only.
 *
 * The trees stay as they are after the one-shot calibration. Every leaf of the trees that take part has
 * LC_CLASSES counters (uint8). lc_learn(x, label) routes one labelled window to its leaf in each of those trees
 * and increments the counter of `label`. A leaf then answers
 *     argmax_k ( 2 * count[k] + (k == class of the leaf after one-shot) ),   ties -> lowest k
 * i.e. the one-shot class until another class has been seen more often in that leaf than the one-shot class
 * plus one half (src/leaf_sweep.py: LAonly, anchor weight 8, prior 4). A counter that reaches 255 halves the
 * counters of its leaf. No buffer, no clustering, no tree training, no Flash write.
 *
 * Tables: as rf_predict.h (internal nodes only, `x < thr` goes left), except that a leaf child also carries
 * the index of the leaf inside its tree:
 *     child = 0x8000 | (leaf index << 3) | class        (leaf index < 4096, class < 8)
 * roots[t] with bit 31 set: the whole tree is one leaf (index 0), class in the low byte.
 * leaf_base[t] .. leaf_base[t + 1]: counter rows of tree t; equal -> the tree keeps no counters (it votes with
 * its one-shot classes). src/check_leafcal_c.py builds the tables from the one-shot model made on the PC; the
 * pruning overlay of oneshot.c (on-device one-shot) is not supported yet.
 */
#pragma once
#include <stdint.h>

#define LC_DIM 80
#define LC_CLASSES 6
#define LC_N_TREES 100
#ifndef LC_MAX_LEAVES
#define LC_MAX_LEAVES 13312     /* counter rows: 13 KiB of leaves x 6 B = 78 KiB; measured need in leaf_sweep_leaves.csv */
#endif

typedef struct {
    const uint32_t *roots;
    const uint8_t *feat;
    const int16_t *thr;
    const uint16_t *left, *right;
    const uint16_t *leaf_base;          /* LC_N_TREES + 1 entries, non-decreasing, last <= LC_MAX_LEAVES */
} lc_model_t;

/* returns 0, or -1 when the model needs more than LC_MAX_LEAVES counter rows (nothing is changed then) */
int lc_init(const lc_model_t *m);
void lc_reset(void);                                 /* all counters to 0: back to the one-shot model */
void lc_learn(const int16_t *x, int label);          /* one labelled window (LC_DIM int16, Q5.10) */
int lc_votes(const int16_t *x, uint16_t *votes);     /* votes per class (LC_CLASSES entries); returns the class */
int lc_predict(const int16_t *x);
unsigned lc_static_bytes(void);
