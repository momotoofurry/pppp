"""A natural start posture for the assist demo (report 35.72).

The start pose fixes only the tool (0.58, 0, 0.35), pointing forward with the fingers closing sideways (35.64); the
7-DoF arm has a whole family of postures for it. Until now the start was the solution with the largest joint-limit
margin, which turned joint 1 by 48 deg and put the elbow out to the side (the user found it odd). Here: many IK
solutions from random seeds; keep those with every limited joint >= MIN_MARGIN from its limit; among them the most
natural one:
  lateral  distance of the elbow (joint 4) and the wrist (joint 6) from the vertical plane through the base axis and
           the tool (the arm 'in line' from the base to the tool, nothing sticking out sideways)
  elbow up the elbow above the line from the shoulder (joint 2) to the wrist (a table-top arm reaching forward)
Then the whole demo path (pick / place at every object and shelf, rd_check.py's path) with the posture task pulling
back to it: worst joint margin and how far the elbow drifts sideways on the way.

usage: python src/assist/natural_start.py [--n 400]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kin  # noqa: E402

RD = np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]], float)
X0 = np.array([0.58, 0.0, 0.35])
MIN_MARGIN = np.radians(15)
OBJ = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])


def joints_xyz(q):
    """positions of joint 1 .. 7 origins (after each joint's fixed transform) in base_link"""
    T = np.eye(4)
    out = []
    for (xyz, r), qi in zip(kin.ORIGINS, q):
        T = T @ kin.tf(xyz, r)
        out.append(T[:3, 3].copy())
        T = T @ kin.rotz(qi)
    return np.array(out)


def lateral(q, tool=None):
    P = joints_xyz(q)
    tool = kin.fk(q)[:3, 3] if tool is None else tool
    d = np.array([tool[0], tool[1], 0.0])
    n = np.cross([0, 0, 1.0], d / max(np.linalg.norm(d), 1e-9))       # normal of the vertical plane base -> tool
    return abs(n @ P[3]) + abs(n @ P[5])


def elbow_up(q):
    P = joints_xyz(q)
    sh, el, wr = P[1], P[3], P[5]
    t = np.clip((el - sh) @ (wr - sh) / max((wr - sh) @ (wr - sh), 1e-9), 0, 1)
    return el[2] - (sh + t * (wr - sh))[2]                                 # > 0: elbow above the shoulder-wrist line


def path(q0):
    q, q_rest = q0.copy(), q0.copy()
    pts = []
    for o in OBJ:
        pts += [np.array([0.58, o[1], o[2]]), o, np.array([0.58, o[1], o[2]]), X0]
    pts += [np.array([0.58, -0.25, 0.10]), np.array([0.76, -0.25, 0.10]), np.array([0.58, -0.25, 0.10]),
            np.array([0.58, 0.25, 0.30]), np.array([0.76, 0.25, 0.30]), X0]
    worst, lat, err = 1e9, 0.0, 0.0
    for tgt in pts:
        for _ in range(300):
            d = tgt - kin.fk(q)[:3, 3]
            if np.linalg.norm(d) < 0.002:
                break
            q = kin.ik_step(q, min(0.08, np.linalg.norm(d) / 0.1) * d / np.linalg.norm(d), RD, 0.1, posture=True,
                            q_rest=q_rest)
            worst = min(worst, kin.margin(q))
            lat = max(lat, lateral(q))
        err = max(err, np.linalg.norm(tgt - kin.fk(q)[:3, 3]))
    return worst, lat, err, q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=400)
    a = ap.parse_args()
    rng = np.random.default_rng(0)
    lim = np.array([np.pi, 2.41, np.pi, 2.66, np.pi, 2.23, np.pi])
    sols = []
    for i in range(a.n):
        q0 = rng.uniform(-lim * 0.9, lim * 0.9)
        q = kin.solve(q0, X0, RD, iters=800)
        pe = np.linalg.norm(kin.fk(q)[:3, 3] - X0)
        re = np.degrees(np.linalg.norm(kin.rot_err(kin.fk(q)[:3, :3], RD)))
        if pe < 0.002 and re < 1.0:
            sols.append(np.array([kin.wrap(v) for v in q]))
    print(f'{len(sols)} of {a.n} seeds reach the start pose')
    ok = [q for q in sols if kin.margin(q) >= MIN_MARGIN]
    print(f'{len(ok)} with every limited joint >= {np.degrees(MIN_MARGIN):.0f} deg from its limit')
    up = [q for q in ok if elbow_up(q) > 0]
    cand = sorted(up or ok, key=lateral)
    # distinct postures (rounded joints) for the report
    seen, rows = set(), []
    for q in cand:
        key = tuple(np.round(np.degrees(q) / 5).astype(int))
        if key in seen:
            continue
        seen.add(key)
        rows.append(q)
        if len(rows) == 5:
            break
    old = np.radians([48, 66, 271, 135, -15, -84, 162])
    old = kin.solve(old, X0, RD, iters=800)
    print('  candidate                                   lateral  elbow-up  margin | path: worst margin  max lateral  end err')
    for name, q in [('old start (largest margin)', old)] + [(f'natural #{i + 1}', q) for i, q in enumerate(rows)]:
        w, lat, err, _ = path(q)
        print(f'  {name:28s} {np.round(np.degrees(q)).astype(int).tolist()!s:38s} '
              f'{100 * lateral(q):5.1f} cm  {100 * elbow_up(q):+5.1f} cm  {np.degrees(kin.margin(q)):5.1f} | '
              f'{np.degrees(w):12.1f} deg  {100 * lat:7.1f} cm  {1000 * err:5.1f} mm')


if __name__ == '__main__':
    main()
