"""PostToolUse hook (Edit|Write): run the src/**/check_*.py that matches the edited file, in Docker.

Matching, for a file under /home/momo1234/model/src (.py/.c/.h):
  src/.../check_X.py itself          -> that check
  src/.../X.py|X.c|X.h               -> check_X.py or check_X_c.py; else every check_X_*.py
Checks that need arguments (check_bridge.py, check_commands_board.py) are skipped.
Files outside the WSL repo (e.g. the old Windows copy) are ignored.
Exit 0 = nothing to run, passed, or Docker not running (warning only); exit 2 = a check failed
(the last lines of its output go back to Claude). Works on Windows (via wsl) and inside WSL.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

REPO = '/home/momo1234/model'
WIN = os.name == 'nt'
REPO_FS = r'\\wsl.localhost\Ubuntu-22.04\home\momo1234\model' if WIN else REPO
UNC = re.compile(r'^[\\/]{2}wsl(?:\.localhost|\$)[\\/]Ubuntu-22\.04', re.I)
NEEDS_ARGS = {'check_bridge.py', 'check_commands_board.py'}
DOCKER = ['docker', 'run', '--rm', '--user', '1000:1000', '-e', 'HOME=/tmp', '-e', 'PYTHONPATH=src',
          '--shm-size=2g', '-v', f'{REPO}:/work', '-w', '/work', 'rf-emg']
TIMEOUT_S = 840


def repo_rel(path):
    p = UNC.sub('', path).replace('\\', '/')
    return p[len(REPO) + 1:] if p.startswith(REPO + '/') else None


def all_checks():
    out = []
    for d, _, files in os.walk(os.path.join(REPO_FS, 'src')):
        rel = os.path.relpath(d, REPO_FS).replace('\\', '/')
        out += [f'{rel}/{f}' for f in files if f.startswith('check_') and f.endswith('.py')]
    return sorted(out)


def checks_for(rel):
    path = PurePosixPath(rel)
    if path.parts[0] != 'src' or path.suffix not in ('.py', '.c', '.h'):
        return []
    if path.name.startswith('check_') and path.suffix == '.py':
        hits = [rel]
    else:
        checks = all_checks()
        hits = [c for c in checks if PurePosixPath(c).name in (f'check_{path.stem}.py', f'check_{path.stem}_c.py')]
        if not hits:
            hits = [c for c in checks if PurePosixPath(c).name.startswith(f'check_{path.stem}_')]
    return [c for c in hits if PurePosixPath(c).name not in NEEDS_ARGS]


def main():
    data = json.loads(sys.stdin.buffer.read().decode('utf-8-sig') or '{}')
    f = (data.get('tool_input') or {}).get('file_path') or (data.get('tool_response') or {}).get('filePath') or ''
    rel = repo_rel(f)
    checks = checks_for(rel) if rel else []
    if not checks:
        return 0
    failed = []
    for c in checks:
        cmd = (['wsl', '-d', 'Ubuntu-22.04', '--'] if WIN else []) + DOCKER + ['python', c]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                               timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            failed.append(f'{c}: timed out after {TIMEOUT_S} s')
            continue
        out = (r.stdout or '') + (r.stderr or '')
        if r.returncode != 0 and re.search(r'Cannot connect to the Docker daemon|docker.*(not found|could not be found)', out):
            print(json.dumps({'systemMessage': f'hook: Docker is not running, skipped {", ".join(checks)}'}))
            return 0
        if r.returncode != 0:
            tail = '\n'.join(out.strip().splitlines()[-60:])
            failed.append(f'{c} (exit {r.returncode}) after editing {rel}:\n{tail}')
    if failed:
        sys.stderr.write('\n\n'.join(failed) + '\n')
        return 2
    print(json.dumps({'systemMessage': f'hook: {", ".join(checks)} passed'}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
