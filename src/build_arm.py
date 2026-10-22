"""Stage 3.4: cross-compile the candidate models for Cortex-M7 (STM32H743) and report sizes.

For every configuration and implementation (our table runtime / emlearn) links
src/c/main.c + startup + linker script into build/<cfg>/arm_<impl>.elf with

  -mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard -Os -ffunction-sections
  -fdata-sections -Wl,--gc-sections --specs=nano.specs --specs=nosys.specs

then records arm-none-eabi-size (text/data/bss) and the worst-case static stack depth from
-fcallgraph-info=su (stack of each function along the deepest call path from Reset_Handler).
Writes results/arm_size.csv.

Usage: .venv/Scripts/python src/build_arm.py [--prefix arm-none-eabi-] [--wsl]
  --wsl runs the toolchain inside WSL (paths are translated with wslpath).
"""
import argparse
import glob
import os
import re
import subprocess
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_c  # noqa: E402

ROOT, BUILD, CSRC = export_c.P.ROOT, export_c.BUILD, export_c.CSRC
OUT = os.path.join(ROOT, 'results')
FLAGS = ['-mcpu=cortex-m7', '-mthumb', '-mfpu=fpv5-d16', '-mfloat-abi=hard', '-Os',
         '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
         '--specs=nano.specs', '--specs=nosys.specs']


def emlearn_dir():
    import emlearn
    return os.path.dirname(emlearn.__file__)


class Tool:
    def __init__(self, prefix, wsl):
        self.prefix, self.wsl = prefix, wsl

    def path(self, p):
        if not self.wsl:
            return p
        return subprocess.run(['wsl', 'wslpath', '-a', p.replace('\\', '/')], capture_output=True,
                              text=True, check=True).stdout.strip()

    def run(self, tool, args, cwd=None):
        cmd = [self.prefix + tool] + args
        if self.wsl:
            cmd = ['wsl', '--cd', self.path(cwd or ROOT), '--'] + cmd
        return subprocess.run(cmd, capture_output=True, text=True, cwd=None if self.wsl else cwd)


def worst_stack(ci_files, root='Reset_Handler'):
    """Deepest static stack path from root (default Reset_Handler) using gcc -fcallgraph-info=su output."""
    stack, edges = {}, {}
    for f in ci_files:
        txt = open(f, encoding='utf8', errors='replace').read()
        for m in re.finditer(r'node: \{ title: "([^"]+)" label: "([^"]*)"', txt):
            name, label = m.group(1), m.group(2)
            s = re.search(r'(\d+) bytes', label)
            stack[name] = max(stack.get(name, 0), int(s.group(1)) if s else 0)
        for m in re.finditer(r'edge: \{ sourcename: "([^"]+)" targetname: "([^"]+)"', txt):
            edges.setdefault(m.group(1), set()).add(m.group(2))

    def depth(n, seen=()):
        if n in seen:
            return 0
        return stack.get(n, 0) + max([depth(c, seen + (n,)) for c in edges.get(n, ())] or [0])

    path, n = [], root
    while n:
        path.append(f'{n}({stack.get(n, 0)})')
        kids = [c for c in edges.get(n, ()) if c not in [p.split('(')[0] for p in path]]
        n = max(kids, key=lambda c: depth(c, tuple(p.split('(')[0] for p in path)), default=None)
    unknown = sorted(c for cs in edges.values() for c in cs if c not in stack)
    return depth(root), ' -> '.join(path), unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prefix', default='arm-none-eabi-')
    ap.add_argument('--wsl', action='store_true')
    args = ap.parse_args()
    T = Tool(args.prefix, args.wsl)
    v = T.run('gcc', ['--version'])
    if v.returncode != 0:
        sys.exit(f'{args.prefix}gcc not found: {v.stderr.strip()}')
    print(v.stdout.splitlines()[0])

    rows = []
    for cfg, c in export_c.CONFIGS.items():
        d = os.path.join(BUILD, cfg)
        for impl in ['table', 'emlearn']:
            obj = os.path.join(d, f'arm_{impl}')
            os.makedirs(obj, exist_ok=True)
            for f in glob.glob(os.path.join(obj, '*')):
                os.remove(f)
            defs = (['-DFEATURES_INT16'] if c['precision'] == 'int16' else []) + \
                   (['-DUSE_EMLEARN', '-I', T.path(emlearn_dir())] if impl == 'emlearn' else [])
            srcs = ['main.c', 'startup_h743.c'] + (['rf_predict.c'] if impl == 'table' else [])
            elf = os.path.join(d, f'arm_{impl}.elf')
            cmd = FLAGS + defs + ['-std=c99', '-Wall', '-fstack-usage', '-fcallgraph-info=su',
                                  '-I', T.path(d), '-I', T.path(CSRC),
                                  '-T', T.path(os.path.join(CSRC, 'stm32h743.ld')),
                                  '-Wl,-Map=' + T.path(elf[:-4] + '.map'),
                                  '-o', T.path(elf)] + [T.path(os.path.join(CSRC, s)) for s in srcs]
            r = T.run('gcc', cmd, cwd=obj)  # .su/.ci files land in cwd
            if r.returncode != 0:
                print(cfg, impl, 'FAILED\n', r.stderr[-3000:])
                rows.append(dict(config=cfg, impl=impl, status='failed', error=r.stderr[-500:]))
                continue
            sz = T.run('size', [T.path(elf)]).stdout.splitlines()[1].split()
            text, data, bss = map(int, sz[:3])
            st, path, unknown = worst_stack(glob.glob(os.path.join(obj, '*.ci')))
            rows.append(dict(config=cfg, impl=impl, status='ok', text=text, data=data, bss=bss,
                             flash_bytes=text + data, flash_KB=(text + data) / 1024,
                             static_ram_bytes=data + bss - 0x1000,  # minus the reserved stack block
                             worst_stack_bytes=st, stack_path=path, stack_unknown=';'.join(unknown)))
            print(rows[-1])
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'arm_size.csv'), index=False, float_format='%.2f')
    print(df.drop(columns=[c for c in ['stack_path', 'error'] if c in df]).to_string(index=False))


if __name__ == '__main__':
    main()
