/* K-Means for the pseudo-labelling step (on the 3-D t-SNE embedding), static memory only.
 * Mirrors sklearn 1.5 KMeans(n_clusters=k, init=<given centres>, n_init=1, algorithm='lloyd', max_iter=300,
 * tol=1e-4) as called by upstream manifold_clustering: tol is relative to the mean data variance, the loop
 * stops when labels stop changing (strict convergence) or the squared centre shift <= tol, and a final
 * assignment is made with the final centres if it did not converge strictly. Empty clusters get the point
 * farthest from its centre (sklearn relocates the farthest points; identical when one cluster is empty).
 * standardize() = sklearn StandardScaler (population std); group_centres() = upstream findGroupCenter
 * (classes 0..k-1, all present after class balancing).
 */
#pragma once
#include <stdint.h>

#ifndef KM_NMAX
#define KM_NMAX 375
#endif
#define KM_DIM 3
#define KM_KMAX 6

/* x: n x KM_DIM; ctr: k x KM_DIM initial centres (updated in place); lab: n labels out.
 * Returns iterations run, or -1. */
int km_fit(const float *x, int n, int k, float *ctr, int max_iter, float tol_rel, uint8_t *lab);
void standardize(float *x, int n);
void group_centres(const float *x, int n, const uint8_t *lab, int k, float *ctr);
unsigned km_static_bytes(void);
