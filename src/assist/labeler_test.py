"""labeler.py (online, 35.71) must give exactly the labels of label_sim2.agree2 with N = 6 (offline, 35.70) on the
same pick-and-place (without a buffer limit, and with BUF = label_sim2.buffered), and the same error against the
simulated user's intent.

usage: python src/assist/labeler_test.py [--trials 100]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assist_sim as S  # noqa: E402
import label_sim as LS  # noqa: E402
import label_sim2 as L2  # noqa: E402
import labeler as LB  # noqa: E402
import modes as M  # noqa: E402
import modes_sim as MS  # noqa: E402


def run(e, rng, kind, buf=None):
    """label_sim2.trial with the online labeler alongside; returns (ok, rec, ma, online {step: label})"""
    ma = M.ModeAssist(MS.OBJ, MS.SHELVES)
    lab = LB.Labeler(ma, buf=buf)
    t_obj = int(rng.integers(3))
    free = [k for k in range(len(MS.SHELVES))
            if all(np.linalg.norm(o[:2] - MS.SHELVES[k][:2]) > 0.06
                   or abs(o[2] - (MS.SHELVES[k][2] + M.OBJ_H / 2)) > 0.03 for o in MS.OBJ)]
    t_shelf = int(rng.choice(free))
    user = L2.User(kind, rng, t_obj)
    dec = LS.RawDecoder(S.SET5, e, rng)
    x = MS.X0.copy()
    hist = [x.copy()] * (S.REACT + 1)
    rec, online = [], {}
    pick_pos = None
    for t in range(MS.T_MAX):
        seen = hist[-1 - S.REACT]
        want = user(ma, seen, t_obj, t_shelf, dec.est)
        cmd = dec(want)
        r = dict(want=want, raw=dec.raw, cmd=cmd, m=ma.m, phase=ma.phase, x=x.copy(), held=ma.held,
                 lowering=ma.lowering is not None, wait=ma.wait_release, lock=None)
        held0 = ma.held
        if held0 is None and ma.phase == 'pick' and ma.goal is not None:
            pick_pos = ma.obj[ma.goal].copy()
        lab.before(cmd, x)
        v = ma.step(cmd if cmd != 'rest' else None, x)
        if ('邊緣' in ma.msg or '太靠近' in ma.msg) and ma.armed is False:
            ma.msg, ma.armed = '', True
        r['grasp'] = held0 is None and ma.held is not None
        r['put'] = held0 is not None and ma.held is None
        if r['grasp']:
            r['pick_pos'] = pick_pos
        online.update(dict(lab.after()))
        rec.append(r)
        x = x + v * M.DT
        hist.append(x.copy())
        on = (ma.held is None and abs(ma.obj[t_obj][2] - (MS.SHELVES[t_shelf][2] + M.OBJ_H / 2)) < 1e-6
              and abs(ma.obj[t_obj][0] - MS.SHELVES[t_shelf][0]) <= M.SHELF_HX - M.EDGE + 1e-6
              and abs(ma.obj[t_obj][1] - MS.SHELVES[t_shelf][1]) <= M.SHELF_HY - M.EDGE + 1e-6)
        if on and ma.m == 1:
            # the trial ends at the first mode-1 step: let the labeler see it (it closes the backing out)
            lab.before('rest', x)
            online.update(dict(lab.after()))
            return True, rec, ma, online
    return False, rec, ma, online


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trials', type=int, default=100)
    a = ap.parse_args()
    E = S.window_errors()
    ok_all = True
    for kind, buf in [(k_, None) for k_ in L2.USERS] + [(k_, LB.BUF) for k_ in L2.USERS]:
        rng = np.random.default_rng(4242 + L2.USERS.index(kind))
        same = n = n_on = wrong = 0
        for _ in range(a.trials):
            ok, rec, ma, online = run(E['G9'], rng, kind, buf)
            if not ok:
                continue
            off = L2.agree2(rec, ma, LB.N_TAIL)
            if buf is not None:
                off = L2.buffered(rec, off, buf)
            offd = {i: l for i, l in enumerate(off) if l is not None}
            same += offd == online
            n += 1
            n_on += len(online)
            wrong += sum(1 for i, l in online.items() if rec[i]['want'] != l)
        ok_k = same == n
        ok_all &= ok_k
        print(f'  {"ok " if ok_k else "BAD"}  {kind:11s} buffer {str(buf):5s}  online == offline in {same}/{n} trials; '
              f'online labels {n_on}, error {100 * wrong / max(n_on, 1):.2f} %')
    print('ALL OK' if ok_all else 'FAILED')


if __name__ == '__main__':
    main()
