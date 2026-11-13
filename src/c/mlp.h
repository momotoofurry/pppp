/* Small MLP for the MCU (report 35.39; exploratory, the comparison model of nn_compare.py, NOT used by the firmware):
 * 80 -> 64 -> 32 -> MLP_K, ReLU, float32, static memory only. Input rows as for ldacal.c: 80 int16 Q5.10, already
 * z-scored by the caller. Training = softmax cross-entropy with L2 on the weights (not the biases), Adam, one sample
 * at a time accumulated over a mini-batch in the given order (no shuffling), as src/check_mlp_bench.py's float64
 * reference.
 * Parameter layout (mlp_load): W1 [80][64], b1 [64], W2 [64][32], b2 [32], W3 [32][MLP_K], b3 [MLP_K] (row = input).
 */
#pragma once
#include <stdint.h>

#define MLP_IN 80
#define MLP_H1 64
#define MLP_H2 32
#ifndef MLP_K
#define MLP_K 8
#endif
#define MLP_NPARAM (MLP_IN * MLP_H1 + MLP_H1 + MLP_H1 * MLP_H2 + MLP_H2 + MLP_H2 * MLP_K + MLP_K)

void mlp_load(const float *params);                  /* MLP_NPARAM floats; also resets Adam */
int mlp_scores(const int16_t *x, float *scores);     /* MLP_K logits; returns the class */
int mlp_predict(const int16_t *x);
/* one epoch over n rows in the given order, mini-batches of `batch` (the last one may be smaller) */
void mlp_train_epoch(const int16_t (*x)[MLP_IN], const uint8_t *y, int n, int batch, float lr, float l2);
void mlp_adam_reset(void);
const float *mlp_params(void);
unsigned mlp_static_bytes(void);
