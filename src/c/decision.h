/* From RF votes to robot commands: low-confidence rejection + k-window agreement (portable C, no state but
 * dc_state_t).
 *
 * Per 100 ms window: top class = most votes (ties -> lowest class), ratio = votes[top] / total trees.
 *   - rejected if ratio < tau (integer test votes[top] * 1000 < tau_permille * total); a rejected window breaks
 *     the run
 *   - a class is "established" when k consecutive accepted windows have the same top class
 *   - when a class is established and it is not the latched class, its command is sent (if it has one) and it
 *     becomes the latched class: holding a gesture sends its command once; the same command is sent again
 *     only after another class (Rest included) has been established in between
 * Gestures (labels 0-5): Power, Lateral, Tripod, Pointer, Open, Rest. Commands (from the one-shot confusion
 * matrix, results/confusion_oneshot_N100_d10_int16.csv): Tripod = grip, Open = release, Power / Pointer =
 * preset pose A / B, Lateral = home (since pilot-freeze-5, 2026-11-06: so that all 6 gestures occur in the task
 * and the self-calibration is not skipped for too few classes, PROTOCOL.md 3.1 / 5), Rest = no command.
 */
#pragma once
#include <stdint.h>

#ifndef DC_CLASSES
#define DC_CLASSES 6
#endif

enum { DC_NONE = 0, DC_POSE_A = 1, DC_GRIP = 2, DC_POSE_B = 3, DC_RELEASE = 4, DC_HOME = 5 };
/* 9 classes (-DDC_CLASSES=9 -DLD_CLASSES=9, 2026-11-17): wrist extension, wrist flexion, radial deviation, ulnar
 * deviation, index point, thumb up, hand open, fist, Rest -> up, down, left, right, forward, back, gripper open,
 * gripper close, none. Command code = class + 1. */
enum { DC9_UP = 1, DC9_DOWN = 2, DC9_LEFT = 3, DC9_RIGHT = 4, DC9_FORWARD = 5, DC9_BACK = 6, DC9_GRIP_OPEN = 7,
       DC9_GRIP_CLOSE = 8 };

typedef struct {
    uint16_t tau_permille;      /* rejection threshold, 0..1000 */
    uint8_t k;                  /* windows that must agree (>= 1) */
    uint8_t k_rest;             /* windows that must agree to establish Rest (the last class; >= 1; dc_init: k) */
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

/* command of each class (DC_NONE for Rest) */
extern const uint8_t dc_class_command[DC_CLASSES];

void dc_init(dc_state_t *s, uint16_t tau_permille, uint8_t k);
void dc_reset(dc_state_t *s);   /* forget the run and the latch (e.g. after a gap in the data) */
/* report 35.79: Rest (stop) may need fewer agreeing windows than a command (start): stopping fast is the safe side.
 * 0 = the same as k. Call after dc_init. */
void dc_set_rest_k(dc_state_t *s, uint8_t k_rest);
/* one window; votes: DC_CLASSES counts summing to total. Returns the command to send (DC_NONE: nothing). */
int dc_step(dc_state_t *s, const uint16_t *votes, int total, dc_out_t *out);
