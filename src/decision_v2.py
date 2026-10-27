"""Decision module on the firmware v2 votes: rejection threshold tau x smoothing rule, chosen across subjects.

1. Votes: the v2 chain in C exactly as check_adapt_c.run_c (update = 1: start-up alignment, class-balanced z-score
   update, self-calibration without t-SNE), but with sc_push_votes / sc_votes_oneshot so the 100 tree votes of every
   100 ms window are kept, for the self-calibrated and the fixed one-shot model. 20 subjects x 3 seeds, electrode
   offsets 0 and 1/2 (C features of the raw-EMG rotation, shift_sweep.py --raw). Cached in build/decision/votes_v2.npz.
2. Rules (state reset at every trial: the data set holds 1 s = 10 windows per trial):
     streak k    decision.c as on the device: k consecutive accepted windows with the same top class
                 (replayed with the C dc_replay, as eval_decision.py)
     major N     new, Python only: of the last N windows (rejected windows count as no vote), a class with more than
                 N / 2 of them is established
   Established class != latched class -> its command is sent (Lateral / Rest send nothing), as decision.c.
3. Metrics per setting (eval_decision.metrics, plus):
     effective   trial-level accuracy: command trials whose first command is right + Rest / Lateral trials with no
                 command, over all trials
     wrong_per_min, latency_ms (trial start -> first right command), correct_trial (command trials only)
4. Choice without looking at the subject it is applied to: leave one subject out, the setting with the best mean
   'effective' on the other 19 at offset 0 (the setting is fixed before the offset is known) is applied to the
   held-out subject at both offsets; also with the constraint wrong_per_min <= 1 on the 19. Compared per subject
   (paired Wilcoxon) with the firmware placeholder tau = 0.6, streak 3 (main_rt.c).
Writes results/decision_v2_sweep.csv (per setting, all subjects), decision_v2_loso.csv (per held-out subject) and
decision_v2_summary.csv.
Usage (in the container): python src/decision_v2.py [--jobs 19]
"""
import argparse
import ctypes
import os
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_adapt_c as AC  # noqa: E402
import check_oneshot_c as CO  # noqa: E402
import check_selfcal_c as CS  # noqa: E402
import eval_decision as ED  # noqa: E402
import pipeline as P  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
VOTES = os.path.join(P.ROOT, 'build', 'decision', 'votes_v2.npz')
TAUS = ED.TAUS
RULES = [('streak', k) for k in (1, 2, 3, 4, 5)] + [('major', n) for n in (3, 5, 7)]
DEFAULT = ('streak', 3, 0.6)
WPM_MAX = 1.0


def record(subject, seed, shift):
    lib = AC.build()
    lib.sc_push_votes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.sc_votes_oneshot.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    # the same set-up as check_adapt_c.run_c, then the stream with votes
    import copy
    import export_c
    import rf_size
    import selfcal_sweep as S
    import shift_sweep as SH
    from pipeline import emg_functions
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    np.random.seed(seed * 1000 + subject)
    z = np.load(SH.prepare(subject, shift))
    Xc_raw, yc = z['Xc'], z['yc']
    blocks = [(z[f'X{b}'], z[f'y{b}']) for b in range(P.N_BLOCKS)]
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    Xc = (Xc_raw - mu) / np.sqrt(var)
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), SH.DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, 50, SH.DEPTH, None)
    mdl = rf_size.compact_forest(emg_functions.append(P.subset(pruned, range(50)), app))
    arrs = [np.ascontiguousarray(a, dtype=t) for a, t in
            zip(export_c.table_arrays(mdl, 'int16'), [np.uint32, np.uint8, np.int16, np.uint16, np.uint16])]
    m = CS.Model(*[a.ctypes.data for a in arrs])
    cal = np.ascontiguousarray(P.quantize(Xc))
    caly = np.ascontiguousarray(yc.astype(np.uint8))
    lib.sc_init(ctypes.byref(m), cal.ctypes.data, caly.ctypes.data, len(cal), seed * 1000 + subject + 1)
    mu32 = np.ascontiguousarray(mu, dtype=np.float32)
    inv32 = np.ascontiguousarray(1.0 / np.sqrt(var), dtype=np.float32)
    calf = np.ascontiguousarray(Xc_raw, dtype=np.float32)
    lib.ad_init(mu32.ctypes.data, inv32.ctypes.data, calf.ctypes.data, len(calf))
    lib.ad_align_reset()
    for r in np.ascontiguousarray(blocks[0][0], dtype=np.float32):
        lib.ad_align_push(r.ctypes.data)
    lib.ad_align_finish()
    out = {k: [] for k in ['votes_sc', 'votes_os', 'y', 'trial']}
    al, q = np.zeros(80, np.float32), np.zeros(80, np.int16)
    for b, (X_raw, y) in enumerate(blocks):
        X32 = np.ascontiguousarray(X_raw, dtype=np.float32)
        vs, vo = np.zeros((len(y), 6), np.uint16), np.zeros((len(y), 6), np.uint16)
        for i in range(len(y)):
            lib.ad_map(X32[i].ctypes.data, al.ctypes.data)
            lib.ad_normalize(al.ctypes.data, q.ctypes.data)
            lib.sc_votes_oneshot(q.ctypes.data, vo[i].ctypes.data)
            pred = lib.sc_push_votes(q.ctypes.data, vs[i].ctypes.data)
            lib.ad_observe(al.ctypes.data, int(pred))
        lib.sc_end_block(ctypes.byref(CS.Stats()))
        lib.ad_end_block(ctypes.byref(AC.AdStats()))
        out['votes_sc'].append(vs)
        out['votes_os'].append(vo)
        out['y'].append(y.astype(np.int8))
        out['trial'].append((b * 100 + np.arange(len(y)) // 10).astype(np.int32))
    res = {k: np.concatenate(v) for k, v in out.items()}
    res['subject'] = np.full(len(res['y']), subject, np.int16)
    res['seed'] = np.full(len(res['y']), seed, np.int16)
    res['shift'] = np.full(len(res['y']), shift, np.float32)
    return res


def replay_major(votes, seg, tau, n):
    """majority of the last n windows (rejected = no vote), as decision.c otherwise"""
    tp = int(round(tau * 1000))
    top = np.argmax(votes, axis=1)
    ok = votes[np.arange(len(votes)), top].astype(np.int64) * 1000 >= tp * ED.TREES
    cmd = np.zeros(len(votes), dtype=np.int8)
    hist, latched = [], -1
    for i in range(len(votes)):
        if i == 0 or seg[i] != seg[i - 1]:
            hist, latched = [], -1
        hist.append(int(top[i]) if ok[i] else -1)
        if len(hist) > n:
            hist.pop(0)
        cnt = np.bincount([h for h in hist if h >= 0], minlength=6)
        c = int(np.argmax(cnt))
        if cnt[c] * 2 > n and c != latched:
            latched = c
            cmd[i] = ED.CLASS_CMD[c]
    return cmd, ok


def metrics(votes, y, seg, cmd, acc):
    r = ED.metrics(votes, y, seg, cmd, acc)
    want = ED.CLASS_CMD[y]
    df = pd.DataFrame(dict(seg=seg, want=want, cmd=cmd))
    first = df[df.cmd != 0].groupby('seg').cmd.first()
    t = df.groupby('seg').want.first().to_frame().join(first, how='left')
    good = np.where(t.want != 0, t.cmd == t.want, t.cmd.isna())
    r['effective'] = good.mean()
    return r


def evaluate(lib, d, rule, par, tau):
    if rule == 'streak':
        cmd, acc, _ = ED.replay(lib, d['votes'], d['seg'], tau, par)
    else:
        cmd, acc = replay_major(d['votes'], d['seg'], tau, par)
    return metrics(d['votes'], d['y'], d['seg'], cmd, acc)


def per_subject(data, model, shift, subject):
    lib = CO.build()
    key = 'votes_sc' if model == 'selfcal' else 'votes_os'
    sel = (data['subject'] == subject) & (data['shift'] == shift)
    seg = np.unique(data['seed'][sel].astype(np.int64) * 100000 + data['trial'][sel], return_inverse=True)[1]
    d = dict(votes=data[key][sel], y=data['y'][sel], seg=seg.astype(np.int32))
    assert (np.bincount(d['seg']) == 10).all()
    return [dict(model=model, shift=shift, subject=subject, rule=rule, par=par, tau=tau,
                 **evaluate(lib, d, rule, par, tau)) for rule, par in RULES for tau in TAUS]


def loso(ps, model, constrained):
    """per held-out subject: setting chosen on the other subjects at offset 0, applied at every offset"""
    keys = ['rule', 'par', 'tau']
    base = ps[(ps.model == model) & (ps['shift'] == 0)]
    out = []
    for s in sorted(set(ps.subject)):
        tr = base[base.subject != s].groupby(keys)[['effective', 'wrong_per_min']].mean()
        if constrained:
            tr = tr[tr.wrong_per_min <= WPM_MAX]
        rule, par, tau = tr.effective.idxmax()
        for sh in sorted(set(ps['shift'])):
            g = ps[(ps.model == model) & (ps['shift'] == sh) & (ps.subject == s)].set_index(keys)
            out.append(dict(model=model, shift=sh, subject=s, constrained=constrained, rule=rule, par=par, tau=tau,
                            **g.loc[(rule, par, tau)].drop(['model', 'shift', 'subject']).to_dict(),
                            **{f'default_{c}': g.loc[DEFAULT][c] for c in
                               ['effective', 'correct_trial', 'wrong_per_min', 'latency_ms', 'rejected']}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.5])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    AC.build()
    CO.build()
    import check_features_c as FC
    import shift_sweep as SH
    FC.lib()
    votes_path = VOTES.replace('.npz', f'{args.suffix}.npz')
    if not os.path.exists(votes_path):
        Parallel(n_jobs=args.jobs)(delayed(SH.prepare)(s, sh) for sh in args.shifts for s in args.subjects)
        import decision_v2 as M                                      # pickle by reference
        res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(M.record)(s, sd, sh) for sh in args.shifts
                                                    for sd in args.seeds for s in args.subjects)
        data = {k: np.concatenate([r[k] for r in res]) for k in res[0]}
        os.makedirs(os.path.dirname(votes_path), exist_ok=True)
        np.savez_compressed(votes_path, **data)
    data = dict(np.load(votes_path))
    print(f'votes ready after {time.time() - t0:.0f} s, {len(data["y"])} windows', flush=True)
    import decision_v2 as M
    res = Parallel(n_jobs=args.jobs, verbose=2)(delayed(M.per_subject)(data, mdl, sh, s) for mdl in ('selfcal', 'oneshot')
                                                for sh in args.shifts for s in args.subjects)
    ps = pd.DataFrame([r for rows in res for r in rows])
    sw = ps.groupby(['model', 'shift', 'rule', 'par', 'tau']).mean(numeric_only=True).drop(columns='subject').reset_index()
    sw.to_csv(os.path.join(OUT, f'decision_v2_sweep{args.suffix}.csv'), index=False, float_format='%.5g')
    lo = pd.DataFrame([r for mdl in ('selfcal', 'oneshot') for c in (False, True) for r in loso(ps, mdl, c)])
    lo.to_csv(os.path.join(OUT, f'decision_v2_loso{args.suffix}.csv'), index=False, float_format='%.5g')
    summ = []
    for (mdl, sh, c), g in lo.groupby(['model', 'shift', 'constrained']):
        row = dict(model=mdl, shift=sh, constrained=c,
                   chosen=' '.join(f'{k}:{n}' for k, n in (g.rule + g.par.astype(str) + '@' + g.tau.astype(str))
                                   .value_counts().items()))
        for col in ['effective', 'correct_trial', 'wrong_per_min', 'latency_ms', 'rejected']:
            row[col], row[f'default_{col}'] = g[col].mean(), g[f'default_{col}'].mean()
        d = g.effective - g.default_effective
        row['effective_better'] = int((d > 0).sum())
        row['effective_p'] = wilcoxon(g.effective, g.default_effective).pvalue if np.any(d != 0) else 1.0
        summ.append(row)
    s = pd.DataFrame(summ)
    s.to_csv(os.path.join(OUT, f'decision_v2_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 260)
    pd.set_option('display.max_colwidth', 60)
    print(s.round(4).to_string(index=False))
    best = sw[(sw.model == 'selfcal')].sort_values('effective', ascending=False)
    for sh in args.shifts:
        print(f'top settings (all subjects, selfcal, offset {sh}):')
        print(best[best['shift'] == sh].head(8).round(4).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
