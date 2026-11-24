"""Closed-loop pick-and-place with the REAL firmware and hindsight labels (report 35.83): the simulated user of
modes_sim.py; every 100 ms its intended gesture plays 200 recorded raw EMG samples (int16, as the board receives them)
into rt_lda.c (9-class PC build, S7: classes 0x1CF, gate 0.5 mode 2, k 5, stop k 2, report 2 = stop events); the
firmware's commands / stops drive modes.py; labeler.py confirms hindsight labels when an object is put down and they go
back as RTL_LABEL_RANGE (board window = the last event's window + the steps since it, as assist_ros.py board does).

Recorded stretches (one donning, its own calibration as on the board): a direction = a probe cue of that gesture from
its motor onset (activity first >= half the median gesture activity, one window before) to cue_off; the release after a
direction = cue_off of a cue of that gesture to the next cue_on; steady rest = rest periods from 0.5 s after their start
(task rests in postures A / B / C, the releases, Rest cues). A held class outlasts its stretch: another stretch of the
class from 1 s after its start (direction) / from its start (rest).
Held-out design: the cues of every class (and the rest stretches) are split in two pools by alternation; a session
runs N trials, the first half drawing only on pool A, the second half only on pool B (never seen by the model, labelled
or not). Conditions on the same seeds: labels off (the cued-pass model all along) / labels on.
Measured per half: success, time, wrong locks, wrong-direction steps (the arm moves another way than the held
direction), stopped-while-held steps after 1.5 s, range labels sent and windows the firmware added.

usage (container): python src/assist/closed_loop_fw.py --dir /sd/T00 [--days T00_d1_G T00_d2_G] [--sessions 5] [--trials 40]
       [--label-classes all|dirs] [--tag x]
  --label-classes dirs (report 35.85): only the direction labels go to the firmware, no Rest labels (is the loss on
  donning 1 from the many Rest windows?)
  --grip-cmds (35.86): the user grasps with Fist at the object and puts down with HandOpen in the shelf (modes.py
  grip_cmds) instead of relaxing 1 s; Fist / HandOpen recordings are played for them.
  --prior P (35.86): a goal prior from speech / an LLM at the start of every trial: with probability P it names the
  target object (and, separately, the target shelf), else a random other one; the named one gets --prior-mass, the
  rest share the remainder. modes.py: P(g) x prior; a low-prior object / shelf locks only after a 1 s stop.
  --scene crowded (35.87): 6 objects, two side by side (8 cm apart) on each of 3 lower shelves, 3 empty upper shelves
  for putting down (the 3-object scene of 35.63 separates its objects by 25-50 cm).
  --lock-dwell context|all (35.88): a stop locks a crowded object / shelf (another within 10 cm in y-z) only after
  1 s ('context'), crowded objects and every shelf ('place'), or every one ('all'); default none (as before).
"""
import argparse
import ctypes
import os
import struct
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'pc'))
import assist_sim as S  # noqa: E402
import labeler as LB  # noqa: E402
import modes as M  # noqa: E402
import modes_sim as MS  # noqa: E402
import check_rt_lda as R  # noqa: E402
import protocol as PR  # noqa: E402
import selftest_analysis as SA  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

CL = S9.SETS['S7']
MASK = sum(1 << c for c in CL)
REST = S9.REST
NAME = {0: 'up', 1: 'down', 2: 'left', 3: 'right', 6: 'grip_open', 7: 'grip_close', 8: 'rest'}
CLS = {'up': 0, 'down': 1, 'left': 2, 'right': 3, 'rest': 8, 'grip_open': 6, 'grip_close': 7}
GRIP_CMDS = False
LOCK_DWELL = 'none'
LOCK_RULE = 'none'
PRIOR, PRIOR_MASS = None, 0.8
DIRS = ('up', 'down', 'left', 'right')
LSB = np.float32(2.5e-7)
FPP = 20


def build9():
    import subprocess
    lib_path = '/work/build/c/librtl9.so'
    src = [os.path.join(R.CSRC, f) for f in R.SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(lib_path) or os.path.getmtime(lib_path) < max(os.path.getmtime(s) for s in deps):
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-Wextra', '-fPIC', '-shared', '-o', lib_path,
                        '-DLD_CLASSES=9', '-DDC_CLASSES=9', '-DRTL_LABEL_MAX=810'] + src + ['-lm'], check=True)
    lib = ctypes.CDLL(lib_path)
    lib.rtl_init.argtypes = [ctypes.POINTER(R.Config)]
    lib.rtl_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.rtl_idle.restype = None
    return lib


def load(d, name):
    day = S9.load_day(d, name, 4.0, frozenset(CL))
    folder = S9.day_folder(d, name)
    X, t0, _ = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))
    q = np.clip(np.round(X.astype(np.float64) / 2.5e-7), -32768, 32767).astype(np.int16)
    F = SA.features(q.astype(np.float32) * LSB)
    nw = len(F)
    act = F[:, 32:40].sum(1)
    gl = np.isin(day['cal_lab'], CL) & (day['cal_lab'] != REST)
    thr = np.median(act[day['cal_rows'][gl]])
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    fr = lambda ms: int(np.clip(round((ms - t0) / 1000 * SA.FS), 0, len(q)))  # noqa: E731
    cues, rel, rest, on, last = [], [], [], {}, None
    for r in task.itertuples():
        if r.segment == 'labelled' and r.event == 'cue_on':
            if last is not None:
                rel.append((fr(last[0]), fr(r.t), last[1])) if last[1] in (0, 1, 2, 3) else None
                rest.append((fr(last[0] + 500), fr(r.t)))
                last = None
            on[('c', r.step)] = r
        elif r.segment == 'labelled' and r.event == 'cue_off' and ('c', r.step) in on:
            a = on.pop(('c', r.step))
            g = S9.G[r.target]
            if g == REST:
                rest.append((fr(a.t + 500), fr(r.t)))
            elif g in CL:
                w = SA.inside(t0, nw, a.t, r.t)
                i = np.flatnonzero(act[w] >= 0.5 * thr)
                st = int(w[max(int(i[0]) - 1, 0)]) * SA.STEP if len(i) else fr(a.t)
                cues.append((st, fr(r.t), g))
                if g in (0, 1, 2, 3, 6, 7):
                    last = (r.t, g)
        elif r.event == 'seg_end':
            last = None
        elif r.segment == 'task' and r.event == 'rest_on':
            on[('r', r.step)] = r
        elif r.segment == 'task' and r.event == 'rest_off' and ('r', r.step) in on:
            a = on.pop(('r', r.step))
            rest.append((fr(a.t + 500), fr(r.t)))
    return dict(name=name, day=day, q=q, cues=cues, rel=rel, rest=[x for x in rest if x[1] - x[0] >= 2000])


def pools(d):
    """two disjoint pools by alternation within each class"""
    P = [dict(dir={c: [] for c in (0, 1, 2, 3, 6, 7)}, rel={c: [] for c in range(4)}, rest=[]) for _ in range(2)]
    cnt = {}
    for st, en, g in d['cues']:
        if g in (0, 1, 2, 3, 6, 7):
            k = cnt.get(g, 0)
            P[k % 2]['dir'][g].append((st, en))
            cnt[g] = k + 1
    cnt = {}
    for st, en, g in d['rel']:
        k = cnt.get(g, 0)
        P[k % 2]['rel'][g].append((st, en))
        cnt[g] = k + 1
    for k, x in enumerate(d['rest']):
        P[k % 2]['rest'].append(x)
    return P


class Board:
    """the firmware on the PC: calibration as on the board, then 100 ms of samples per step"""

    def __init__(self, lib, d):
        self.lib, self.d = lib, d
        self.enc, self.dec = PR.Encoder(), PR.Decoder()
        self.events, self.status = [], []
        self.txcb = R.TX(self._tx)
        lib.rtl_init(ctypes.byref(R.Config(self.txcb, R.NOW(0), 0, 0, 0, 5)))
        self._ctl(14, bytes([MASK & 0xFF, MASK >> 8]))
        self._ctl(13, bytes([50, 0, 2]))
        self._ctl(5, bytes([0, 0, 0, 0, 5, 2]))
        self._ctl(6, bytes([2]))
        self._ctl(1)
        q = d['q']
        day = d['day']
        rows, lab = day['cal_rows'], day['cal_lab']
        o = np.argsort(rows)
        rows, lab = rows[o], lab[o]
        runs, s0 = [], 0
        for i in range(1, len(rows) + 1):
            if i == len(rows) or rows[i] != rows[i - 1] + 1 or lab[i] != lab[i - 1]:
                runs.append((rows[s0], rows[i - 1], lab[s0]))
                s0 = i
        before = {(a * SA.STEP + SA.WIN) // FPP - 1: g for a, _, g in runs}
        after = {(b * SA.STEP + SA.WIN) // FPP - 1 for _, b, _ in runs}
        fit_after = max(after)
        for k in range(fit_after + 1):
            b = b''
            if k in before:
                b += R.ctl(self.enc, 2, bytes([int(before[k])]))
            b += self.enc.packet(PR.SAMPLES, q[k * FPP:(k + 1) * FPP].tobytes())
            if k in after:
                b += R.ctl(self.enc, 3)
            if k == fit_after:
                b += R.ctl(self.enc, 4)
            self._send(b)
            if k == fit_after:
                lib.rtl_idle()
        assert [v for e, v in self.status if e == 1] == [0], self.status
        self._ctl(1)                                           # stream reset before the session
        self.windows = 0

    def _tx(self, ptr, n):
        for t, _, p in self.dec.feed(ctypes.string_at(ptr, n)):
            if t == PR.COMMAND:
                w, _, cmd, cls, _ = struct.unpack('<IIBBH', p[:12])
                self.events.append((w, cls))
            elif t == PR.STATUS:
                self.status.append(struct.unpack('<B3xi', p[:8]))

    def _send(self, b):
        self.lib.rtl_rx(ctypes.c_char_p(b), len(b))

    def _ctl(self, sub, payload=b''):
        self._send(R.ctl(self.enc, sub, payload))
        self.lib.rtl_idle()

    def feed(self, frames):
        for i in range(0, len(frames), FPP):
            self._send(self.enc.packet(PR.SAMPLES, frames[i:i + FPP].tobytes()))
        self.lib.rtl_idle()

    def label(self, w0, w1, cls):
        n0 = len(self.status)
        self._send(R.ctl(self.enc, 15, struct.pack('<IIB', w0, w1, cls)))
        self.lib.rtl_idle()
        r = [v for e, v in self.status[n0:] if e == 21]
        return r[0] if r else None


class Player:
    """the intended class -> the next 200 recorded samples"""

    def __init__(self, d, pool, rng):
        self.q, self.p, self.rng = d['q'], pool, rng
        self.want, self.seg, self.i = None, None, 0

    def _pick(self, lst):
        return lst[self.rng.integers(len(lst))]

    def frames(self, want):
        if want != self.want:
            if want == 'rest' and self.want in DIRS and self.p['rel'][CLS[self.want]]:
                self.seg = self._pick(self.p['rel'][CLS[self.want]])
            elif want == 'rest':
                self.seg = self._pick(self.p['rest'])
            else:
                self.seg = self._pick(self.p['dir'][CLS[want]])
            self.want, self.i = want, self.seg[0]
        if self.i + SA.STEP > self.seg[1]:
            if want == 'rest':
                self.seg = self._pick(self.p['rest'])
                self.i = self.seg[0]
            else:
                st, en = self._pick(self.p['dir'][CLS[want]])
                self.seg = (min(st + 2000, en - SA.STEP), en)
                self.i = self.seg[0]
        f = self.q[self.i:self.i + SA.STEP]
        self.i += SA.STEP
        return f


LABEL_CLASSES = ('up', 'down', 'left', 'right', 'rest')


# 35.87: crowded scene: lower shelf tops z 0.05, upper 0.25, y -0.25 / 0 / 0.25, x 0.72; two objects per lower shelf
CROWD_LOWER = [(0.72, y, 0.05) for y in (-0.25, 0.0, 0.25)]
CROWD_SHELVES = np.array(CROWD_LOWER + [(0.72, y, 0.25) for y in (-0.25, 0.0, 0.25)])
CROWD_OBJ = np.array([(x, y + dy, z + 0.05) for (x, y, z) in CROWD_LOWER for dy in (-0.04, 0.04)])


def prior_vec(rng, n, target):
    named = target if rng.random() < PRIOR else int(rng.choice([k for k in range(n) if k != target]))
    v = np.full(n, (1 - PRIOR_MASS) / (n - 1))
    v[named] = PRIOR_MASS
    return v, named == target


def trial(board, player, rng, labels_on, st, prng=None):
    ma = M.ModeAssist(MS.OBJ, MS.SHELVES, rule='mix', grip_cmds=GRIP_CMDS, lock_dwell=LOCK_DWELL,
                      lock_rule=LOCK_RULE)
    lab = LB.Labeler(ma)
    t_obj = int(rng.integers(3))
    free = [k for k in range(len(MS.SHELVES))
            if all(np.linalg.norm(o[:2] - MS.SHELVES[k][:2]) > 0.06 or abs(o[2] - (MS.SHELVES[k][2] + M.OBJ_H / 2)) > 0.03
                   for o in MS.OBJ)]
    t_shelf = int(rng.choice(free))
    if PRIOR is not None:
        # 35.88: own stream, so trials stay paired by seed with the no-prior runs (35.86-35.87 drew it from rng)
        ma.base.prior, ok_o = prior_vec(prng, len(MS.OBJ), t_obj)
        sp, ok_s = prior_vec(prng, len(MS.SHELVES), t_shelf)
        ma.shelf_prior = sp
        st['prior_right'] += ok_o + ok_s
        st['prior_n'] += 2
    x = MS.X0.copy()
    hist = [x.copy()] * (S.REACT + 1)
    last_lock, wrong_lock, held = None, 0, 0
    lab_w, lab_want = {}, {}
    for t in range(MS.T_MAX):
        want = MS.user(ma, hist[-1 - S.REACT], t_obj, t_shelf, board.est)
        if GRIP_CMDS and want == 'rest' and ma.m == 2 and ma.lowering is None and not ma.wait_release:
            # the user's grasp / put-down is a Fist / HandOpen instead of a relax (the user policy's relax there)
            if ma.phase == 'pick' and ma.goal == t_obj and np.linalg.norm(ma.obj[t_obj] - hist[-1 - S.REACT]) < M.GRASP_TOL:
                want = 'grip_close'
            elif ma.phase == 'place' and ma.shelf == t_shelf and ma.inside(hist[-1 - S.REACT]):
                want = 'grip_open'
        n0 = len(board.events)
        board.feed(player.frames(want))
        for w, cls in board.events[n0:]:
            board.est = NAME[cls]
            board.last_w, board.last_step = w, board.step
        board.step += 1
        cmd = board.est if board.est in DIRS or (GRIP_CMDS and board.est in M.GRIPS) else 'rest'
        # 35.83 window of this step, as assist_ros.py board estimates it
        w_now = None if board.last_w is None else board.last_w + (board.step - 1 - board.last_step)
        lab.before(cmd if cmd in DIRS else 'rest', x)
        lab_w[lab.k] = w_now
        lab_want[lab.k] = want
        if want in DIRS:
            st['dir_steps'] += 1
            st['dir_wrong'] += cmd in DIRS and cmd != want
        v = ma.step(cmd if cmd != 'rest' else None, x)
        new = lab.after()
        for k_, lb in new:                                 # label vs what the simulated user meant at that step
            st['lab_n'] += 1
            st['lab_ok'] += lab_want.get(k_) == lb
        if labels_on and new:
            runs = []
            for k_, lb in sorted(new):
                w_ = lab_w.get(k_)
                if w_ is None or lb not in LABEL_CLASSES:
                    continue
                if runs and runs[-1][2] == lb and w_ == runs[-1][1] + 1:
                    runs[-1][1] = w_
                elif not (runs and runs[-1][2] == lb and w_ == runs[-1][1]):
                    runs.append([w_, w_, lb])
            for w0, w1, lb in runs:
                r = board.label(w0, w1, CLS[lb])
                st['ranges'] += 1
                st['added'] += max(r or 0, 0)
        if ('邊緣' in ma.msg or '太靠近' in ma.msg) and ma.armed is False:
            ma.msg = ''
            ma.armed = True
        lock = (ma.phase, ma.goal, ma.shelf) if ma.m == 2 else None
        if lock != last_lock and lock is not None and lock[0] in ('pick', 'place'):
            if (lock[0] == 'pick' and lock[1] != t_obj) or (lock[0] == 'place' and lock[2] != t_shelf):
                wrong_lock += 1
                st['wl_' + lock[0]] += 1                    # 35.88: wrong object (pick) or wrong shelf (place)
                if lock[0] == 'place' and not ma.has_room(lock[2]):
                    st['wl_full'] += 1                      # 35.89: a shelf with no free spot
        if lock is not None and ((lock[0] == 'pick' and lock[1] != t_obj) or (lock[0] == 'place' and lock[2] != t_shelf)):
            st['wrong_s'] += M.DT                           # 35.89: time spent in a wrong lock
        last_lock = lock
        x = x + v * M.DT
        hist.append(x.copy())
        on = (ma.held is None and abs(ma.obj[t_obj][2] - (MS.SHELVES[t_shelf][2] + M.OBJ_H / 2)) < 1e-6
              and abs(ma.obj[t_obj][0] - MS.SHELVES[t_shelf][0]) <= M.SHELF_HX - M.EDGE + 1e-6
              and abs(ma.obj[t_obj][1] - MS.SHELVES[t_shelf][1]) <= M.SHELF_HY - M.EDGE + 1e-6)
        if on and ma.m == 1:
            # the backing-out labels come when the arm is back in mode 1: one more labeler step
            st['grip_ok'] += ma.n_grip_ok
            st['grip_refused'] += ma.n_grip_refused
            return True, (t + 1) * M.DT, wrong_lock
    st['grip_ok'] += ma.n_grip_ok
    st['grip_refused'] += ma.n_grip_refused
    return False, MS.T_MAX * M.DT, wrong_lock


def session(lib, d, seed, n, labels_on):
    rng = np.random.default_rng(seed)
    prng = np.random.default_rng(seed + 100000)
    board = Board(lib, d)
    board.est, board.last_w, board.last_step, board.step = 'rest', None, 0, 0
    P = pools(d)
    rows = []
    for half in (0, 1):
        player = Player(d, P[half], rng)
        for i in range(n // 2):
            st = dict(dir_steps=0, dir_wrong=0, ranges=0, added=0, lab_n=0, lab_ok=0, grip_ok=0, grip_refused=0,
                      prior_right=0, prior_n=0, wl_pick=0, wl_place=0, wl_full=0, wrong_s=0.0)
            ok, tm, wl = trial(board, player, rng, labels_on, st, prng)
            rows.append(dict(half=half, ok=ok, time=tm, wrong_locks=wl, **st))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', default=['T00_d1_G', 'T00_d2_G'])
    ap.add_argument('--sessions', type=int, default=5)
    ap.add_argument('--trials', type=int, default=40)
    ap.add_argument('--out', default='/work/results/selftest_T00')
    ap.add_argument('--label-classes', default='all', choices=['all', 'dirs'])
    ap.add_argument('--tag', default='')
    ap.add_argument('--grip-cmds', action='store_true')
    ap.add_argument('--prior', type=float, default=None)
    ap.add_argument('--prior-mass', type=float, default=0.8)
    ap.add_argument('--labels', default='both', choices=['both', 'off', 'on'])
    ap.add_argument('--scene', default='3obj', choices=['3obj', 'crowded'])
    ap.add_argument('--lock-dwell', default='none', choices=['none', 'context', 'place', 'all'])
    ap.add_argument('--lock-rule', default='none', choices=['none', 'room', 'intent'])
    a = ap.parse_args()
    global LOCK_DWELL
    LOCK_DWELL = a.lock_dwell
    global LOCK_RULE
    LOCK_RULE = a.lock_rule
    if a.scene == 'crowded':
        MS.OBJ, MS.SHELVES = CROWD_OBJ.copy(), CROWD_SHELVES.copy()
    global GRIP_CMDS, PRIOR, PRIOR_MASS
    GRIP_CMDS, PRIOR, PRIOR_MASS = a.grip_cmds, a.prior, a.prior_mass
    global LABEL_CLASSES
    if a.label_classes == 'dirs':
        LABEL_CLASSES = ('up', 'down', 'left', 'right')
    lib = build9()
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)
    p(f'closed loop with rt_lda.c (S7, gate 0.5, k 5, stop k 2) and hindsight range labels ({a.label_classes}); '
      f'{a.sessions} sessions x {a.trials} trials; first half pool A, second half pool B (held out); grip commands '
      f'{a.grip_cmds}; goal prior ' + ('off' if a.prior is None else f'P {a.prior} mass {a.prior_mass}')
      + f'; scene {a.scene} ({len(MS.OBJ)} objects, {len(MS.SHELVES)} shelves); lock dwell {a.lock_dwell}; lock rule {a.lock_rule}')
    p('  donning  labels  half   success   time median s   wrong locks/trial   wrong-direction steps   '
      'ranges/trial   windows added/trial   label error (vs intent)')
    allres = []
    for name in a.days:
        d = load(a.dir, name)
        for on in {'both': (False, True), 'off': (False,), 'on': (True,)}[a.labels]:
            res = pd.concat([session(lib, d, 100 + s, a.trials, on).assign(session=s) for s in range(a.sessions)])
            res['labels'], res['donning'] = on, name
            allres.append(res)
            for h in (0, 1):
                r = res[res.half == h]
                tm = r[r.ok].time
                p(f'  {name[4:6]}       {"on " if on else "off"}     {"A" if h == 0 else "B"}     {100 * r.ok.mean():5.1f} %   '
                  f'{np.median(tm) if len(tm) else float("nan"):6.1f}          {r.wrong_locks.mean():5.2f}               '
                  f'{100 * r.dir_wrong.sum() / max(r.dir_steps.sum(), 1):5.1f} %                {r.ranges.mean():5.2f}          '
                  f'{r.added.mean():6.1f}              {100 * (1 - r.lab_ok.sum() / max(r.lab_n.sum(), 1)):5.1f} %'
                  + (f'   grips ok {r.grip_ok.mean():.2f} refused {r.grip_refused.mean():.2f}/trial' if a.grip_cmds else '')
                  + (f'   prior right {100 * r.prior_right.sum() / max(r.prior_n.sum(), 1):.0f} %' if a.prior is not None else '')
                  + f'   wrong locks: object {r.wl_pick.mean():.2f}, shelf {r.wl_place.mean():.2f} '
                  + f'(full {r.wl_full.mean():.2f}); in wrong lock {r.wrong_s.mean():.1f} s/trial')
    df = pd.concat(allres)
    df.to_csv(os.path.join(a.out, f'closed_loop_fw_trials{a.tag}.csv'), index=False)
    # paired: pool B, labels on - off, per session
    if a.labels != 'both':
        with open(os.path.join(a.out, f'closed_loop_fw{a.tag}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        return
    p('\npool B (held out), labels on - off, mean over sessions (paired by seed):')
    for name in a.days:
        b = df[(df.donning == name) & (df.half == 1)]
        g = b.groupby(['labels', 'session'])
        succ = g.ok.mean().unstack(0)
        wd = (g.dir_wrong.sum() / g.dir_steps.sum()).unstack(0)
        tm = g.apply(lambda x: x[x.ok].time.median()).unstack(0)
        p(f'  {name[4:6]}: success {100 * (succ[True] - succ[False]).mean():+.1f} points, wrong-direction steps '
          f'{100 * (wd[True] - wd[False]).mean():+.2f} points, time median {(tm[True] - tm[False]).mean():+.1f} s '
          f'(sessions {len(succ)})')
    with open(os.path.join(a.out, f'closed_loop_fw{a.tag}.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
