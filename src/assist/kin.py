"""Kinova Gen3 7-DoF kinematics from the URDF that ros2_kortex ships (kortex_description/robots/gen3_2f85.urdf;
joint origins copied below), for the assist demo in RViz (report 35.57).
FK: base_link -> end_effector_link -> tool point TOOL m further along the end effector's z (between the Robotiq 2F-85
fingertips). IK: one damped-least-squares velocity step for position + orientation.
"""
import numpy as np

# (xyz, rpy) of joint_1 .. joint_7 and the fixed end-effector joint; every joint turns about its local z
ORIGINS = [((0, 0, 0.15643), (3.1416, 0, 0)),
           ((0, 0.005375, -0.12838), (1.5708, 0, 0)),
           ((0, -0.21038, -0.006375), (-1.5708, 0, 0)),
           ((0, 0.006375, -0.21038), (1.5708, 0, 0)),
           ((0, -0.20843, -0.006375), (-1.5708, 0, 0)),
           ((0, 0.00017505, -0.10593), (1.5708, 0, 0)),
           ((0, -0.10593, -0.00017505), (-1.5708, 0, 0))]
EE = ((0, 0, -0.061525), (3.14159265358979, 0, 0))
TOOL = 0.13
LIMITS = {1: 2.41, 3: 2.66, 5: 2.23}             # revolute joints 2, 4, 6 (0-based index), rad


def rpy(r, p, y):
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def tf(xyz, r):
    T = np.eye(4)
    T[:3, :3] = rpy(*r)
    T[:3, 3] = xyz
    return T


def rotz(q):
    T = np.eye(4)
    T[:2, :2] = [[np.cos(q), -np.sin(q)], [np.sin(q), np.cos(q)]]
    return T


def fk(q):
    """-> 4x4 pose of the tool point in base_link"""
    T = np.eye(4)
    for (xyz, r), qi in zip(ORIGINS, q):
        T = T @ tf(xyz, r) @ rotz(qi)
    T = T @ tf(*EE)
    T[:3, 3] = T[:3, 3] + T[:3, 2] * TOOL
    return T


def rot_err(R, Rd):
    """axis-angle vector rotating R to Rd (base frame)"""
    E = Rd @ R.T
    ang = np.arccos(np.clip((np.trace(E) - 1) / 2, -1, 1))
    if ang < 1e-6:
        return np.zeros(3)
    w = np.array([E[2, 1] - E[1, 2], E[0, 2] - E[2, 0], E[1, 0] - E[0, 1]]) / (2 * np.sin(ang))
    return w * ang


def jacobian(q, eps=1e-6):
    T0 = fk(q)
    J = np.zeros((6, 7))
    for i in range(7):
        dq = np.array(q, float)
        dq[i] += eps
        T1 = fk(dq)
        J[:3, i] = (T1[:3, 3] - T0[:3, 3]) / eps
        J[3:, i] = rot_err(T0[:3, :3], T1[:3, :3]) / eps
    return J


def ik_step(q, v, Rd, dt, k_rot=2.0, damp=0.02, qdot_max=1.0):
    """one velocity step: tool linear velocity v (m/s) and orientation pulled toward Rd -> new joint angles"""
    q = np.asarray(q, float)
    T = fk(q)
    w = k_rot * rot_err(T[:3, :3], Rd)
    J = jacobian(q)
    x = np.concatenate([v, w])
    qd = J.T @ np.linalg.solve(J @ J.T + damp ** 2 * np.eye(6), x)
    s = np.abs(qd).max() / qdot_max
    if s > 1:
        qd = qd / s
    qn = q + qd * dt
    for i, lim in LIMITS.items():
        qn[i] = np.clip(qn[i], -lim, lim)
    return qn


def solve(q0, p, Rd, iters=300):
    """position + orientation IK by repeated velocity steps (for the start pose)"""
    q = np.asarray(q0, float)
    for _ in range(iters):
        e = p - fk(q)[:3, 3]
        q = ik_step(q, 5.0 * e, Rd, 0.05)
    return q
