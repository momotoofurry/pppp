---
name: gesture-redesign-after-selftest
description: "After the self-test (6 gestures, unchanged), switch to 7-class directional control (up/down/left/right/forward/back + rest) for the real Kinova phase"
metadata:
  node_type: memory
  type: project
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-19T08:00:24.268Z
---

Decided 2026-11-16: the self-test runs with the current 6 gestures (Power, Lateral, Tripod, Pointer, Open, Rest; R12 fixed). Afterwards the user wants intuitive Cartesian control of the robot arm: forward / back / left / right / up / down + rest = 7 classes.

**Why:** more intuitive control for the real-robot experiment; it also fills Campbell's own future work (>2 DOF, physical device), but makes the work directly comparable to CIIL.

**How to apply:** when the self-test is done, propose the redesign:
- Proposed mapping (right hand, palm down): up = wrist extension, down = wrist flexion, left = radial deviation, right = ulnar deviation, forward = pointer, back = fist, rest = rest; avoid pronation/supination (shifts the band).
- Changes needed: `LD_CLASSES` / `DC_CLASSES` 6 -> 7, continuous velocity control (hold = move, rest = stop) in decision + kinova_bridge, TaskScreen direction cues, analysis and new pre-registered rules.
- Open question for the user: the gripper (2 more classes = 9, a mode switch, or shared-autonomy auto-grasp).
- Simulate first on a public dataset with wrist movements (check which NinaPro databases include wrist flexion/extension and radial/ulnar deviation); the existing results on grasp gestures do not transfer directly.

**Experiment split (decided 2026-11-16).** The user first considered adding the RViz sim arm to the self-test and then decided against it.
- Experiment 1 = the self-test as planned. It is cued, with no arm, and validates the calibration method / soft labels (accuracy, R12).
- Experiment 2 = goal-directed arm control. It comes after the 7-class redesign, first with the RViz sim (`kinova_bridge.py --ros --task-labels`), then on the real Kinova. Here the user chooses the commands; metrics are completion time, wrong commands and interventions, with cued probe segments interleaved for accuracy.

**Latency is a design priority (user, 2026-11-16).** For arm control the user wants latency as low as possible. Rough estimate: start of motion ~300-450 ms (mostly the 200 ms window plus K = 3 voting); MCU processing is only ~2 ms. Plan for experiment 2:
- confidence-gated start (`decision <tau> <k>`: start at once when confident);
- stop from the amplitude gate on a short window;
- 50 ms step;
- speed proportional to amplitude.
Measure end-to-end latency from the timestamps (emg.csv / mcu.csv / robot.csv). Sweep window / step / K offline on the pilot data for an accuracy-vs-latency curve.

**UPDATE 2026-11-17: the user chose 9 classes, superseding the 7-class plan above.** The order is the class index; rest must be last because the firmware treats LD_CLASSES-1 as rest.
- 0 up = wrist extension
- 1 down = wrist flexion
- 2 left = radial deviation
- 3 right = ulnar deviation
- 4 forward = index point
- 5 back = thumbs-up
- 6 gripper open = hand open
- 7 gripper close = fist
- 8 rest

Gripper uses two gestures, not auto-grasp or a toggle; the user chose this. Day 1 on 2026-11-17 (6 grasps, 4 sensors) was declared a procedure test. The 9-class self-test is cued only at first.

**Implemented 2026-11-17** (report 35.45):
- Firmware `rtl_task_9c` is flashed.
- Bridge `--classes 9`, TaskScreen `--gestures nine`, and the panel gesture set "9 方向" (default) are in place. Files are named `T00_d<day>_G`.
- `src/selftest9_analysis.py` compares S9, S7 (without Point / ThumbUp) and S5 (wrist directions + Rest).
- Pre-registered rule: pick the largest set with pooled probe window accuracy >= 85 %. Claude proposed 85 %; the user confirmed it on 2026-11-17. Do not change it after recording.
- Not recorded yet. Planned 2026-11-19, postponed to Monday 2026-11-23 (day 2 at least one day later, same placement).
- DB2 simulation (report 35.46/35.47): 4 sensors with one pass gives S9 51 %, S7 59 %, S5 64 %; each extra pass adds about 3-6 points.
- 35.49: task soft labels are added to the 9-gesture self-test. Segments: labelled, task, labelled, task, labelled; each task segment has 40 trials (8 arm commands × 5). Soft labels are replayed offline.
  - Rule 2: D(S9) = mean over P1, P2 of (cue_soft − cue); GO if D ≥ +2.
  - Validated with injected drift: S9 +10.6 → GO.
- Public-data evidence, 2026-11-17:
  - Ozdemir 2022 (4 sensors on targeted muscles, 35.52): 7 classes with two cued passes reach 90.7 %.
  - GrabMyo cross-day (35.51): a frozen day-1 model loses about 11 points; accumulation plus soft labels beats daily short calibration by +4 to +8 points on days 8 and 29. Supination and pronation stood in for left and right.
- The user then chose TWO cued passes (35.48).
- 35.53 (committed before the first 9-gesture recording, commit 1af2808):
  - Rule 3 = cross-day accumulation, acc vs cue on later days, S9, GO if mean ≥ +2. Needs two days with the same placement.
  - The analysis also reports live command latency. `src/selftest_quality.py` is the data-quality check to run first.
  - Day-1 6-gesture live control: 25/80 right; median latency 1.17 s. Board firmware is now `rtl_task_9c2` (RTL_LABEL_MAX 810), and the panel counts passes.

**Shared autonomy goes into the thesis, but only after the self-test data (user, 2026-11-17).**
- Role: application layer in experiment 2; the calibration + soft labels stay the main contribution.
- One intent-inference module feeds both the soft-label prior and the assist level alpha.
- Simple linear policy blending with a fixed rule (example: assist above goal probability 0.7, alpha capped at 0.6); auto-grasp keeps 7 classes.
- Conditions: A = cue only, no assist; B = cue + soft, no assist (main comparison); C = cue + soft + assist. Measure accuracy on the cued probes.
- RL for alpha is future work only.
- Do not build it before the data is in. Bring it to the advisor after the self-test; rename the title only once the advisor agrees.
- **Update 2026-11-18 (user: "先做"):** a PC / RViz prototype was built before the data, scoped to not touch the board firmware or the recording protocol (report 35.57: src/assist/, src/pc/sim/assist_ros.py). MCU port and the real arm still wait for the self-test and the advisor.
- **Changed 2026-11-18 (reports 35.55 / 35.56):** the intent probability is NOT used as a label prior. If the goal is inferred from EMG alone, labels add nothing. Labels come from goals that are independent of EMG: given by the task, or confirmed after the grasp (hindsight).
- The main thesis contribution is cross-day accumulation on the MCU. Wrist-only S5 plus assist is the application.
- 2026-11-19 (commit 0025b06, reports 35.64/35.65): Gazebo check passes 5/5 with a simulated grasp (gz_attach.py; real grip needs the real arm); tool orientation fixed so the 2F-85 fingers close sideways. Hindsight label rule "agree" (position rule AND own-motion rule) gives 0.7-2.7 % label error vs self-training e, on ~70 % of windows (simulation only). 35.66 (commit 71c0fe8): per-window hindsight labels in GrabMyo G5 accumulation give +5.2 vs acc (42/43), near perfect labels +5.5; most of the gain is from labelling every window and the rest windows (same windows as 35.55: +1.3). Literature-based improvements: items 1-3 implemented in 35.67 (commit 9f1e760): modes.py rule 'mix' (default; 'lead' = old), assist exit on mismatching input, RViz mode colours + bell. Still open: proportional speed, adjustable assist + agency questionnaire.
- Proportional speed: user chose to do it AFTER the two self-test days (2026-11-19), together with the board changes: board sends a normalised amplitude per window (rest = 0, cued gesture = 1), PC speed = V_MAX x amplitude (clamped), same amplitude for the fast-stop gate; add a short light / medium / strong force test to experiment 2.
- 35.70/35.71 (commit 56a25dd): label rule agree2_t6 (position AND decoded command agree, no label 6 steps before a command change, 3-D undo check) is in the assist system as src/assist/labeler.py (assist_ros --labels); labels recorded only, sending to the board waits for after Monday. Sim: error 0.1-2.9 %, 57-73 % windows; GrabMyo +5.0 to +5.3.
- 35.69 (commit db27485, latency): planned AFTER the Monday recording (not done yet): features.h FE_WIN 400->200, FE_STEP 200->100; decision.c k 3->4, margin 0->1, Rest k_rest = 2 (Ozdemir S5: start 452->351 ms, stop 423->161 ms); PC loop 50 ms. Already done: assist_ros --seg 1.0 --vel 1 defaults (Gazebo stop ~204->50 ms).

Related: [[thesis-direction-edge-ai-robotics]], [[robot-application-plan]], [[user-wants-to-help-people]].
