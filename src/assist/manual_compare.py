"""Paired simulation comparing ManualControl (manual mode-switch baseline) vs ModeAssist (two-mode + auto intent lock)
under identical targets, seeds, and window error rates, plus statistical power analysis for real Kinova trials.

Usage: python3 src/assist/manual_compare.py [--trials 200] [--scene 3obj|crowded]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assist_sim as S
import manual as MAN
import modes as M
import scenes as SC

X0 = np.array([0.58, 0.0, 0.35])
T_MAX = 900
LEAD = M.V_MAX * M.DT * (S.REACT + S.K) * 0.6
SET6 = ('up', 'down', 'left', 'right', 'switch', 'rest')


def user_modeassist(ma, seen, t_obj, t_shelf, est, shelves):
    if ma.lowering is not None or ma.wait_release:
        return 'rest'
    if ma.m == 2:
        if ma.phase == 'pick':
            if ma.goal != t_obj:
                return 'down'
            return 'rest' if np.linalg.norm(ma.obj[t_obj] - seen) < M.GRASP_TOL else 'up'
        if ma.phase == 'out':
            return 'down'
        if ma.phase == 'place':
            if ma.shelf != t_shelf:
                return 'down'
            if '邊緣' in ma.msg or seen[0] < shelves[t_shelf][0] - 0.01:
                return 'up'
            return 'rest'
        return 'down'
    if ma.held is None:
        tgt = ma.obj[t_obj]
        tol = M.LOCK_ALIGN * 0.6
    else:
        tgt = np.array([0, shelves[t_shelf][1], shelves[t_shelf][2] + M.OBJ_H / 2 + 0.04])
        tol = 0.02
    d = tgt - seen
    d[0] = 0.0
    if np.abs(d[1:]).max() < tol:
        return 'rest'
    i = 1 if abs(d[1]) >= abs(d[2]) else 2
    want = S.axis_cmd(d, (i,))
    if abs(d[i]) < LEAD and est not in (None, 'rest'):
        return 'rest'
    return want


def run_modeassist(obj0, sh, t_obj, t_shelf, e, seed):
    rng = np.random.default_rng(seed)
    ma = M.ModeAssist(obj0.copy(), sh, rule='mix', lock_rule='intent')
    col = M.Collisions(ma)
    dec = S.Decoder(S.SET5, e, rng)
    x = X0.copy()
    hist = [x.copy()] * (S.REACT + 1)
    sw_steps = 0
    for t in range(T_MAX):
        want = user_modeassist(ma, hist[-1 - S.REACT], t_obj, t_shelf, dec.est, sh)
        cmd = dec(want)
        if ma.wait_release:
            sw_steps += 1
        xp = x.copy()
        v = ma.step(cmd if cmd != 'rest' else None, x)
        if ('邊緣' in ma.msg or '太靠近' in ma.msg) and ma.armed is False:
            ma.msg = ''
            ma.armed = True
        x = x + v * M.DT
        col.check(x, xp)
        hist.append(x.copy())
        on = (ma.held is None and ma.m == 1
              and abs(ma.obj[t_obj][2] - (sh[t_shelf][2] + M.OBJ_H / 2)) < 1e-4
              and abs(ma.obj[t_obj][0] - sh[t_shelf][0]) <= M.SHELF_HX - M.EDGE + 1e-4
              and abs(ma.obj[t_obj][1] - sh[t_shelf][1]) <= M.SHELF_HY - M.EDGE + 1e-4)
        if on:
            return True, (t + 1) * M.DT, col.n, ma.switches, 100.0 * sw_steps / (t + 1)
    return False, T_MAX * M.DT, col.n, ma.switches, 100.0 * sw_steps / T_MAX


def run_manual(obj0, sh, t_obj, t_shelf, e, seed):
    rng = np.random.default_rng(seed)
    mc = MAN.ManualControl(obj0.copy(), sh)
    mc.goal = t_obj
    col = M.Collisions(mc)
    dec = S.Decoder(SET6, e, rng)
    x = X0.copy()
    hist = [x.copy()] * (S.REACT + 1)
    sw_steps = 0
    for t in range(T_MAX):
        want = MAN.manual_user(mc, hist[-1 - S.REACT], t_obj, t_shelf, dec.est, LEAD)
        cmd = dec(want)
        # Herlant (2016) mode-switching overhead: steps commanding/executing a switch or waiting for post-switch release
        if want == 'switch' or cmd == 'switch' or mc.wait_release:
            sw_steps += 1
        xp = x.copy()
        v = mc.step(cmd if cmd != 'rest' else None, x)
        x = x + v * M.DT
        col.check(x, xp)
        hist.append(x.copy())
        on = (mc.held is None and mc.m == 1 and mc.at_travel(x)
              and abs(mc.obj[t_obj][2] - (sh[t_shelf][2] + M.OBJ_H / 2)) < 1e-4
              and abs(mc.obj[t_obj][0] - sh[t_shelf][0]) <= M.SHELF_HX - M.EDGE + 1e-4
              and abs(mc.obj[t_obj][1] - sh[t_shelf][1]) <= M.SHELF_HY - M.EDGE + 1e-4)
        if on:
            return True, (t + 1) * M.DT, col.n, mc.switches, 100.0 * sw_steps / (t + 1)
    return False, T_MAX * M.DT, col.n, mc.switches, 100.0 * sw_steps / T_MAX


def power_paired_diff(diffs, n_pairs, n_mc=2000, rng=None):
    """Estimated power of a one-sided paired sign-flip / t-test at alpha=0.05 with n_pairs trials."""
    if rng is None:
        rng = np.random.default_rng(42)
    hits = 0
    for _ in range(n_mc):
        samp = rng.choice(diffs, size=n_pairs, replace=True)
        sd = samp.std(ddof=1)
        if sd > 1e-9 and samp.mean() / (sd / np.sqrt(n_pairs)) > 1.75:
            hits += 1
    return hits / n_mc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trials', type=int, default=200)
    ap.add_argument('--scene', default='crowded', choices=['3obj', 'crowded', 'crowded12'])
    a = ap.parse_args()
    obj0, sh = SC.load(a.scene)
    free = SC.free_shelves(obj0, sh)
    print(f'=== Scene: {a.scene} ({len(obj0)} objects, {len(free)} free shelves), {a.trials} paired trials ===')
    for e in (0.0, 0.10, 0.174, 0.25):
        rng_t = np.random.default_rng(1000)
        res_ma, res_man = [], []
        for i in range(a.trials):
            t_obj = int(rng_t.integers(len(obj0)))
            t_shelf = int(rng_t.choice(free))
            res_ma.append(run_modeassist(obj0, sh, t_obj, t_shelf, e, 2000 + i))
            res_man.append(run_manual(obj0, sh, t_obj, t_shelf, e, 2000 + i))
        ma_ok = np.mean([r[0] for r in res_ma]) * 100
        man_ok = np.mean([r[0] for r in res_man]) * 100
        ma_t = np.array([r[1] for r in res_ma])
        man_t = np.array([r[1] for r in res_man])
        both = [i for i in range(a.trials) if res_ma[i][0] and res_man[i][0]]
        ma_col = np.mean([r[2] > 0 for r in res_ma]) * 100
        man_col = np.mean([r[2] > 0 for r in res_man]) * 100
        ma_sw = np.mean([r[3] for r in res_ma])
        man_sw = np.mean([r[3] for r in res_man])
        ma_swp = np.mean([r[4] for r in res_ma])
        man_swp = np.mean([r[4] for r in res_man])
        diff_all = man_t - ma_t
        pwr12 = power_paired_diff(diff_all, 12) * 100
        pwr24 = power_paired_diff(diff_all, 24) * 100
        print(f'e={e:.3f}:')
        print(f'  ModeAssist: ok={ma_ok:5.1f}%  time={ma_t.mean():5.1f}s (med {np.median(ma_t):4.1f}s)  '
              f'col_trials={ma_col:4.1f}%  switches={ma_sw:4.1f}  sw_time={ma_swp:4.1f}%')
        print(f'  Manual:     ok={man_ok:5.1f}%  time={man_t.mean():5.1f}s (med {np.median(man_t):4.1f}s)  '
              f'col_trials={man_col:4.1f}%  switches={man_sw:4.1f}  sw_time={man_swp:4.1f}%')
        if both:
            db = man_t[both] - ma_t[both]
            print(f'  Paired diff (Manual - ModeAssist): all={diff_all.mean():+5.1f}s '
                  f'(both-ok n={len(both)}: {db.mean():+5.1f}s, med {np.median(db):+5.1f}s) | '
                  f'power @12={pwr12:.0f}% @24={pwr24:.0f}%')


if __name__ == '__main__':
    main()
