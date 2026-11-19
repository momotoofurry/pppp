"""Online hindsight task labels for the two-mode assist (report 35.71): the 35.70 rule agree2_t6, run while the arm
is used, on what the system itself logs (never the user's intent).

Each control step the labeler stores what the system knew that step (established command, tool position, mode,
phase, lowering, 'relax first' prompt). A pick-and-place is confirmed when the held object is put down: then all
stored steps of that pick-and-place (approach, grasp, carry, place) are labelled in hindsight with agree2 (35.70:
the position rule and the command rule must give the same class; no label N_TAIL steps before a command change;
undo check: put back within 3 cm of where it was picked -> no labels). The backing out after the put-down is
labelled when the arm is back in mode 1 (S = the 'down' gesture, same tail rule).
Buffer (35.70's MCU design): the per-step facts above are a few bytes each and are kept for the whole
pick-and-place (up to MAX_STEPS); the feature windows are what costs memory on the MCU, and only BUF windows before
each confirmation are kept: steps up to the grasp get a label only if they are within BUF steps before the grasp,
steps after it only if within BUF before the put-down. On the MCU the pick-part labels are applied at the grasp to
pending class sums (5 classes x 80 features, about 1.6 KB) and committed at the put-down, or dropped on an undo.

Output: on_step() returns a list of (step index, label) whenever labels become final; label in up / down / left /
right / rest (the 5-class gestures: in mode 2 'up' = W = forward, 'down' = S = back).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import label_sim2 as L2  # noqa: E402

N_TAIL = 6
BUF = 200                     # feature windows kept before each confirmation (100 ms steps: 20 s)
MAX_STEPS = 6000              # per-step facts kept (10 min); a longer pick-and-place gives no labels


class Labeler:
    def __init__(self, ma, n_tail=N_TAIL, buf=BUF):
        self.ma, self.n_tail, self.buf = ma, n_tail, buf
        self.rec = []             # steps of the current pick-and-place
        self.out = []             # steps backing out after the put-down: (index, command)
        self.backing = False
        self.skip_out = False
        self.k = 0
        self.pick_pos = None
        self.n_trials = self.n_undo = self.n_overflow = 0
        self.last = None          # summary of the last labelled pick-and-place

    def before(self, cmd, x):
        """call before ma.step(): the state the step starts from"""
        ma = self.ma
        self._held0 = ma.held
        if ma.held is None and ma.phase == 'pick' and ma.goal is not None:
            self.pick_pos = ma.obj[ma.goal].copy()
        self._r = dict(k=self.k, cmd=cmd, m=ma.m, phase=ma.phase, x=np.asarray(x, float).copy(), held=ma.held,
                       lowering=ma.lowering is not None, wait=ma.wait_release)

    def after(self):
        """call after ma.step(); returns [(step, label)] that became final at this step"""
        ma, r = self.ma, self._r
        r['grasp'] = self._held0 is None and ma.held is not None
        r['put'] = self._held0 is not None and ma.held is None
        if r['grasp']:
            r['pick_pos'] = self.pick_pos
        self.k += 1
        done = []
        if self.backing:
            if r['m'] == 2 and r['phase'] == 'out':     # the state this step started from
                self.out.append((r['k'], r['cmd']))
                if ma.m == 1:                           # this step reached the travel plane: backing out is over
                    done += self._label_out()
                    self.backing = False
                return done
            done += self._label_out()
            self.backing = False
        if r['put']:
            self.rec.append(r)
            done += self._label_trial()
            self.backing, self.out = True, []
            return done
        self.rec.append(r)
        if len(self.rec) > MAX_STEPS:
            self.rec.pop(0)
        return done

    def _label_trial(self):
        rec = self.rec
        self.rec = []
        if not any(rr['grasp'] for rr in rec):
            self.n_overflow += 1
            self.last = dict(n=0, why='pick-and-place longer than MAX_STEPS (no grasp kept)')
            return []
        # agree2 needs the record from the grasp's approach: drop steps before an earlier put (none here) and use it
        rr = [dict(r_, want=None, raw=None, lock=None) for r_ in rec]
        if L2.undo(rr):
            self.n_undo += 1
            self.skip_out = True                      # the backing out of an undo is not labelled either
            self.last = dict(n=0, why='put back where it was picked (undo)')
            return []
        labs = L2.agree2(rr, self.ma, self.n_tail)
        if self.buf is not None:
            labs = L2.buffered(rr, labs, self.buf)
        self.n_trials += 1
        res = [(r_['k'], l) for r_, l in zip(rec, labs) if l is not None]
        self.last = dict(n=len(res), of=len(rec), counts={c: sum(1 for _, l in res if l == c)
                                                          for c in ('up', 'down', 'left', 'right', 'rest')})
        return res

    def _label_out(self):
        steps = self.out
        self.out = []
        if self.skip_out:
            self.skip_out = False
            return []
        cmds = [c for _, c in steps]
        res = []
        for i, (k, c) in enumerate(steps):
            tail = c != 'rest' and any(cc != c for cc in cmds[i + 1:i + 1 + self.n_tail])
            if c == 'down' and not tail:
                res.append((k, 'down'))
        return res
