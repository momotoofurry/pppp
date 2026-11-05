"""Nested re-test of "6 channels are as good as 8" (report 27.2).

The earlier backward elimination (channel_sweep.py --greedy -> results/channel_greedy*.csv) chose the channels on
the mean of all 20 subjects and then reported the chosen 6-channel set (ch123567: 81.53 vs 81.85 %, p = 0.99) on
the same 20 subjects, so the choice and the test share data (selection bias, as in Calikusu 2026's warning).
Here the choice is made without the subjects it is tested on, with the same 2-fold design and the same code:
  - every subject's accuracy comes from channel_sweep.job (pre-training on the other fold, then the recommended MCU
    setting: 100 trees, depth 10, int16, 375-row buffer, t-SNE 500 + K-Means), seeds 0, 1, 2
  - outer fold A (test subjects 0-9): drop 2 channels by backward elimination scored ONLY on fold B's subjects
    (10-19); then report the chosen set on subjects 0-9. Outer fold B the other way round.
  - result: per subject (seed mean) chosen 6-ch minus all8 on the 20 outer subjects: mean, 95 % t CI, 95 % paired
    bootstrap CI (10,000 resamples of subjects), Wilcoxon p, better / worse.
Writes results/channel_nested.csv (per row), channel_nested_steps.csv, channel_nested_summary.csv.
Usage (in the container): python src/channel_nested.py [--jobs 20]
"""
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel_sweep as CH  # noqa: E402
import pipeline as P  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
SEEDS = [0, 1, 2]
TEST = {'A': set(range(10)), 'B': set(range(10, 20))}


def subj_acc(df, name):
    g = df[df.set == name]
    return g.groupby(['subject', 'seed']).acc_selfcal.mean().groupby(level='subject').mean() * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()
    cache = {}

    def need(sets):
        new = [ch for ch in sets if CH.set_name(ch) not in cache]
        if new:
            df = CH.run_sets(new, SEEDS, args.jobs)
            for ch in new:
                cache[CH.set_name(ch)] = df[df.set == CH.set_name(ch)]
            print(f'ran {len(new)} sets, {time.time() - t0:.0f} s', flush=True)

    full = list(range(8))
    need([full])
    steps, chosen = [], {}
    for outer, inner in (('A', 'B'), ('B', 'A')):
        current = full
        while len(current) > 6:
            cands = [[c for c in current if c != d] for d in current]
            need(cands)
            score = {CH.set_name(ch): subj_acc(cache[CH.set_name(ch)], CH.set_name(ch)).loc[sorted(TEST[inner])].mean()
                     for ch in cands}
            best = max(cands, key=lambda ch: score[CH.set_name(ch)])
            for d, ch in zip(current, cands):
                steps.append(dict(outer=outer, scored_on=inner, n_channels=len(ch), removed=d + 1, set=CH.set_name(ch),
                                  acc_inner=score[CH.set_name(ch)], chosen=ch == best))
            current = best
        chosen[outer] = CH.set_name(current)
    df = pd.concat(cache.values(), ignore_index=True)
    df.to_csv(os.path.join(OUT, 'channel_nested.csv'), index=False, float_format='%.4f')
    pd.DataFrame(steps).to_csv(os.path.join(OUT, 'channel_nested_steps.csv'), index=False, float_format='%.4g')

    ref = subj_acc(df, 'all8')
    d, six = [], []
    for outer, name in chosen.items():
        a = subj_acc(df, name).loc[sorted(TEST[outer])]
        six.append(a)
        d.append(a - ref.loc[sorted(TEST[outer])])
    d, six = pd.concat(d).sort_index(), pd.concat(six).sort_index()
    n, m = len(d), d.mean()
    h = stats.t.ppf(0.975, n - 1) * d.std(ddof=1) / np.sqrt(n)
    rng = np.random.default_rng(0)
    boot = np.array([d.values[rng.integers(0, n, n)].mean() for _ in range(10000)])
    # in-sample number for comparison: the old greedy choice ch123567 on all 20 subjects (this run's rows)
    old = 'ch123567'
    old_d = subj_acc(df, old) - ref if old in cache else None
    sm = pd.DataFrame([dict(
        chosen_A=chosen['A'], chosen_B=chosen['B'], acc_all8=ref.mean(), acc_6ch_nested=six.mean(), diff=m,
        t_ci_lo=m - h, t_ci_hi=m + h, boot_ci_lo=np.percentile(boot, 2.5), boot_ci_hi=np.percentile(boot, 97.5),
        wilcoxon_p=stats.wilcoxon(d).pvalue if np.any(d != 0) else 1.0, better=int((d > 0).sum()), worse=int((d < 0).sum()),
        worst=d.min(), insample_ch123567_diff=old_d.mean() if old_d is not None else np.nan,
        seconds=time.time() - t0)])
    sm.to_csv(os.path.join(OUT, 'channel_nested_summary.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(pd.DataFrame(steps).round(2).to_string(index=False))
    print(sm.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
