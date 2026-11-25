# R19: 60 Hz quality gate from the absolute hum (written 2026-11-25, BEFORE the S7 recordings T00_d1_S / T00_d2_S)

Report 35.106. Follows R18 (35.105, failed: a ratio flags almost every Rest window, and its truth counted the harmless
~5 uV hum on ch1 during gestures). Everything below was set on the 11/23 days (T00_d1_G, T00_d2_G) and is judged
ONLY on next week's S7 days.

## Detector (`src/hum_abs.py`, MCU-computable from features.c's PSD, no new FFT)
Per channel ch1-4 and 200 ms window: H_ch = RMS of the 60 Hz fundamental in uV = sqrt(max(P(52-68 Hz) - floor, 0) /
(NFFT x sum w^2)), floor = mean bin power of 32-46 and 74-88 Hz x the number of 52-68 Hz bins. Calibrated on
synthetic signals (35.106: 10 uV -> 10.0, 3 uV -> 2.98) and against the 2 s coherent fit on cued Rest (ratio 0.91-1.01).
- T = 7.07 uV (geometric mean of the 11/23 cued-Rest medians, 14.30 and 3.50 uV).
- RHO = 0.5.

## Rule A: calibration alert (the MCU keeps every cued window and reports)
Alert for a session if >= 50 % of its cued Rest windows have max_ch H_ch > T.
Truth A per session: median over its cued Rest windows of max_ch h_ch, where h_ch = the 2 s coherent least-squares
fit of the 59.98 Hz fundamental (not computable on the MCU): >= T -> must alert; <= T / 2 -> must not alert;
in between -> not judged.
**A passes** if every judged session of T00_d1_S, T00_d2_S is right (at least one must be judged; none judged ->
undecided).

## Rule B: label gate (label updates skip flagged windows)
Flag a window if, on any channel, H_ch > T AND H_ch > RHO x RMS_ch (RMS_ch = the band-passed window RMS).
Truth B per window with h_ch as above: HARMFUL if any channel has h_ch > 1.5 T and h_ch > 1.5 RHO x RMS_ch; CLEAN if
every channel has h_ch < T / 2 or h_ch < RHO / 2 x RMS_ch; else not scored (a grey zone on BOTH sides of the rule:
a window right at the rule's edge cannot be scored fairly; 35.106 development: with no margin on the harmful side
the recall was 81.3 %, with x1.25 89.0 %, with x1.5 93.9 %; x1.5 fixed here, before the S7 days. Averaging H over the
last 3-10 windows did not help: 81-84 %).
**B passes** if, pooled over T00_d1_S and T00_d2_S: false flags <= 5 % of CLEAN windows, and recall >= 90 % of
HARMFUL windows (recall judged only with >= 30 HARMFUL windows; fewer -> recall reported, B decided on false flags).
Reported, not decided: the fraction of task-segment windows flagged; per class among cued windows.

## What follows
- A passes -> the firmware gets the alert: H_ch from the PSD features.c already computes, a status event per
  calibration with the cued-Rest share over T; the panel shows "redo Rest" (default off until then).
- B passes -> label updates (range labels, task labels) skip flagged windows; a run-time setting, default off.
- Fails -> nothing in the firmware; reported as is.
The frozen firmware rtl_task_s7f and the frozen S7 rules (P1 / P2) are not touched either way.
Development numbers on 11/23 (not a decision): results/hum_106/levels_1123.txt, combo_1123.txt, r19_dryrun_1123.txt.
