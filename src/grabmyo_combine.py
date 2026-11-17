"""combine the per-subject lines of the 4 GrabMyo runs: mean per condition and day, and paired differences on days 8+29"""
import glob
import re
import statistics as st

N = 'results/grabmyo'
CONDS = ['fixed', 'cue', 'cue_soft', 'acc', 'acc_soft']
rows, lines = {}, []
for f in sorted(glob.glob(f'{N}/grabmyo_crossday_*.txt')):
    for ln in open(f, encoding='utf-8'):
        m = re.match(r'\s*(\d+) (ring8|4ch)\s+(G\d)\s+(.*)$', ln)
        if not m:
            continue
        vals = [tuple(float(x) for x in v) for v in re.findall(r'(\d+\.\d)/\s*(\d+\.\d)/\s*(\d+\.\d)', m.group(4))]
        rows.setdefault((m.group(2), m.group(3)), {})[int(m.group(1))] = dict(zip(CONDS, vals))
        lines.append(ln.rstrip())
out = [f'subjects per config: ' + ', '.join(f'{k[0]} {k[1]} {len(v)}' for k, v in rows.items())]
for (cfg, s), subj in rows.items():
    out.append(f'\n{cfg} {s} (n {len(subj)}): mean day1 / day8 / day29')
    for c in CONDS:
        m = [st.mean(v[c][d] for v in subj.values()) for d in range(3)]
        out.append(f'  {c:9s} {m[0]:5.1f} / {m[1]:5.1f} / {m[2]:5.1f}')
    late = {c: [(v[c][1] + v[c][2]) / 2 for v in subj.values()] for c in CONDS}
    for c in ('acc', 'cue_soft', 'acc_soft', 'fixed'):
        d = [a - b for a, b in zip(late[c], late['cue'])]
        out.append(f'  {c:9s} - cue (days 8+29): {st.mean(d):+5.2f} (SD {st.stdev(d):.2f}), better in {sum(x > 0 for x in d)}/{len(d)}')
    d = [a - b for a, b in zip(late['acc_soft'], late['acc'])]
    out.append(f'  acc_soft  - acc (days 8+29): {st.mean(d):+5.2f}, better in {sum(x > 0 for x in d)}/{len(d)}')
    out.append(f'  >= 85 % on days 8+29 (mean): cue {sum(x >= 85 for x in late["cue"])}, acc_soft {sum(x >= 85 for x in late["acc_soft"])} of {len(d)}')
open(f'{N}/combined.txt', 'w', encoding='utf-8').write('\n'.join(lines + [''] + out) + '\n')
print('\n'.join(out))
