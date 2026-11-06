"""Power of the two candidate primary endpoints (report 31; for the sample-size talk with the advisor), simulation.

Closed-loop task endpoint (PROTOCOL 2): per subject the true day-2 success probability of F is p_F (0.70; also
0.55 / 0.85), A = p_F + d_i with d_i ~ Normal(delta, tau) (subject-to-subject spread of the true effect), each
condition n_trials Bernoulli trials; per-subject observed difference; paired t-test (two-sided, alpha 0.05) and
the share of runs whose 95% CI excludes 0 with mean > 0. Trial-level mixed models use the same information in this
balanced design, so their power is close to the paired t on proportions (not simulated here).
Replay (algorithm) endpoint: the same recorded day-2 EMG through the F and the A firmware; no trial noise, the
difference varies only between subjects: d_i ~ Normal(delta, tau_replay); paired t.
Spreads from the data (no new choices): tau_replay = 1.63 points = SD of the Kyranou A1 replay difference
(results/external_check_summary_freeze4.csv: diff 1.373, 95% CI 0.012..2.735, n 8 -> SD = half-width / t(7) * sqrt 8);
3.44 = SD on the development data (results/power_calc.csv, base). Effects delta: 1.4 (Kyranou, post hoc), 3, 5, 7.6.
Writes results/power_sim.csv. Usage (in the container): python src/power_sim.py
"""
import os

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RNG = np.random.default_rng(0)
REPS = 4000
TAU_KYR = 1.363 / stats.t.ppf(0.975, 7) * np.sqrt(8)     # 1.373 - 0.012 = 1.361, 2.735 - 1.373 = 1.362
TAU_DEV = 3.435


def power(diffs):
    t = stats.ttest_1samp(diffs, 0.0, axis=1)
    return float(((t.pvalue < 0.05) & (diffs.mean(1) > 0)).mean())


def main():
    rows = []
    for delta in [1.4, 3.0, 5.0, 7.6]:
        for tau_name, tau in [('kyranou', TAU_KYR), ('dev', TAU_DEV)]:
            for n_sub in [8, 12, 16, 20, 30, 40]:
                d_true = RNG.normal(delta, tau, (REPS, n_sub)) / 100.0
                rows.append(dict(endpoint='replay', delta=delta, tau=tau_name, tau_points=round(tau, 2),
                                 p_F=None, trials=None, subjects=n_sub, power=power(d_true * 100)))
                for p_f in [0.55, 0.70, 0.85]:
                    pa = np.clip(p_f + d_true, 0, 1)
                    for n_tr in [40, 60, 100]:
                        sf = RNG.binomial(n_tr, p_f, (REPS, n_sub)) / n_tr
                        sa = RNG.binomial(n_tr, pa) / n_tr
                        rows.append(dict(endpoint='task', delta=delta, tau=tau_name, tau_points=round(tau, 2),
                                         p_F=p_f, trials=n_tr, subjects=n_sub, power=power((sa - sf) * 100)))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(ROOT, 'results', 'power_sim.csv'), index=False)
    print('tau_kyranou', round(TAU_KYR, 3))
    k = df[(df.tau == 'kyranou') & ((df.endpoint == 'replay') | (df.p_F == 0.70))]
    print(k.pivot_table(index=['endpoint', 'delta', 'trials'], columns='subjects', values='power', dropna=False)
          .round(2).to_string())


if __name__ == '__main__':
    main()
