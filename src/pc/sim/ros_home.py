"""Test helper: arm to the 'home' pose of poses_sim.json and gripper open, through ros_relay.py, before a run."""
import json
import socket
import sys

poses = json.load(open(sys.argv[1]))
s = socket.create_connection(('127.0.0.1', 50557), timeout=60)
f = s.makefile('r', encoding='utf-8')
for i, m in enumerate([dict(kind='joints', target=poses['home'], speed=20.0), dict(kind='gripper', target=0.0)], 1):
    s.sendall((json.dumps(dict(id=i, **m)) + '\n').encode())
    while True:
        r = json.loads(f.readline())
        if r.get('id') == i:
            print(m['kind'], r['event'], r.get('note', ''), flush=True)
            break
s.close()
