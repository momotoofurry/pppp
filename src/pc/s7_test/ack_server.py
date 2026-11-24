# report 35.85 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""WSL side of the relay round-trip test: accept one connection, ack every command line, send one range label."""
import socket
import time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', 50561)); s.listen(1)
c, _ = s.accept()
n = 0
for line in c.makefile('r'):
    f = line.strip().split(',')
    if len(f) > 2 and f[2] == 'command':
        c.sendall(f'ack,{f[0]}\n'.encode()); n += 1
        if n == 3:
            c.sendall(b'range,10,20,0\n')
    if n >= 5:
        break
time.sleep(1)
print('acked', n, flush=True)
