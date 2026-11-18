"""Shared-autonomy assist for wrist-only EMG control of an assistive arm (report 35.57, 2026-11-18; prototype on the
PC, to be ported to C on the MCU after the self-test).

The user controls direction and timing with 4 wrist gestures (S5: up, down, left, right + Rest); the system adds what
the user cannot command: depth (forward / back), gripper orientation and grasping. Every 100 ms (one decision step):

  u        the established command as a unit vector in the user's frame (= robot base frame here: x forward, y left,
           z up); 0 for Rest (or when the activity gate says the user is relaxed). Rest always stops the arm.
  goal     before a goal is locked, each candidate object g scores the agreement of u with the direction to its
           pre-grasp point in the plane the user can command (y, z):
               s_g <- LAMBDA * s_g + cos(u, P_yz (pre_g - x))      (only while u != 0)
           P(g) = softmax(BETA * s). A goal is locked when max P >= P_LOCK.
  blend    before lock: v = |u| V_MAX ((1 - a) u + a d_g) with a = A_MAX * clip((P - P_ON) / (P_LOCK - P_ON), 0, 1)
           for the leading goal (d_g = unit vector to its pre-grasp point, all three axes): the arm already bends
           toward the likely goal while the user steers.
           after lock: holding any direction gesture = "go": v = V_MAX * d_goal (pre-grasp point, then the grasp point);
           the gesture opposite to the one held at lock time, held for CANCEL_STEPS steps, cancels (back to steering).
  grasp    at the grasp point (distance < GRASP_TOL) the gripper closes automatically; then the arm lifts LIFT m while
           the user holds any gesture: done.
Rest / relaxed: v = 0 in every state (the user can always stop).

These parameter values are first guesses, to be tuned in simulation (assist_sim.py) and RViz; not validated.
"""
import numpy as np

V_MAX = 0.08          # m/s
DT = 0.1              # s per decision step
LAMBDA, BETA = 0.9, 3.0
P_ON, P_LOCK, A_MAX = 0.5, 0.8, 0.6
PRE = np.array([-0.10, 0.0, 0.0])   # pre-grasp point: 10 cm in front of the object (approach along +x)
GRASP_TOL, LIFT = 0.015, 0.10
CANCEL_STEPS = 5

DIRS = {'up': (0, 0, 1), 'down': (0, 0, -1), 'left': (0, 1, 0), 'right': (0, -1, 0),
        'forward': (1, 0, 0), 'back': (-1, 0, 0)}


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.zeros_like(v)


class Assist:
    def __init__(self, objects, assist=True):
        """objects: (n, 3) object positions (grasp points) in the base frame"""
        self.obj = np.asarray(objects, float)
        self.assist = assist
        self.reset()

    def reset(self):
        self.s = np.zeros(len(self.obj))
        self.goal = None              # locked object index
        self.lock_cmd = None
        self.cancel = 0
        self.state = 'steer'          # steer | approach | grasped | done
        self.grip = 0.0               # 0 open .. 1 closed
        self.lift_from = None

    def probs(self):
        e = np.exp(BETA * (self.s - self.s.max()))
        return e / e.sum()

    def step(self, cmd, x):
        """cmd: established command name or None (Rest / relaxed); x: tool position. Returns velocity (3,)."""
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
            proj = to.copy()
            proj[:, 0] = 0.0                       # the user commands y and z only
            cos = np.array([u @ unit(p) for p in proj])
            self.s = LAMBDA * self.s + cos
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
