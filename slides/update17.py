"""In-place edits of 碩論題目討論_MOMO_v17.pptx (from 2026-10-27 the deck is no longer versioned: only v17 is edited).
Each step checks whether it was already applied, so the script can be re-run on the current v17. Numbers are read
from results/. Writes to a temporary file first and replaces v17 only if every step succeeded.

2026-10-29 first board run (results/bench_board_64mhz_nocache.txt, report 18):
  - 「韌體 v2：Cortex-M7 RAM ...」: the "MCU 時間：待上板" card and the speaker-notes sentence -> the measured times
  - 「工作紀錄（2/2）」: title up to 10/29, one more row (copy of the last row's XML), row heights re-split
2026-10-30: new slide 「目前完成的目標」 before the work logs (copy of the work-log slide; status / goal / result);
  both work logs and slide 2's done / to-do cards rewritten in plain words
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

# ------------------------------------------------------------------ 2026-10-29: route B on the board (report 19)
import pandas as pd  # noqa: E402
RB = pd.read_csv(os.path.join(R, 'board_replay_windows.csv'))
agree = (RB.board == RB.pc).mean()
lat_med = RB.latency_ms.median()
row = [r for r in tbl.rows if r.cells[0].text == '10/29'][0]
if '路線 B' not in row.cells[1].text:
    for c, add in zip(list(row.cells)[1:], ('；路線 B：PC 即時串流 2 個 block 到板子',
                                      f"；路線 B 和 PC 逐視窗 {agree:.0%} 相同、端到端延遲中位 {lat_med:.1f} ms")):
        r = c.text_frame.paragraphs[0].runs[-1]
        r.text = r.text.replace('（480 MHz＋快取；另量 64 MHz 無快取）', '（480 MHz＋快取）') + add
    done.append('work log 10/29 route B')
for c in row.cells:                                                      # keep the row to two lines
    r = c.text_frame.paragraphs[0].runs[-1]
    t = r.text.replace('NUCLEO-H753ZI，CubeMX／HAL 專案跑整條韌體 v2', 'NUCLEO-H753ZI 跑整條韌體 v2') \
              .replace('；路線 B：PC 即時串流 2 個 block 到板子', '；路線 B 即時串流') \
              .replace(f"；64 MHz 無快取 {win_ms:.1f} ms", '') \
              .replace('；每類預測次數和 PC 相同；路線 B 和 PC', '；路線 B 和 PC').replace('端到端延遲中位', '延遲中位')
    if t != r.text:
        r.text = t
        done.append('10/29 shorter')

# ------------------------------------------------------------------ 2026-10-30: plain-language progress (goals slide, logs, slide 2)
from pptx.dml.color import RGBColor  # noqa: E402

STATUS_COLOR = {'完成': RGBColor(0x2E, 0x7D, 0x32), '部分': RGBColor(0xB2, 0x6A, 0x00), '未做': RGBColor(0x77, 0x77, 0x77)}


def fill(tbl, header, rows):
    """header + data rows into a copied work-log table; extra rows are copies of the row two up (keeps the banding)"""
    for c, text_ in zip(tbl.rows[0].cells, header):
        set_text(c, text_)
    height = sum(r.height for r in list(tbl.rows)[1:])
    while len(tbl.rows) - 1 > len(rows):
        tbl._tbl.remove(tbl._tbl.tr_lst[-1])
    while len(tbl.rows) - 1 < len(rows):
        tbl._tbl.append(copy.deepcopy(tbl._tbl.tr_lst[-2] if len(tbl.rows) > 2 else tbl._tbl.tr_lst[-1]))
    for r, texts in zip(list(tbl.rows)[1:], rows):
        r.height = int(height / len(rows))
        for c, text_ in zip(r.cells, texts):
            paras = c.text_frame.paragraphs
            set_text(c, text_)
            for p in paras[1:]:
                p._p.getparent().remove(p._p)


PC = pd.read_csv(os.path.join(R, 'paper_comparison.csv')).set_index('metric (%)')
AD = pd.read_csv(os.path.join(R, 'adapt_c_check_summary.csv')).set_index(['shift', 'update'])
PCA = pd.read_csv(os.path.join(R, 'pca_baseline_summary.csv'))
ram = pd.read_csv(os.path.join(R, 'ram_history.csv')).ram_KB.iloc[-1]
RS = pd.read_csv(os.path.join(R, 'board_replay_summary.csv'))
rep = PC.loc['self-cal, all blocks (mean)']
CC = pd.read_csv(os.path.join(R, 'causal_check_summary.csv')).set_index(['shift', 'align', 'upd'])
f0, f5 = AD.loc[(0, 0), 'c_fixed'], AD.loc[(0.5, 0), 'c_fixed']          # fixed model (no alignment needed)
a0, a5 = CC.loc[(0, 'c60', 'R3'), 'adapt_all'], CC.loc[(0.5, 'c60', 'R3'), 'adapt_all']   # firmware of 10/30, causal
v0, v5 = AD.loc[(0, 1), 'c_adapt'], AD.loc[(0.5, 1), 'c_adapt']           # report 12 (alignment saw block 0)
d_lo, d_hi = PCA.v2_vs_pca_cum_diff.min(), PCA.v2_vs_pca_cum_diff.max()

GOAL_TITLE = '目前完成的目標：方法和板子都驗證了，剩真人實驗'
GOAL_HDR = ('狀態', '目標（要回答的問題）', '結果')
GOAL_ROWS = [
    ('完成', '先在電腦上把論文的方法做出來 [1]',
     f"準確率 {rep['ours (seed-avg)']:.2f}%，和論文的 {rep['paper']:.2f}% 幾乎一樣 → 起點可信"),
    ('完成', '整套程式要塞進板子的 256 KB 記憶體',
     f"只用 {ram:.1f} KB，還剩 {256 - ram:.1f} KB"),
    ('完成', '不用重新標記，模型自己適應使用者（RQ2）',
     f"電腦模擬（不偷看的評估）：準確率 {f0:.2f}% → {a0:.2f}%；電極偏掉半格時 {f5:.2f}% → {a5:.2f}%"),
    ('完成', '比另一種免標籤方法好（PCA 對齊 [8]，RQ2）',
     f"電腦模擬：{len(PCA)} 種電極偏移情況都比它高 {d_lo:.1f}～{d_hi:.1f} 個百分點"),
    ('完成', '板子算得夠快（RQ3）',
     f"板子實測：每 0.1 秒的資料 {f_win:.2f} ms 就算完；自我校正一次 {f_end:.3f} 秒；第 1 天校正 {f_os:.1f} 秒"),
    ('部分', '板子上的結果和電腦一樣準（RQ1）',
     f"錄好的資料即時送進板子：{RS.board_acc[0]:.2f}%／{RS.board_acc[1]:.2f}%，每個判斷都和電腦相同；還沒用真的感測器"),
    ('部分', '實驗室電腦的轉送程式',
     f"不用安裝；接板子測過，傳輸錯誤 {int(RS.crc_errors.sum())} 次；還沒接真的 Trigno"),
    ('未做', '真人戴感測器、第 2 天實驗、Kinova 任務（RQ3）、功耗', 'IRB 通過後才能收受試者；功耗要電流表'),
]
GOAL_FOOT = '電腦模擬：20 人 × 11 段資料 × 3 次；板子：NUCLEO-H753ZI。截至 10/30，細節：report.md'
GOAL_NOTES = (
    f"這頁整理目前做到哪裡。在電腦上重現論文、把程式塞進 256 KB、免標籤自我校正和 PCA 比較組都完成了，"
    f"不過準確率還是電腦模擬的數字；10/30 照審查意見把評估改成不偷看 block 0、buffer 轉到新座標，數字是改過以後的。板子上已經量到速度：每 0.1 秒的資料只要 {f_win:.2f} 毫秒，自我校正一次約 "
    f"{f_end:.2f} 秒；把錄好的資料即時送進板子，板子上的每一個判斷都和電腦一樣。實驗室電腦的轉送程式也準備好了。"
    f"還沒做的是接真的 Trigno、真人跨日實驗和 Kinova 任務，要等 IRB；功耗要等電流表。")

goal = [s for s in prs.slides if title_shape(s) is not None and
        title_shape(s).text_frame.text.startswith(('目標進度', '目前完成的目標'))]
if not goal:
    new = prs.slides.add_slide(lg.slide_layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    for sh in lg.shapes:
        new.shapes._spTree.append(copy.deepcopy(sh._element))
    ns = new.notes_slide
    if ns.notes_text_frame is None:                                      # this deck's notes master has no body placeholder
        ns.shapes._spTree.append(copy.deepcopy(find('我想做的事').notes_slide.notes_placeholder._element))
    ids = prs.slides._sldIdLst
    el = ids[-1]
    ids.remove(el)
    ids.insert(list(prs.slides).index(find('工作紀錄（1/2）')), el)       # before the work logs
    goal = [new]
gs = goal[0]
def rows_text(t):
    return [tuple(c.text for c in r.cells) for r in list(t.rows)[1:]]


if title_shape(gs).text_frame.text != GOAL_TITLE or rows_text(named(gs, 'Table log').table) != GOAL_ROWS:
    set_text(title_shape(gs), GOAL_TITLE)
    fill(named(gs, 'Table log').table, GOAL_HDR, GOAL_ROWS)
    for r in list(named(gs, 'Table log').table.rows)[1:]:
        run = r.cells[0].text_frame.paragraphs[0].runs[0]
        run.font.bold = True
        run.font.color.rgb = STATUS_COLOR[run.text]
    set_text(named(gs, 'Text 2'), GOAL_FOOT)
    gs.notes_slide.notes_text_frame.text = GOAL_NOTES
    done.append('goals slide')

# the work logs in plain words (same numbers as the earlier rows, from report.md / results/)
LOG_HDR = ('日期', '做了什麼', '結果')
LOG1 = [
    ('10/17', '在電腦上重現論文；把模型縮小、改寫成 C',
     '準確率 84.63%（論文 84.6%）；模型縮到 88.1 KB，放得進板子'),
    ('10/18', '讓自我校正少用記憶體（少存資料、樹變小）',
     '記憶體估 219 KB；準確率 83.44%，仍比不校正高 3.76 個百分點'),
    ('10/19', '自我校正全部改寫成 C；測跨兩天的資料',
     'C 版 83.22%，和 Python 版（83.27%）沒有差別；1 人第 2 天從 75% 拉回 93%'),
    ('10/20', '簡報 v12（給老師的短版）', '—'),
    ('10/23', '第 1 天校正、即時判斷也寫成板子的程式；訂好 PC↔板子的傳輸格式',
     '校正後 79.40%，和 Python 版（79.68%）沒有差別；記憶體 253.2 KB，勉強塞進 256 KB'),
    ('10/24', '測只用 6 個電極夠不夠；再省記憶體',
     '6 個 81.53% vs 8 個 81.85%，沒有差別；記憶體降到 223.8 KB'),
]
LOG2 = [
    ('10/25', '模擬束帶戴歪（電極轉了一格或半格）；開機自動找回方向',
     '轉一格時掉到 45.9%，自動找回方向後回到 83.23%；偏半格 71.42%（最難）'),
    ('10/26', '讓資料的正規化跟著使用者慢慢更新',
     '偏半格再多 3.23 個百分點（p = 0.02）；休息時間多也不會變差'),
    ('10/27', '簡化：拿掉 t-SNE，做出韌體 v2',
     '拿掉後準確率一樣（83.21% vs 83.23%），記憶體降到 175.9 KB；v2 83.87%、偏半格 74.74%'),
    ('10/27', '試 3 個提高準確率的方法：校正資料加轉動、挑樹、只用可靠的標籤',
     '都沒有明顯改善（最多 +0.96，不顯著），加轉動還讓沒偏移時 −2.52 → 都不採用'),
    ('10/27', '調整「什麼時候才送出指令」',
     '預設設定：73.6% 的判斷可用，每分鐘 1.14 次誤指令；換規則沒有更好'),
    ('10/27', '比較組：另一種免標籤方法（PCA 對齊 [8]）',
     f"我們的 v2 在 {len(PCA)} 種偏移都比它高 {d_lo:.1f}–{d_hi:.1f} 個百分點"),
    ('10/29', '第一次上板（480 MHz）；用錄好的資料即時串流到板子（路線 B）',
     f"每 0.1 秒資料只花 {f_win:.2f} ms；自我校正一次 {f_end:.3f} s；每個判斷都和電腦相同、延遲 {lat_med:.1f} ms"),
    ('10/30', '實驗室電腦的轉送程式；照審查修正評估（開機對齊不偷看、buffer 轉座標），放進韌體',
     f"轉送程式傳輸錯誤 {int(RS.crc_errors.sum())} 次；修正後 {a0:.2f}%、偏半格 {a5:.2f}%（原報 {v0:.2f}／{v5:.2f}）；"
     '開機只做一種手勢會估錯 → 規定 8 秒做 6 種'),
]
LOG_FOOT = '電腦模擬：20 人 × 11 段資料 × 3 次；「個百分點」是準確率相差多少；p < 0.05 才算真的有差別。細節：report.md、Notion'
lg1 = find('工作紀錄（1/2）')
t1 = named(lg1, 'Table log').table
if t1.rows[0].cells[2].text != LOG_HDR[2]:
    fill(t1, LOG_HDR, LOG1)
    set_text(named(lg1, 'Text 2'), LOG_FOOT)
    done.append('log 1 plain')
if tbl.rows[0].cells[2].text != LOG_HDR[2] or rows_text(tbl) != LOG2:
    fill(tbl, LOG_HDR, LOG2)
    set_text(named(lg, 'Text 2'), LOG_FOOT)
    set_text(title_shape(lg), '工作紀錄（2/2）：10/25–10/30')
    done.append('log 2 plain')

# slide 2: the "done" / "to do" cards were written before the board arrived
s2 = find('我想做的事')
S2_DONE = (f"重現論文：{rep['ours (seed-avg)']:.2f}%（論文 {rep['paper']:.1f}%）",
           f"韌體：{a0:.1f}%，只用 {ram:.1f} KB 記憶體",
           f"電極偏半格：{f5:.1f}% → {a5:.1f}%",
           f"比 PCA 對齊 [8] 高 {d_lo:.1f}～{d_hi:.1f} 點",
           f"板子上每 0.1 秒算 {f_win:.2f} ms，判斷和電腦相同")
if (not named(s2, 'Col 0 head').text_frame.text.startswith('已經做到（電腦') or
        [p.text.lstrip('• ') for p in named(s2, 'Col 0 list').text_frame.paragraphs] != list(S2_DONE)):
    set_text(named(s2, 'Col 0 head'), '已經做到（電腦＋板子）')
    for sh, items in ((named(s2, 'Col 0 list'),
                       (S2_DONE[0],
                        S2_DONE[1],
                        f"電極偏半格：{f5:.1f}% → {a5:.1f}%",
                        f"比 PCA 對齊 [8] 高 {d_lo:.1f}～{d_hi:.1f} 點",
                        f"板子上每 0.1 秒算 {f_win:.2f} ms，判斷和電腦相同")),
                      (named(s2, 'Col 2 list'),
                       ('真人戴 Trigno 收資料，跨日驗證（RQ1、RQ2）',
                        'Kinova 夾放＋預設位置：成功率、誤觸發（RQ3）',
                        '功耗（要電流表）'))):
        tf = sh.text_frame
        for p in tf.paragraphs[len(items):]:
            p._p.getparent().remove(p._p)
        while len(tf.paragraphs) < len(items):
            tf._txBody.append(copy.deepcopy(tf.paragraphs[-1]._p))
        for p, text_ in zip(tf.paragraphs, items):
            p.runs[0].text = ('• ' + text_) if p.runs[0].text.startswith('•') else text_
            for r in p.runs[1:]:
                r._r.getparent().remove(r._r)
    for r in named(s2, 'Ask').text_frame.paragraphs[0].runs:
        if '已訂購' in r.text:
            r.text = r.text.replace('開發板 NUCLEO-H753ZI 已訂購', '開發板已到、已上板驗證')
    done.append('slide 2 progress')

# ------------------------------------------------------------------ save
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
tmp = deck + '.tmp.pptx'
prs.save(tmp)
shutil.move(tmp, deck)
print('updated' if done else 'nothing to do', deck, done)
