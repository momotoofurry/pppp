"""Compare reproduced arm-position accuracies with numbers reported in the paper.

Paper: Jiang, Ma, Nazarpour, "Posture-invariant myoelectric control with
self-calibrating random forests", Front. Neurorobot. 2024 (PMC11652494).
Only numbers stated in the text/tables are used (absolute per-position values
are only in Fig. 6 and are not transcribed).

Usage: .venv/Scripts/python src/compare_paper.py   (after make_baseline.py)
Writes results/paper_comparison.csv
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')
POS = ['P2', 'P4', 'P5', 'P6', 'P8']

PAPER = {
    # metric -> value (%); text of Section 3 / Table 1
    'LDA @P5 (mean)': 76.0, 'LDA @P5 (SD)': 9.3,
    'RF @P5 (mean)': 77.6, 'RF @P5 (SD)': 9.6,
    'LDA drop P5->P2': 6.4, 'LDA drop P5->P4': 5.8, 'LDA drop P5->P6': 4.5, 'LDA drop P5->P8': 2.9,
    'one-shot gain over RF @P2': 2.5, 'one-shot gain over RF @P4': 3.5, 'one-shot gain over RF @P5': 4.2,
    'one-shot gain over RF @P6': 2.6, 'one-shot gain over RF @P8': 3.1,
    'self-cal gain over one-shot @P2': 3.3, 'self-cal gain over one-shot @P4': 4.2,
    'self-cal gain over one-shot @P5': 3.7, 'self-cal gain over one-shot @P6': 5.0,
    'self-cal gain over one-shot @P8': 4.1,
    'self-cal, all blocks (mean)': 84.6, 'self-cal, all blocks (SD)': 8.5,
}


def metrics(df):
    """df: rows of one seed (or seed-averaged), columns method/subject/position/accuracy."""
    # per-subject accuracy at each position, then mean/SD over subjects
    ps = df.groupby(['method', 'subject', 'position']).accuracy.mean().unstack('position') * 100
    allb = df.groupby(['method', 'subject']).accuracy.mean() * 100
    m = lambda name: ps.loc[name]
    lda, rf, one, sc = (m('LDA (calib only)'), m('RF (calib only)'),
                        m('fixed: one-shot RF'), m('self-calibrating RF'))
    r = {
        'LDA @P5 (mean)': lda.P5.mean(), 'LDA @P5 (SD)': lda.P5.std(),
        'RF @P5 (mean)': rf.P5.mean(), 'RF @P5 (SD)': rf.P5.std(),
    }
    for p in ['P2', 'P4', 'P6', 'P8']:
        r[f'LDA drop P5->{p}'] = lda.P5.mean() - lda[p].mean()
    for p in POS:
        r[f'one-shot gain over RF @{p}'] = one[p].mean() - rf[p].mean()
    for p in POS:
        r[f'self-cal gain over one-shot @{p}'] = sc[p].mean() - one[p].mean()
    r['self-cal, all blocks (mean)'] = allb.loc['self-calibrating RF'].mean()
    r['self-cal, all blocks (SD)'] = allb.loc['self-calibrating RF'].std()
    return r


def main():
    df = pd.read_csv(os.path.join(OUT, 'baseline.csv'))
    seeds = sorted(df.seed.unique())
    per_seed = pd.DataFrame({s: metrics(df[df.seed == s]) for s in seeds})
    avg = metrics(df.groupby(['method', 'subject', 'block', 'position'], as_index=False).accuracy.mean())
    out = pd.DataFrame({
        'paper': pd.Series(PAPER),
        'ours (seed-avg)': pd.Series(avg),
        'ours min over seeds': per_seed.min(axis=1),
        'ours max over seeds': per_seed.max(axis=1),
    })
    out['diff (ours-paper)'] = out['ours (seed-avg)'] - out['paper']
    out.index.name = 'metric (%)'
    out.to_csv(os.path.join(OUT, 'paper_comparison.csv'), float_format='%.2f')
    print(f'seeds: {seeds}  (SD = across 20 subjects; drops/gains = differences of subject means)')
    print(out.round(2).to_string())


if __name__ == '__main__':
    main()
