"""Label-free update gate: can the board tell, without labels, that it should NOT self-calibrate now? (report 32)

Same harness and data as pseudo_quality.py (pilot-freeze-5 C code, PC build with -DSC_DIAG=1; dev = arm_position
20 subjects x 3 seeds, streams base and rest2; ext = Kyranou 8 x 3, A1 and A3_P2..P8). Per block the current
model's votes (sc_push_votes, 100 trees) give label-free indicators, computable on the MCU at no RAM cost:
  conf_hi    share of the block's windows whose top vote share >= 0.6 (the decision rule's acceptance, tau 0.6)
  conf_mean  mean top vote share over the block
  share5     share of the block's windows predicted as the 5th most frequent class (the cls5 rule, which needs
             >= 5 windows ~ 1.7 %, as a proportion threshold; targets the failure mode of report 22 / 27.1:
             only a few gestures in the block, K-Means still forced into 6 clusters)
(conf_hi / conf_mean were tried first; share5 was added after they failed - both rounds are reported.)
At the block end the update runs as in the firmware (cls5: skipped if fewer than 5 classes are predicted >= 5
times), and in addition the GATE skips it (sc_skip_block + ad_skip_block, exactly as cls5) when the indicator of
that block is below theta. Gate off = the firmware.
Outputs:
  results/update_gate_updates.csv  per update (gate off): indicators, pseudo-label accuracy (true labels, diagnostic
                                   only), gain on the next block
  results/update_gate_blocks.csv   per block accuracy of F, A (firmware) and A + gate for every indicator x theta
  results/update_gate_summary.csv  per data / comp / indicator / theta: mean accuracy over blocks 1.., A - F,
                                   A+gate - A with paired t CI over subjects (seeds averaged), share of updates gated
  results/update_gate_loso.csv     theta chosen leave-one-subject-out on dev (base and rest2 pooled), applied to the
                                   left-out subject
Dev is where theta is chosen; Kyranou was already used (report 24-27), so it is only a consistency check, not a
validation. The real test is the study (PROTOCOL v4: replay of the day-2 F stream through F, A and A + gate).
Usage (container; Kyranou at /data): python src/update_gate.py [--data /data] [--jobs 16]
"""
import argparse
import ctypes
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_adapt_c as CA  # noqa: E402
import check_features_c as FC  # noqa: E402
import check_selfcal_c as CS  # noqa: E402
import external_check as EX  # noqa: E402
import pipeline as P  # noqa: E402
import pseudo_quality as PQ  # noqa: E402
import shift_sweep as SH  # noqa: E402
import stress_check as ST  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
GATES = [(None, None)] + [('conf_hi', t) for t in (0.3, 0.4, 0.5, 0.6, 0.7)] + \
        [('conf_mean', t) for t in (0.5, 0.55, 0.6, 0.65, 0.7)] + \
        [('share5', t) for t in (0.03, 0.05, 0.07, 0.10)]


def lib_():
    lib = PQ.build()
    lib.sc_push_votes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return lib


def run(lib, md, blocks, adapt, seed, subject, gate=(None, None), record=False):
    lib.sc_init(ctypes.byref(md['m']), md['cal'].ctypes.data, md['caly'].ctypes.data, len(md['cal']),
                seed * 1000 + subject + 1)
    lib.ad_init(md['mu'].ctypes.data, md['inv'].ctypes.data, md['calf'].ctypes.data, len(md['calf']))
    lib.ad_align_reset()
    k = 0
    if adapt:
        X0 = blocks[0][0]
        for i in range(ST.ALIGN_N):
            lib.ad_align_push(X0[i].ctypes.data)
        k = lib.ad_align_finish()
    truth = {}
    al, q = np.zeros(80, np.float32), np.zeros(80, np.int16)
    votes = np.zeros(6, np.uint16)
    scale, offset = np.zeros(80, np.float32), np.zeros(80, np.float32)
    ids = np.zeros(375, np.int32)
    ps, mo = np.zeros(375, np.uint8), np.zeros(375, np.uint8)
    acc, upd = [], []
    for b, (X, y) in enumerate(blocks):
        start = ST.ALIGN_N if b == 0 else 0
        pred = np.full(len(y), -1)
        share = []
        for i in range(start, len(y)):
            lib.ad_map(X[i].ctypes.data, al.ctypes.data)
            lib.ad_normalize(al.ctypes.data, q.ctypes.data)
            if adapt:
                lib.sc_diag_tag(b * PQ.TAG + i)
                truth[b * PQ.TAG + i] = int(y[i])
                pred[i] = lib.sc_push_votes(q.ctypes.data, votes.ctypes.data)
                share.append(votes.max() / max(int(votes.sum()), 1))
                lib.ad_observe(al.ctypes.data, int(pred[i]))
            else:
                pred[i] = lib.sc_predict_oneshot(q.ctypes.data)
        m = np.arange(len(y)) >= start
        acc.append(((pred == y)[m].sum(), m.sum()))
        if not adapt:
            continue
        share = np.array(share)
        cnt = np.sort(np.bincount(pred[pred >= 0], minlength=6))[::-1]
        ind = dict(conf_hi=float((share >= 0.6).mean()), conf_mean=float(share.mean()),
                   share5=float(cnt[4] / max(cnt.sum(), 1)))
        present = int((np.bincount(pred[pred >= 0], minlength=6) >= ST.MIN_WIN).sum())
        gated = gate[0] is not None and ind[gate[0]] < gate[1]
        if present < 5 or gated:
            lib.sc_skip_block()
            lib.ad_skip_block()
            upd.append(dict(block=b, skipped=int(present < 5), gated=int(gated), **ind))
            continue
        st, ast = CS.Stats(), CA.AdStats()
        lib.ad_end_block_map(ctypes.byref(ast), scale.ctypes.data, offset.ctypes.data)
        if ast.updated:
            lib.sc_rescale(scale.ctypes.data, offset.ctypes.data, 1)
        lib.sc_end_block(ctypes.byref(st))
        n = lib.sc_diag_get(ids.ctypes.data, ps.ctypes.data, mo.ctypes.data)
        t = np.array([truth[int(v)] for v in ids[:n]])
        upd.append(dict(block=b, skipped=0, gated=0, clustered=st.clustered, n_sel=n,
                        pseudo_acc=(ps[:n] == t).mean() * 100, changed=(ps[:n] != mo[:n]).mean() * 100, **ind))
    return acc, upd


def one(lib, md, blocks, seed, subject, meta):
    accF, _ = run(lib, md, blocks, False, seed, subject)
    rows, U = [], []
    for g in GATES:
        accA, upd = run(lib, md, blocks, True, seed, subject, g)
        for b, (a, f) in enumerate(zip(accA, accF)):
            rows.append(dict(meta, ind=g[0] or 'none', theta=g[1] if g[1] is not None else np.nan, block=b,
                             accA=a[0] / a[1] * 100, accF=f[0] / f[1] * 100,
                             gated=sum(u['gated'] for u in upd if u['block'] == b)))
        if g[0] is None:
            gain = {b: (a[0] / a[1] - f[0] / f[1]) * 100 for b, (a, f) in enumerate(zip(accA, accF))}
            for u in upd:
                U.append(dict(meta, **u, gain_next=gain.get(u['block'] + 1, np.nan)))
    return rows, U


def job_dev(subject, seed):
    lib = lib_()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    z0, z1 = np.load(SH.prepare(subject, 0)), np.load(SH.prepare(subject, 1))
    md = ST.model(subject, seed, z0['Xc'], z0['yc'])
    st = ST.streams(z0, z1)
    R, U = [], []
    for sc in ('base', 'rest2'):
        r, u = one(lib, md, st[sc], seed, subject, dict(data='dev', comp=sc, subject=subject, seed=seed))
        R += r
        U += u
    return R, U


def job_ext(data, p, seed):
    lib = lib_()
    elib = ST.build()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    d1 = [EX.Session(data, p, 1, b) for b in (1, 2)]
    d2 = [EX.Session(data, p, 2, b) for b in (1, 2)]
    md, _ = EX.calibrate(elib, d1[0], p, seed, 0)
    if md is None:
        return [], []
    tests = {'A1': EX.stream(d2, 5, EX.ROW1, 0)}
    for pos in EX.A3_POS:
        tests[f'A3_P{pos}'] = EX.stream(d1, pos, EX.ROW1, 0)
    R, U = [], []
    for comp, blocks in tests.items():
        r, u = one(lib, md, blocks, seed, p, dict(data='ext', comp=comp, subject=p, seed=seed))
        R += r
        U += u
    return R, U


def subject_means(blk):
    """per subject (seeds averaged), blocks 1.. (block 0 is before the first update)"""
    b = blk[blk.block >= 1]
    return b.groupby(['data', 'comp', 'ind', 'theta', 'subject'], dropna=False)[['accA', 'accF', 'gated']].mean().reset_index()


def summarise(sm):
    base = sm[sm.ind == 'none'].set_index(['data', 'comp', 'subject'])['accA']
    out = []
    for (data, comp, ind, theta), g in sm.groupby(['data', 'comp', 'ind', 'theta'], dropna=False):
        g = g.set_index('subject')
        a0 = base.loc[(data, comp)].reindex(g.index)
        d_gate = g.accA - a0
        d_af = g.accA - g.accF
        n = len(g)
        tc = stats.t.ppf(0.975, n - 1)
        out.append(dict(data=data, comp=comp, ind=ind, theta=theta, n=n, accF=g.accF.mean(), accA=g.accA.mean(),
                        A_minus_F=d_af.mean(), gate_minus_A=d_gate.mean(),
                        gate_ci_lo=d_gate.mean() - tc * d_gate.std(ddof=1) / np.sqrt(n),
                        gate_ci_hi=d_gate.mean() + tc * d_gate.std(ddof=1) / np.sqrt(n),
                        better=int((d_gate > 0).sum()), worse=int((d_gate < 0).sum()), gated_per_block=g.gated.mean()))
    return pd.DataFrame(out)


def loso(sm):
    dev = sm[sm.data == 'dev']
    pooled = dev.groupby(['ind', 'theta', 'subject'], dropna=False)['accA'].mean().reset_index()
    base = pooled[pooled.ind == 'none'].set_index('subject')['accA']
    rows = []
    for s in sorted(pooled.subject.unique()):
        tr = pooled[pooled.subject != s]
        m = tr.groupby(['ind', 'theta'], dropna=False)['accA'].mean()
        ind, theta = m.idxmax()
        te = pooled[(pooled.subject == s) & (pooled.ind == ind) & (pooled.theta.fillna(-1) == (theta if theta == theta else -1))]
        rows.append(dict(left_out=s, ind=ind, theta=theta, accA_gate=float(te.accA.iloc[0]), accA=float(base[s])))
    r = pd.DataFrame(rows)
    r['diff'] = r.accA_gate - r.accA
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='/data')
    ap.add_argument('--jobs', type=int, default=16)
    args = ap.parse_args()
    lib_()
    ST.build()
    FC.lib()
    tasks = [delayed(job_dev)(s, sd) for s in range(20) for sd in (0, 1, 2)]
    if os.path.isdir(os.path.join(args.data, 'data')):
        tasks += [delayed(job_ext)(args.data, p, sd) for p in EX.SUBJECTS for sd in EX.SEEDS]
    res = Parallel(n_jobs=args.jobs, verbose=2)(tasks)
    blk = pd.DataFrame([r for rr, _ in res for r in rr])
    upd = pd.DataFrame([u for _, uu in res for u in uu])
    blk.to_csv(os.path.join(OUT, 'update_gate_blocks.csv'), index=False, float_format='%.3f')
    upd.to_csv(os.path.join(OUT, 'update_gate_updates.csv'), index=False, float_format='%.3f')
    u = upd[(upd.skipped == 0)]
    for (data, comp), g in u.groupby(['data', 'comp']):
        msg = []
        for c in ('conf_hi', 'conf_mean', 'share5', 'changed'):
            gg = g[[c, 'pseudo_acc', 'gain_next']].dropna()
            msg.append(f'{c}: r(pseudo)={stats.spearmanr(gg[c], gg.pseudo_acc)[0]:+.2f} '
                       f'r(gain_next)={stats.spearmanr(gg[c], gg.gain_next)[0]:+.2f}')
        print(data, comp, len(g), '|', '; '.join(msg))
    sm = subject_means(blk)
    s = summarise(sm)
    s.to_csv(os.path.join(OUT, 'update_gate_summary.csv'), index=False, float_format='%.3f')
    print(s.round(2).to_string(index=False))
    lo = loso(sm)
    lo.to_csv(os.path.join(OUT, 'update_gate_loso.csv'), index=False, float_format='%.3f')
    print(lo.round(2).to_string(index=False))
    t = stats.ttest_1samp(lo['diff'], 0)
    print(f"LOSO gate - firmware on dev: mean {lo['diff'].mean():+.3f}, p {t.pvalue:.3f}, chosen:",
          lo.groupby(['ind', 'theta'], dropna=False).size().to_dict())


if __name__ == '__main__':
    main()
