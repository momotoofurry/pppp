"""RAM of the full device build (variant 'board', from v2 'board2', -Os: one-shot + self-calibration + features + UART board layer) at
the commits that changed it, read from results/arm_selfcal_size.csv and results/arm_selfcal_modules.csv as committed
there (git show), so the numbers are the linker output of that commit, not recomputed.
RAM = .data + .bss + worst-case stack (as arm_selfcal_size.py); per-module .bss from arm_selfcal_modules.csv.
Writes results/ram_history.csv. Runs on the host (needs git, standard library only): python3 src/ram_history.py
"""
import csv
import io
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = [('e6b1bcd', 'board layer added', 'board'), ('f15cf9e', 'octree 2.5 n cells', 'board'),
         ('5519744', '16-bit P, shared workspace', 'board'), ('61b3544', 'v2: no t-SNE, adapt.c', 'board2')]
GROUPS = {'tsne.c': 'tsne', 'selfcal.c': 'selfcal', 'features.c': 'features', 'oneshot.c': 'oneshot', 'adapt.c': 'adapt'}


def rows(commit, name, variant):
    txt = subprocess.run(['git', '-C', ROOT, 'show', f'{commit}:results/{name}'], check=True, capture_output=True,
                         text=True).stdout
    return [r for r in csv.DictReader(io.StringIO(txt)) if r['variant'] == variant and r['opt'] == '-Os']


out = []
for commit, step, variant in STEPS:
    size = rows(commit, 'arm_selfcal_size.csv', variant)[0]
    total = int(size['data']) + int(size['bss']) + int(size['worst_stack_bytes'])
    part = dict(tsne=0, selfcal=0, features=0, oneshot=0, adapt=0)
    for m in rows(commit, 'arm_selfcal_modules.csv', variant):
        if m['module'] in GROUPS:
            part[GROUPS[m['module']]] += int(m['bss'])
    other = total - sum(part.values())
    out.append(dict(commit=commit, step=step, variant=variant, ram_B=total, ram_KB=round(total / 1024, 2),
                    tsne_KB=round(part['tsne'] / 1024, 2), selfcal_KB=round(part['selfcal'] / 1024, 2),
                    features_KB=round(part['features'] / 1024, 2), oneshot_KB=round(part['oneshot'] / 1024, 2),
                    adapt_KB=round(part['adapt'] / 1024, 2), other_KB=round(other / 1024, 2)))
with open(os.path.join(ROOT, 'results', 'ram_history.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)
for r in out:
    print(r)
