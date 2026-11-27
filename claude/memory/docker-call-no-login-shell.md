---
name: docker-call-no-login-shell
description: "Run rf-emg Docker via `wsl -d Ubuntu-22.04 -- docker run -v /home/momo1234/model:/work`, not inside `bash -lc`"
metadata:
  node_type: memory
  type: reference
  originSessionId: c782b928-dcd9-4756-880c-3c824dcf5be9
  modified: 2026-11-05T13:22:20.658Z
---

Calling `docker run -v "$PWD":/work` from `wsl.exe -- bash -lc 'cd ~/model && ...'` mounted a stale copy of the repo (files from Oct 17), so new scripts were "not found". Plain `wsl -d Ubuntu-22.04 -- docker run --rm --user 1000:1000 -e HOME=/tmp --shm-size=2g -v /home/momo1234/model:/work -w /work rf-emg ...` (or `bash -c`, non-login) mounts the real repo. Kyranou data: `-v /mnt/d/kyranou:/data:ro`.
