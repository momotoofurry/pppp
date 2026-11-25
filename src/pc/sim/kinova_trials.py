"""Trial logger for the real-arm study (report 35.101; lab_kit/實驗設計_Kinova實機.md).

  make: the balanced trial list of one day, written (and committed) BEFORE the session
    python3 src/pc/sim/kinova_trials.py make --scene crowded --n 24 --practice 2 --seed 101 --out trials_T00_k1.csv
    every object the same number of times, the put-down shelves (the empty ones) as equal as possible, random order
  run: one session, next to assist_ros.py board --scene <same> --trial-port 50570 --task-events task_events.csv
    python3 src/pc/sim/kinova_trials.py run --list trials_T00_k1.csv --events task_events.csv --out k1_trials.csv
    per trial: shows the target -> (helper) Enter -> 'reset,<id>' to assist_ros (gripper open, arm to the start pose,
    objects back at their start positions in the assist) -> GO; the first put-down ends the trial:
      success       the target object on the target shelf (assist_ros 'putdown' event: object, the shelf it stands on)
                    AND the helper confirms it really stands there (y); n -> failed_physical
                    (the software's put-down alone is not proof: report 35.101)
      wrong_object / wrong_shelf / not_on_shelf / timeout (--limit s, default 90) / abort:<reason> (helper: x + Enter)
    counts per trial: wrong object locks, wrong shelf locks, grasps of another object. Rows are written at once.
    Every 8 scored trials a 60 s break (Enter skips). --auto: no waits (Gazebo rehearsal).
"""
import argparse
import csv
import os
import select
import socket
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assist'))
import scenes as SC  # noqa: E402

COLS = ['trial', 'practice', 'target_obj', 'target_shelf', 'outcome', 'time_s', 'put_obj', 'put_shelf',
        'wrong_lock_obj', 'wrong_lock_shelf', 'wrong_grasp', 'air_grasp', 'start_unix_ms', 'end_unix_ms', 'helper_ok',
        'note']


def make_list(scene, n, practice, seed):
    """-> rows (trial, practice, obj, shelf): practice trials first, then n scored ones"""
    obj, shelves = SC.load(scene)
    free = SC.free_shelves(obj, shelves)
    no = len(obj)
    assert n % no == 0, f'--n must be a multiple of the {no} objects'
    rng = np.random.default_rng(seed)
    objs = rng.permutation(np.repeat(np.arange(no), n // no))
    sh = rng.permutation(np.resize(np.array(free), n))
    rows = [(i + 1, 1, int(rng.integers(no)), int(rng.choice(free))) for i in range(practice)]
    rows += [(practice + i + 1, 0, int(o), int(s)) for i, (o, s) in enumerate(zip(objs, sh))]
    return rows


class Events:
    """tails assist_ros.py's task-events file (reopened from the start when assist_ros rewrites it)"""

    def __init__(self, path):
        self.path, self.f, self.pos = path, None, 0
        if os.path.exists(path):
            self.pos = os.path.getsize(path)            # only events from now on

    def read(self):
        out = []
        if not os.path.exists(self.path):
            return out
        size = os.path.getsize(self.path)
        if size < self.pos:                             # assist_ros restarted: a new file
            self.pos = 0
        with open(self.path, encoding='utf-8') as f:
            f.seek(self.pos)
            for line in f:
                if not line.endswith('\n'):
                    break                                # half-written line: next time
                self.pos += len(line.encode('utf-8'))
                p = line.rstrip('\n').split(',')
                if len(p) >= 3 and p[0] != 'unix_ms':
                    out.append(dict(ms=float(p[0]), ev=p[2], a=p[3] if len(p) > 3 else '', b=p[4] if len(p) > 4 else '',
                                    detail=','.join(p[5:]) if len(p) > 5 else ''))
        return out


def judge(target_obj, target_shelf, put_obj, put_shelf):
    if put_obj != target_obj:
        return 'wrong_object'
    if put_shelf is None:
        return 'not_on_shelf'
    if put_shelf != target_shelf:
        return 'wrong_shelf'
    return 'success'


class Session:
    """one trial at a time; send(line) talks to assist_ros, events.read() returns its new events, ask(prompt) waits
    for the helper (Enter) and line() polls a typed line during a trial (None when nothing)"""

    def __init__(self, send, events, limit=90.0, auto=False, ask=None, line=None, say=print, clock=time.time):
        self.send, self.events, self.limit, self.auto = send, events, limit, auto
        self.ask = ask or (lambda p: input(p))
        self.line = line or (lambda: None)
        self.say, self.clock = say, clock
        self.pending = []                               # events read together with the reset answer, for the trial

    def _read(self):
        out, self.pending = self.pending + self.events.read(), []
        return out

    def reset(self, tid):
        """-> start time (unix ms) once assist_ros confirmed the reset"""
        force = False
        while True:
            self.send(f'reset,{tid}' + (',force' if force else ''))
            t0 = self.clock()
            got = None
            while got is None and self.clock() - t0 < 10.0:
                evs = self._read()
                for i, e in enumerate(evs):
                    if e['ev'] in ('reset_done', 'reset_refused') and e['a'] == str(tid):
                        got = e
                        self.pending = evs[i + 1:]      # later events belong to the trial
                        break
                if got is None:
                    time.sleep(0.05)
            if got is None:
                self.say('  !! 手臂程式沒有回應（assist_ros 有開 --trial-port 嗎？），再送一次')
                continue
            if got['ev'] == 'reset_done':
                return got['ms']
            if got['detail'] == 'holding':
                if self.auto:
                    force = True
                else:
                    self.ask('  夾爪還夾著物體：協助者扶住物體後按 Enter，夾爪會張開、手臂回起點 ')
                    force = True
            else:
                self.say('  手臂在模式 2：請受試者用 S 退回前方平面')
                if not self.auto:
                    self.ask('  退出來之後按 Enter ')
                else:
                    time.sleep(1.0)

    def trial(self, tid, practice, obj, shelf, names):
        on, sn = names
        self.say('')
        self.say('=' * 60)
        self.say(f'  {"練習" if practice else "試驗"} {tid}：把【{on[obj]}】（物體 {obj}）放到【{sn[shelf]}】（架子 {shelf}）')
        self.say('=' * 60)
        if not self.auto:
            self.ask('  協助者：上一個物體已從上層架子拿下、6 個物體都在原位（照記號），受試者準備好後按 Enter ')
        start = self.reset(tid)
        self.say(f'\a  開始！限時 {self.limit:.0f} 秒（中止：協助者輸入 x 再按 Enter）')
        r = dict(trial=tid, practice=practice, target_obj=obj, target_shelf=shelf, outcome='', time_s='', put_obj='',
                 put_shelf='', wrong_lock_obj=0, wrong_lock_shelf=0, wrong_grasp=0, air_grasp=0, start_unix_ms=f'{start:.0f}',
                 end_unix_ms='', helper_ok='', note='')
        while True:
            now = self.clock() * 1000
            for e in self._read():
                if e['ms'] < start:
                    continue
                if e['ev'] == 'lock_obj' and e['a'] != str(obj):
                    r['wrong_lock_obj'] += 1
                elif e['ev'] == 'lock_shelf' and e['a'] != str(shelf):
                    r['wrong_lock_shelf'] += 1
                elif e['ev'] == 'grasp' and e['a'] != str(obj):
                    r['wrong_grasp'] += 1
                elif e['ev'] == 'grip_empty':             # 35.107: closed on air (assist_ros --grip-check)
                    r['air_grasp'] += 1
                elif e['ev'] == 'putdown':
                    po = int(e['a'])
                    ps = int(e['b']) if e['b'] != '' else None
                    r.update(outcome=judge(obj, shelf, po, ps), put_obj=po, put_shelf='' if ps is None else ps,
                             time_s=f'{(e["ms"] - start) / 1000:.1f}', end_unix_ms=f'{e["ms"]:.0f}', note=e['detail'])
                    # 35.101: the software's put-down is not proof (Gazebo rehearsal: an object pushed away, never
                    # grasped, still counted): the helper confirms the object really stands on the target shelf
                    if not self.auto:
                        ans = ''
                        while ans not in ('y', 'n'):
                            ans = self.ask('  協助者：目標物體真的站在目標架子上嗎？（y／n）').strip().lower()[:1]
                        r['helper_ok'] = ans
                        if ans == 'n' and r['outcome'] == 'success':
                            r['outcome'] = 'failed_physical'
                    return r
            typed = self.line()
            if typed is not None and typed.strip().lower().startswith('x'):
                why = self.ask('  中止原因（例如 急停／掉落／其他）：').strip() or 'unspecified'
                r.update(outcome=f'abort:{why}', time_s=f'{(now - start) / 1000:.1f}', end_unix_ms=f'{now:.0f}')
                return r
            if now - start > self.limit * 1000:
                r.update(outcome='timeout', time_s=f'{self.limit:.1f}', end_unix_ms=f'{now:.0f}')
                return r
            time.sleep(0.05)


def summary(rows, say=print):
    sc = [r for r in rows if not int(r['practice'])]
    if not sc:
        return
    ok = [r for r in sc if r['outcome'] == 'success']
    t = np.array([float(r['time_s']) if r['outcome'] == 'success' else np.nan for r in sc], float)
    say('')
    say(f'計分試驗 {len(sc)} 個：成功 {len(ok)}（{100 * len(ok) / len(sc):.1f} %）；'
        f'成功試驗的時間中位數 {np.nanmedian(t) if len(ok) else float("nan"):.1f} s；'
        f'鎖錯物體 {np.mean([int(r["wrong_lock_obj"]) for r in sc]):.2f}、鎖錯架子 '
        f'{np.mean([int(r["wrong_lock_shelf"]) for r in sc]):.2f} 次／試驗')
    other = {}
    for r in sc:
        if r['outcome'] != 'success':
            other[r['outcome']] = other.get(r['outcome'], 0) + 1
    if other:
        say('失敗：' + '、'.join(f'{k} {v}' for k, v in other.items()))
    say('（K1 用兩天合計判定：成功率 >= 80 % 且沒有系統造成的安全事件）')


def stdin_line():
    if not sys.stdin.isatty():
        return None
    r, _, _ = select.select([sys.stdin], [], [], 0)
    return sys.stdin.readline() if r else None


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('make')
    m.add_argument('--scene', default='crowded')
    m.add_argument('--n', type=int, default=24)
    m.add_argument('--practice', type=int, default=2)
    m.add_argument('--seed', type=int, required=True)
    m.add_argument('--out', required=True)
    r = sub.add_parser('run')
    r.add_argument('--list', required=True)
    r.add_argument('--scene', default='crowded')
    r.add_argument('--events', default='task_events.csv')
    r.add_argument('--out', required=True)
    r.add_argument('--port', type=int, default=50570)
    r.add_argument('--limit', type=float, default=90.0)
    r.add_argument('--break-every', type=int, default=8)
    r.add_argument('--auto', action='store_true')
    r.add_argument('--only', type=int, default=0, help='run only the first N rows (rehearsal)')
    a = ap.parse_args()
    if a.cmd == 'make':
        rows = make_list(a.scene, a.n, a.practice, a.seed)
        with open(a.out, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['trial', 'practice', 'obj', 'shelf', 'scene', 'seed'])
            for row in rows:
                w.writerow(list(row) + [a.scene, a.seed])
        print(f'{a.out}: {len(rows)} rows ({a.practice} practice); objects ' +
              str(np.bincount([x[2] for x in rows if not x[1]]).tolist()) + ', shelves ' +
              str({k: sum(1 for x in rows if not x[1] and x[3] == k) for k in sorted({x[3] for x in rows})}))
        return
    with open(a.list, encoding='utf-8') as f:
        plan = list(csv.DictReader(f))
    if plan and plan[0].get('scene') and plan[0]['scene'] != a.scene:
        sys.exit(f'the list was made for scene {plan[0]["scene"]}, not {a.scene}')
    if a.only:
        plan = plan[:a.only]
    names = SC.names(*SC.load(a.scene))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ev = Events(a.events)
    s = Session(lambda line: sock.sendto(line.encode('ascii'), ('127.0.0.1', a.port)), ev, a.limit, a.auto, line=stdin_line)
    done = []
    new = not os.path.exists(a.out)
    with open(a.out, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        scored = 0
        for p in plan:
            row = s.trial(int(p['trial']), int(p['practice']), int(p['obj']), int(p['shelf']), names)
            w.writerow(row)
            f.flush()
            done.append(row)
            print(f'  -> {row["outcome"]}，{row["time_s"]} s；鎖錯物體 {row["wrong_lock_obj"]}、架子 {row["wrong_lock_shelf"]}')
            if not row['practice']:
                scored += 1
                if scored % a.break_every == 0 and scored < sum(1 for x in plan if not int(x['practice'])) and not a.auto:
                    print('\n  休息 60 秒（按 Enter 提早繼續）')
                    t0 = time.time()
                    while time.time() - t0 < 60:
                        if stdin_line() is not None:
                            break
                        time.sleep(0.2)
    summary(done)


if __name__ == '__main__':
    main()
