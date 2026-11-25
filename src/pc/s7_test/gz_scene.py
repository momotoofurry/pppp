"""35.101 Gazebo rehearsal helper (the helper's job in the real study): where did the previous trial's object really
end up, then put every object back at its start position (/gazebo/set_entity_state).
  python3 gz_scene.py <scene> [<prev object> <prev shelf>]
prints 'PHYSICAL obj <k> on shelf <s> upright|tilted <deg> -> ok|FAIL' for the previous trial, then 'RESET n objects'."""
import math
import os
import sys

import rclpy
from gazebo_msgs.msg import EntityState
from gazebo_msgs.srv import GetEntityState, SetEntityState

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'assist'))
import scenes as SC  # noqa: E402

scene = sys.argv[1]
OBJ, SHELVES = SC.load(scene)
rclpy.init()
n = rclpy.create_node('gz_scene')
get = n.create_client(GetEntityState, '/gazebo/get_entity_state')
put = n.create_client(SetEntityState, '/gazebo/set_entity_state')
if not get.wait_for_service(timeout_sec=10.0) or not put.wait_for_service(timeout_sec=10.0):
    sys.exit('no gazebo state services')


def call(cli, req):
    fut = cli.call_async(req)
    rclpy.spin_until_future_complete(n, fut, timeout_sec=5.0)
    return fut.result()


if len(sys.argv) > 3:
    k, want = int(sys.argv[2]), int(sys.argv[3])
    req = GetEntityState.Request()
    req.name, req.reference_frame = f'object_{k}', 'world'
    r = call(get, req)
    p, q = r.state.pose.position, r.state.pose.orientation
    tilt = math.degrees(2 * math.acos(min(1.0, math.sqrt(q.w * q.w + q.z * q.z))))
    on = SC.shelf_of([p.x, p.y, p.z], SHELVES)
    ok = on == want and tilt < 10
    print(f'PHYSICAL obj {k} at ({p.x:.3f}, {p.y:.3f}, {p.z:.3f}) on shelf {on} tilt {tilt:.1f} deg (target {want}) -> '
          f'{"ok" if ok else "FAIL"}', flush=True)
for i, o in enumerate(OBJ):
    s = EntityState()
    s.name, s.reference_frame = f'object_{i}', 'world'
    s.pose.position.x, s.pose.position.y, s.pose.position.z = float(o[0]), float(o[1]), float(o[2]) + 0.001
    s.pose.orientation.w = 1.0
    req = SetEntityState.Request()
    req.state = s
    call(put, req)
print(f'RESET {len(OBJ)} objects', flush=True)
rclpy.shutdown()
