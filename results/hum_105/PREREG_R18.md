# R18: a 60 Hz quality gate the MCU can run (written 2026-11-25, BEFORE any detector was evaluated)

Report 35.105. Data: T00_d1_G, T00_d2_G (raw EMG, ch1-4).

## Truth (not computable on the MCU, only for judging)
Mains hum is phase-coherent at a fixed frequency, EMG is not. Hum amplitude per channel from a least-squares fit of
sin / cos at k x 59.98 Hz (k = 1..8) over 2 s blocks (20 x 100 ms) of the band-passed signal: EMG leaks into the
16 regressors 10 times less than in one 200 ms window (35.97's per-window fit was inflated on active windows).
Every window takes the hum RMS of the block it starts in. Per window: hum = max over ch1-4.
  HUM window: truth >= 5 uV (the emg-iot alert level);  CLEAN window: truth <= 2 uV;  in between: not scored.

## Detector (MCU: from the PSD features.c already computes per channel, 512-point FFT of the Hamming window)
Peak ratio per channel R = mean power per bin in 52-68 Hz / mean power per bin in 32-46 Hz and 74-88 Hz
(the Hamming main lobe of a 400-sample window is +-10 Hz, so the neighbour bands are outside it; EMG is smooth over
30-90 Hz, hum is a narrow peak). Window flag = max over ch1-4 of R > T.

## Threshold and decision
T is chosen on DAY 1 only: the smallest T with false flags <= 5 % of its CLEAN windows. Then judged on DAY 2:
  PASS if, on day 2, recall >= 90 % of HUM windows and false flags <= 5 % of CLEAN windows.
Reported, not decided: the same on day 1, per class (cued windows), the fraction of each day's task-segment windows
flagged, and the 120 Hz band added (52-68 + 112-128 Hz).
If it passes: the firmware computes R (no change to the 80 features) and, with a threshold set at run time
(default off, so the frozen behaviour is unchanged):
  - label updates (range labels, task labels) skip flagged windows;
  - calibration keeps every window (a class could otherwise lose all of them: day 1's Rest was hummed throughout) and
    reports per class how many cued windows were flagged, so the panel can ask to redo that cue.
