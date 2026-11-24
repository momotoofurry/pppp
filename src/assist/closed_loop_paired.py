"""35.88-35.89: per-session mean of a trial measure, difference vs a base run, paired by session seed
(closed_loop_fw.py draws the prior from its own stream since 35.88, so every condition replays the same trials).
95 % CI: t over the sessions. Time: median of the successful trials per session.
usage: closed_loop_paired.py [base_tag cond_tag ...]   (tags as in closed_loop_fw_trials_<tag>.csv)"""
import sys

import numpy as np
import pandas as pd
from scipy import stats

R = '/work/results/selftest_T00/closed_loop_fw_trials_%s.csv'


def per_session(x, measure):
    if measure == 'time':
        return x[x.ok].groupby('session').time.median()
    return x.groupby('session')[measure].mean()


def main():
    tags = sys.argv[1:] or ['88s_base', '88s_all', '88s_ctx', '88s_place', '88s_uni', '88s_p95', '88s_p50']
    b = pd.read_csv(R % tags[0])
    for measure in ('wrong_locks', 'time'):
        print(f'\n{measure}: per-session value, difference vs {tags[0]}: mean [95 % CI over paired sessions]')
        for c in tags[1:]:
            x = pd.read_csv(R % c)
            out = []
            for (don, h), g in x.groupby(['donning', 'half']):
                gb = b[(b.donning == don) & (b.half == h)]
                d = (per_session(g, measure) - per_session(gb, measure)).dropna()
                t = stats.t.ppf(0.975, len(d) - 1)
                se = d.std(ddof=1) / np.sqrt(len(d))
                out.append(f'{don[4:6]}{"AB"[h]} {d.mean():+.2f} [{d.mean() - t * se:+.2f},{d.mean() + t * se:+.2f}]')
            print(f'{c:22s}', '  '.join(out))


if __name__ == '__main__':
    main()
