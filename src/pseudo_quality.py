"""Pseudo-label quality vs. what the next update brings (pilot-freeze-4 C code, PC build with -DSC_DIAG=1).

Question (report 27): is the small / missing gain on new data explained by noisy pseudo-labels, as in Odeyemi 2026
(pseudo-labels hurt when target-day accuracy is ~67 %)? The firmware is unchanged; SC_DIAG only records, after each
sc_end_block(), which buffer rows were used for training and with which pseudo-label (K-Means cluster, or the
one-shot model label when K-Means did not run), so they can be compared with the true labels.

Runs, each F (fixed one-shot model) and A (firmware: 60-window start-up alignment, R3 block end, cls5 skip rule):
  dev   arm_position 20 subjects x 3 seeds (stress_check.py model / streams): base, rest2 (only Rest/Tripod/Open)
  ext   Kyranou 2025 8 subjects x 3 seeds, 0-2 s (external_check.py): A1 (day 1 -> day 2), A3_P2/P4/P6/P8
Per update (block b, not skipped): n_sel, pseudo_acc (pseudo-label == true label over the training rows),
model_acc (one-shot re-label == true label, before K-Means), cur_frac (share of the rows from block b), and the
outcome on block b+1: gain_next = A - F, d_gain = gain on b+1 - gain on b. Dev and ext are development data for this
question (both were used before); it is a diagnostic, nothing in the firmware is selected with it.
Writes results/pseudo_quality.csv (per update), pseudo_quality_summary.csv, and prints the reproduction check
(A on the same blocks as stress_check base cls5 / external_check_freeze4 A1).
Usage (container; Kyranou mounted read-only at /data): python src/pseudo_quality.py [--data /data] [--jobs 16]
"""
import argparse
import ctypes
import os
import subprocess
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
import shift_sweep as SH  # noqa: E402
import stress_check as ST  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libpseudo.so')
TAG = 100000                                    # row id = block * TAG + index in block


def build():
    src = [os.path.join(CA.CSRC, f) for f in CA.SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(s) for s in deps):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-DSC_EMBED=0', '-DSC_DIAG=1',
                        '-o', LIB] + src + ['-lm'], check=True)
    lib = ctypes.CDLL(LIB)
    lib.sc_init.argtypes = [ctypes.POINTER(CS.Model), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
    for f in ('sc_push', 'sc_predict_oneshot', 'ad_align_push'):
        getattr(lib, f).argtypes = [ctypes.c_void_p]
    lib.sc_end_block.argtypes = [ctypes.POINTER(CS.Stats)]
    lib.ad_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    lib.ad_map.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.ad_normalize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.ad_observe.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.ad_end_block_map.argtypes = [ctypes.POINTER(CA.AdStats), ctypes.c_void_p, ctypes.c_void_p]
    lib.sc_rescale.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    lib.sc_diag_tag.argtypes = [ctypes.c_int32]
    lib.sc_diag_get.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    return lib


def run(lib, md, blocks, adapt, seed, subject):
    """as external_check.run / stress_check.run_one (cls5); A also returns the pseudo-label record per update"""
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
    scale, offset = np.zeros(80, np.float32), np.zeros(80, np.float32)
    ids = np.zeros(ST.SC_BUF if hasattr(ST, 'SC_BUF') else 375, np.int32)
    ps, mo = np.zeros(len(ids), np.uint8), np.zeros(len(ids), np.uint8)
    acc, upd = [], []
    for b, (X, y) in enumerate(blocks):
        start = ST.ALIGN_N if b == 0 else 0
        pred = np.full(len(y), -1)
        for i in range(start, len(y)):
            lib.ad_map(X[i].ctypes.data, al.ctypes.data)
            lib.ad_normalize(al.ctypes.data, q.ctypes.data)
            if adapt:
                lib.sc_diag_tag(b * TAG + i)
                truth[b * TAG + i] = int(y[i])
                pred[i] = lib.sc_push(q.ctypes.data)
                lib.ad_observe(al.ctypes.data, int(pred[i]))
            else:
                pred[i] = lib.sc_predict_oneshot(q.ctypes.data)
        m = np.arange(len(y)) >= start
        acc.append(((pred == y)[m].sum(), m.sum()))
        if not adapt:
            continue
        present = int((np.bincount(pred[pred >= 0], minlength=6) >= ST.MIN_WIN).sum())
        if present < 5:
            lib.sc_skip_block()
            lib.ad_skip_block()
            upd.append(dict(block=b, k_est=k, skipped=1))
            continue
        st, ast = CS.Stats(), CA.AdStats()
        lib.ad_end_block_map(ctypes.byref(ast), scale.ctypes.data, offset.ctypes.data)
        if ast.updated:
            lib.sc_rescale(scale.ctypes.data, offset.ctypes.data, 1)
        lib.sc_end_block(ctypes.byref(st))
        n = lib.sc_diag_get(ids.ctypes.data, ps.ctypes.data, mo.ctypes.data)
        t = np.array([truth[int(v)] for v in ids[:n]])
        cur = (ids[:n] // TAG) == b
        upd.append(dict(block=b, k_est=k, skipped=0, clustered=st.clustered, n_sel=n,
                        pseudo_acc=(ps[:n] == t).mean() * 100, model_acc=(mo[:n] == t).mean() * 100,
                        cur_frac=cur.mean() * 100, pseudo_acc_cur=(ps[:n][cur] == t[cur]).mean() * 100 if cur.any() else np.nan,
                        true_classes=len(np.unique(t)),
                        changed=(ps[:n] != mo[:n]).mean() * 100,
                        fixed_by_km=((ps[:n] == t) & (mo[:n] != t)).mean() * 100,
                        broken_by_km=((ps[:n] != t) & (mo[:n] == t)).mean() * 100))
    return acc, upd


def pair(lib, md, blocks, seed, subject, meta):
    accF, _ = run(lib, md, blocks, False, seed, subject)
    accA, upd = run(lib, md, blocks, True, seed, subject)
    gain = [(a[0] / a[1] - f[0] / f[1]) * 100 for a, f in zip(accA, accF)]
    blk = [dict(meta, block=b, okA=a[0], okF=f[0], n=a[1]) for b, (a, f) in enumerate(zip(accA, accF))]
    for u in upd:
        b = u['block']
        u.update(meta, gain_cur=gain[b], accA_next=np.nan, accF_next=np.nan, gain_next=np.nan, d_gain=np.nan)
        if b + 1 < len(blocks):
            u.update(accA_next=accA[b + 1][0] / accA[b + 1][1] * 100, accF_next=accF[b + 1][0] / accF[b + 1][1] * 100,
                     gain_next=gain[b + 1], d_gain=gain[b + 1] - gain[b])
    return blk, upd


def job_dev(subject, seed):
    lib = build()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    z0, z1 = np.load(SH.prepare(subject, 0)), np.load(SH.prepare(subject, 1))
    md = ST.model(subject, seed, z0['Xc'], z0['yc'])
    st = ST.streams(z0, z1)
    B, U = [], []
    for sc in ('base', 'rest2'):
        b, u = pair(lib, md, st[sc], seed, subject, dict(data='dev', comp=sc, subject=subject, seed=seed))
        B += b
        U += u
    return B, U


def job_ext(data, p, seed):
    lib = build()
    elib = ST.build()                               # calibration exactly as external_check (same C code)
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    d1 = [EX.Session(data, p, 1, b) for b in (1, 2)]
    d2 = [EX.Session(data, p, 2, b) for b in (1, 2)]
    md, _ = EX.calibrate(elib, d1[0], p, seed, 0)
    if md is None:
        return [], []
    tests = {'A1': EX.stream(d2, 5, EX.ROW1, 0)}
    for pos in EX.A3_POS:
        tests[f'A3_P{pos}'] = EX.stream(d1, pos, EX.ROW1, 0)
    B, U = [], []
    for comp, blocks in tests.items():
        b, u = pair(lib, md, blocks, seed, p, dict(data='ext', comp=comp, subject=p, seed=seed))
        B += b
        U += u
    return B, U


def corr(d, x, y):
    d = d[[x, y]].dropna()
    if len(d) < 5:
        return dict(n=len(d))
    r, p = stats.spearmanr(d[x], d[y])
    return dict(n=len(d), spearman_r=r, spearman_p=p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='/data')
    ap.add_argument('--jobs', type=int, default=16)
    args = ap.parse_args()
    build()
    ST.build()
    FC.lib()
    tasks = [delayed(job_dev)(s, sd) for s in range(P.N_SUBJECTS if hasattr(P, 'N_SUBJECTS') else 20)
             for sd in (0, 1, 2)]
    if os.path.isdir(os.path.join(args.data, 'data')):
        tasks += [delayed(job_ext)(args.data, p, sd) for p in EX.SUBJECTS for sd in EX.SEEDS]
    else:
        print('no Kyranou data at', args.data, '- dev only')
    res = Parallel(n_jobs=args.jobs, verbose=5)(tasks)
    blk = pd.DataFrame([r for b, _ in res for r in b])
    upd = pd.DataFrame([r for _, u in res for r in u])
    upd.to_csv(os.path.join(OUT, 'pseudo_quality.csv'), index=False, float_format='%.3f')
    blk.to_csv(os.path.join(OUT, 'pseudo_quality_blocks.csv'), index=False)

    # reproduction: dev base blocks 1-10 (stress_check base cls5 84.73), ext A1 all blocks (external freeze4 74.44)
    def acc(g, col):
        return (g.groupby(['subject', 'seed'])[[col, 'n']].sum().pipe(lambda s: s[col] / s.n * 100)
                .groupby(level='subject').mean().mean())
    print('repro dev base, blocks 1-10: A %.2f F %.2f' % (
        acc(blk[(blk.data == 'dev') & (blk.comp == 'base') & (blk.block >= 1)], 'okA'),
        acc(blk[(blk.data == 'dev') & (blk.comp == 'base') & (blk.block >= 1)], 'okF')))
    if (blk.data == 'ext').any():
        print('repro ext A1: A %.2f F %.2f' % (acc(blk[blk.comp == 'A1'], 'okA'), acc(blk[blk.comp == 'A1'], 'okF')))

    u = upd[upd.skipped == 0].copy()
    u['group'] = np.where(u.comp.str.startswith('A3'), 'A3', u.comp)
    rows = []
    for (data, grp), g in u.groupby(['data', 'group']):
        row = dict(data=data, group=grp, updates=len(g), skipped=int((upd[(upd.data == data) & (
            np.where(upd.comp.str.startswith('A3'), 'A3', upd.comp) == grp)].skipped == 1).sum()),
                   clustered_pct=g.clustered.mean() * 100, n_sel=g.n_sel.mean(),
                   pseudo_acc=g.pseudo_acc.mean(), pseudo_acc_p10=g.pseudo_acc.quantile(0.1),
                   model_acc=g.model_acc.mean(), km_fixed=g.fixed_by_km.mean(), km_broken=g.broken_by_km.mean(),
                   cur_frac=g.cur_frac.mean(), gain_next=g.gain_next.mean(), d_gain=g.d_gain.mean())
        row.update({f'pa_vs_gain_next_{k}': v for k, v in corr(g, 'pseudo_acc', 'gain_next').items()})
        row.update({f'pa_vs_d_gain_{k}': v for k, v in corr(g, 'pseudo_acc', 'd_gain').items()})
        rows.append(row)
    sm = pd.DataFrame(rows)
    # binned: pooled over everything with a next block
    u2 = u.dropna(subset=['d_gain']).copy()
    u2['bin'] = pd.cut(u2.pseudo_acc, [0, 60, 70, 80, 90, 100.01], right=False,
                       labels=['<60', '60-70', '70-80', '80-90', '>=90'])
    bins = u2.groupby(['data', 'bin'], observed=True).agg(updates=('d_gain', 'size'), pseudo_acc=('pseudo_acc', 'mean'),
                                                          gain_next=('gain_next', 'mean'), d_gain=('d_gain', 'mean'),
                                                          d_gain_neg_pct=('d_gain', lambda s: (s < 0).mean() * 100))
    sm.to_csv(os.path.join(OUT, 'pseudo_quality_summary.csv'), index=False, float_format='%.4g')
    bins.to_csv(os.path.join(OUT, 'pseudo_quality_bins.csv'), float_format='%.4g')
    pd.set_option('display.width', 260)
    pd.set_option('display.max_columns', 40)
    print(sm.round(3).to_string(index=False))
    print(bins.round(2).to_string())


if __name__ == '__main__':
    main()
