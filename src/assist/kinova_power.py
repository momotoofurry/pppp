"""35.99: how detectable is the steering assist (level 0.6 vs 0) in the planned real-arm design?
Per-trial results of closed_loop_fw (same seeds -> same targets per row). Design: 6 pairs of blocks, 4 trials per block,
block score = median time (failure = 90 s), randomization test over the 2^6 orders (one-sided). Power by resampling."""
import itertools, numpy as np, pandas as pd
R = '/work/results/selftest_T00/'
import sys
TAG = sys.argv[1] if len(sys.argv) > 1 else '99'
a = pd.read_csv(R + f'closed_loop_fw_trials{TAG}_level0.6.csv'); b = pd.read_csv(R + f'closed_loop_fw_trials{TAG}_level0.csv')
print('scene tag', TAG)
assert len(a) == len(b)
ta = np.where(a.ok, a.time, 90.0); tb = np.where(b.ok, b.time, 90.0)
same_target = True
d = tb - ta
print(f'trials {len(a)}; success A {100*a.ok.mean():.1f} %  B {100*b.ok.mean():.1f} %')
print(f'time mean A {ta.mean():.1f}  B {tb.mean():.1f} s; median A {np.median(ta):.1f}  B {np.median(tb):.1f}')
print(f'paired per-trial diff B-A: mean {d.mean():+.2f} s, median {np.median(d):+.2f}, SD {d.std():.1f}; B slower in {(d>0).mean()*100:.0f} %, equal {(d==0).mean()*100:.0f} %')
print(f'trial time SD A {ta.std():.1f} s; wrong locks A {a.wrong_locks.mean():.2f} B {b.wrong_locks.mean():.2f}')
signs = np.array(list(itertools.product([1, -1], repeat=6)))
def pval(x):
    obs = x.mean(); return np.mean((signs * x).mean(1) >= obs - 1e-12)
rng = np.random.default_rng(0)
for nb, npair in ((4, 6), (4, 12), (8, 12)):
    if npair > 6:
        S = np.array(list(itertools.product([1, -1], repeat=npair))) if npair <= 12 else None
    hits, meds = 0, []
    for _ in range(1000):
        x = []
        for p in range(npair):
            ia = rng.choice(len(ta), nb); ib = rng.choice(len(tb), nb)
            x.append(np.median(tb[ib]) - np.median(ta[ia]))
        x = np.array(x); meds.append(np.median(x))
        p = pval(x) if npair == 6 else np.mean((S * x).mean(1) >= x.mean() - 1e-12)
        hits += p < 0.05
    print(f'design {npair} pairs x {nb} trials/block: power {hits/10:.0f} %, median block diff {np.median(meds):+.1f} s')
