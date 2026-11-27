---
name: t00-self-run-plan
description: "T00 self-run scheduled 2026-11-18/19; CNN, VLM, DB6 and PC-free ideas deferred until after it"
metadata:
  node_type: memory
  type: project
  originSessionId: c782b928-dcd9-4756-880c-3c824dcf5be9
  modified: 2026-11-07T17:25:55.525Z
---

The user will run T00 (own data, per the T00 SOP) on 2026-11-18 (Wed) and 2026-11-19 (Thu), 24 ± 4 h apart. On the same lab visit they will photograph the Trigno base station (model label, 68-pin analog-output connectors) and, if time allows, the Kinova wrist-camera view.

Decided 2026-11-08: all extra ideas wait until T00 data is back. These are the CNN + AdaBN / last-layer pseudo-label baseline, the wrist camera + VLM, the Ninapro DB6 second dataset (only next-day matters; low priority) and the PC-free demo (Trigno analog out to the MCU, MCU Ethernet to Kinova).

**Why:** the user wants to see their own data first; the main line (TCU check, T00, PROTOCOL v4 with the advisor, IRB) blocks graduation, the extras do not.

**How to apply:** after T00, first check that the data is complete and run the board replay. Only then raise the deferred items, in priority order. A CNN comparison has to be frozen and pre-registered before the first formal subject. Related: [[thesis-writing-rules]].
