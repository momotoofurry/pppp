"""In-place edits of 碩論題目討論_MOMO_v17.pptx (from 2026-10-27 the deck is no longer versioned: only v17 is edited).
Each step checks whether it was already applied, so the script can be re-run on the current v17. Numbers are read
from results/. Writes to a temporary file first and replaces v17 only if every step succeeded.

2026-10-29 first board run (results/bench_board_64mhz_nocache.txt, report 18):
  - 「韌體 v2：Cortex-M7 RAM ...」: the "MCU 時間：待上板" card and the speaker-notes sentence -> the measured times
  - 「工作紀錄（2/2）」: title up to 10/29, one more row (copy of the last row's XML), row heights re-split
usage: python update17.py /d/碩論題目討論_MOMO_v17.pptx
"""
import copy
import os
import re
import shutil
import sys

from pptx import Presentation
from pptx.util import Inches

deck = sys.argv[1]
R = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
prs = Presentation(deck)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


def title_shape(s):
    for sh in s.shapes:
        if sh.name == 'Text 0' and sh.has_text_frame and abs(sh.top - Inches(0.35)) < Inches(0.3):
            return sh
    return None


def find(prefix):
    hits = [s for s in prs.slides if title_shape(s) is not None and title_shape(s).text_frame.text.startswith(prefix)]
    assert len(hits) == 1, (prefix, len(hits))
    return hits[0]


def named(s, name):
    hits = [sh for sh in s.shapes if sh.name == name]
    assert len(hits) == 1, (name, len(hits))
    return hits[0]


def set_text(shape, text_):
    p = shape.text_frame.paragraphs[0]
    p.runs[0].text = text_
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)


def bench(name):
    """stage -> (mean us, max us); 'window' -> us; 'hash' -> (image, votes)"""
    out = {}
    for line in open(os.path.join(R, name), encoding='utf-8'):
        m = re.match(r'(\S.*?)\s+n=\s*\d+\s+mean\s+\d+ cyc\s+(\d+) us\s+max\s+\d+ cyc\s+(\d+) us', line)
        if m:
            out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        m = re.match(r'per 100 ms window \(mean\): \d+ cyc = (\d+) us', line)
        if m:
            out['window'] = int(m.group(1))
    return out


done = []

# ------------------------------------------------------------------ 2026-10-29: first board run
B = bench('bench_board_64mhz_nocache.txt')
win_ms, end_s, os_s = B['window'] / 1000, B['sc_end_block'][0] / 1e6, B['os_calibrate+flash'][0] / 1e6
fe_share = B['features (window)'][0] / B['window']

s12 = find('韌體 v2：Cortex-M7 RAM')
val, lab = named(s12, 'Stat time value'), named(s12, 'Stat time label')
if val.text_frame.text.startswith('MCU 時間'):
    set_text(val, f"{win_ms:.0f} ms／視窗")
    set_text(lab, f"板子實測（64 MHz、無快取）：每 100 ms 視窗 {win_ms:.1f} ms（特徵擷取佔 {fe_share:.0%}）；"
                  f"自我校正一次 {end_s:.2f} s、one-shot {os_s:.1f} s")
    nf = s12.notes_slide.notes_text_frame
    old = '時間要等板子到了用 DWT 計數器量。'
    assert old in nf.text
    nf.text = nf.text.replace(old, f"板子到了以後先用最慢的設定量了一輪：64 MHz、沒開快取，每個 100 ms 的視窗只要 {win_ms:.0f} ms，"
                                   f"一次自我校正 {end_s:.1f} 秒，one-shot 校正 {os_s:.0f} 秒；480 MHz 加快取的正式數字接著量。")
    done.append('slide 12 timing')

lg = find('工作紀錄（2/2）')
tbl = named(lg, 'Table log').table
if not any(r.cells[0].text == '10/29' for r in tbl.rows):
    t = title_shape(lg).text_frame.paragraphs[0]
    assert t.runs[0].text.endswith('10/25–10/27'), t.runs[0].text
    t.runs[0].text = t.runs[0].text.replace('10/25–10/27', '10/25–10/29')
    height = sum(r.height for r in list(tbl.rows)[1:])
    tbl._tbl.append(copy.deepcopy(tbl._tbl.tr_lst[-1]))
    texts = ('10/29', '第一次上板：NUCLEO-H753ZI，CubeMX／HAL 專案跑整條韌體 v2（64 MHz、無快取）',
             f"每 100 ms 視窗 {win_ms:.1f} ms（特徵佔 {fe_share:.0%}）；自我校正一次 {end_s:.2f} s；one-shot {os_s:.1f} s；"
             '每類預測次數和 PC 相同')
    for c, text_ in zip(list(tbl.rows)[-1].cells, texts):
        paras = c.text_frame.paragraphs
        paras[0].runs[0].text = text_
        for r in paras[0].runs[1:]:
            r._r.getparent().remove(r._r)
        for p in paras[1:]:
            p._p.getparent().remove(p._p)
    n = len(tbl.rows) - 1
    for r in list(tbl.rows)[1:]:
        r.height = int(height / n)
    done.append('work log 10/29')
for c in tbl.rows[0].cells:                                              # the log now has a board measurement
    for r in c.text_frame.paragraphs[0].runs:
        if 'PC 模擬或 linker 實測' in r.text:
            r.text = r.text.replace('PC 模擬或 linker 實測', 'PC 模擬、linker 或板子實測')
            done.append('log header')
for c in list(tbl.rows)[-1].cells:                                       # wording of the first run of this step
    for r in c.text_frame.paragraphs[0].runs:
        if r.text.endswith('；預測和 PC 相同'):
            r.text = r.text.replace('；預測和 PC 相同', '；每類預測次數和 PC 相同')
            done.append('10/29 wording')

# ------------------------------------------------------------------ 2026-10-29: 480 MHz + caches (the official numbers)
F = bench('bench_board_480mhz_cache.txt')
f_win, f_end, f_endmax, f_os = F['window'] / 1000, F['sc_end_block'][0] / 1e6, F['sc_end_block'][1] / 1e6, \
    F['os_calibrate+flash'][0] / 1e6
if '64 MHz' in lab.text_frame.text:
    set_text(val, f"{f_win:.1f} ms／視窗")
    set_text(lab, f"板子實測（480 MHz＋快取）：每 100 ms 視窗 {f_win:.2f} ms（預算的 {f_win / 100:.1%}）；"
                  f"自我校正一次 {f_end:.3f} s、one-shot {f_os:.1f} s")
    nf = s12.notes_slide.notes_text_frame
    i = nf.text.index('板子到了以後')
    nf.text = nf.text[:i] + (f"板子上實測：480 MHz 加快取時，每個 100 ms 的視窗只要 {f_win:.2f} ms，不到 3%；一次自我校正 "
                             f"{f_end:.3f} 秒，最多 {f_endmax:.2f} 秒，而且 30 秒才做一次；one-shot 校正約 {f_os:.0f} 秒，"
                             f"主要是抹除 Flash。最慢的 64 MHz、不開快取也只用掉一半的時間。")
    done.append('slide 12 timing 480 MHz')
row = [r for r in tbl.rows if r.cells[0].text == '10/29'][0]
if '480 MHz' not in row.cells[1].text:
    texts = ('10/29', '第一次上板：NUCLEO-H753ZI，CubeMX／HAL 專案跑整條韌體 v2（480 MHz＋快取；另量 64 MHz 無快取）',
             f"每 100 ms 視窗 {f_win:.2f} ms（預算的 {f_win / 100:.1%}）；自我校正一次 {f_end:.3f} s；one-shot {f_os:.1f} s；"
             f"64 MHz 無快取 {win_ms:.1f} ms；每類預測次數和 PC 相同")
    for c, text_ in zip(row.cells, texts):
        p = c.text_frame.paragraphs[0]
        p.runs[0].text = text_
        for r in p.runs[1:]:
            r._r.getparent().remove(r._r)
    done.append('work log 10/29 480 MHz')

# ------------------------------------------------------------------ save
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
tmp = deck + '.tmp.pptx'
prs.save(tmp)
shutil.move(tmp, deck)
print('updated' if done else 'nothing to do', deck, done)
