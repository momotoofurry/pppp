/* Per-session LDA re-calibration from labelled windows, static memory only (exploratory, report 35.10; NOT part
 * of the frozen firmware). The comparator of leafcal.c: the classic short re-calibration, in a form that can keep
 * accumulating labelled windows over any number of sessions in fixed memory.
 *
 * State = running sums only: per class the count and the sum of the rows, and one symmetric LD_DIM x LD_DIM sum of
 * outer products (packed lower triangle). No rows are stored.
 *   ld_add(x, label)   one labelled window (LD_DIM int16, Q5.10, already z-scored by the caller)
 *   ld_fit()           class means; pooled within-class covariance S = (G - sum_c n_c m_c m_c^T) / N; OAS shrinkage
 *                      rho = min(1, (a + mu^2) / ((N + 1)(a - mu^2 / p))), mu = tr(S) / p, a = mean(S_ij^2)
 *                      (Chen et al. 2010, as sklearn.covariance.oas: needs only S and N, so the sums are enough);
 *                      C = (1 - rho) S + rho mu I; Cholesky; w_c = C^-1 m_c, b_c = -m_c.w_c / 2 (equal priors)
 *   ld_predict(x)      argmax_c (x.w_c + b_c)
 * ld_reset() + 60 x ld_add + ld_fit = a new LDA from one start-up sequence (LDAr_oas in src/lda_anchor.py);
 * without ld_reset the labels accumulate (LDAcum_oas). float32 throughout.
 */
#pragma once
#include <stdint.h>

#define LD_DIM 80
#define LD_CLASSES 6
#define LD_Q 1024.0f            /* Q5.10 */
#define LD_TRI (LD_DIM * (LD_DIM + 1) / 2)

void ld_reset(void);
void ld_add(const int16_t *x, int label);
/* 0: ok. -1: a class has no window. -2: the covariance is not positive definite (the old model is kept). */
int ld_fit(void);
int ld_scores(const int16_t *x, float *scores);      /* LD_CLASSES discriminant values; returns the class */
int ld_predict(const int16_t *x);
float ld_shrinkage(void);                            /* rho of the last ld_fit */
unsigned ld_static_bytes(void);
