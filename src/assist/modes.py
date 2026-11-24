"""Two-mode control for continuous pick-and-place with 4 wrist directions (report 35.63, 2026-11-19).

The user's design (2026-11-18): mode 1 = free control, mode 2 = W approaches / S backs out; switch to 2 when a target
is confirmed, back to 1 after backing out; plus a manual switch. Collision and placement rules were added after
discussing what happens on a real arm.

Commands every 100 ms: 'up' 'down' 'left' 'right' (W S A D) or None (rest / relaxed: the arm stops), plus toggle()
for the manual switch (E key here; on the EMG side a wrist co-contraction detected by amplitude, not built yet).

MODE 1 (free): W / S / A / D move up / down / left / right IN THE TRAVEL PLANE x = X_TRAVEL, 2 cm in front of the
  shallowest shelf front (shelves have different depths: moving sideways at the depth of a deeper shelf would sweep
  into a shallower one; found by modes_test.py). With an empty hand the assist bends the path (y, z only) toward the
  likely object inside its zone (assist.py blend + zone). Depth is only ever changed in mode 2.
  Stopping (relax) in front of an object (y-z within LOCK_ALIGN of its pre-grasp point, empty hand) -> MODE 2 'pick'.
  Stopping in front of a shelf while holding an object (object over the shelf width, its bottom from 2 cm below to
  10 cm above the shelf top: real stops are not precise) -> MODE 2 'place'; W first lifts the object to 1 cm above the
  top if it is lower, then goes in.
MODE 2 (depth): W = forward, S = back; A / D do nothing inside a shelf, and in front of it switch back to mode 1.
  'pick':  W goes to the locked object (corrects y, z on the way); relax 1 s at it = grasp (stays in mode 2, 'out').
           S backs out; at / behind the pre-grasp point -> mode 1 (that object is not re-locked until the tool moved).
  'place': W goes straight in (keeps y, z) up to 3 cm before the shelf's back edge; relax 1 s = put down IF the spot is
           valid: object centre >= EDGE from the shelf edges and >= GAP + diameter from other objects on that shelf.
           The arm then lowers the object onto the shelf top by itself and opens ('out'). An invalid spot gives a
           reason (too close to an edge / to object k) and nothing happens.
  'out':   after a grasp or a put-down, inside the shelf: S backs out (W lifts a held object at most 2 cm); back at
           the travel plane -> mode 1.
  Every mode-2 phase returns to mode 1 only at the travel plane (S); A / D and toggle() are refused elsewhere.
  'free':  entered with toggle() anywhere: W / S move forward / back freely.
toggle(): mode 1 -> 2 ('free' unless a pick / place lock applies); mode 2 -> 1 only when not inside a shelf.
Safety: inside a shelf or within SLOW_ZONE in front of it the speed is halved. Rest always stops.
"""
import numpy as np

import assist as A

V_MAX, DT = A.V_MAX, A.DT
PRE = A.PRE
LOCK_ALIGN = 0.05
CONFIRM_STEPS = A.CONFIRM_STEPS
GRASP_TOL = A.GRASP_TOL
OBJ_R, OBJ_H = 0.03, 0.10          # objects: cylinders, radius / height (m)
SHELF_HX, SHELF_HY = 0.10, 0.08    # shelf board half sizes in x / y (board 20 x 16 cm, 2 cm thick)
EDGE, GAP = 0.03, 0.02             # put-down: centre this far from the edges; this much free space to other objects
SLOW_ZONE, SLOW = 0.05, 0.5
LIFT_IN = 0.02                     # max lift of a held object while still inside a shelf
# mode-1 steering (35.67, from the literature):
#   rule 'mix'  - the assist heads along the probability- and zone-weighted mean of the directions to the candidate
#                 objects, m = sum_g P(g) zone_g unit(pre_g - x) (y, z); its share a = LEVEL * ramp(|m|, MIX_ON, MIX_FULL).
#                 One likely object: as before. Two likely objects in a similar direction: help along what they share.
#                 Two in opposite directions: m cancels, no help (cf. hindsight optimization, Javdani et al. 2018;
#                 confidence-scaled blending, Dragan & Srinivasa 2013).
#   rule 'lead' - 35.63: blend toward the single most likely object.
#   Exit (both rules): if for MISMATCH_STEPS steps in a row the command fits none of the candidate objects (cos below
#   MISMATCH_COS to each) or opposes the assist direction, the assist switches off until the user relaxes (cf. the
#   confidence-aware shared autonomy of Zurek et al. 2021: input matching no known goal).
#   'mix' never pushes against the command (the opposing part of its direction is dropped), and each object's pull
#   fades out within ARRIVE of its pre-grasp point (modes_test.py: at an object, W was cancelled by the pull back).
MIX_ON, MIX_FULL = 0.3, 0.8
# 35.86: explicit gripper commands (S7 Fist = close, HandOpen = open), only where they mean something: Fist at the
# locked object in mode 2 'pick' (within GRASP_TOL) grasps at once, HandOpen inside the shelf in 'place' puts down
# (same spot check as the relax); anywhere else they are a stop and are counted as refused. The 1 s relax still works.
GRIPS = ('grip_close', 'grip_open')
# 35.86: goal prior (speech / LLM): an object or shelf whose prior is below PRIOR_LOW is locked only after the user
# stays stopped CONFIRM_STEPS in front of it (a deliberate choice overrides the prior); the others lock at once
PRIOR_LOW = 0.2
# 35.88: lock dwell by context: an object (shelf) whose pre-grasp point (centre) has another one within NEAR_LOCK in
# y-z is crowded; there a stop locks only after CONFIRM_STEPS (35.87: the dwell removed most wrong locks in a crowded
# scene but cost 2-4 s per trial when applied everywhere)
NEAR_LOCK = 0.10
ARRIVE = 0.02
MISMATCH_STEPS, MISMATCH_COS = 10, -0.2


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.zeros_like(v)


class ModeAssist:
    def __init__(self, objects, shelves, level=0.6, zone=0.12, rule='mix', grip_cmds=False, lock_dwell='none'):
        """objects: (n, 3) object centres; shelves: (m, 3) centres of the shelf tops; rule: 'mix' | 'lead' (mode-1
        steering, see MIX_ON); grip_cmds: explicit gripper commands (35.86, see GRIPS)"""
        self.grip_cmds = grip_cmds
        self.lock_dwell = lock_dwell                # 35.88: 'none' | 'context' | 'place' | 'all'
        self.n_grip_ok = self.n_grip_refused = 0
        self._prev_cmd = None                       # 35.86: a held Fist / HandOpen counts once
        self.shelf_prior = None                     # 35.86: prior over the shelves (None: off); objects: self.base.prior
        self.base = A.Assist(objects, mode='blend', level=level, zone=zone)   # steering assist (mode 1, empty hand)
        self.rule, self.level = rule, level
        self.assist_off = False                     # switched off by mismatching input until the next relax
        self.mis_n = 0
        self.a_last, self.dir_last = 0.0, np.zeros(3)   # last assist share / direction (hints, tests)
        self.n_off = 0                              # how often the assist was switched off (tests)
        self.switches = 0                           # mode changes (1 <-> 2), for the experiment log
        self.wait_release = False                   # after a switch made while W / S was held: no motion until a relax
        self.obj = self.base.obj                    # shared array: positions update in place
        self.shelves = np.asarray(shelves, float)
        self.m = 1
        self.phase = None                           # mode 2: 'pick' | 'place' | 'out' | 'free'
        self.goal = None                            # pick: target object
        self.held = None                            # object in the gripper
        self.shelf = None                           # place: shelf index
        self.rest_n = 0
        self.armed = True
        self.block = None                           # object not to re-lock until the tool moved away
        self.block_shelf = None                     # (shelf, y, z) not to re-lock until the tool moved away (35.68)
        self.last_put = None                        # object put down in this 'out' phase (blocked on return, 35.68)
        self.lowering = None                        # (shelf top + half height) while putting down
        self.released = None                        # object just put down (the open gripper is still around it)
        self.msg = ''                               # last refusal / reason (for the hints)
        self.lift_from = None
        self.x_travel = float(min(sh[0] for sh in self.shelves) - SHELF_HX - 0.02)

    # ------------------------------------------------------------------ geometry
    def at_travel(self, x):
        return x[0] <= self.x_travel + 0.005
    def front(self, k):
        return self.shelves[k][0] - SHELF_HX

    def shelf_of(self, x):
        """index of the shelf whose width (y) and height band the tool is in, or None"""
        for k, sh in enumerate(self.shelves):
            if abs(x[1] - sh[1]) < SHELF_HY + 0.04 and sh[2] - 0.03 < x[2] < sh[2] + 0.17:
                return k
        return None

    def inside(self, x):
        k = self.shelf_of(x)
        return k is not None and x[0] > self.front(k) + 0.01

    def near_shelf(self, x):
        k = self.shelf_of(x)
        return k is not None and x[0] > self.front(k) - SLOW_ZONE

    def z_max_in(self, k):
        """highest centre of a held object going into shelf k: its top 1 cm under the board (2 cm thick) of any
        shelf above k in the same lane (modes_sim, 35.67: a stop high in the place band hit the board above)"""
        sh = self.shelves[k]
        z = np.inf
        for j, o in enumerate(self.shelves):
            if j != k and o[2] > sh[2] and abs(o[1] - sh[1]) < 2 * SHELF_HY and abs(o[0] - sh[0]) < 2 * SHELF_HX:
                z = min(z, o[2] - 0.02 - OBJ_H / 2 - 0.01)
        return z

    def spot_ok(self, x, k):
        """(ok, reason) for putting the held object down with its centre at x on shelf k"""
        sh = self.shelves[k]
        if abs(x[0] - sh[0]) > SHELF_HX - EDGE or abs(x[1] - sh[1]) > SHELF_HY - EDGE:
            return False, '太靠架子邊緣'
        for i, o in enumerate(self.obj):
            if i == self.held:
                continue
            on_shelf = abs(o[2] - (sh[2] + OBJ_H / 2)) < 0.03
            if on_shelf and np.linalg.norm(o[:2] - x[:2]) < 2 * OBJ_R + GAP:
                return False, f'太靠近物體 {i}'
        return True, ''

    # ------------------------------------------------------------------ manual switch
    def toggle(self, x):
        x = np.asarray(x, float)
        if self.lowering is not None:
            return '正在放下，稍等'
        if self.m == 1:
            self._lock(x, manual=True)
            if self.m == 1:
                self.m, self.phase = 2, 'free'
            return f'切到模式 2（{self.phase}）'
        if not self.at_travel(x):
            return '不在前方平面上，不能切回模式 1：先按 S 退回'
        self._to_mode1(x)
        return '切到模式 1'

    def _to_mode1(self, x=None):
        if self.phase == 'pick':
            self.block = self.goal
        # 35.68: after backing out, the user must relax once (wait_release); relaxing right there must not lock the
        # shelf just left, or the object just put down, again (it looped: lock, S, relax, lock...)
        if x is not None and self.phase in ('out', 'place'):
            k = self.shelf if self.phase == 'place' else self.shelf_of(x)
            if k is not None:
                self.block_shelf = (k, x[1], x[2])
            if self.last_put is not None:
                self.block = self.last_put
            self.last_put = None
        self.m, self.phase, self.goal, self.shelf = 1, None, None, None

    def _grip(self, cmd, x):
        """35.86: Fist / HandOpen as gripper commands where they mean something, else a stop (counted as refused)"""
        if (cmd == 'grip_close' and self.m == 2 and self.phase == 'pick' and self.armed and self.goal is not None
                and np.linalg.norm(self.obj[self.goal] - x) < GRASP_TOL):
            self.held, self.phase, self.lift_from, self.rest_n, self.armed = self.goal, 'out', x[2], 0, False
            self.goal = None
            self.n_grip_ok += 1
        elif cmd == 'grip_open' and self.m == 2 and self.phase == 'place' and self.armed and self.inside(x):
            self.rest_n = 0
            ok, why = self.spot_ok(x, self.shelf)
            if ok:
                self.lowering = self.shelves[self.shelf][2] + OBJ_H / 2
                self.n_grip_ok += 1
            else:
                self.msg, self.armed = why, False
                if self._prev_cmd != cmd:
                    self.n_grip_refused += 1
        else:
            if self._prev_cmd != cmd:                   # a held Fist / HandOpen counts once
                self.n_grip_refused += 1
            return self._rest(x)                        # a stop, as a relax (the relax rules still apply)
        return np.zeros(3)

    def _prior_ok(self, prior, k, pts=None, shelf=False):
        """lock k now? 35.86: with a prior, a low-prior target needs a deliberate 1 s stop. 35.88: lock_dwell 'all'
        needs it everywhere, 'context' only where another candidate (pts) is within NEAR_LOCK in y-z"""
        crowded = shelf and self.lock_dwell == 'place'     # 'place': every shelf lock dwells (35.88: most wrong locks)
        if pts is not None and self.lock_dwell in ('context', 'place'):
            d = np.linalg.norm((pts - pts[k])[:, 1:], axis=1)
            d[k] = np.inf
            crowded = crowded or bool((d < NEAR_LOCK).any())
        if prior is not None:
            need = prior[k] < PRIOR_LOW and (self.lock_dwell not in ('context', 'place') or crowded)
        else:
            need = self.lock_dwell == 'all' or crowded
        return not need or self.rest_n >= CONFIRM_STEPS

    def _lock(self, x, manual=False):
        """mode 1 -> 2 when stopped in front of an object (empty hand) or a shelf (holding)"""
        if self.held is None:
            pre = self.obj + PRE
            d = np.linalg.norm((pre - x)[:, 1:], axis=1)
            prior = getattr(self.base, 'prior', None)
            for g in np.argsort(d):
                if d[g] < LOCK_ALIGN and self.at_travel(x) and g != self.block and not self._on_hold(g):
                    if not self._prior_ok(prior, g, pre):
                        return                          # wait: a longer stop locks it anyway
                    self.m, self.phase, self.goal = 2, 'pick', int(g)
                    return
        else:
            k = self.shelf_of(x)
            if k is not None and self.block_shelf is not None and k == self.block_shelf[0]:
                return
            if k is not None and self.at_travel(x):
                bottom = x[2] - OBJ_H / 2 - self.shelves[k][2]
                if abs(x[1] - self.shelves[k][1]) <= SHELF_HY - EDGE and -0.02 <= bottom <= 0.10:
                    if not self._prior_ok(self.shelf_prior, k, self.shelves, shelf=True):
                        return
                    self.m, self.phase, self.shelf = 2, 'place', k
                    return
                if True:
                    self.msg = ('高度不對：物體底部要在架面下 2 公分到架面上 10 公分之間' if not -0.02 <= bottom <= 0.10
                                else '左右要在架子寬度內')

    def _on_hold(self, g):
        return g == self.held

    # ------------------------------------------------------------------ step
    def step(self, cmd, x):
        m0 = self.m
        v = self._step(cmd, x)
        self._prev_cmd = cmd
        if self.m != m0:
            self.switches += 1
            self.assist_off, self.mis_n = False, 0
            # 35.68 (user): S backs out, the mode switches to 1 at the travel plane, and the same held S would now mean
            # DOWN and drop the arm at once. W / S change meaning between the modes, so after a switch made while W / S
            # is held the arm waits until the user relaxes once (A / D at the plane mean the same in both: no wait)
            if cmd in ('up', 'down'):
                self.wait_release = True
        return v

    def _step(self, cmd, x):
        x = np.asarray(x, float)
        if self.wait_release:
            if cmd in A.DIRS:
                return np.zeros(3)                      # hold still until a relax
            self.wait_release = False
        u =np.array(A.DIRS[cmd], float) if cmd in A.DIRS else np.zeros(3)
        moving = np.linalg.norm(u) > 0
        slow = SLOW if (self.near_shelf(x) or self.inside(x)) else 1.0
        if self.held is not None:
            self.obj[self.held] = x
        if self.released is not None and np.linalg.norm(self.obj[self.released][:2] - x[:2]) > 0.07:
            self.released = None
        if self.block is not None and np.linalg.norm((self.obj[self.block] + PRE - x)[1:]) > 1.5 * LOCK_ALIGN:
            self.block = None
        if self.block_shelf is not None and np.linalg.norm(np.array(self.block_shelf[1:]) - x[1:]) > LOCK_ALIGN:
            self.block_shelf = None
        # automatic lowering after a valid put-down
        if self.lowering is not None:
            if x[2] - self.lowering > 0.002:
                return np.array([0, 0, -min(V_MAX * 0.5, (x[2] - self.lowering) / DT)])
            self.obj[self.held] = [x[0], x[1], self.lowering]
            self.released = self.last_put = self.held
            self.held, self.lowering, self.phase, self.armed = None, None, 'out', False
            return np.zeros(3)
        if self.grip_cmds and cmd in GRIPS:
            return self._grip(cmd, x)
        if not moving:
            return self._rest(x)
        self.rest_n, self.armed = 0, True
        self.msg = ''
        if self.m == 1:
            if self.held is None:
                v = self._steer(cmd, u, x)
            else:
                v = V_MAX * u
            v[0] = (self.x_travel - x[0]) / DT if abs(self.x_travel - x[0]) > 1e-4 else 0.0   # stay in the plane
            return v * slow
        # mode 2
        ins = self.inside(x)
        if cmd in ('left', 'right'):
            if not self.at_travel(x):
                self.msg = ('在架子裡：A／D 不能動，先按 S 退出' if ins else '先按 S 退回前方平面，A／D 才能動')
                return np.zeros(3)
            self._to_mode1(x)
            return self._step(cmd, x)
        fwd = cmd == 'up'
        if self.phase == 'pick':
            g = self.goal
            if fwd:
                d = self.obj[g] - x
                k = self.shelf_of(self.obj[g])
                front = self.front(k) if k is not None else self.obj[g][0] + PRE[0]
                if self.inside(x):
                    d = np.array([d[0], 0.0, 0.0])        # inside the shelf: straight in only (lined up before)
                elif np.linalg.norm(d[1:]) > 0.002 and x[0] >= front - 0.01:
                    d = np.array([0.0, d[1], d[2]])       # line up first: no sideways move inside the shelf
                return min(V_MAX * slow, np.linalg.norm(d) / DT) * unit(d)
            if self.at_travel(x):
                self._to_mode1(x)
                return np.zeros(3)
            return np.array([-min(V_MAX * slow, (x[0] - self.x_travel) / DT), 0, 0])
        if self.phase == 'place':
            k = self.shelf
            if fwd:
                z_min = self.shelves[k][2] + OBJ_H / 2 + 0.01      # object bottom 1 cm above the top
                if x[2] < z_min - 0.001:
                    return np.array([0, 0, min(V_MAX * slow, (z_min - x[2]) / DT)])   # lift first (before going in)
                z_max = self.z_max_in(k)                           # object top 1 cm under a board above (35.67)
                if x[2] > z_max + 0.001:
                    return np.array([0, 0, -min(V_MAX * slow, (x[2] - z_max) / DT)])  # lower first
                lim = self.shelves[k][0] + SHELF_HX - EDGE
                for i, o in enumerate(self.obj):
                    if i != self.held and abs(o[2] - x[2]) < OBJ_H and abs(o[1] - x[1]) < 2 * OBJ_R + GAP and o[0] > x[0]:
                        lim = min(lim, o[0] - (2 * OBJ_R + GAP))      # an object in the lane: stop before it
                return np.array([min(V_MAX * slow, max(lim - x[0], 0) / DT), 0, 0])
            if self.at_travel(x):
                self._to_mode1(x)
                return np.zeros(3)
            return np.array([-min(V_MAX * slow, (x[0] - self.x_travel) / DT), 0, 0])
        if self.phase == 'out':
            if fwd:
                if self.held is not None and x[2] - self.lift_from < LIFT_IN:
                    return np.array([0, 0, V_MAX * slow])
                return np.zeros(3)
            if self.at_travel(x):
                self._to_mode1(x)
                return np.zeros(3)
            return np.array([-min(V_MAX * slow, (x[0] - self.x_travel) / DT), 0, 0])
        # 'free': forward stops at the front of a shelf in line (going in is for pick / place only)
        if fwd:
            k = self.shelf_of(x)
            lim = self.front(k) - 0.005 if k is not None else np.inf
            return np.array([min(V_MAX * slow, max(lim - x[0], 0) / DT), 0, 0])
        return np.array([-V_MAX * slow, 0, 0])

    def _steer(self, cmd, u, x):
        """mode 1, empty hand: the user's direction blended with the assist's (y, z only; depth stays in the plane)"""
        pre = self.obj + PRE
        P = self.base.probs()
        zones = np.array([self.base.zone(g, x) for g in range(len(self.obj))])
        D = pre - x
        D[:, 0] = 0.0
        # pull per object: unit direction, fading out within ARRIVE of its pre-grasp point (no jitter on arrival)
        D = np.array([d / max(np.linalg.norm(d), ARRIVE) for d in D])
        if self.rule == 'lead':
            v = self.base.step(cmd, x)                  # 35.63: blend + zone toward the most likely object
            self.base.state = 'steer'
            g = int(np.argmax(P))
            a = self.level * np.clip((P[g] - A.P_ON) / (A.P_FINAL - A.P_ON), 0, 1) * zones[g]
            dirn = D[g]
        else:
            self.base._score(u, x)
            P = self.base.probs()
            w = P * zones
            m = (w[:, None] * D).sum(0)
            a = self.level * float(np.clip((np.linalg.norm(m) - MIX_ON) / (MIX_FULL - MIX_ON), 0, 1))
            dirn = unit(m)
        # exit: the command fits none of the candidates, or opposes where the assist is heading
        w_cand = P * zones
        cand = [g for g in range(len(self.obj)) if w_cand[g] > 0.05]
        if cand:
            fits = any(u @ D[g] > MISMATCH_COS for g in cand)
            against = a > 0 and u @ dirn < -0.5
            self.mis_n = self.mis_n + 1 if (not fits or against) else 0
            if self.mis_n >= MISMATCH_STEPS and not self.assist_off:
                self.assist_off = True
                self.n_off += 1
        else:
            self.mis_n = 0
        if self.assist_off:
            a = 0.0
        if self.rule == 'mix' and u @ dirn < 0:
            dirn = dirn - (u @ dirn) * u                # never push against the user's command: keep only the sideways part
        self.a_last, self.dir_last = a, dirn
        if self.rule == 'lead' and not self.assist_off:
            vyz = np.array([0.0, v[1], v[2]])
            return np.linalg.norm(v) * unit(vyz)
        return V_MAX * unit((1 - a) * u + a * dirn)

    def _rest(self, x):
        if self.m == 1:
            self.assist_off, self.mis_n = False, 0      # relaxing gives the assist back
            self.rest_n += 1
            if self.rest_n >= CONFIRM_STEPS and (self.block is not None or self.block_shelf is not None):
                # 35.68: staying stopped 1 s in front of the object / shelf just left is a deliberate choice: lock it
                # again (a short relax after backing out does not; modes_sim: users stuck after an accidental S)
                self.block, self.block_shelf, self.armed = None, None, True
            if self.armed:
                self._lock(x)
            return np.zeros(3)
        if self.phase == 'pick' and self.armed and np.linalg.norm(self.obj[self.goal] - x) < GRASP_TOL:
            self.rest_n += 1
            if self.rest_n >= CONFIRM_STEPS:
                self.held, self.phase, self.lift_from, self.rest_n, self.armed = self.goal, 'out', x[2], 0, False
                self.goal = None
            return np.zeros(3)
        if self.phase == 'place' and self.armed and self.inside(x):
            self.rest_n += 1
            if self.rest_n >= CONFIRM_STEPS:
                self.rest_n = 0
                ok, why = self.spot_ok(x, self.shelf)
                if ok:
                    self.lowering = self.shelves[self.shelf][2] + OBJ_H / 2
                else:
                    self.msg, self.armed = why, False
            return np.zeros(3)
        self.rest_n = 0
        return np.zeros(3)

    lock_cmd = None

    def probs(self):
        return self.base.probs()

    @property
    def state(self):
        return f'mode{self.m}' + (f'-{self.phase}' if self.m == 2 else '')

    @property
    def grip(self):
        return 1.0 if self.held is not None else 0.0

    def describe(self, x):
        """(code, short English text for RViz, Chinese hint, object index for the marker) of the current state"""
        x = np.asarray(x, float)
        if self.wait_release:
            return ('wait', 'RELAX first', f'已切到模式 {self.m}：先放鬆（空白鍵），再重新出力',
                    self.held if self.held is not None else self.goal)
        if self.msg:
            return 'msg', 'X', self.msg, self.held if self.held is not None else self.goal
        if self.lowering is not None:
            return 'lower', 'putting down', '正在把物體放到架面上', self.held
        if self.m == 1:
            if self.held is not None:
                return 'carry', 'MODE 1', f'模式 1：夾著物體 {self.held}，自由移動；在架子前方停下就切到模式 2 放置', self.held
            if self.assist_off:
                return 'off', 'MODE 1  assist off', '模式 1：輔助暫停（你的方向和系統猜的不同），放鬆一下就恢復', None
            P = self.base.probs()
            g = int(np.argmax(P))
            if P[g] >= A.P_ON and self.base.zone(g, x) > 0:
                return 'lead', f'MODE 1  {g}?', f'模式 1：系統猜是物體 {g}，在它前面停下就切到模式 2', g
            return 'free1', 'MODE 1', '模式 1：自由控制（W／S／A／D 上下左右）', None
        if self.phase == 'pick':
            if np.linalg.norm(self.obj[self.goal] - x) < GRASP_TOL:   # same as the grasp rule (a relax here grasps)
                return 'grasp', 'MODE 2  SPACE 1s: grasp', f'模式 2：到了物體 {self.goal}，空白鍵放鬆 1 秒夾起', self.goal
            return 'pick', 'MODE 2  W: in / S: out', f'模式 2：鎖定物體 {self.goal}，W 接近、S 退出', self.goal
        if self.phase == 'place':
            if self.inside(x):
                return 'place', 'MODE 2  SPACE 1s: put down', '模式 2：W／S 調整深度，空白鍵放鬆 1 秒放下', self.held
            return 'place_in', 'MODE 2  W: in / S: out', f'模式 2：放到架子 {self.shelf}，W 放進去、S 退出', self.held
        if self.phase == 'out':
            return 'out', 'MODE 2  S: back out', '模式 2：按 S 退回前方平面，退回後自動回模式 1', self.held
        return 'free2', 'MODE 2  W/S', '模式 2（手動）：W 前進、S 後退，E 切回模式 1', None


class Collisions:
    """counts contacts the controller should never cause: the held object or the gripper inside a shelf board or
    another object, and sideways moves inside a shelf (sweeping)"""
    def __init__(self, ma):
        self.ma = ma
        self.n = 0
        self.kinds = {}

    def hit(self, kind):
        self.n += 1
        self.kinds[kind] = self.kinds.get(kind, 0) + 1

    def check(self, x, x_prev):
        ma = self.ma
        held = ma.held
        for k, sh in enumerate(ma.shelves):
            in_xy = abs(x[0] - sh[0]) < SHELF_HX and abs(x[1] - sh[1]) < SHELF_HY
            overlap = x[2] - OBJ_H / 2 < sh[2] - 0.002 and x[2] + OBJ_H / 2 > sh[2] - 0.02
            if held is not None and in_xy and overlap and ma.lowering is None:
                self.hit('held object into a shelf board')
            if in_xy and sh[2] - 0.02 < x[2] < sh[2] - 0.002:
                self.hit('gripper into a shelf board')
        for i, o in enumerate(ma.obj):
            if i == held or i == ma.goal or i == ma.released:
                continue
            d = np.linalg.norm(o[:2] - x[:2])
            if d < 2 * OBJ_R - 0.005 and abs(o[2] - x[2]) < OBJ_H:
                self.hit(f'touches object {i}')
        if ma.inside(x_prev) and ma.inside(x) and abs(x[1] - x_prev[1]) > 1e-4:
            self.hit('sideways inside a shelf')
