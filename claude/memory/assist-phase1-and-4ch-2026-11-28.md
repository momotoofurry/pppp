---
name: assist-phase1-and-4ch-2026-11-28
description: "2026-11-28: native 4ch (40-dim) firmware preset s7_4ch (AXI RAM 191.2 KB), features.c NaN guard, manual mode-switch baseline, grip_cmds no auto-relax, 50 Hz smoother, SVD adaptive IK, /assist_world/objects topic"
metadata:
  node_type: memory
  type: project
  modified: 2026-11-28T01:20:00+08:00
---

Work completed on branch `leaf-refresh` (board remains frozen at `rtl_task_s7f`; NOT flashed, NOT pushed):

1. **Native 4-channel (40-dim) firmware support** (`src/c/features.h`, `ldacal.h`, `protocol.h`, `rt_lda.c`, `firmware/build_fw.sh`):
   - Compile-time `-DFE_CH=4 -DLD_DIM=40` (`preset s7_4ch`); `PK_CH` stays 8 so TrignoBridge and existing 8-col recordings work unchanged.
   - STM32H753 build (`arm-none-eabi-gcc 14.3.1`, `-Os`): AXI RAM drops from 391,868 B (382.68 KB, 74.74 %) to **195,740 B (191.15 KB, 37.33 %)**; Flash 26,424 B (25.80 KB, includes NaN guard).
   - `features.c` adds `isfinite()` guard for detached/flat sensor channels (all-zero windows -> finite 0.0; 100.00 % bit-exact on `T00_d1_G` / `T00_d2_G`).
   - Pending: run `closed_loop_fw.py` regression once Docker Desktop WSL integration is active.

2. **Assistive arm system upgrades (Phase 1)** (`src/assist/`, `src/pc/sim/assist_ros.py`):
   - **Manual mode-switch baseline** (`manual.py`, `manual_compare.py`, `assist_ros.py --control manual`): 200 paired trials on `crowded` show `ModeAssist` has **0.0 %** collision trials vs **36.0–54.5 %** for `Manual` (at S7 error `e = 0.174`: 100.0 % vs 95.5 % success, 40.2 s vs 44.5 s, 0.0 % vs 50.5 % collisions).
   - **Agreed default assist config**: `--scene crowded12` (12 cm spacing), `--lock-rule intent`, `--level 0.0` (no mode-1 steering fight), `--grip gripper` (`grip_cmds=True` now disables 1 s auto-grasp/put-down on relax; `c`/`o` keys added for keyboard testing), `--grip-open-pos 0.25` (partial open), `--grip-check`.
   - **Real-arm smoothness & safety**: `kin.py` upgraded to SVD selective adaptive damping + smooth null-space attenuation (`min_sv()`); `smoother.py` + `assist_ros.py --ctrl-hz 50 --acc-max 0.25 --stop-dec 0.60` for smooth 50 Hz trajectory sub-stepping; `--effort-limit` joint-torque contact-stop; `/assist_world/objects` (`PoseArray`) topic for future AprilTag integration.
