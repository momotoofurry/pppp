# R17: shrinkage with the effective sample size (written 2026-11-25, BEFORE any accuracy of this rule was computed)

Report 35.98. Base = L (log RMS/WL/MAV, R16 candidate). Diagnostics so far (no accuracy):
- diag5: the additive noise-floor model is refuted (floor-corrected log does not align the effort directions, makes
  skew worse, clips 6-66 % of windows). Not tested for accuracy.
- diag6: 'shared covariance + one class-specific direction' cannot be established: the Marchenko-Pastur edge assumes
  independent windows, which they are not, and the top direction is stable across the two days for only 2 of 6
  gestures. Not built.
- diag7 (nested ANOVA, space L+U): the between-cue share of the within-class variance (ICC) is 0.04-0.07 in the cued
  pass (2 consecutive cues per class) but 0.22-0.34 among the later probe cues (other postures, later in time). The
  cued pass does not see the cue-to-cue variability, and OAS treats its 420 overlapping windows as independent, so the
  shrinkage is too weak (rho 0.05).

## Rule K (Kish-corrected OAS)
OAS with N_eff = N / (1 + (m - 1) ICC) instead of N, m = windows per cue (self-test cued pass 30; DB6 10), ICC fixed
at 0.25 (a round value between the two days' probe estimates 0.22 and 0.34; probes are only used for this constant).
One line on the MCU (the N passed to the solver). Everything else unchanged.

## Decision
Self-test (structure_r16.py data, S7): A(L+K) - A(L) mean >= +1 point and > 0 on both days.
DB6 (db6_sim protocol, cue1 accumulated): cue1(L+K) - cue1(L) paired 95 % CI above 0.
K is a CANDIDATE only if both hold; confirmation on next week's S7 recording as in R16. Frozen firmware unchanged.
Reported, not decided: ICC in {0, 0.05, 0.1, 0.25, 0.5, 1} (sensitivity: is the theory-picked value near the best?),
fixed and within on DB6, cross-day fixed on the self-test.
