---
name: s7-recording-pending-analyses
description: "After the S7 recordings (T00_d1_S, T00_d2_S, two different days) run the frozen P1/P2 analysis plus two pre-registered offline tests (R16 log, R19 hum gate)"
metadata:
  node_type: memory
  type: project
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-25T08:48:44.757Z
---

When the S7 self-test is recorded (planned the week after 2026-11-25, two different days, slots 16:11:15:5), run:
1. the frozen decision: selftest_quality.py, selftest_s7_prereg.py (P1 >= 80 %, P2 <= 2/min), selftest9_analysis.py --sets S7;
2. R16 confirmation of the log front end (report 35.97): `src/structure_r16.py --days T00_d1_S T00_d2_S` (both days > 0, mean >= +2);
3. R19 60 Hz gate (report 35.106, results/hum_106/PREREG_R19.md): `src/hum_gate_r19.py --dir /sd/T00 --days T00_d1_S T00_d2_S --out results/hum_106` (no --dev);
4. R20 4x4 Riemannian tangent space (report 35.110, results/riemann_110/PREREG_R20.md): `src/riemann_r20.py --dir /sd/T00 --days T00_d1_S T00_d2_S --out results/riemann_110` (no --dev).

**Why:** both R16 and R19 were pre-registered on the 11/23 data and may only be judged on new recordings.

**How to apply:** firmware changes (log features, hum alert / label gate, double buffer 35.103, seqlock 35.104) go into the next firmware only after these; the board stays rtl_task_s7f until then. Related: [[board-firmware-s7b]], [[selftest-day1-2026-11-23]].
