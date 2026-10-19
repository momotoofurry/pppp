/* CART tree training for on-device self-calibration (Cortex-M7), static memory only.
 *
 * Mirrors one tree of scikit-learn 1.5 RandomForestClassifier(max_depth, max_leaf_nodes, bootstrap=True,
 * max_features='sqrt', criterion='gini', min_samples_split=2, min_samples_leaf=1) as used by self-calibration:
 *   - bootstrap: n draws with replacement -> integer sample weights; rows with weight 0 are dropped
 *   - best splitter: features visited in random order until max_features non-constant ones were tried;
 *     for each, rows sorted by value, every boundary between distinct values scored with the gini proxy
 *     sum_c(w_left,c^2)/w_left + sum_c(w_right,c^2)/w_right; the best one wins (first on ties)
 *   - with max_leaf_nodes: best-first growth (frontier ordered by weighted impurity decrease), as
 *     sklearn's BestFirstTreeBuilder; a node is a leaf if depth >= max_depth, < 2 rows or pure
 *   - leaf class = argmax of weighted class counts (ties -> lowest class)
 * Data are the int16 Q5.10 features as stored in RAM. Threshold = midpoint of the two values around the split
 * (as sklearn), rounded up, so a < thr <= b and the inference rule `x < thr` (rf_predict.c, upstream
 * get_predictions) reproduces the training split exactly.
 * Differences from sklearn: own RNG (xorshift32), so trees are not bit-identical to sklearn's.
 */
#pragma once
#include <stdint.h>

#ifndef RFT_NMAX
#define RFT_NMAX 440            /* training rows: 375 buffer + 60 calibration (+ margin) */
#endif
#ifndef RFT_DIM
#define RFT_DIM 80
#endif
#ifndef RFT_CLASSES
#define RFT_CLASSES 6
#endif
#ifndef RFT_MAX_LEAVES
#define RFT_MAX_LEAVES 32
#endif
#define RFT_MAX_NODES (2 * RFT_MAX_LEAVES - 1)

typedef struct {
    int n_nodes;                         /* nodes 0..n_nodes-1, root 0 */
    int16_t left[RFT_MAX_NODES];         /* -1 for a leaf */
    int16_t right[RFT_MAX_NODES];
    uint8_t feature[RFT_MAX_NODES];
    int16_t thr[RFT_MAX_NODES];          /* go left if x < thr (Q5.10) */
    uint8_t cls[RFT_MAX_NODES];          /* majority class of the node (used at leaves) */
    uint16_t count[RFT_MAX_NODES][RFT_CLASSES];   /* weighted class counts (for the PC check) */
} rft_tree_t;

/* rows[i]: pointer to RFT_DIM int16 features of training row i; y[i] in 0..RFT_CLASSES-1.
 * max_leaves <= RFT_MAX_LEAVES (0 = RFT_MAX_LEAVES). Returns 0, -1 if n > RFT_NMAX. */
int rft_train(const int16_t *const *rows, const uint8_t *y, int n, int max_depth, int max_leaves,
              int max_features, uint32_t seed, rft_tree_t *out);

unsigned rft_static_bytes(void);
