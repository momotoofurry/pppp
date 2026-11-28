# R20: 4x4 Riemannian Tangent Space features (written 2026-11-28, BEFORE the S7 recordings T00_d1_S / T00_d2_S)

Report 35.110. Developed on the 11/23 recordings (`T00_d1_G`, `T00_d2_G`) and validated on the public multi-day dataset GrabMyo (43 participants, Days 1 / 8 / 29, G7 = 7 classes, 4 channels; `results/riemann_110/grabmyo_43subj.txt`). Judged ONLY on next week's S7 recordings (`T00_d1_S`, `T00_d2_S`, two different days).

## Feature definition (`src/riemann_r20.py`, MCU-computable in 4x4 float32)
Per 200 ms filtered 4-channel window $X \in \mathbb{R}^{4 \times 400}$ (zero-mean per channel):
- Sample covariance: $C_i = \frac{1}{400} X_i X_i^\top + (10^{-6}\operatorname{tr}(C_i) + 10^{-15}) I_4$.
- Session reference $\bar{R}_{\text{RA}}$: AIRM Riemannian geometric mean of $C_i$ over the session's active cued windows (computed once at `RTL_FIT`).
- 10-D tangent space vector `TS-10D (RA)`: upper triangle of $\log(\bar{R}_{\text{RA}}^{-1/2} C_i \bar{R}_{\text{RA}}^{-1/2})$, off-diagonals scaled by $\sqrt{2}$.
- `Log40D+TS10 (RA)`: concatenation of `Log-40D` (R16: log RMS / WL / MAV) and `TS-10D (RA)` (50 features total), session z-scored and classified by OAS shrinkage LDA.

## Criteria (fixed before `T00_d1_S` / `T00_d2_S`)
- **R20-A (Primary, `Log40D+TS10` vs `Base-40D`)**: **PASS** if on S7 probe windows (P0–P2):
  1. same-day `cue` accuracy improves on **both days** (`d1 > 0` and `d2 > 0`);
  2. mean `cue` gain over the two days is **>= +2.0 percentage points**;
  3. cross-day accumulation `acc` (`d1+d2 -> d2`) does not degrade (`diff >= 0`).
- **R20-B (Incremental over R16, `Log40D+TS10` vs `Log-40D`)**: **PASS** if:
  1. same-day `cue` accuracy improves over `Log-40D` on **both days** (`d1 > 0` and `d2 > 0`);
  2. mean `cue` gain over `Log-40D` is **>= +1.0 percentage point**.
- **Reported, not decided**: `TS-10D (RA)` alone (10-D ultra-lightweight model), `40D+TS10 (RA)`, and zero-shot `d1 -> d2`.

## What follows
- **R20-A PASS and R20-B PASS**: next 4-channel firmware adopts `Log40D+TS10` (50-D, 4x4 Jacobi eigendecomposition in C, bit-exact PC check).
- **R20-A PASS and R20-B FAIL**: keep the simpler R16 `Log-40D` (if R16 passed).
- **R20-A FAIL**: do not add tangent space to firmware; report honestly in `report.md`.
- The frozen board firmware `rtl_task_s7f` and frozen S7 rules (P1 / P2) are untouched either way.
