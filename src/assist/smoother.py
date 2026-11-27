"""Cartesian velocity smoother (trapezoidal acceleration / stop-deceleration limiter) for smooth real-arm motion."""
import numpy as np


class VelocitySmoother:
    def __init__(self, acc_max=0.25, stop_dec=0.60):
        """acc_max: m/s^2 for starting/turning (0 = disabled / pass-through); stop_dec: m/s^2 when stopping."""
        self.acc_max = float(acc_max)
        self.stop_dec = float(stop_dec)
        self.v = np.zeros(3, float)

    def reset(self):
        self.v[:] = 0.0

    def step(self, v_target, dt):
        vt = np.asarray(v_target, float)
        if self.acc_max <= 0.0 or dt <= 0.0:
            self.v = vt.copy()
            return self.v.copy()
        dv = vt - self.v
        n = float(np.linalg.norm(dv))
        stopping = float(np.linalg.norm(vt)) < 1e-6
        a_lim = self.stop_dec if (stopping and self.stop_dec > 0.0) else self.acc_max
        max_dv = a_lim * dt
        if n > max_dv:
            self.v = self.v + dv * (max_dv / n)
        else:
            self.v = vt.copy()
        return self.v.copy()


if __name__ == '__main__':
    sm = VelocitySmoother(acc_max=0.25, stop_dec=0.60)
    dt = 0.02
    # Ramp up to 0.08 m/s: should take ~0.32 s (16 steps), never exceeding acc_max
    prev = np.zeros(3)
    for k in range(20):
        v = sm.step([0.08, 0.0, 0.0], dt)
        assert np.linalg.norm(v - prev) <= 0.25 * dt + 1e-9
        prev = v
    assert abs(sm.v[0] - 0.08) < 1e-9
    # Stop: should reach 0 within ~0.14 s (7 steps)
    for k in range(8):
        v = sm.step([0.0, 0.0, 0.0], dt)
    assert np.linalg.norm(sm.v) < 1e-9
    # Disabled mode
    sm0 = VelocitySmoother(acc_max=0.0)
    assert np.allclose(sm0.step([0.08, 0.0, 0.0], dt), [0.08, 0.0, 0.0])
    print('ALL OK')
