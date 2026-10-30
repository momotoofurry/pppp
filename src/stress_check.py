"""Test B (VALIDATION_PLAN.md 4B): the firmware under stress on the development data (arm_position, 20 subjects x 3
seeds), C code as rt.c (causal 60-window start-up alignment, R3 block end), and candidate rollback rules.

Scenarios (test blocks; block 0 = start-up alignment on its first 60 windows, then classified and scored):
  base      blocks as recorded
  rest2     every block keeps only Rest, Tripod and Open (grip / release), ~150 windows per block
  absent    Power (gesture 0) is missing from blocks 1-6 and comes back in blocks 7-10
  wrong     blocks 1-4 come from the recording with the electrode ring rotated by one position (strap slipped after
            the start-up alignment, no new alignment), blocks 5-10 normal again (strap put back)
  half      calibration with only the first 5 of the 10 windows per gesture (shorter hold)
  low       calibration features of the raw EMG x 0.5 (weak contraction; C features recomputed, so ZC / SSC
            thresholds act on the scaled signal)
Variants: fixed (one-shot model, no adaptation), fw (rt.c: z-score update first, buffer + calibration rows mapped,
new trees), and fw with a rollback rule checked after every update on the stored calibration rows (labelled day-1
data, already in RAM): abs90 / abs80 = restore the previous trees and z-score (buffer mapped back) when the updated
model classifies fewer than 90 % / 80 % of them correctly; drop05 / drop10 = when it lost more than 5 / 10 points
against the model before the update; cls4 / cls5 = skip the whole update (no z-score update, no new trees) when
fewer than 4 / 5 predicted classes have >= 5 windows in the block ('rolled' counts the skipped updates). Writes results/stress_check.csv (per block, per class counts) and
stress_check_summary.csv. Usage (in the container): python src/stress_check.py [--jobs 19]
"""
import argparse
import copy
import ctypes
import os
import subprocess
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_adapt_c as CA  # noqa: E402
import check_features_c as FC  # noqa: E402
import check_selfcal_c as CS  # noqa: E402
import export_c  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import shift_sweep as SH  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libstress.so')
SCEN = ['base', 'rest2', 'absent', 'wrong', 'half', 'low']
VARS = ['fixed', 'fw', 'abs90', 'abs80', 'drop05', 'drop10', 'cls4', 'cls5']
MIN_WIN = 5                                  # AD_MIN_CLASS
ALIGN_N = 60
REST2 = (5, 2, 4)


def build():
    src = [os.path.join(CA.CSRC, f) for f in CA.SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(s) for s in deps):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-DSC_EMBED=0', '-DSC_ROLLBACK=1',
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
    return lib


def low_cal(subject, scale=0.5):
    """calibration features of the raw EMG x scale (as shift_sweep.raw_features)"""
    data = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), 'calibration', 'data.npy'))
    label = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), 'calibration', 'label.npy'))
    data = (data * scale).astype(np.float32)
    L = FC.lib()
    out = np.zeros((len(data), FC.NWIN, 80), dtype=np.float32)
    for t, rec in enumerate(data):
        rec = np.ascontiguousarray(rec)
        assert L.fe_recording(rec.ctypes.data, rec.shape[1], out[t].ctypes.data, FC.NWIN) == FC.NWIN
    return out[:, FC.W0:, :].astype(np.float64).reshape(-1, 80), np.repeat(label, FC.NWIN - FC.W0)


def model(subject, seed, Xc_raw, yc):
    """one-shot model as check_adapt_c.run_c (same numpy seed) -> ctypes arrays"""
    np.random.seed(seed * 1000 + subject)
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    Xc = (Xc_raw - mu) / np.sqrt(var)
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), SH.DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, 50, SH.DEPTH, None)
    mdl = rf_size.compact_forest(emg_functions.append(P.subset(pruned, range(50)), app))
    roots, feat, thr, left, right = export_c.table_arrays(mdl, 'int16')
    arrs = [np.ascontiguousarray(a, dtype=t) for a, t in
            [(roots, np.uint32), (feat, np.uint8), (thr, np.int16), (left, np.uint16), (right, np.uint16)]]
    return dict(arrs=arrs, m=CS.Model(*[a.ctypes.data for a in arrs]),
                cal=np.ascontiguousarray(P.quantize(Xc)), caly=np.ascontiguousarray(yc.astype(np.uint8)),
                mu=np.ascontiguousarray(mu, dtype=np.float32), inv=np.ascontiguousarray(1 / np.sqrt(var), dtype=np.float32),
                calf=np.ascontiguousarray(Xc_raw, dtype=np.float32))


def streams(z0, z1):
    """scenario -> list of (X float32, y) test blocks"""
    blk = [(np.ascontiguousarray(z0[f'X{b}'], dtype=np.float32), z0[f'y{b}']) for b in range(P.N_BLOCKS)]
    rot = [(np.ascontiguousarray(z1[f'X{b}'], dtype=np.float32), z1[f'y{b}']) for b in range(P.N_BLOCKS)]

    def keep(X, y, m):
        return np.ascontiguousarray(X[m]), y[m]
    out = {'base': blk, 'half': blk, 'low': blk}
    out['rest2'] = [blk[0]] + [keep(X, y, np.isin(y, REST2)) for X, y in blk[1:]]
    out['absent'] = [blk[0]] + [keep(X, y, y != 0) if b <= 6 else (X, y) for b, (X, y) in enumerate(blk[1:], 1)]
    out['wrong'] = [blk[0]] + [rot[b] if b <= 4 else blk[b] for b in range(1, P.N_BLOCKS)]
    return out


def run_one(lib, md, blocks, var, seed, subject):
    lib.sc_init(ctypes.byref(md['m']), md['cal'].ctypes.data, md['caly'].ctypes.data, len(md['cal']),
                seed * 1000 + subject + 1)
    lib.ad_init(md['mu'].ctypes.data, md['inv'].ctypes.data, md['calf'].ctypes.data, len(md['calf']))
    lib.ad_align_reset()
    X0 = blocks[0][0]
    for i in range(ALIGN_N):
        lib.ad_align_push(X0[i].ctypes.data)
    k = lib.ad_align_finish()
    al, q = np.zeros(80, np.float32), np.zeros(80, np.int16)
    scale, offset = np.zeros(80, np.float32), np.zeros(80, np.float32)
    ncal = len(md['cal'])
    rows = []
    for b, (X, y) in enumerate(blocks):
        start = ALIGN_N if b == 0 else 0
        pred = np.full(len(y), -1)
        for i in range(start, len(y)):
            lib.ad_map(X[i].ctypes.data, al.ctypes.data)
            lib.ad_normalize(al.ctypes.data, q.ctypes.data)
            if var == 'fixed':
                pred[i] = lib.sc_predict_oneshot(q.ctypes.data)
            else:
                pred[i] = lib.sc_push(q.ctypes.data)
                lib.ad_observe(al.ctypes.data, int(pred[i]))
        rolled, cal_before, cal_after = 0, np.nan, np.nan
        need = {'cls4': 4, 'cls5': 5}.get(var)
        present = int((np.bincount(pred[pred >= 0], minlength=6) >= MIN_WIN).sum())
        if need and present < need:                       # skip this update: no z-score, no new trees (the
            lib.sc_skip_block()                           # block's rows stay in the buffer for the next update)
            lib.ad_skip_block()
            rolled = 1
        elif var != 'fixed':
            st, ast = CS.Stats(), CA.AdStats()
            lib.sc_save()
            lib.ad_save()
            cal_before = lib.sc_cal_correct() / ncal
            lib.ad_end_block_map(ctypes.byref(ast), scale.ctypes.data, offset.ctypes.data)
            if ast.updated:
                lib.sc_rescale(scale.ctypes.data, offset.ctypes.data, 1)
            lib.sc_end_block(ctypes.byref(st))
            cal_after = lib.sc_cal_correct() / ncal
            bad = {'abs90': cal_after < 0.90, 'abs80': cal_after < 0.80, 'drop05': cal_before - cal_after > 0.05,
                   'drop10': cal_before - cal_after > 0.10}.get(var, False)
            if bad:
                rolled = 1
                lib.sc_restore()
                lib.ad_restore()
                if ast.updated:                                   # buffer + calibration rows back to the old statistics
                    inv_s = np.where(scale != 0, 1 / np.where(scale != 0, scale, 1), 0).astype(np.float32)
                    inv_o = np.ascontiguousarray(-offset * inv_s, dtype=np.float32)
                    inv_s = np.ascontiguousarray(inv_s)
                    lib.sc_rescale(inv_s.ctypes.data, inv_o.ctypes.data, 1)
        m = np.arange(len(y)) >= start
        row = dict(block=b, k_est=k, n=int(m.sum()), ok=int((pred == y)[m].sum()), rolled=rolled,
                   cal_before=cal_before, cal_after=cal_after)
        for c in range(6):
            mc = m & (y == c)
            row[f'n{c}'], row[f'ok{c}'] = int(mc.sum()), int((pred[mc] == c).sum())
            row[f'pred{c}'] = int((pred[m] == c).sum())
        rows.append(row)
    return rows


def job(subject, seed):
    lib = build()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    z0, z1 = np.load(SH.prepare(subject, 0)), np.load(SH.prepare(subject, 1))
    Xc, yc = z0['Xc'], z0['yc']
    half = (np.arange(len(yc)) % (FC.NWIN - FC.W0)) < 5
    cals = {'normal': (Xc, yc), 'half': (Xc[half], yc[half]), 'low': low_cal(subject)}
    mds = {c: model(subject, seed, *v) for c, v in cals.items()}
    st = streams(z0, z1)
    rows = []
    for sc in SCEN:
        md = mds[sc] if sc in ('half', 'low') else mds['normal']
        for var in VARS:
            for r in run_one(lib, md, st[sc], var, seed, subject):
                r.update(subject=subject, seed=seed, scen=sc, var=var)
                rows.append(r)
    return rows


def summarise(df):
    def acc(g, blocks=None, cls=None):
        g = g if blocks is None else g[g.block.isin(blocks)]
        if cls is None:
            return g.ok.sum() / g.n.sum() * 100
        return g[f'ok{cls}'].sum() / max(g[f'n{cls}'].sum(), 1) * 100
    per = []
    for (sc, var, s), g in df.groupby(['scen', 'var', 'subject']):
        seeds = [h for _, h in g.groupby('seed')]
        per.append(dict(scen=sc, var=var, subject=s, acc=np.mean([acc(h) for h in seeds]),
                        focus=np.mean([acc(h, range(7, 11), 0) if sc == 'absent' else
                                       acc(h, range(5, 11)) if sc == 'wrong' else
                                       acc(h, range(1, 11)) for h in seeds]),
                        absent_pred=np.mean([h[h.block.between(1, 10)][[f'pred{c}' for c in (0, 1, 3)]].sum().sum() /
                                             h[h.block.between(1, 10)].n.sum() * 100 if sc == 'rest2' else np.nan
                                             for h in seeds]),
                        rolled=g.rolled.sum() / len(seeds)))
    per = pd.DataFrame(per)
    # recovery after the strap is put back ('wrong'): first block >= 5 within 2 points of the same variant in 'base'
    rec = []
    for (var, s, seed), g in df[df.scen == 'wrong'].groupby(['var', 'subject', 'seed']):
        base = df[(df.scen == 'base') & (df['var'] == var) & (df.subject == s) & (df.seed == seed)].set_index('block')
        g = g.set_index('block')
        t = next((b - 5 for b in range(5, 11) if g.ok[b] / g.n[b] >= base.ok[b] / base.n[b] - 0.02), 6)
        rec.append(dict(var=var, subject=s, seed=seed, recover_blocks=t))
    rec = pd.DataFrame(rec).groupby(['var', 'subject']).recover_blocks.mean().reset_index()
    out = []
    for sc in SCEN:
        w = per[per.scen == sc].pivot(index='subject', columns='var')
        for var in VARS:
            row = dict(scen=sc, var=var, acc=w['acc'][var].mean(), worst_subject=w['acc'][var].min(),
                       focus=w['focus'][var].mean(), focus_worst=w['focus'][var].min(),
                       rollbacks_per_run=w['rolled'][var].mean())
            if sc == 'rest2':
                row['pred_absent_pct'] = w['absent_pred'][var].mean()
            if sc == 'wrong':
                r = rec[rec['var'] == var].recover_blocks
                row['recover_blocks_mean'], row['never_recovered'] = r.mean(), int((r >= 6).sum())
            for ref in ('fixed', 'fw'):
                if var == ref:
                    continue
                d = w['focus'][var] - w['focus'][ref]
                row[f'vs_{ref}'] = d.mean()
                row[f'vs_{ref}_better'], row[f'vs_{ref}_worse'] = int((d > 0).sum()), int((d < 0).sum())
                row[f'vs_{ref}_worst'] = d.min()
                row[f'vs_{ref}_p'] = wilcoxon(d).pvalue if np.any(d != 0) else 1.0
            out.append(row)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--subjects', type=int, default=20)
    args = ap.parse_args()
    build()
    FC.lib()
    for s in range(args.subjects):
        for sh in (0, 1):
            SH.prepare(s, sh)
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(job)(s, seed) for s in range(args.subjects) for seed in range(3))
    df = pd.DataFrame([r for rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'stress_check.csv'), index=False)
    sm = summarise(df)
    sm.to_csv(os.path.join(OUT, 'stress_check_summary.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 260)
    pd.set_option('display.max_columns', 40)
    print(sm.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
