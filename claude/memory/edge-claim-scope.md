---
name: edge-claim-scope
description: "Thesis \"on the MCU\" claim = intent decoding + calibration learning only; EMG reaches the board via the PC (user confirmed 2026-11-19)"
metadata:
  node_type: memory
  type: project
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-19T09:33:12.027Z
---

User confirmed 2026-11-19 that Avanti EMG goes sensors -> Delsys base -> PC -> board; the PC relays it to the STM32.

The thesis claim is scoped as "intent decoding (features, classification, voting) and calibration learning (OAS LDA sums, cross-day accumulation, label updates) run on the MCU; the model never leaves the board". It is not "the whole system on the MCU": arm control, IK, scene and assist blending stay on the PC.

**Why:** the user asked whether keeping assist logic on the PC breaks the edge claim; agreed it does not, as long as the PC never classifies, never retrains and pushes weights back, and never receives EMG/features for learning. Labels from the PC (cue or task soft labels) are supervision only.

**How to apply:** in the thesis limitations, state that the PC only relays EMG without processing, and that a product could use an analog front end wired directly to the MCU. Moving the hindsight labeler to the MCU is optional (a plus, not required), decided after both self-test days. Related: [[gesture-redesign-after-selftest]], [[thesis-direction-edge-ai-robotics]].
