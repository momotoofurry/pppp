---
name: selftest-day1-2026-11-23
description: Day 1 (9 gestures) recorded 2026-11-23 on 3rd try; slots now 16:11:15:5; TCU NOT MASTER after probe; attempts 1-3 kept aside
metadata:
  node_type: memory
  type: project
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-23T09:49:20.387Z
---

Self-test day 1 (`T00_d1_G`) was recorded on 2026-11-23, 17:33–17:48, on the third try. That recording is the one kept as day 1.

- **Slot mapping changed from 11/17:** EDC→16, FDS→11, FCR→15, FCU→5, so the slots string is `16:11:15:5:16:11:15:5` (it was `16:15:11:5`). Day 2 must use the same string.
- **The three tries:**
  - Try 1: 60 Hz noise on the laptop charger, task 22/80.
  - Try 2: gestures too light and ch4 noisy, task 44/80.
  - Try 3 (kept): task 57/80, 119 false triggers at rest, no clipping. Point and ThumbUp are near the rest level, and ch3 (FCR) is weak.
- **Where the files are:** tries 1–2 are kept in `lab_kit_selftest\_T00_d1_G_第N次_*` and `D:\selftest_data\T00\T00_d1_G_第N次_*`. The empty try (no data, NOT MASTER) is `_T00_d1_G_第3次_沒錄到_NOT_MASTER`.
- **TCU pitfall:** after `probe`, or after a run that ends with a read timeout, Trigno Control Utility keeps the old connection as master, and the next run gets `START -> CONNECTION NOT MASTER` with 0 EMG. Fix: fully restart TCU, then skip probe and go straight to 開始錄製.
- **Panel pitfall:** when the panel restarts, the slots box is cleared. Fill it in before every run.
- **Python on Windows:** run the analysis with `C:\Users\kirit\AppData\Local\Programs\Python\Python310\python.exe`, which has numpy and pandas. WSL python lacks pandas, and docker is not inside the Ubuntu-22.04 distro. The script path is `\\wsl.localhost\Ubuntu-22.04\home\momo1234\model-leaf\src\...`.

**Why:** day 2 has to match day 1's placement and settings for criterion 3 to hold.

**How to apply:** before day 2, reuse the slots string above, run on battery, and use the same effort as try 3. If the panel shows NOT MASTER, restart TCU.

Related: [[selftest-4-sensors]].

**Donning 2 (`T00_d2_G`)** was recorded the same evening, 2026-11-23 17:52–18:07. The user removed the sensors and re-stuck them inside pen-drawn outlines on the arm, so it counts as a re-donning on the same day (no overnight gap, and possibly fatigue from the first session).
- Two-run means: S9 70.9 %, S7 82.6 %, S5 80.3 %.
- Rule 1: no set reaches 85 %, so S7 is best and placement/gestures should be revised. Rule 2 GO (S9 D̄ +2.31). Rule 3 NO-GO (D3 +1.73).
- Output: scratchpad `s9_d12.txt`.
