---
name: board-firmware-s7b
description: "Board runs rtl_task_s7b since 2026-11-24 (S7 mask, gate mode 2, k5, stop k2); panel defaults to S7 (_S files); backups and restore path"
metadata:
  node_type: memory
  type: project
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-24T10:16:28.292Z
---

On 2026-11-24 the NUCLEO-H753ZI was flashed with `D:\stm32\blink_leaf\build\rtl_task_s7b`. It replaced `rtl_task_9c2`.
- **What it adds:** a class mask (RTL_SET_CLASSES 14), gate mode 2 (0.5 × the median gesture activity), and k_rest (stop after 2 windows).
- **How it is switched on:** TrignoBridge `--preset s7` sends `classes 0x1CF`, `gate 50 2` and `reject 0 0 5 2`.
- **Verification:** on the same bytes, the board matched the PC build exactly (1,511 windows, 21 commands). Model sector 7 md5 stayed `68893f3b`.
- **Backups:** `backup\board_bank1_rtl_task_9c2_2026-11-24.bin` and `board_sector_2026-11-24.bin`. Old sources are in `backup\emg_rtl_task_before_s7_2026-11-24`. Old exes and the old SOP are in `lab_kit_selftest\_舊版_2026-11-24_S7之前\`.
- **Panel:** now defaults to the S7 set. Files are named `T00_d<n>_S`, and day numbering restarts at 1.
- **Analysis of S7 days:** `selftest9_analysis.py --sets S7` and `check_rt_s7.py --days ..._S`.

**Why:** report 35.76–35.80. Point and ThumbUp dragged Rest down. The activity gate removed rest drift in the EMG-driven arm sim, and stop k2 made stopping faster.

**How to apply:**
- Next self-test recordings use the S7 set, with donnings at least 1 day apart.
- With the old 9-gesture set, the board still behaves like 9c2 unless the preset is sent.
- Arm runs: TrignoBridge --preset s7 --fwd-pred 1 and `report 3`; assist_ros.py board stops 0.5 s without heartbeat, guards a workspace box, sends direction-only range labels by default (35.85).
- Committed as f0b4ce0, 4d215fc, then 37ac42a (35.85 safety fixes) (s7e: stop events = report bit 1, RTL_LABEL_RANGE ring 256 + queue; assist_ros board mode, udp_tcp_relay); not pushed.
- Flash backups of each step: backupoard_bank1_rtl_task_{9c2,s7b,s7c,s7d}_2026-11-24{,b,c,d}.bin and board_sector_2026-11-24{,b,c,d}.bin; sector 7 md5 68893f3b throughout.

Related: [[selftest-day1-2026-11-23]], [[real-robot-validation-must-have]].
