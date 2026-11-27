---
name: kinova-control-on-wsl
description: "Real Kinova sessions run Kortex driver + assist_ros in WSL on the one laptop (user decision 2026-11-25); the \"WSL pauses\" were a kernel clock fault, not pauses"
metadata:
  node_type: memory
  type: project
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-25T12:01:24.183Z
---

User chose WSL (Ubuntu-22.04) over a second native-Linux PC for the real Kinova closed loop (2026-11-25). SOP_Kinova實機.md section 1.5 holds the setup; native two-PC layout kept as 1.6 fallback.

**2026-11-25 correction (report 35.109):** the "WSL pauses every ~30 s" (35.92) were never pauses: 0 real stops on CLOCK_MONOTONIC_RAW. The kernel tick was ~9470 us (nominal 10000), so CLOCK_MONOTONIC ran 5.3 % slow and the time sync stepped the wall clock back every 30 s. Tick kept changing (9467 -> 9479): suspected hv_utils TimeSync vs systemd-timesyncd (wsl.conf systemd=true). FIXED the same evening: user disabled systemd-timesyncd in WSL (manually in a WSL terminal; `wsl -- sudo` cannot prompt) and restarted WSL; tick then 9998-10003, loop_jitter 300 s PASS (rate +0.006 %). Still to check: after laptop sleep/resume. Side effect: wsl --shutdown breaks Docker Desktop's WSL integration (restart it).

**Why:** assist_ros times everything on the monotonic clock, so a bad tick slows the control loop, arm speed and deadman by the same %.

**How to apply:** before any real-arm session run loop_jitter (it now checks the rate and the tick); do not call WSL "pausing" again without checking the raw clock. Related: [[real-robot-validation-must-have]], [[board-firmware-s7b]].
