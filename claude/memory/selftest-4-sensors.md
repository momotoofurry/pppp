---
name: selftest-4-sensors
description: "Self-test runs with 4 Avanti sensors on target muscles (slots 5:11:15:16 repeated) because the lab's Trigno IM sensors do not stream (2026-11-17)"
metadata:
  node_type: memory
  type: project
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-17T11:52:52.260Z
---

On 2026-11-17 the self-test switched from the 8-sensor ring to 4 sensors on target muscles.

**Hardware facts:**
- The lab has 4 Trigno Avanti (TCU "T14", SDK type O) in TCU slots 5, 11, 15, 16. They work at 2000 Hz.
- It also has 4 Trigno IM (T11, type L) in slots 9, 10, 12, 13. These send all zeros on every port.
- The base is SP-W02 with TCU 3.6.0. Its USB driver had to be installed first.
- The user could not borrow other sensors and declined Myo.

**Setup:**
- Panel slots: `16:15:11:5:16:15:11:5`. The bridge now allows repeated slots, because empty channels make the firmware features NaN.
- Muscles as actually placed: ch1 EDC = slot 16, ch2 FDS = slot 15, ch3 radial (FCR/FPL) = slot 11, ch4 FCU = slot 5.
- Recorded in SOP section 3B and report 35.43 (commit c07b790).

**Why:** this is the only way to record this week without firmware changes.

**How to apply:**
- In the analysis and the deck, label the results as 4-channel target-muscle results, not comparable to the DB6 8-ring simulation. R12 is computed as pre-registered.
- Before the formal experiment, revisit the sensors with the advisor: fix or replace the IM sensors to get 8 working ones.

**Board firmware since 2026-11-17 night:** `rtl_task_9c2` (9 classes, RTL_LABEL_MAX 810, two cued passes). The 6-class build `rtl_task_cal4` is still in `build/`. Ask before switching back.

Related: [[gesture-redesign-after-selftest]], [[advisor-working-style]].
