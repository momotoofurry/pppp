"""Standard manual mode-switching baseline for RQ4 (no auto-lock, no alignment, no steering assist).

Matches how a conventional 2-DOF / 4-direction assistive arm (e.g., Kinova JACO/Gen3) is operated:
  - Mode 1 (Y-Z):  up/down/left/right move in Z / Y.
  - Mode 2 (X):    up = forward (+X), down = back (-X); left/right do nothing.
  - Mode switch:   explicit 'switch' command toggles Mode 1 <-> Mode 2 (counted once per press;
                   if pressed while W/S was held, waits for relax just like modes.py).
  - Grasp / Put:   relax CONFIRM_STEPS (1 s) within GRASP_TOL of an object (empty hand) grasps it;
                   relax CONFIRM_STEPS while holding at a valid spot (spot_ok AND object bottom
                   within PUT_Z_TOL of the shelf top) releases it.
  - Same V_MAX, DT, SLOW_ZONE/SLOW, GRASP_TOL, spot_ok as modes.py, with NO auto-lock,
    NO auto Y/Z alignment, NO auto height lift/lower, and NO travel-plane guard.
"""
import numpy as np

import assist as A
import modes as M

V_MAX, DT = M.V_MAX, M.DT
GRASP_TOL = M.GRASP_TOL
CONFIRM_STEPS = M.CONFIRM_STEPS
OBJ_R, OBJ_H = M.OBJ_R, M.OBJ_H
SHELF_HX, SHELF_HY = M.SHELF_HX, M.SHELF_HY
EDGE, GAP = M.EDGE, M.GAP
SLOW_ZONE, SLOW = M.SLOW_ZONE, M.SLOW
PUT_Z_TOL = 0.025


class ManualControl:
    def __init__(self, objects, shelves):
        self.obj = np.array(objects, float)
        self.shelves = np.asarray(shelves, float)
        self.m = 1                      # 1: Y-Z, 2: X (depth)
        self.held = None
        self.goal = None                # set by caller only for Collisions to ignore the intended pick target
        self.lowering = None            # unused; kept for modes.Collisions compatibility
        self.released = None
        self.rest_n = 0
        self.armed = True
        self.switches = 0
        self.wait_release = False
        self._prev_cmd = None
        self.msg = ''
        self.x_travel = float(min(sh[0] for sh in self.shelves) - SHELF_HX - 0.02)

    def at_travel(self, x):
        return x[0] <= self.x_travel + 0.015

    def toggle(self, x):
        self.m = 2 if self.m == 1 else 1
        self.switches += 1
        self.wait_release = True
        self.rest_n = 0
        return f'手動切到模式 {self.m}'

    def probs(self):
        return np.full(len(self.obj), 1.0 / max(1, len(self.obj)))

    @property
    def state(self):
        return f'manual-m{self.m}'

    @property
    def grip(self):
        return 1.0 if self.held is not None else 0.0

    def describe(self, x):
        if self.wait_release:
            return 'wait', 'RELAX first', f'手動模式 {self.m}：先放鬆再動作', self.held
        if self.m == 1:
            return 'free1', 'MANUAL M1 (Y/Z)', '手動模式 1（上下左右）；E 切換到前後', self.held
        return 'free2', 'MANUAL M2 (X)', '手動模式 2（W 前進／S 後退）；E 切回上下左右', self.held

    def front(self, k):
        return self.shelves[k][0] - SHELF_HX

    def shelf_of(self, x):
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

    def spot_ok(self, x, k):
        sh = self.shelves[k]
        if abs(x[0] - sh[0]) > SHELF_HX - EDGE or abs(x[1] - sh[1]) > SHELF_HY - EDGE:
            return False, 'too close to edge'
        for i, o in enumerate(self.obj):
            if i == self.held:
                continue
            on_shelf = abs(o[2] - (sh[2] + OBJ_H / 2)) < 0.03
            if on_shelf and np.linalg.norm(o[:2] - x[:2]) < 2 * OBJ_R + GAP:
                return False, f'too close to object {i}'
        return True, ''

    def step(self, cmd, x):
        x = np.asarray(x, float)
        prev = self._prev_cmd
        self._prev_cmd = cmd
        if self.held is not None:
            self.obj[self.held] = x
        if self.released is not None and np.linalg.norm(self.obj[self.released][:2] - x[:2]) > 0.07:
            self.released = None
        if cmd == 'switch':
            if prev != 'switch':
                self.m = 2 if self.m == 1 else 1
                self.switches += 1
                self.wait_release = True
                self.rest_n = 0
            return np.zeros(3)
        if self.wait_release:
            if cmd in A.DIRS and cmd not in ('left', 'right'):
                return np.zeros(3)
            self.wait_release = False
        if cmd is None or cmd not in A.DIRS:
            return self._rest(x)
        self.rest_n, self.armed = 0, True
        self.msg = ''
        slow = SLOW if (self.near_shelf(x) or self.inside(x)) else 1.0
        if self.m == 1:
            u = np.array(A.DIRS[cmd], float)
            return V_MAX * slow * u
        if cmd == 'up':
            return np.array([V_MAX * slow, 0.0, 0.0])
        if cmd == 'down':
            return np.array([-V_MAX * slow, 0.0, 0.0])
        return np.zeros(3)

    def _rest(self, x):
        if not self.armed:
            return np.zeros(3)
        if self.held is None:
            d = np.linalg.norm(self.obj - x, axis=1)
            g = int(np.argmin(d))
            if d[g] < GRASP_TOL:
                self.rest_n += 1
                if self.rest_n >= CONFIRM_STEPS:
                    self.held = g
                    self.rest_n, self.armed = 0, False
                return np.zeros(3)
        else:
            k = self.shelf_of(x)
            if k is not None:
                z_tgt = self.shelves[k][2] + OBJ_H / 2
                if abs(x[2] - z_tgt) <= PUT_Z_TOL:
                    ok, why = self.spot_ok(x, k)
                    if ok:
                        self.rest_n += 1
                        if self.rest_n >= CONFIRM_STEPS:
                            self.obj[self.held] = [x[0], x[1], z_tgt]
                            self.released = self.held
                            self.held = None
                            self.rest_n, self.armed = 0, False
                        return np.zeros(3)
                    else:
                        self.msg = why
        self.rest_n = 0
        return np.zeros(3)


def manual_user(mc, seen, t_obj, t_shelf, est, lead):
    """Reasonable human policy for manual mode-switching:
    1. Pick: back out to travel plane -> Mode 1 align (y, z) to object within 1 cm -> Mode 2 move +x to object -> relax to grasp.
    2. Out:  Mode 2 back out to travel plane.
    3. Place: Mode 1 align (y, z) to shelf centre at height = place_z + 1.5 cm (clears shelf board AND within PUT_Z_TOL=2.5 cm!)
              -> Mode 2 move +x to shelf centre -> relax to put down -> Mode 2 back out to travel plane -> Mode 1.
    Note: entering at place_z + 1.5 cm avoids an extra Mode 2->1->2 switch inside the shelf (fairest possible manual strategy).
    """
    if mc.wait_release:
        return 'rest'
    if est == 'switch':
        return 'rest'   # let go after a switch completes so we never double-toggle
    sh = mc.shelves[t_shelf]
    obj_p = mc.obj[t_obj]
    place_z = sh[2] + OBJ_H / 2

    def need_mode(want_m):
        return 'switch' if mc.m != want_m else None

    def move_yz(tgt_y, tgt_z, tol):
        dy, dz = tgt_y - seen[1], tgt_z - seen[2]
        if max(abs(dy), abs(dz)) < tol:
            return None
        if abs(dy) >= abs(dz):
            if abs(dy) < lead and est not in (None, 'rest', 'switch'):
                return 'rest'
            return 'left' if dy > 0 else 'right'
        if abs(dz) < lead and est not in (None, 'rest', 'switch'):
            return 'rest'
        return 'up' if dz > 0 else 'down'

    def move_x(tgt_x, tol):
        dx = tgt_x - seen[0]
        if abs(dx) < tol:
            return None
        if abs(dx) < lead * 0.5 and est not in (None, 'rest', 'switch'):
            return 'rest'
        return 'up' if dx > 0 else 'down'

    placed = (mc.held is None and abs(obj_p[2] - place_z) < 1e-4
              and abs(obj_p[0] - sh[0]) <= SHELF_HX - EDGE + 1e-4
              and abs(obj_p[1] - sh[1]) <= SHELF_HY - EDGE + 1e-4)
    if placed:
        if not mc.at_travel(seen):
            return need_mode(2) or 'down'
        return need_mode(1) or 'rest'

    if mc.held is None:
        dyz = np.linalg.norm(obj_p[1:] - seen[1:])
        if dyz > 0.011:
            if not mc.at_travel(seen):
                return need_mode(2) or 'down'
            sw = need_mode(1)
            if sw:
                return sw
            return move_yz(obj_p[1], obj_p[2], 0.008) or 'rest'
        if abs(obj_p[0] - seen[0]) >= GRASP_TOL * 0.7:
            sw = need_mode(2)
            if sw:
                return sw
            return move_x(obj_p[0], GRASP_TOL * 0.7) or 'rest'
        return 'rest'

    # Holding object: target shelf centre at entry_z = place_z + 0.015 (clears board, within PUT_Z_TOL=0.025)
    entry_z = place_z + 0.015
    in_xy = abs(seen[0] - sh[0]) <= SHELF_HX - EDGE - 0.005 and abs(seen[1] - sh[1]) <= SHELF_HY - EDGE - 0.005
    if in_xy and seen[0] > mc.front(t_shelf):
        if abs(seen[2] - place_z) > PUT_Z_TOL * 0.85:
            sw = need_mode(1)
            if sw:
                return sw
            return move_yz(sh[1], place_z, PUT_Z_TOL * 0.6) or 'rest'
        return 'rest'

    if abs(sh[1] - seen[1]) > 0.015 or abs(entry_z - seen[2]) > 0.008:
        if not mc.at_travel(seen):
            return need_mode(2) or 'down'
        sw = need_mode(1)
        if sw:
            return sw
        return move_yz(sh[1], entry_z, 0.007) or 'rest'

    sw = need_mode(2)
    if sw:
        return sw
    return move_x(sh[0], 0.015) or 'rest'


if __name__ == '__main__':
    import scenes as SC
    obj, sh = SC.load('3obj')
    mc = ManualControl(obj, sh)
    mc.goal = 0
    col = M.Collisions(mc)
    x = np.array([0.58, 0.0, 0.35])
    free = SC.free_shelves(obj, sh)
    t_sh = free[0]
    for step in range(900):
        c = manual_user(mc, x, 0, t_sh, None, 0.005)
        xp = x.copy()
        v = mc.step(c if c != 'rest' else None, x)
        x = x + v * DT
        col.check(x, xp)
        if (mc.held is None and mc.m == 1 and mc.at_travel(x)
                and abs(mc.obj[0][2] - (sh[t_sh][2] + OBJ_H / 2)) < 1e-4
                and abs(mc.obj[0][0] - sh[t_sh][0]) <= SHELF_HX - EDGE + 1e-4
                and abs(mc.obj[0][1] - sh[t_sh][1]) <= SHELF_HY - EDGE + 1e-4):
            print(f'manual smoke 3obj e=0: OK in {(step+1)*DT:.1f}s, switches={mc.switches}, col={col.n}')
            break
    else:
        raise AssertionError(f'manual smoke failed: state m={mc.m} held={mc.held} x={x}')
    print('ALL OK')
