---
name: real-robot-validation-must-have
description: "User wants physical Kinova validation as a must-have, not a bonus (2026-11-19); self-only engineering validation first, multi-participant study needs IRB"
metadata:
  node_type: memory
  type: project
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-20T13:45:13.336Z
---

On 2026-11-19 the user said physical validation on the real robot is an essential skill they want to show. The real Kinova Gen3 closed-loop experiment moves from bonus to **must-have**.

Split agreed in conversation:
- **Must-have:** the user alone on the real arm (engineering validation) runs the full closed loop: MCU decoding, real task-confirmed labels, end-to-end and stop latency on the real arm, cross-day accumulation using real-task labels, and the two-mode assist.
- **Bonus:** a multi-participant user study (task time, agency, NASA-TLX). It needs IRB and advisor approval first.
- Robot-focused research direction under discussion: confidence-aware assist (the MCU sends the LDA posterior, the PC sets the blend). Not decided; the title still waits for the advisor.

**Topic confirmed 2026-11-20:** the user considered switching to "PC vision (RGB-D / 6D pose) + sEMG + ROS 2 shared autonomy" and decided to keep the current topic. Vision is only a bonus: AprilTag with the Gen3 wrist vision module, processed on the PC, after the real arm works. The must-have scene uses known positions (grid slots chosen at random per trial, plus positions the system tracks after each put-down).

**Why:** the user values hands-on physical system validation as a career skill. See [[career-goal-fab-it]] and [[thesis-direction-edge-ai-robotics]].

**How to apply:**
- Order: both self-test days → board changes → real-arm closed loop.
- Plan safety: speed and workspace limits, e-stop within reach, a second person present.
- Ask the advisor whether a self-experiment on the arm needs IRB.
- Related: [[edge-claim-scope]], [[robot-application-plan]].
