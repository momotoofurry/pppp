"""External validation on Kyranou, Szymaniak, Nazarpour, Sci Data 2025 (Dryad doi:10.5061/dryad.8sf7m0czv), as
pre-registered in EXTERNAL_PLAN.md (commit 8d16592): 8 subjects, Delsys Trigno 16 channels at 2 kHz, two days,
two sessions per day (folders participant{N}_day{D}_block{B}), 150 trials of 5 s per session.

Fixed before any classification (from the README, the recording code and a label-free look at the signals):
- grasp codes (recording code posture_data_collection.py, graspsDict): 1 power, 2 lateral, 3 tripod, 4 pointer,
  5 open, 6 rest -> label = grasp - 1, the same order as arm_position (0 Power ... 5 Rest).
- HDF5 key = trials.csv row_number (keys '0'..'149'); each trial is float32 16 x ~10,000 (some 9,960-9,980), volts,
  already band-pass filtered 20-450 Hz (4th-order Butterworth) at recording time.
- channels: the README / paper / code do not say which channel sits where. Pooled correlation of the 50 ms log-RMS
  envelope (8 subjects, day 1 session 1, no labels) shows a zig-zag ring 9-1-10-2-11-3-12-4-13-5-14-6-15-7-16-8-(9):
  every channel of 1-8 is most correlated with two channels of 9-16 and vice versa. So rows 0-7 (channels 1-8) are one
  ring of 8 in file order, rows 8-15 (channels 9-16) the other ring in file order, channel 8 + i sitting between
  channels i - 1 and i (half a position before channel i). This is the plan's default (row 1 = channels 1-8 in file
  order, row 2 = channels 9-16 in file order, no reordering). Which of the two is the band starting at the extensor
  carpi ulnaris is not identifiable; it does not matter here. Row 2 is also proximal/distal to row 1, so A2 is a half
  position offset plus a longitudinal shift.
- the paper says the sensors were not removed between the two sessions of a day, and have to be removed and charged
  after at most 3 hours of recording: day 1 -> day 2 is a re-donning.
- windows: the first 2 s of each trial (samples 0-3999) as one arm_position recording (C features, 19 windows, windows
  9-18 kept -> 10 per trial); sensitivity: samples 4000-7999.
- calibration (day 1 P5, session 1): for each gesture its a-th P5 trial in recorded order is the one-shot calibration
  (60 windows), its (a+1)-th trial the verification (one-shot model, no alignment, as verify_check.py; pass when
  >= 70 % of the 60 windows are right, as TrignoBridge verify); a = 0, 1, 2, the first pass is used. Done per seed
  (each seed is one independent run of the device). A subject is excluded when any of its seeds fails all 3 tries.
- test streams in recorded order (trials.csv row order), 30 trials = 300 windows per block. F = fixed one-shot model,
  no start-up alignment, no update (adapt 0). A = pilot-freeze-3 (adapt 1): start-up alignment on the first 60
  windows of the stream, z-score update, buffer + calibration rows mapped, new trees, update skipped when fewer than
  5 predicted classes have >= 5 windows (stress_check.py variant cls5 = the firmware). The first 60 windows are not
  scored in either F or A, so both are scored on the same windows.
Comparisons: A1 day 1 P5 -> day 2 P5 (both sessions, 2 blocks); A2 day 1 P5 session 2 only (1 block), channels 9-16
(half offset) and channels 1-8 (reference); A3 day 1 P2 / P4 / P6 / P8 (both sessions, 2 blocks each); A4 estimated
rotation of A in A1 / A3 (strap not rotated: k != 0 counts as a false rotation) and its distribution in A2.
With 1 block (A2) the update after the block reaches no scored window: A2 measures F vs start-up alignment only.

Writes results/external_check.csv (per block), external_verify.csv, external_check_summary.csv.
--tag X writes external_checkX*.csv: 2026-11-02 _freeze4 = the alignment confidence rule (report 25), run on this
data AFTER it was used (not independent; the rule was made after seeing report 24).
Usage (in the container, data mounted read-only): python src/external_check.py --data /data [--jobs 16] [--tag X]
"""
import argparse
import ctypes
import os
import sys

import h5py
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_adapt_c as CA  # noqa: E402
import check_features_c as FC  # noqa: E402
import check_selfcal_c as CS  # noqa: E402
import pipeline as P  # noqa: E402
import shift_sweep as SH  # noqa: E402
import stress_check as ST  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
SUBJECTS = range(1, 9)
SEEDS = (0, 1, 2)
ROW1, ROW2 = list(range(0, 8)), list(range(8, 16))
SPANS = {'0-2s': 0, '2-4s': 4000}
REC = 4000
PER_TRIAL = FC.NWIN - FC.W0                          # 10 windows per trial
BLOCK_TRIALS = 30
ALIGN_N, MIN_CLASSES, MIN_WIN = ST.ALIGN_N, 5, ST.MIN_WIN
VERIFY_PASS, VERIFY_TRIES = 70.0, 3
A3_POS = (2, 4, 6, 8)


class Session:
    """one folder: trials.csv in recorded order + the EMG file"""

    def __init__(self, data, p, day, block):
        d = os.path.join(data, 'data', f'participant_{p}', f'participant{p}_day{day}_block{block}')
        self.trials = pd.read_csv(os.path.join(d, 'trials.csv'), index_col=0).sort_values('row_number')
        assert len(self.trials) == 150 and (self.trials.row_number.values == np.arange(150)).all()
        self.path = os.path.join(d, 'emg_data.hdf5')

    def pick(self, position):
        t = self.trials[self.trials.target_position == position]
        return t.row_number.values, t.grasp.values.astype(int) - 1

    def features(self, rows, channels, t0):
        """C features of samples t0 .. t0 + 3999 of `channels` for each trial in `rows` -> (len(rows) * 10, 80)"""
        L = FC.lib()
        out = np.zeros((len(rows), FC.NWIN, 80), dtype=np.float32)
        with h5py.File(self.path, 'r') as f:
            for i, r in enumerate(rows):
                x = np.asarray(f[str(r)], dtype=np.float32)
                assert x.shape[0] == 16 and x.shape[1] >= t0 + REC, x.shape
                rec = np.ascontiguousarray(x[channels, t0:t0 + REC])
                assert L.fe_recording(rec.ctypes.data, REC, out[i].ctypes.data, FC.NWIN) == FC.NWIN
        return out[:, FC.W0:, :].astype(np.float64).reshape(-1, 80)


def stream(sessions, position, channels, t0):
    """test trials of `position` over the sessions in recorded order -> list of (X float32, y) blocks of 30 trials"""
    X, y = [], []
    for s in sessions:
        rows, g = s.pick(position)
        X.append(s.features(rows, channels, t0))
        y.append(np.repeat(g, PER_TRIAL))
    X, y = np.concatenate(X), np.concatenate(y)
    n = BLOCK_TRIALS * PER_TRIAL
    return [(np.ascontiguousarray(X[i:i + n], dtype=np.float32), y[i:i + n]) for i in range(0, len(y), n)]


def run(lib, md, blocks, adapt, seed, subject):
    """F (adapt = False) or A (adapt = True) on the blocks, as rt.c; returns per-block rows"""
    lib.sc_init(ctypes.byref(md['m']), md['cal'].ctypes.data, md['caly'].ctypes.data, len(md['cal']),
                seed * 1000 + subject + 1)
    lib.ad_init(md['mu'].ctypes.data, md['inv'].ctypes.data, md['calf'].ctypes.data, len(md['calf']))
    lib.ad_align_reset()
    k = 0
    if adapt:
        X0 = blocks[0][0]
        for i in range(ALIGN_N):
            lib.ad_align_push(X0[i].ctypes.data)
        k = lib.ad_align_finish()
    al, q = np.zeros(80, np.float32), np.zeros(80, np.int16)
    scale, offset = np.zeros(80, np.float32), np.zeros(80, np.float32)
    rows = []
    for b, (X, y) in enumerate(blocks):
        start = ALIGN_N if b == 0 else 0
        pred = np.full(len(y), -1)
        for i in range(start, len(y)):
            lib.ad_map(X[i].ctypes.data, al.ctypes.data)
            lib.ad_normalize(al.ctypes.data, q.ctypes.data)
            if adapt:
                pred[i] = lib.sc_push(q.ctypes.data)
                lib.ad_observe(al.ctypes.data, int(pred[i]))
            else:
                pred[i] = lib.sc_predict_oneshot(q.ctypes.data)
        skipped = 0
        if adapt:
            present = int((np.bincount(pred[pred >= 0], minlength=6) >= MIN_WIN).sum())
            if present < MIN_CLASSES:
                lib.sc_skip_block()
                lib.ad_skip_block()
                skipped = 1
            else:
                st, ast = CS.Stats(), CA.AdStats()
                lib.ad_end_block_map(ctypes.byref(ast), scale.ctypes.data, offset.ctypes.data)
                if ast.updated:
                    lib.sc_rescale(scale.ctypes.data, offset.ctypes.data, 1)
                lib.sc_end_block(ctypes.byref(st))
        m = np.arange(len(y)) >= start
        rows.append(dict(block=b, k_est=k, n=int(m.sum()), ok=int((pred == y)[m].sum()), skipped=skipped))
    return rows


def calibrate(lib, s, p, seed, t0):
    """one-shot model from day 1 P5 session 1 with the verification retries -> (model or None, verify rows)"""
    rows, g = s.pick(5)
    log = []
    for a in range(VERIFY_TRIES):
        cal = [rows[np.flatnonzero(g == c)[a]] for c in range(6)]
        ver = [rows[np.flatnonzero(g == c)[a + 1]] for c in range(6)]
        Xc, yc = s.features(cal, ROW1, t0), np.repeat(np.arange(6), PER_TRIAL)
        Xv = np.ascontiguousarray(s.features(ver, ROW1, t0), dtype=np.float32)
        md = ST.model(p, seed, Xc, yc)
        lib.sc_init(ctypes.byref(md['m']), md['cal'].ctypes.data, md['caly'].ctypes.data, len(md['cal']), 1)
        lib.ad_init(md['mu'].ctypes.data, md['inv'].ctypes.data, md['calf'].ctypes.data, len(md['calf']))
        q = np.zeros(80, np.int16)
        ok = 0
        for i in range(len(yc)):
            lib.ad_normalize(Xv[i].ctypes.data, q.ctypes.data)
            ok += lib.sc_predict_oneshot(q.ctypes.data) == yc[i]
        acc = ok / len(yc) * 100
        log.append(dict(subject=p, seed=seed, span=t0, attempt=a, verify_acc=acc, passed=acc >= VERIFY_PASS))
        if acc >= VERIFY_PASS:
            return md, log
    return None, log


def job(data, p, seed, span):
    lib = ST.build()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    t0 = SPANS[span]
    d1 = [Session(data, p, 1, b) for b in (1, 2)]
    d2 = [Session(data, p, 2, b) for b in (1, 2)]
    md, vlog = calibrate(lib, d1[0], p, seed, t0)
    for v in vlog:
        v['span'] = span
    if md is None:
        return [], vlog
    tests = {'A1': stream(d2, 5, ROW1, t0), 'A2_row1': stream(d1[1:], 5, ROW1, t0),
             'A2_row2': stream(d1[1:], 5, ROW2, t0)}
    for pos in A3_POS:
        tests[f'A3_P{pos}'] = stream(d1, pos, ROW1, t0)
    out = []
    for comp, blocks in tests.items():
        for var, adapt in (('F', False), ('A', True)):
            for r in run(lib, md, blocks, adapt, seed, p):
                r.update(subject=p, seed=seed, span=span, comp=comp, var=var)
                out.append(r)
    return out, vlog


def paired(d):
    """A - F per subject -> mean, 95 % t CI, Wilcoxon p, better / worse, worst"""
    d = np.asarray(d, dtype=float)
    n = len(d)
    m, se = d.mean(), d.std(ddof=1) / np.sqrt(n)
    h = stats.t.ppf(0.975, n - 1) * se
    return dict(n=n, diff=m, ci_lo=m - h, ci_hi=m + h, wilcoxon_p=stats.wilcoxon(d).pvalue if np.any(d != 0) else 1.0,
                better=int((d > 0).sum()), worse=int((d < 0).sum()), worst=d.min())


def summarise(df, vf):
    fail = vf.groupby(['span', 'subject', 'seed']).passed.any().loc[lambda s: ~s]
    bad = sorted({(sp, s) for sp, s, _ in fail.index})              # (span, subject): any seed failed all tries
    df = df[[(sp, s) not in bad for sp, s in zip(df.span, df.subject)]]
    acc = (df.groupby(['span', 'comp', 'var', 'subject', 'seed'])[['ok', 'n']].sum()
           .assign(acc=lambda g: g.ok / g.n * 100).groupby(['span', 'comp', 'var', 'subject']).acc.mean().unstack('var'))
    rows = []
    for (span, comp), g in acc.groupby(level=['span', 'comp']):
        rows.append(dict(span=span, comp=comp, F=g.F.mean(), A=g.A.mean(), **paired(g.A - g.F),
                         worst_subject=int(g.index.get_level_values('subject')[np.argmin((g.A - g.F).values)])))
    for span, g in acc.groupby(level='span'):                         # A3 pooled: per subject mean over 4 positions
        a3 = g[g.index.get_level_values('comp').str.startswith('A3')].groupby(level='subject').mean()
        rows.append(dict(span=span, comp='A3_all', F=a3.F.mean(), A=a3.A.mean(), **paired(a3.A - a3.F),
                         worst_subject=int(a3.index[np.argmin((a3.A - a3.F).values)])))
    sm = pd.DataFrame(rows)
    ka = df[(df['var'] == 'A') & (df.block == 0)]
    krow = []
    for (span, comp), g in ka.groupby(['span', 'comp']):
        krow.append(dict(span=span, comp=comp, runs=len(g), k_nonzero_pct=(g.k_est != 0).mean() * 100,
                         k_counts=' '.join(f'{k}:{c}' for k, c in g.k_est.value_counts().sort_index().items())))
    sk = df[df['var'] == 'A'].groupby(['span', 'comp']).skipped.sum().rename('skipped_updates').reset_index()
    return sm.merge(pd.DataFrame(krow), on=['span', 'comp'], how='left').merge(sk, on=['span', 'comp'], how='left'), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='/data')
    ap.add_argument('--jobs', type=int, default=16)
    ap.add_argument('--tag', default='')
    args = ap.parse_args()
    ST.build()
    FC.lib()
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(job)(args.data, p, s, sp)
                                                for p in SUBJECTS for s in SEEDS for sp in SPANS)
    df = pd.DataFrame([r for rs, _ in res for r in rs])
    vf = pd.DataFrame([v for _, vs in res for v in vs])
    df.to_csv(os.path.join(OUT, f'external_check{args.tag}.csv'), index=False)
    vf.to_csv(os.path.join(OUT, f'external_verify{args.tag}.csv'), index=False, float_format='%.2f')
    sm, bad = summarise(df, vf)
    sm.to_csv(os.path.join(OUT, f'external_check_summary{args.tag}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 260)
    pd.set_option('display.max_columns', 30)
    print('verification:', vf.groupby(['span', 'subject', 'seed']).attempt.max().add(1).value_counts().to_dict(),
          '(tries used -> runs);', 'excluded subjects:', bad)
    print(sm.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
