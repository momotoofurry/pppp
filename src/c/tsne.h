/* Barnes-Hut t-SNE (3-D) for the self-calibration buffer, written for a Cortex-M7 MCU.
 *
 * Mirrors scikit-learn 1.5 TSNE(n_components=3, perplexity, learning_rate='auto', init='random',
 * method='barnes_hut', angle=0.5) as called by the upstream manifold_clustering:
 *   - exact k nearest neighbours (k = 3 * perplexity + 1, self excluded) on squared euclidean distance
 *   - per-point binary search for the Gaussian bandwidth (100 steps, tolerance 1e-5, double)
 *   - P = (P_cond + P_cond^T) / sum, kept as the k directed edges per point (no CSR transpose):
 *     every edge applies its attractive force to both endpoints, which equals the symmetrised sum
 *   - Student-t with dof = n_components - 1 = 2, gradient scale 2 (dof + 1) / dof, as sklearn
 *   - 250 iterations with early exaggeration 12 and momentum 0.5, then momentum 0.8; gains
 *     (+0.2 / x0.8, min 0.01); update and gains are reset between the two phases; learning rate
 *     max(n / 12 / 4, 50); stop early if the gradient norm (checked every 50 iterations) <= 1e-7
 *   - repulsive forces from an octree with the sklearn summary rule
 *     (cell max width^2 / distance^2 < angle^2; a leaf holding the query point is skipped)
 * Differences: the KL-based "no progress" stop (sklearn checks every 50 iterations; it never fired in
 * our runs, which always reach max_iter) is not implemented; the initial embedding is passed in
 * (sklearn: 1e-4 * standard normal) so the PC comparison can use the same draw.
 *
 * Memory: everything is static (sized by TSNE_NMAX / TSNE_K at compile time), no malloc.
 * Input: the buffer as int16 Q5.10 features (n x TSNE_DIM, row-major), as stored in RAM.
 */
#pragma once
#include <stdint.h>

#ifndef TSNE_NMAX
#define TSNE_NMAX 375           /* max points (class-balanced buffer) */
#endif
#ifndef TSNE_K
#define TSNE_K 31               /* neighbours: 3 * perplexity + 1 for perplexity 10 */
#endif
#ifndef TSNE_DIM
#define TSNE_DIM 80
#endif
#ifndef TSNE_CELLS
#define TSNE_CELLS (3 * TSNE_NMAX)   /* octree cells; on overflow a point is merged into its cell */
#endif

typedef struct {
    int n_iter;                 /* iterations run */
    int cells_max;              /* largest octree used (cells) */
    int cell_overflow;          /* points merged because the octree was full (0 expected) */
    int tree_depth_max;
    double grad_norm;           /* at the last check */
} tsne_stats_t;

/* rows[i]: TSNE_DIM int16 (Q5.10) features of point i (rows of the RAM buffer, no copy);
 * init / y: n x 3 float (y may alias init). Returns 0, or -1 if n > TSNE_NMAX or n <= k. */
int tsne_run(const int16_t *const *rows, int n, float perplexity, int max_iter, const float *init, float *y,
             tsne_stats_t *st);

/* bytes of static memory used by the t-SNE module (for the report) */
unsigned tsne_static_bytes(void);
