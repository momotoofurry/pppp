"""Run one of the upstream self-calibrating-rf scripts with a fixed random seed.

The upstream scripts set no seed (RandomForestClassifier, TSNE and the tree
replacement permutation all draw from numpy's global RNG), so each run gives a
slightly different result. Seeding the global RNG before executing the script
makes a run reproducible without editing the upstream code.

Accuracy files the replay scripts save under <repo>/results/ are redirected to
results/upstream/seed<N>/, so several seeds can run in parallel.

Usage (from the project root):
    .venv/Scripts/python -u src/run_upstream.py demo_feature_extract.py
    .venv/Scripts/python -u src/run_upstream.py demo_replay.py --seed 0
    .venv/Scripts/python -u src/run_upstream.py main_replay_arm_position.py --seed 0
"""
import argparse
import os
import runpy
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.join(ROOT, 'external', 'self-calibrating-rf')
RESULTS = os.path.join(ROOT, 'results', 'upstream')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('script')
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()

    out_dir = os.path.join(RESULTS, f'seed{args.seed}')
    np_save = np.save

    def save(file, arr, *a, **kw):
        parts = os.path.normpath(str(file)).split(os.sep)
        if 'results' in parts:
            os.makedirs(out_dir, exist_ok=True)
            file = os.path.join(out_dir, parts[-1])
        return np_save(file, arr, *a, **kw)

    np.save = save
    np.random.seed(args.seed)
    os.chdir(REPO)  # upstream scripts use paths relative to the repo root
    sys.path.insert(0, REPO)
    t0 = time.time()
    runpy.run_path(args.script, run_name='__main__')
    print(f'[run_upstream] {args.script} seed={args.seed} took {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
