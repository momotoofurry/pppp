---
name: slides-keep-latest-builder
description: "In ~/model/slides keep only the newest buildNN.py; delete the previous version's builder when a new deck version is made"
metadata:
  node_type: memory
  type: feedback
  originSessionId: c782b928-dcd9-4756-880c-3c824dcf5be9
  modified: 2026-10-25T13:46:40.473Z
---

When a new deck version (碩論題目討論_MOMO_vNN.pptx) is built, keep only the newest `slides/buildNN.py`; remove the previous builder in the same commit (git rm) and keep the version table in slides/README.md as history (old scripts recoverable via `git log -- slides/`).

**Why:** the user asked twice (2026-10-25) to delete the earlier versions' builders and keep only the latest.

**How to apply:** after building v(N+1), `git rm slides/buildN.py`, update README's run command and note that the previous builder is in git history.
