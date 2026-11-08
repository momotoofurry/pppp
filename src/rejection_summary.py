"""Rejection and accuracy per condition from one session's board log and its TaskScreen files (T00, pilot, study).

Why: a confidence threshold can reject far more windows once the signals shift (other day, fatigue), and its gain
can come almost only from the Rest class (Aydogan & Canturk 2026; Pero 2026; report 33). This script measures
both on our own recordings, with the labels of the 'labelled' segments of TaskScreen.

Inputs in --dir, for every --name (a run.bat session, e.g. T00_d1):
  <name>_mcu.csv          TrignoBridge: PRED rows (report 1) = every classified window, PC receive time unix_ms,
                          gesture = top class, accepted = vote share >= the board's tau, ratio = vote share
  <name>_<cond>_task.csv  TaskScreen, one per condition (A, F, FR, AR, ...; a rerun '_task_2.csv' is its own row)
Labelled windows: PRED rows whose receive time is in [cue_on + --skip, cue_on + --cue] of a cue of a completed
labelled run ('pre' = the first completed run of the file, 'post' = the last one, if there are two or more).
Default skip 0.9 s = the transition left out, as the day-1 calibration does; cue 2 s = TaskScreen's default.

Rows of --out (long format), per name x condition x block (pre / post / task) x group:
  group = each gesture, 'active' = the 5 command gestures pooled, 'Rest'
  n                  windows
  rejected_pct       accepted = 0 (vote share below the board's tau: no command can come from it)
  acc_pct            top class == cued gesture, all windows
  acc_accepted_pct   the same over accepted windows only
  ratio_median       median vote share
  rest_cmd_pct       (Rest only) accepted windows whose top class is not Rest: what can turn into a false command
  task block         all windows between trial_on and trial_end of the completed task run: rejected_pct only
                     (no window-level labels there)
Offline tau sweep (--taus): for the active windows of each block, coverage (ratio >= tau) and accuracy of the
covered windows. Window level only: the board also needs k = 3 equal windows before a command, so this is not the
command rate.

  python src/rejection_summary.py --dir results/study/T00 --name T00_d1 --name T00_d2 \
      --out results/study/T00/rejection_T00.csv
Standard library only.
"""
import argparse
import bisect
import csv
import glob
import os
import re
import statistics
import sys

GESTURES = ['Power', 'Lateral', 'Tripod', 'Pointer', 'Open', 'Rest']
ACTIVE = GESTURES[:5]


def read_preds(path):
    """[(unix_ms, top, accepted, ratio)] sorted by time"""
    out = []
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if r.get('kind') != 'pred':
                continue
            try:
                out.append((float(r['unix_ms']), r['gesture'], int(r['accepted']), float(r['ratio'])))
            except (TypeError, ValueError):
                continue
    out.sort()
    return out


def runs(rows):
    """completed runs: [(segment, rows)] in file order (aborted runs left out, as src/task_summary.py)"""
    out, cur = [], None
    for r in rows:
        if r['event'] == 'seg_start':
            cur = (r['segment'], [])
        if cur is not None:
            cur[1].append(r)
            if r['event'] in ('seg_end', 'seg_abort'):
                if r['event'] == 'seg_end':
                    out.append(cur)
                cur = None
    return out


def in_range(preds, t0, t1):
    """PRED rows with t0 <= unix_ms < t1 (preds sorted; (t,) sorts before every (t, ...))"""
    i = bisect.bisect_left(preds, (t0,))
    j = bisect.bisect_left(preds, (t1,))
    return preds[i:j]


def stats(wins):
    """wins: [(label, top, accepted, ratio)]"""
    n = len(wins)
    if n == 0:
        return dict(n=0)
    acc = [w for w in wins if w[2]]
    d = dict(n=n,
             rejected_pct=round(100 * (n - len(acc)) / n, 2),
             acc_pct=round(100 * sum(w[0] == w[1] for w in wins) / n, 2),
             acc_accepted_pct=round(100 * sum(w[0] == w[1] for w in acc) / len(acc), 2) if acc else '',
             ratio_median=round(statistics.median(w[3] for w in wins), 3))
    return d


def label_blocks(task_rows, preds, skip_ms, cue_ms):
    """{'pre': [(label, top, accepted, ratio)], 'post': [...]} from the completed labelled runs"""
    lab = [rr for seg, rr in runs(task_rows) if seg == 'labelled']
    blocks = {}
    for name, rr in ([('pre', lab[0])] if lab else []) + ([('post', lab[-1])] if len(lab) >= 2 else []):
        wins = []
        for r in rr:
            if r['event'] == 'cue_on' and r['target'] in GESTURES:
                t = float(r['unix_ms'])
                wins += [(r['target'], top, a, q) for _t, top, a, q in in_range(preds, t + skip_ms, t + cue_ms)]
        blocks[name] = wins
    return blocks


def task_windows(task_rows, preds):
    """all PRED rows inside the trials of the last completed task run"""
    task = [rr for seg, rr in runs(task_rows) if seg == 'task']
    if not task:
        return None
    on, out = {}, []
    for r in task[-1]:
        if r['event'] == 'trial_on':
            on[r['trial']] = float(r['unix_ms'])
        elif r['event'] == 'trial_end' and r['trial'] in on:
            out += in_range(preds, on.pop(r['trial']), float(r['unix_ms']) + 1)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='rejection and accuracy per condition (see the module docstring)')
    ap.add_argument('--dir', required=True)
    ap.add_argument('--name', action='append', required=True, help='session name of run.bat, e.g. T00_d1 (repeatable)')
    ap.add_argument('--skip', type=float, default=0.9, help='seconds after cue_on left out (transition)')
    ap.add_argument('--cue', type=float, default=2.0, help='cue length in seconds (TaskScreen --cue)')
    ap.add_argument('--taus', default='0.4,0.5,0.6,0.7,0.8')
    ap.add_argument('--out', default='')
    a = ap.parse_args(argv)
    taus = [float(x) for x in a.taus.split(',') if x]
    rows, sweep = [], []
    for name in a.name:
        mpath = os.path.join(a.dir, name + '_mcu.csv')
        if not os.path.exists(mpath):
            print(f'missing {mpath}', file=sys.stderr)
            continue
        preds = read_preds(mpath)
        files = sorted(glob.glob(os.path.join(a.dir, name + '_*_task*.csv')))
        if not preds or not files:
            print(f'{name}: {len(preds)} PRED rows, {len(files)} task files: nothing to do', file=sys.stderr)
            continue
        for f in files:
            m = re.match(re.escape(name) + r'_(.+?)_task(?:_(\d+))?\.csv$', os.path.basename(f))
            if not m:
                continue
            cond = m.group(1) + (f'_{m.group(2)}' if m.group(2) else '')
            with open(f, newline='') as fh:
                trows = list(csv.DictReader(fh))
            for block, wins in label_blocks(trows, preds, 1000 * a.skip, 1000 * a.cue).items():
                groups = [(g, [w for w in wins if w[0] == g]) for g in GESTURES]
                groups.insert(0, ('active', [w for w in wins if w[0] in ACTIVE]))
                for g, ww in groups:
                    d = dict(name=name, cond=cond, block=block, group=g, **stats(ww))
                    if g == 'Rest' and ww:
                        d['rest_cmd_pct'] = round(100 * sum(w[2] and w[1] != 'Rest' for w in ww) / len(ww), 2)
                    rows.append(d)
                act = [w for w in wins if w[0] in ACTIVE]
                for tau in taus:
                    cov = [w for w in act if w[3] >= tau - 1e-9]
                    sweep.append(dict(name=name, cond=cond, block=block, tau=tau, n=len(act),
                                      coverage_pct=round(100 * len(cov) / len(act), 2) if act else '',
                                      acc_covered_pct=round(100 * sum(w[0] == w[1] for w in cov) / len(cov), 2) if cov else ''))
            tw = task_windows(trows, preds)
            if tw is not None:
                n = len(tw)
                rows.append(dict(name=name, cond=cond, block='task', group='all', n=n,
                                 rejected_pct=round(100 * sum(1 - w[2] for w in tw) / n, 2) if n else '',
                                 ratio_median=round(statistics.median(w[3] for w in tw), 3) if n else ''))
    if not rows:
        print('no labelled windows found', file=sys.stderr)
        return 1
    print(f'{"name":8} {"cond":5} {"block":5} {"group":8} {"n":>5} {"rej%":>6} {"acc%":>6} {"accA%":>6} {"ratio":>6} {"restcmd%":>8}')
    for d in rows:
        if d['group'] in ('active', 'Rest', 'all'):
            print(f'{d["name"]:8} {d["cond"]:5} {d["block"]:5} {d["group"]:8} {d["n"]:>5} {str(d.get("rejected_pct", "")):>6} '
                  f'{str(d.get("acc_pct", "")):>6} {str(d.get("acc_accepted_pct", "")):>6} {str(d.get("ratio_median", "")):>6} '
                  f'{str(d.get("rest_cmd_pct", "")):>8}')
    if a.out:
        keys = ['name', 'cond', 'block', 'group', 'n', 'rejected_pct', 'acc_pct', 'acc_accepted_pct', 'ratio_median',
                'rest_cmd_pct']
        with open(a.out, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        sp = os.path.splitext(a.out)[0] + '_tau.csv'
        with open(sp, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['name', 'cond', 'block', 'tau', 'n', 'coverage_pct', 'acc_covered_pct'])
            w.writeheader()
            w.writerows(sweep)
        print(f'saved {a.out} and {sp}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
