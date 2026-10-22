/* From RF votes to robot commands: low-confidence rejection + k-window agreement (portable C, no state but
 * dc_state_t).
 *
 * Per 100 ms window: top class = most votes (ties -> lowest class), ratio = votes[top] / total trees.
 *   - rejected if ratio < tau (integer test votes[top] * 1000 < tau_permille * total); a rejected window breaks
 *     the run
 *   - a class is "established" when k consecutive accepted windows have the same top class
 *   - when a class is established and it is not the latched class, its command is sent (if it has one) and it
 *     becomes the latched class: holding a gesture sends its command once; the same command is sent again
 *     only after another class (Rest and Lateral included) has been established in between
 * Gestures (labels 0-5): Power, Lateral, Tripod, Pointer, Open, Rest. Commands (from the one-shot confusion
 * matrix, results/confusion_oneshot_N100_d10_int16.csv): Tripod = grip, Open = release, Power / Pointer =
 * preset pose A / B, Lateral and Rest = no command.
 */
#pragma once
#include <stdint.h>

#define DC_CLASSES 6

enum { DC_NONE = 0, DC_POSE_A = 1, DC_GRIP = 2, DC_POSE_B = 3, DC_RELEASE = 4 };

typedef struct {
    uint16_t tau_permille;      /* rejection threshold, 0..1000 */
    uint8_t k;                  /* windows that must agree (>= 1) */
    int8_t last;                /* top class of the current run of accepted windows, -1 none */
    uint8_t run;                /* length of that run (saturates at k) */
    int8_t latched;             /* last established class, -1 none */
} dc_state_t;

typedef struct {
    int8_t top;                 /* most voted class */
    uint16_t ratio_permille;    /* votes[top] * 1000 / total */
    uint8_t accepted;           /* ratio >= tau */
    int8_t established;         /* class established in this window, -1 none */
} dc_out_t;

/* command of each class (DC_NONE for Lateral and Rest) */
extern const uint8_t dc_class_command[DC_CLASSES];

void dc_init(dc_state_t *s, uint16_t tau_permille, uint8_t k);
void dc_reset(dc_state_t *s);   /* forget the run and the latch (e.g. after a gap in the data) */
/* one window; votes: DC_CLASSES counts summing to total. Returns the command to send (DC_NONE: nothing). */
int dc_step(dc_state_t *s, const uint16_t *votes, int total, dc_out_t *out);
