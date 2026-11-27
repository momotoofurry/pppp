---
name: patch-scripts-keep-eol
description: Edit WSL repo files via Python patch scripts that keep CRLF/LF as found; PowerShell eats $vars in wsl -c strings
metadata:
  node_type: memory
  type: feedback
  originSessionId: 940361ee-1e88-4b6f-b364-4f25c47f2d6e
  modified: 2026-11-24T14:54:45.546Z
---

Files in the WSL repo (`~/model-leaf`) can't be edited with the Edit tool (the WSL-share hook blocks it). Instead, edit them with Python patch scripts in the scratchpad, run through `wsl -- python3 ...`. Each exact replacement must assert one match.

- **Keep the line endings.** Read with `newline=''`, detect `\r\n`, edit in `\n`, and convert back before writing.
  - Some files are CRLF: `src/assist/modes.py`, `assist.py`, `src/pc/ExperimentPanel.cs`.
  - On 2026-11-24 a patch rewrote modes.py/assist.py as LF. The diff showed every line as changed, and a follow-up commit (df41fe7) was needed.
- **Don't build bash commands inside PowerShell strings.** PowerShell expands `$f`, `$S`, `$t` and also `\$`, and `$b` overwrites `$B` (variables are case-insensitive). Write a .sh file in the scratchpad and run `wsl -- bash file.sh`.
- **Watch long-running processes.**
  - Background PowerShell jobs stop at 10 min. For long Docker runs, use `docker run -d`, then `docker wait`.
  - `Start-Process -ArgumentList` can turn a leading `\\wsl.localhost` into `\wsl...`. Copy the script to a plain path instead.

**Why:** these cost several retries and one noisy commit in the S7 work.

**How to apply:** use this for any patch to model-leaf files or any mixed PowerShell/WSL command. Related: [[docker-call-no-login-shell]].
