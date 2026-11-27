---
name: robot-application-plan
description: "Planned Kinova Gen3 extension (voice + SmolVLA reach + 6-gesture sEMG fine control), decisions and measured facts as of 2026-11-09"
metadata:
  node_type: memory
  type: project
  originSessionId: 4ccc490f-b44f-4e28-8983-bf5c41e9f51f
  modified: 2026-11-13T06:32:19.907Z
---

**Status (decided 2026-11-10): side project / future work only — NOT part of the thesis experiments.** Main line has since moved (2026-11-12/13): LDA + task-provided labels, see [[thesis-direction-edge-ai-robotics]] and PROPOSAL.md on branch `leaf-refresh` (~/model-leaf). The pilot still uses frozen pilot-freeze-5 (RF, discrete commands, taught poses). VLA must never enter the subject experiment flow unreported; at most a "future work" paragraph or a separate post-experiment demo. Don't push this as main work.

Original plan (discussed 2026-11-09):
- Kinova Gen3 7DoF + Robotiq 2F-85 + wrist RealSense. Subject says object name (Vosk, restricted grammar, 3–4 objects + 「停」) → fixed English instruction "move above the {obj}" → SmolVLA moves gripper above object → sEMG fine control.
- Gesture map (proposed, from results/confusion_oneshot_N100_d10_int16.csv): Pointer=下降, Tripod=上升 (both hold-to-move via per-window PK_PRED), Power=夾, Open=張, Lateral=回原位, Rest=不動. Remapped on PC only; frozen firmware pilot-freeze-5 is not changed. Risk to check: Power→Open 12.6% window-level (drop while holding).
- Fallback executor: classical grasp (RealSense depth + AprilTag/YOLO + MoveIt 2).
- Measured on RTX 3060 Laptop 6 GB (fake data, Docker image `smolvla-test`, lerobot 0.7.0): SmolVLA inference peak 1202 MiB, 529–830 ms per 50-step chunk; expert-only fine-tune batch 8 peak 3739 MiB. pi0/pi0.5/SLA do not fit.
- Compute/network: user will run everything on own laptop (TCU is Windows-only → Windows + WSL2). Plan: WSL2 `networkingMode=mirrored` (user edits .wslconfig themself); Linux VM is fallback (no CUDA in VM). WSL already has ROS 2 Humble + ros-humble-kortex-* + gen3 moveit config (src/pc/sim/gen3_sim.sh, fake hardware); kinova_vision not installed. LeRobot needs Python ≥3.12 → keep SmolVLA in Docker, talk to ROS over socket.
- Daily paper-search routine was updated with this extension (topics 9–10).
- Done (WSL repo, not pushed): f7f07f9 command-level replay of the map (report.md §34; hold-to-move only ~35% of held windows move, false open 2.4% in Power trials); d6b4411 task manager FSM `src/pc/task_manager/` (pure logic, check passes).
- Pending, user chose to wait for weekly quota reset (2026-11-12 14:00): Vosk test (download model + user speaks), SmolVLA demo-data recorder (needs Gen3 camera in lab), wiring FSM to PK_PRED / Vosk / Gen3.

**Why:** user wants an assistive-robot demo built on the existing self-calibrating RF sEMG work without touching frozen firmware.
**How to apply:** treat as proposal, not approved protocol; any firmware change needs a new tag and must wait until after T00/pilot/formal experiments. Related: [[thesis-writing-rules]], [[docker-call-no-login-shell]].
