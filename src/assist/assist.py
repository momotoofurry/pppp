"""Shared-autonomy assist for wrist-only EMG control of an assistive arm (report 35.57 / 35.58, 2026-11-18; prototype
on the PC, to be ported to C on the MCU after the self-test).

The user controls direction and timing with 4 wrist gestures (S5: up, down, left, right + Rest); the system adds what
the user cannot command: depth (forward / back), gripper orientation and grasping. Every 100 ms (one decision step):

  u        the established command as a unit vector in the user's frame (= robot base frame here: x forward, y left,
           z up); 0 for Rest (or when the activity gate says the user is relaxed). Rest always stops the arm.
  goal     each candidate object g scores the agreement of u with the direction to its pre-grasp point in the plane
           the user can command (y, z):  s_g <- LAMBDA * s_g + cos(u, P_yz (pre_g - x))   (only while u != 0);
           P(g) = softmax(BETA * s).

Two modes (35.57 had only 'takeover'; the user found it gave no sense of control, so 35.58 adds 'blend'):

takeover   before lock: v = V_MAX ((1 - a) u + a d_g), a = A_MAX * clip((P - P_ON) / (P_LOCK - P_ON), 0, 1)
           (d_g = unit vector to the leading goal's pre-grasp point, all three axes). At P >= P_LOCK the goal is
           locked and any held gesture pointing toward it means "go": the system drives the straight path to the
           pre-grasp point and in. A gesture pointing away, held CANCEL_STEPS steps, cancels. The gripper closes
           automatically at the object, then any gesture lifts.
blend      the user's direction always counts: v = V_MAX unit((1 - a) u + a d_g) with a = LEVEL * ramp(P) (LEVEL <= 0.6:
           the user's share is at least 40 %); the depth comes from d_g, so the arm moves forward only while the user
           pushes toward the goal. Lock (35.62, the user's choice: after the target is chosen, W approaches and S
           cancels, whatever gesture brought the arm there): when the user STOPS (relaxes) within LOCK_ALIGN (y, z) in
           front of an object, that object is locked ('final'); then up (W) = approach it (the arm corrects y, z on the
           way and stops at the object), down (S) = back out to the pre-grasp point and cancel the lock, left / right =
           cancel and steer that way. A cancelled object is not locked again until the tool has moved 1.5 LOCK_ALIGN
           away from it. The gripper closes only when the user relaxes
           CONFIRM_STEPS steps at the object (the user's confirmation). After the grasp the user moves freely.
           keep=True (continuous use, 35.59): control never ends. The grasped object moves with the tool; relaxing
           CONFIRM_STEPS steps with the object over a shelf (place_ok) opens the gripper and leaves the object there;
           then the user steers again and can pick it or another one up. Relaxing anywhere else only stops the arm.
           zone=r (35.60): the assist acts only near an object: its share a is multiplied by a ramp of the y-z distance
           from the tool to that object's pre-grasp point, 0 beyond r and 1 within ZONE_FULL. Outside every zone the
           user has plain direct control (no bending, no added depth); the guess is shown only inside a zone.
Rest / relaxed: v = 0 in every state (the user can always stop).

Parameter values are first guesses, tuned in simulation (assist_sim.py) and RViz; not validated with people.
"""
import numpy as np

V_MAX = 0.08          # m/s
DT = 0.1              # s per decision step
LAMBDA, BETA = 0.9, 3.0
P_ON, P_LOCK, A_MAX = 0.5, 0.8, 0.6
P_FINAL, ALIGN, CONFIRM_STEPS = 0.9, 0.03, 10
LOCK_ALIGN = 0.05                   # m (y-z): stopping this close in front of an object locks it (blend, 35.62)
PRE = np.array([-0.10, 0.0, 0.0])   # pre-grasp point: 10 cm in front of the object (approach along +x)
GRASP_TOL, LIFT = 0.015, 0.10
CANCEL_STEPS = 5
ZONE_FULL = 0.04                    # m: full assist this close (y-z) to a pre-grasp point (zone mode)

DIRS = {'up': (0, 0, 1), 'down': (0, 0, -1), 'left': (0, 1, 0), 'right': (0, -1, 0),
        'forward': (1, 0, 0), 'back': (-1, 0, 0)}
OPPOSITE = {'up': 'down', 'down': 'up', 'left': 'right', 'right': 'left'}


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.zeros_like(v)


class Assist:
    def __init__(self, objects, assist=True, mode='takeover', level=A_MAX, keep=False, shelves=None, zone=None):
        """objects: (n, 3) object positions (grasp points) in the base frame; shelves: (m, 3) centres of the shelf
        tops where an object can be put down (keep=True)"""
        self.obj = np.array(objects, float)
        self.assist = assist
        self.mode = mode
        self.level = level
        self.keep = keep
        self.zone_r = zone
        self.shelves = np.zeros((0, 3)) if shelves is None else np.asarray(shelves, float)
        self.reset()

    def zone(self, g, x):
        """0..1: how much the assist may act for goal g at tool position x (1 everywhere without zone mode)"""
        if self.zone_r is None:
            return 1.0
        d = np.linalg.norm((self.obj[g] + PRE - np.asarray(x, float))[1:])
        return float(np.clip((self.zone_r - d) / (self.zone_r - ZONE_FULL), 0.0, 1.0))

    def place_ok(self, x):
        """the shelf under the held object (its centre at the tool), or None: within 5 cm sideways and the object's
        bottom (centre - 5 cm) at most 2 cm above the shelf top"""
        for sh in self.shelves:
            if np.linalg.norm(x[:2] - sh[:2]) < 0.05 and 0.04 <= x[2] - sh[2] <= 0.07:
                return sh
        return None

    def reset(self):
        self.s = np.zeros(len(self.obj))
        self.goal = None              # locked / final / grasped object index
        self.lock_cmd = None          # takeover: gesture at lock time; blend: gesture that started the final approach
        self.cancel = 0
        self.rest_n = 0
        self.approach = None          # blend: (goal, gesture) the user was pushing toward that goal with, before alignment
        self.armed = True             # blend: a relax counts only after the user moved since the last grasp / put-down
        self.final_block = None       # blend: goal whose final approach the user just left
        self.state = 'steer'          # takeover: steer | approach | grasped | done; blend: steer | final | grasped | done
        self.grip = 0.0               # 0 open .. 1 closed
        self.lift_from = None

    def probs(self):
        e = np.exp(BETA * (self.s - self.s.max()))
        return e / e.sum()

    def _score(self, u, x):
        proj = self.obj + PRE - x
        proj[:, 0] = 0.0                           # the user commands y and z only
        self.s = LAMBDA * self.s + np.array([u @ unit(p) for p in proj])

    def step(self, cmd, x):
        """cmd: established command name or None (Rest / relaxed); x: tool position. Returns velocity (3,)."""
        if self.mode == 'blend':
            return self._step_blend(cmd, x)
        return self._step_takeover(cmd, x)

    # ------------------------------------------------------------------ blend
    def _step_blend(self, cmd, x):
        x = np.asarray(x, float)
        u = np.array(DIRS[cmd], float) if cmd in DIRS else np.zeros(3)
        moving = np.linalg.norm(u) > 0
        if self.state == 'done':
            return np.zeros(3)
        if self.state == 'grasped':
            if self.keep:
                self.obj[self.goal] = x                    # the object moves with the gripper
                if not moving:
                    sh = self.place_ok(x) if self.armed else None
                    if sh is not None:
                        self.rest_n += 1
                        if self.rest_n >= CONFIRM_STEPS:   # relaxed over a shelf: put it down (it settles on the top)
                            self.obj[self.goal] = [x[0], x[1], sh[2] + 0.05]
                            self.grip, self.state, self.final_block = 0.0, 'steer', self.goal
                            self.goal, self.rest_n, self.armed = None, 0, False
                            self.s[:] = 0.0
                    else:
                        self.rest_n = 0
                    return np.zeros(3)
                self.rest_n, self.armed = 0, True
                return V_MAX * u
            if moving and x[2] - self.lift_from >= LIFT:
                self.state = 'done'
            return V_MAX * u
        pre = self.obj + PRE
        if self.final_block is not None and np.linalg.norm((pre[self.final_block] - x)[1:]) > 1.5 * LOCK_ALIGN:
            self.final_block = None
        if not moving:
            near = np.linalg.norm(self.obj - x, axis=1)
            k = int(np.argmin(near))
            if near[k] < GRASP_TOL and self.armed:
                self.rest_n += 1
                if self.rest_n >= CONFIRM_STEPS:       # the user relaxed at the object: grasp
                    self.goal, self.grip, self.state, self.lift_from = k, 1.0, 'grasped', x[2]
                    self.rest_n, self.armed = 0, False
                return np.zeros(3)
            self.rest_n = 0
            if self.state == 'steer' and self.assist:  # stopped in front of an object: lock it (35.62)
                dyz = np.linalg.norm((pre - x)[:, 1:], axis=1)
                g = int(np.argmin(dyz))
                if dyz[g] < LOCK_ALIGN and self.final_block != g:
                    self.state, self.goal = 'final', g
            return np.zeros(3)
        self.rest_n, self.armed = 0, True
        if self.state == 'final':
            g = self.goal
            if cmd == 'up':                            # W: approach (corrects y, z on the way, stops at the object)
                d = self.obj[g] - x
                return min(V_MAX, np.linalg.norm(d) / DT) * unit(d)
            if cmd == 'down':                          # S: back out to the pre-grasp point, then the lock is cancelled
                d = pre[g] - x
                if np.linalg.norm(d) < 0.01 or x[0] <= pre[g][0] + 0.005:   # not past the pre-grasp point: cancel here
                    self.state, self.goal, self.final_block = 'steer', None, g
                    return np.zeros(3)
                return min(V_MAX, np.linalg.norm(d) / DT) * unit(d)
            self.final_block = g                        # A / D: cancel the lock and steer that way
            self.state, self.goal = 'steer', None
        self._score(u, x)
        if not self.assist:
            return V_MAX * u
        P = self.probs()
        g = int(np.argmax(P))
        a = self.level * np.clip((P[g] - P_ON) / (P_FINAL - P_ON), 0.0, 1.0) * self.zone(g, x)
        return V_MAX * unit((1 - a) * u + a * unit(pre[g] - x))

    # ------------------------------------------------------------------ takeover (35.57)
    def _step_takeover(self, cmd, x):
        x = np.asarray(x, float)
        u = np.array(DIRS[cmd], float) if cmd in DIRS else np.zeros(3)
        moving = np.linalg.norm(u) > 0
        if self.state == 'done' or not moving:
            if self.state == 'approach' and not moving:
                self.cancel = 0
            return np.zeros(3)
        if self.state == 'grasped':
            v = V_MAX * np.array([0, 0, 1.0])
            if x[2] - self.lift_from >= LIFT:
                self.state = 'done'
            return v
        pre = self.obj + PRE
        if self.state == 'steer':
            to = pre - x
            self._score(u, x)
            if not self.assist:
                return V_MAX * u
            P = self.probs()
            g = int(np.argmax(P))
            if P[g] >= P_LOCK:
                self.goal, self.lock_cmd, self.state, self.cancel = g, cmd, 'approach', 0
            else:
                a = A_MAX * np.clip((P[g] - P_ON) / (P_LOCK - P_ON), 0.0, 1.0)
                return V_MAX * unit((1 - a) * u + a * unit(to[g]))
        # approach: a held gesture that points toward the locked goal (or any gesture once aligned) = go; a gesture
        # pointing away from it (once aligned in y, z: the opposite of the lock-time gesture) held for CANCEL_STEPS
        # steps cancels the lock: the goal is penalised and the user steers again
        g = self.goal
        to_yz = (pre[g] - x)[1:]
        if np.linalg.norm(to_yz) > 0.02:
            away = u[1:] @ unit(to_yz) <= 0.0
        else:
            away = np.allclose(u, -np.array(DIRS[self.lock_cmd], float))
        if away:
            self.cancel += 1
            if self.cancel >= CANCEL_STEPS:
                self.s[g] -= 2.0
                self.state, self.goal, self.cancel = 'steer', None, 0
                return V_MAX * u
            return np.zeros(3)
        self.cancel = 0
        tgt = pre[g] if np.linalg.norm((pre[g] - x)[1:]) > 0.01 else self.obj[g]   # align in y, z, then go in
        d = tgt - x
        if np.linalg.norm(self.obj[g] - x) < GRASP_TOL:
            self.grip, self.state, self.lift_from = 1.0, 'grasped', x[2]
            return np.zeros(3)
        return min(V_MAX, np.linalg.norm(d) / DT) * unit(d)
