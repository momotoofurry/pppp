"""35.98 part 3: how much of the within-class variance is between cues (one held gesture) vs within a cue?
Nested ANOVA per feature, space L+U (40 features), session z-score. ICC = between-cue share. Kish design effect
deff = 1 + (m - 1) ICC, effective sample size N_eff = N / deff. OAS shrinkage computed with N vs N_eff.
Cal: 2 cued passes x 30 windows per class. Probes (diagnostic only, never used by a rule): ~10 windows per cue."""
import pickle, numpy as np
D = pickle.load(open('/sp/days.pkl', 'rb'))
S7 = [0, 1, 2, 3, 6, 7, 8]
UNIQ = [k * 8 + c for k in range(10) for c in range(4)]
def LU(F):
    F = F.copy()
    for k in (0, 1, 4):
        F[:, k * 8:(k + 1) * 8] = np.log(np.maximum(F[:, k * 8:(k + 1) * 8], 1e-12))
    return F[:, UNIQ]
def oas(Sw, N):
    d = Sw.shape[0]; mu = np.trace(Sw) / d; al = np.mean(Sw ** 2)
    return min((al + mu ** 2) / ((N + 1) * (al - mu ** 2 / d)), 1)
def icc(groups):
    """groups: list of (windows x features) arrays of one class's cues -> per feature between-cue share"""
    allw = np.vstack(groups); m = np.mean([len(g) for g in groups])
    gm = np.array([g.mean(0) for g in groups])
    within = np.mean([g.var(0, ddof=1) for g in groups], 0)
    between = np.maximum(gm.var(0, ddof=1) - within / m, 0)
    return between / (between + within), m
for name, d in D.items():
    F = LU(d['F'])
    cr, cl = d['cal_rows'], d['cal_lab']
    mu, sd = F[cr].mean(0), F[cr].std(0)
    Z = (F - mu) / sd
    # cal cues: consecutive runs of the same label in cal_rows order
    cues = {g: [] for g in S7}
    start = 0
    for i in range(1, len(cl) + 1):
        if i == len(cl) or cl[i] != cl[start] or cr[i] != cr[i - 1] + 1:
            if cl[start] in cues:
                cues[cl[start]].append(Z[cr[start:i]])
            start = i
    ic = np.array([icc(cues[g])[0] for g in S7]); m = np.mean([len(c) for g in S7 for c in cues[g]])
    ncue = [len(cues[g]) for g in S7]
    # probe cues
    pc = {g: [] for g in S7}
    for p in d['probes']:
        for w, g in p:
            if g in pc:
                pc[g].append(Z[w])
    icp = np.array([icc(pc[g])[0] for g in S7]); mp = np.mean([len(c) for g in S7 for c in pc[g]])
    R = np.vstack([Z[cr[cl == g]] - Z[cr[cl == g]].mean(0) for g in S7]); N = len(R); Sw = R.T @ R / N
    I1, I2 = np.median(ic), np.median(icp)
    de1 = 1 + (m - 1) * I1
    print(f'== {name}: cal cues per class {ncue}, {m:.0f} windows each; probe cues per class {[len(pc[g]) for g in S7]}, {mp:.0f} windows each')
    print(f'   ICC (between-cue share), median over features and classes: from cal {I1:.2f}  | from probes {I2:.2f}')
    print(f'   per class (cal): {np.median(ic,1).round(2)}  | (probes): {np.median(icp,1).round(2)}')
    print(f'   N {N}, design effect from cal {de1:.1f} -> N_eff {N/de1:.0f};  OAS rho with N {oas(Sw, N):.3f}, with N_eff {oas(Sw, N/de1):.3f}')
