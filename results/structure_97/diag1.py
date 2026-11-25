"""35.97 structure study, part 1: does the data meet LDA's assumptions? (cued windows, both days)"""
import pickle, numpy as np
from scipy import stats
D = pickle.load(open('/sp/days.pkl', 'rb'))
FN = ['RMS', 'WL', 'SSC', 'ZC', 'MAV', 'SKEW', 'SVAR', 'MDF', 'MNF', 'PKF']
GN = ['Ext', 'Flex', 'Rad', 'Uln', 'Point', 'Thumb', 'Open', 'Fist', 'Rest']
S7 = [0, 1, 2, 3, 6, 7, 8]
np.set_printoptions(precision=3, suppress=True, linewidth=160)
for name, d in D.items():
    F = d['F']
    X, y = F[d['cal_rows']], d['cal_lab']
    print(f'===== {name}: cued windows {X.shape}')
    dup = np.max(np.abs(F[:, [k * 8 + c for k in range(10) for c in range(4)]] - F[:, [k * 8 + c + 4 for k in range(10) for c in range(4)]]))
    print('ch5-8 minus ch1-4, max abs over all windows:', dup)
    idx = [k * 8 + c for k in range(10) for c in range(4)]     # the 40 distinct features
    X = X[:, idx]
    names = [f'{FN[k]}{c+1}' for k in range(10) for c in range(4)]
    # 1. rank / eigen spectrum of the pooled within-class covariance (z-scored)
    m = X.mean(0); s = X.std(0); Z = (X - m) / s
    W = sum(np.cov(Z[y == g].T, bias=True) * (y == g).sum() for g in S7) / np.isin(y, S7).sum()
    ev = np.sort(np.linalg.eigvalsh(W))[::-1]
    print('within-class cov (S7, z-scored, 40 features): eigen share of top 1/3/5/10:',
          [round(ev[:k].sum() / ev.sum(), 3) for k in (1, 3, 5, 10)], ' participation ratio', round(ev.sum() ** 2 / (ev ** 2).sum(), 2))
    # 2. Gaussianity: within-class skewness of amplitude features raw vs log
    amp = [names.index(f'{f}{c}') for f in ('RMS', 'MAV', 'WL') for c in range(1, 5)]
    sk_raw = np.array([[stats.skew(X[y == g, j]) for j in amp] for g in S7])
    sk_log = np.array([[stats.skew(np.log(X[y == g, j])) for j in amp] for g in S7])
    print('amplitude features (RMS/MAV/WL x 4 ch): within-class |skew| median raw', np.median(np.abs(sk_raw)).round(2),
          ' log', np.median(np.abs(sk_log)).round(2))
    # 3. equal covariance: per-class SD of RMS per channel, raw vs log, ratio max/min over classes
    for lab, f in (('raw', lambda v: v), ('log', np.log)):
        sd = np.array([[f(X[y == g, names.index(f'RMS{c}')]).std() for c in range(1, 5)] for g in S7])
        print(f'RMS per-class SD ({lab}) rows=class {[GN[g] for g in S7]}, cols ch1-4\n', sd,
              '\n  max/min over classes per channel:', (sd.max(0) / sd.min(0)).round(1))
    # 4. RMS vs MAV vs WL redundancy (correlation within class, log)
    for c in range(1, 5):
        r = [np.corrcoef(np.log(X[y == g, names.index(f'RMS{c}')]), np.log(X[y == g, names.index(f'MAV{c}')]))[0, 1] for g in S7]
        r2 = [np.corrcoef(np.log(X[y == g, names.index(f'RMS{c}')]), np.log(X[y == g, names.index(f'WL{c}')]))[0, 1] for g in S7]
        print(f'ch{c} within-class corr logRMS-logMAV median {np.median(r):.3f}, logRMS-logWL {np.median(r2):.3f}')
    # 5. effort direction: top PC of within-class cov of log RMS (4 ch) per active class
    for g in S7[:-1]:
        L = np.log(X[y == g][:, [names.index(f'RMS{c}') for c in range(1, 5)]])
        w, v = np.linalg.eigh(np.cov(L.T))
        u = v[:, -1] * np.sign(v[:, -1].sum())
        print(f'  {GN[g]:5s} log-RMS within-class: top PC share {w[-1]/w.sum():.2f}, direction {u.round(2)}, cos to (1,1,1,1) {u.sum()/2:.2f}')
