"""print where the objects really are in Gazebo (gazebo_ros_state /gazebo/get_entity_state): position and tilt"""
import math
import sys
import rclpy
from gazebo_msgs.srv import GetEntityState

rclpy.init()
n = rclpy.create_node('gz_objects')
cli = n.create_client(GetEntityState, '/gazebo/get_entity_state')
if not cli.wait_for_service(timeout_sec=10.0):
    sys.exit('no /gazebo/get_entity_state')
for i in range(3):
    req = GetEntityState.Request()
    req.name, req.reference_frame = f'object_{i}', 'world'
    fut = cli.call_async(req)
    rclpy.spin_until_future_complete(n, fut, timeout_sec=5.0)
    r = fut.result()
    p, q = r.state.pose.position, r.state.pose.orientation
    tilt = math.degrees(2 * math.acos(min(1.0, math.sqrt(q.w * q.w + q.z * q.z))))   # angle of the axis from vertical
    print(f'object_{i}: x {p.x:.3f} y {p.y:.3f} z {p.z:.3f}  tilt {tilt:.1f} deg  ({"ok" if r.success else "not found"})')
rclpy.shutdown()
