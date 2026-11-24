# report 35.86 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
#!/bin/bash
# 35.86: assist_ros.boardreader with a fake relay: priors, gripper commands, heartbeat / deadman
source /opt/ros/humble/setup.bash
cd /home/momo1234/model-leaf/src/pc/sim
python3 - <<'PY'
import socket, time
import numpy as np
import assist_ros as AR
poll, close = AR.boardreader('127.0.0.1:50571', 'gripper', '/tmp/tb_events.csv', 0.5)
c = socket.create_connection(('127.0.0.1', 50571)); time.sleep(0.2)
def send(s): c.sendall((s + '\n').encode()); time.sleep(0.15)
ok = True
def check(name, cond):
    global ok
    ok &= bool(cond); print(('ok  ' if cond else 'BAD ') + name)
send('1,1,pred,100,0,Rest,,1,0,0,')
send('1,prior,obj,0.1,0.8,0.1')
po = poll.take_prior('obj')
check('object prior parsed and normalised', po is not None and np.allclose(po, [0.1, 0.8, 0.1]))
check('prior taken once', poll.take_prior('obj') is None)
send('1,prior,shelf,1,1,1,1,4')
check('shelf prior normalised', np.allclose(poll.take_prior('shelf'), [0.125] * 4 + [0.5]))
send('1,prior,obj,-1,2,0')
check('negative prior refused', poll.take_prior('obj') is None)
send('1,1,command,101,0,Fist,grip_close,,1,,,')
check('gripper mode: Fist -> grip_close', poll() == 'grip_close')
send('1,1,command,102,0,Rest,none,,1,,,')
check('none -> rest', poll() == 'rest')
send('1,1,command,103,0,WristExt,up,,1,,,')
for k in range(3):
    send('1,1,pred,%d,0,WristExt,,1,0,0,' % (104 + k))
check('held up with heartbeat', poll() == 'up')
time.sleep(0.7)
check('heartbeat stopped 0.7 s -> deadman rest', poll() == 'rest')
send('1,1,pred,110,0,WristExt,,1,0,0,')
check('heartbeat back alone does not resume', poll() == 'rest')
send('1,1,command,111,0,UlnarDev,right,,1,,,')
check('a new command resumes', poll() == 'right')
send('1,1,status,,,,,,,,packets lost,5')
check('packets lost -> rest', poll() == 'rest')
send('1,1,command,112,0,WristExt,up,,1,,,')
check('up again before the reset', poll() == 'up')
import struct
c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
c.close(); time.sleep(0.3)                               # RST: connection reset by peer
check('connection reset -> rest (no crash)', poll() == 'rest')
c = socket.create_connection(('127.0.0.1', 50571)); time.sleep(0.2)
send('1,1,command,113,0,UlnarDev,right,,1,,,')
check('reconnect after the reset works', poll() == 'right')
c.close(); time.sleep(0.3)
check('connection closed -> rest', poll() == 'rest')
print('ALL OK' if ok else 'FAILED')
PY
