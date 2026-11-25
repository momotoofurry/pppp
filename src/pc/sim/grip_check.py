"""Gripper feedback for the real arm (report 35.107): did the Robotiq 2F-85 close on an object, or on air?

The GripperCommand action (robotiq_gripper_controller, a GripperActionController) returns the finger joint position
(knuckle, rad: 0 = open, about 0.8 = fully closed), stalled (stopped before the goal) and reached_goal. Closing on a
6 cm cylinder stops the fingers about half way: the 85 mm stroke closes to about 60 mm, a knuckle of roughly
(85 - 60) / 85 x 0.8 = 0.24 rad [to be checked on the real arm, SOP 6.3d]. Closing on air goes to the end.
  outcome(position, stalled, reached_goal) -> 'object' | 'empty'
Only meaningful with real fingers: the fake hardware and Gazebo (gz_attach.py holds the object by teleporting it)
always report a fully closed gripper, so assist_ros.py checks it only with --grip-check."""

EMPTY_POS = 0.70        # rad: a close that ends beyond this held nothing (fully closed ~0.8; 6 cm object ~0.24)


def outcome(position, stalled, reached_goal):
    """'object' if the fingers stopped well before fully closed, else 'empty'"""
    if position is None:
        return 'empty'
    return 'object' if float(position) < EMPTY_POS else 'empty'


if __name__ == '__main__':
    ok = True
    for pos, st, rg, want in ((0.24, True, False, 'object'), (0.55, True, False, 'object'), (0.79, False, True, 'empty'),
                              (0.80, False, True, 'empty'), (0.72, True, False, 'empty'), (None, False, False, 'empty')):
        got = outcome(pos, st, rg)
        print(('ok   ' if got == want else 'FAIL ') + f'position {pos} stalled {st} reached {rg} -> {got}')
        ok &= got == want
    print('ALL OK' if ok else 'SOME FAILED')
