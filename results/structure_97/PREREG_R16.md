# R16: front-end changes derived from the structure of the self-test data (written 2026-11-25, BEFORE any accuracy was computed)

Report 35.97. Data: T00_d1_G, T00_d2_G (11/23, two donnings), gesture set S7. Only structure diagnostics were run so far
(diag1-4: no classifier, no accuracy).

## What the diagnostics showed (no accuracies)
1. ch5-8 are exact copies of ch1-4 (max |diff| 0): 40 of the 80 features are duplicates, the pooled covariance is singular.
2. Amplitude features (RMS, MAV, WL) are right-skewed within a class (median |skew| 0.56-0.67); log halves it (0.31-0.40).
   Within-class spread of log RMS is mostly one direction (top PC 58-94 %), i.e. effort (multiplicative).
3. Mains hum (59.98 Hz and harmonics) is intermittent: whole-recording median 0.5-5 uV, p90 4-13 uV per channel.
   During day 1's cued Rest it was 10-17 uV against 2-3 uV of other signal (ch2-4): day 1's Rest was louder than several
   gestures, and every Rest window had its PSD peak at 60 Hz. Day 2's Rest hum was 2-4 uV. So the Rest class (and the
   day-to-day shift) is partly a model of the hum, which a 200 ms window cannot tell from EMG.

## Derivations
- N (notch): hum is phase-coherent at a fixed frequency, EMG is not. A narrow notch (2 Hz wide at k x 59.98 Hz, k = 1..8,
  causal IIR, scipy iirnotch Q = f/2) removes the hum and only ~16 Hz of the 10-500 Hz EMG band (~3 %).
- U (unique): drop ch5-8 (exact duplicates): the same information, a non-singular covariance, 40 instead of 80 features
  (running sums 80x80 -> 40x40: 27.5 KB -> about 7 KB).
- L (log): log of RMS, WL, MAV (per channel) before the session z-score: effort becomes additive, the class shape closer
  to Gaussian, which is what LDA assumes.

## Conditions (all else = the board's model as in selftest9_analysis.Model: session z-score, Q5.10, OAS LDA, equal priors)
B0 (current), N, U, L, N+U, N+U+L. Features of every condition come from the same C feature code (fe_recording).

## Metrics
- Primary, A: rule 1's metric for S7 = cue-model window accuracy over all probe windows (P0-P2), per day.
- Secondary: cross-day fixed (day-X model with day-X z-score on day-Y probes, both directions); per-class recall of Rest;
  offline command accuracy of the task trials (decide(), K_DC 3).

## Decision (per condition vs B0)
A condition is a CANDIDATE for the next firmware if mean dA >= +2 points over the two days AND dA > 0 on both days.
Otherwise it is not adopted. n = 1 person, 2 days: a candidate is CONFIRMED only if the same holds on next week's S7
recording (T00_d1_S, T00_d2_S), analysed offline with this exact code; the frozen board firmware (rtl_task_s7f) and the
frozen P1/P2 rules for next week are NOT changed either way.
