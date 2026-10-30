"""In-place edits of 碩論題目討論_MOMO_v17.pptx (from 2026-10-27 the deck is no longer versioned: only v17 is edited).
Each step checks whether it was already applied, so the script can be re-run on the current v17. Numbers are read
from results/. Writes to a temporary file first and replaces v17 only if every step succeeded.

2026-10-29 first board run (results/bench_board_64mhz_nocache.txt, report 18):
  - 「韌體 v2：Cortex-M7 RAM ...」: the "MCU 時間：待上板" card and the speaker-notes sentence -> the measured times
  - 「工作紀錄（2/2）」: title up to 10/29, one more row (copy of the last row's XML), row heights re-split
2026-10-30 (restructure): main deck = claim, questions, architecture, 4 key results, done / not done, answers to
  the reviews, stop rules, study design; the other slides go to the appendix (nothing deleted)
2026-10-30 (review): claims limited to the evidence (slides 2, 3, 5, 6, 12, 16, 17), version tags on the
  evidence slides, new slide 「失敗條件與停止規則」 after the goals slide
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

GOAL_TITLE = '目前完成的目標：公開資料與板子已驗證，真人跨日待驗證'
GOAL_HDR = ('狀態', '目標（要回答的問題）', '結果')
GOAL_ROWS = [
    ('完成', '先在電腦上把論文的方法做出來 [1]',
     f"準確率 {rep['ours (seed-avg)']:.2f}%，和論文的 {rep['paper']:.2f}% 幾乎一樣 → 起點可信"),
    ('完成', '整套程式要塞進板子的 256 KB 記憶體',
     f"只用 {ram:.1f} KB，還剩 {256 - ram:.1f} KB"),
    ('部分', '一次初始校正後，模型免標籤自己適應（RQ2）',
     f"公開資料因果回放＋MCU 實作完成：{f0:.2f}% → {a0:.2f}%，偏半格 {f5:.2f}% → {a5:.2f}%（開發集）；真人跨日待驗證"),
    ('完成', '比另一種免標籤方法好（PCA 對齊 [8]，RQ2）',
     f"公開資料：{len(PCA)} 種電極偏移情況都比它高 {d_lo:.1f}～{d_hi:.1f} 個百分點"),
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
     '拿掉後準確率一樣（83.21% vs 83.23%），記憶體降到 175.9 KB；v2 83.87%、偏半格 74.74%（舊評估）'),
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
if (not named(s2, 'Col 0 head').text_frame.text.startswith('已經做到（') or
        [p.text.lstrip('• ') for p in named(s2, 'Col 0 list').text_frame.paragraphs] != list(S2_DONE)):
    set_text(named(s2, 'Col 0 head'), '已經做到（公開資料＋板子）')
    for sh, items in ((named(s2, 'Col 0 list'),
                       (S2_DONE[0],
                        S2_DONE[1],
                        f"電極偏半格：{f5:.1f}% → {a5:.1f}%",
                        f"比 PCA 對齊 [8] 高 {d_lo:.1f}～{d_hi:.1f} 點",
                        f"板子上每 0.1 秒算 {f_win:.2f} ms，判斷和電腦相同")),
                      (named(s2, 'Col 2 list'),
                       ('凍結版本，用獨立受試者的真實 Trigno 跨日資料驗證（RQ1、RQ2）',
                        '非控制動作的誤觸發／分鐘；開機流程的成功率與負擔',
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

# ------------------------------------------------------------------ 2026-10-30: review — claims match the evidence
from pptx.util import Pt  # noqa: E402

STATUS_COLOR.update({'已做': RGBColor(0x2E, 0x7D, 0x32), '限制': RGBColor(0xC6, 0x28, 0x28)})


def set_list(sh, items):
    """one paragraph per item, keeping the first run's format; '• ' kept if the box used it"""
    tf = sh.text_frame
    bullet = tf.paragraphs[0].runs[0].text.startswith('•')
    for p in tf.paragraphs[len(items):]:
        p._p.getparent().remove(p._p)
    while len(tf.paragraphs) < len(items):
        tf._txBody.append(copy.deepcopy(tf.paragraphs[-1]._p))
    for p, text_ in zip(tf.paragraphs, items):
        p.runs[0].text = ('• ' + text_) if bullet else text_
        for r in p.runs[1:]:
            r._r.getparent().remove(r._r)


def texts(sh):
    return [p.text for p in sh.text_frame.paragraphs]


def put(sh, text_):
    """single-paragraph text; returns 1 if it changed"""
    if sh.text_frame.text == text_:
        return 0
    set_text(sh, text_)
    for p in sh.text_frame.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    return 1


def put_list(sh, items):
    want = [('• ' + t) if sh.text_frame.paragraphs[0].runs[0].text.startswith('•') else t for t in items]
    if texts(sh) == want:
        return 0
    set_list(sh, items)
    return 1


def version_tag(s, text_):
    hits = [sh for sh in s.shapes if sh.name == 'Version tag']
    if hits:
        if hits[0].text_frame.text == '附錄｜' + text_:       # moved to the appendix later (restructure step)
            return 0
        return put(hits[0], text_)
    tb = s.shapes.add_textbox(Inches(7.7), Inches(0.08), Inches(5.0), Inches(0.3))
    tb.name = 'Version tag'
    tf = tb.text_frame
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = 3                                                       # right
    r = p.add_run()
    r.text = text_
    r.font.size = Pt(11)
    r.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
    return 1


n_rev = 0
# slide 2: claims
s2 = find('我想做的事')
n_rev += put(named(s2, 'Lead'), '把 Jiang 的自我校正隨機森林 [1][7] 放進 STM32H7（256 KB RAM 內）：一次初始有標籤校正後，'
                                 '之後跨日使用免標籤適應；預計用 Kinova 離散指令任務驗證')
n_rev += put(named(s2, 'Col 0 head'), '已經做到（公開資料＋板子）')
n_rev += put(named(s2, 'Col 1 head'), '和現有研究的差別')
n_rev += put_list(named(s2, 'Col 1 list'), ['Jiang [1][2][7]：只在 PC 上跑，沒有記憶體限制',
                                            'Zanghieri [8]：GAP9 免標籤，但只做特徵層對齊、不更新分類器',
                                            'Orlandi [12]：GAP9 裝置端重訓，偽標籤靠已知任務目標',
                                            '本研究：單核 Cortex-M7、256 KB 預算、分群偽標籤＋換樹，不需任務目標'])
n_rev += put_list(named(s2, 'Col 2 list'), ['凍結版本，用獨立受試者的真實 Trigno 跨日資料驗證（RQ1、RQ2）',
                                            '非控制動作的誤觸發／分鐘；開機流程的成功率與負擔',
                                            'Kinova 夾放＋預設位置：成功率、誤觸發（RQ3）',
                                            '功耗（要電流表）'])

# slide 3: contributions, ③ is a plan
s3 = find('和最接近的研究差在哪')
t3 = [sh for sh in s3.shapes if sh.has_table][0].table
for r in t3.rows:
    if r.cells[0].text == '更新需要標籤？':
        n_rev += put(r.cells[3], '初次校正之後不需要（偽標籤，重新訓練分類器）')
    if r.cells[0].text == '受試者即時跨日':
        n_rev += put(r.cells[3], '預計：EMG 運算在 MCU 上（PC 只當感測器橋接）＋Kinova 任務')
c3 = named(s3, 'Text 1').text_frame.paragraphs[0].runs
C3 = ('貢獻　', f"① 方法：一次初始校正後、256 KB RAM 內的免標籤自我校正 RF（公開資料因果回放 {a0:.1f}%，固定模型 {f0:.1f}%；"
               f"開發集結果）　② 系統：分群偽標籤＋換樹在單核 Cortex-M7 上執行，不需任務目標（[8] 只做特徵層對齊，[12] 靠任務目標）"
               f"　③ 預計驗證：真人跨日＋Kinova 閉迴路（還沒做）")
if [r.text for r in c3] != list(C3):
    c3[0].text, c3[1].text = C3
    for r in c3[2:]:
        r._r.getparent().remove(r._r)
    n_rev += 1

# slide 5: system boundary
s5 = find('STM32 做')
n_rev += put(title_shape(s5), 'STM32 做 EMG 運算與決策，PC 只轉送資料與指令')
n_rev += put_list(named(s5, 'Box 0 body'), ['8 通道、2 kHz', '現在：PC 串流（路線 B）', '之後：類比輸出→ADC'])
n_rev += put_list(named(s5, 'Box 2 body'), ['樣本：Trigno→UART', '指令：→Kortex API', '不做 EMG 運算', '記錄時間戳'])
n_rev += put_list(named(s5, 'Card 0 body'), ['RF 投票比例低於門檻 → 不送指令', '連續 k 個視窗同一手勢才觸發',
                                             'τ 0.6、k 3（凍結，先導不再調）'])
n_rev += put_list(named(s5, 'Card 2 body'), ['主要：任務成功率、誤觸發／分鐘', '次要：完成時間、離線準確率',
                                             '端到端延遲：動作開始到手臂開始動'])

# slide 6: pre-training does not use pilot data (pilot = validation only)
s6 = find('Flash 存預訓練樹池')
n_rev += put(named(s6, 'Text 5'), '作者用 66 人公開資料訓練的樹（截到深度 10），存在 Flash；先導資料只做驗證，不拿來訓練')
n_rev += put(named(s6, 'Text 11'), '第 1 天（唯一一次有標籤）每個手勢錄 2 秒：剪枝預訓練樹（Flash）＋附加新樹（RAM）')

# version tags on the evidence slides
n_rev += version_tag(find('偽標籤不需要 t-SNE'), 'Ablation：t-SNE vs 不嵌入（v2 之前的流程）')
n_rev += version_tag(find('z-score 跟著更新'), 'Ablation：t-SNE 版流程')
s12 = find('韌體 v2：Cortex-M7 RAM')
n_rev += version_tag(s12, '韌體 v2：不做 t-SNE＋類別平衡 z-score')
s13 = [s for s in prs.slides if title_shape(s) is not None and '跨兩天 demo' in title_shape(s).text_frame.text][0]
n_rev += version_tag(s13, '單一受試者跨日 demo（舊版 t-SNE 韌體邏輯）')
n_rev += put(title_shape(s13), '1 人跨兩天 demo（舊版 t-SNE）：第 2 天拉回 92%')
s16 = find('束帶情境')
n_rev += version_tag(s16, '模擬：公開資料的通道內插偏移')

# slide 12: port correctness = bit-exact comparisons, not a p value
n_rev += put(named(s12, 'Stat ram value'), f"{ram:.1f} KB")
n_rev += put(named(s12, 'Stat ram label'), '完整韌體的 RAM（含 10/30 的 buffer 轉座標）；舊版 223.8 KB；拿掉 t-SNE 92.5 KB')
n_rev += put(named(s12, 'Stat est label'), f"C 版，舊評估（偷看 block 0）；轉法 60／60 和 Python 相同，準確率差 +0.21（p = 0.06，"
                                            f"不是等效檢定）。因果版 {a0:.2f}%")
n_rev += put(named(s12, 'Footnote'), '移植正確的主要證據是逐位比對：特徵、one-shot、預測和 Python 逐位相同；板子關掉 FMA 後和 PC 逐位相同'
                                     '（第 18 節）；自我校正的樹是隨機的，只能比準確率分布。RAM = .data＋.bss＋最深靜態 stack（linker＋callgraph '
                                     '上界，執行期峰值還沒量）。Flash 111 KB（含 88 KB 模型）。')

# slide 16: the start-up needs the prescribed gestures
n_rev += put(title_shape(s16), '束帶情境：開機做完指定動作才能救回整格轉動，半格最難')
n_rev += put(named(s16, 'Stat tail label'), '開機看到 6 種手勢時整格轉動 20／20 估對；只做 Power 15／20、只休息 7／20 → 規定 8 秒依序做 6 種')
n_rev += put(named(s16, 'Stat gain label'), f"偏半格最難：兩邊一樣像，對齊沒幫助；現在的韌體 {a5:.1f}%")
n_rev += put(named(s16, 'Footnote'), '偏移 k + f 格：每個通道 = (1 − f) × 第 c + k 個電極 ＋ f × 第 c + k + 1 個電極的原始 EMG（相鄰電極線性內插，'
                                     '一階近似）。開機對齊：至少 60 個視窗（6 秒）內做過多種手勢，用每個通道 log RMS／MAV／WL 的平均和 calibration '
                                     '的輪廓比，選 8 種整數轉法中最像的。資料是貼片不是束帶；沒有模擬使用中慢慢滑動。')

# slide 17: Kinova is a planned validation
n_rev += put(title_shape(find('核心是嵌入式自我校正')), '核心是嵌入式自我校正，Kinova 閉迴路是預計的驗證')

# new slide after the goals slide: failure conditions and stop rules
STOP_TITLE = '失敗條件與停止規則：哪些情況不主張、系統怎麼處理'
STOP_HDR = ('狀態', '情況', '系統怎麼做／怎麼寫')
STOP_ROWS = [
    ('限制', '偏移超過 ¼ 格，或偏半格', f"不主張開機對齊能解決（半格時 {a5:.1f}%）；靠配戴對齊記號，先導時量實際做到幾次"),
    ('部分', '開機的指定手勢沒做完（< 60 個視窗）', '韌體回 ALIGN_SHORT、轉法不變；還要加：PC 提示重做，對齊成功前不送指令'),
    ('已做', '某類手勢在 block 裡太少', '每類 ≥ 5 個視窗才算進 z-score、≥ 2 類才更新；最少的類 < 10 筆時不分群、用模型標籤'),
    ('已做', '更新後變差', '只出現少數手勢時會越學越差（−6.4 點）：預測少於 5 類就不更新（−1.3）；所以第 1 天校正後先 verify，< 70% 重做（report 22）'),
    ('已做', '更新期間的即時控制', '推論在中斷內持續；板子 33 分鐘、65 次更新：不掉資料，更新期間最大延遲 9.7 ms、緩衝只用 6%（report 21）'),
    ('已做', '終點的優先順序', '主要：任務成功率、誤觸發／分鐘；次要：完成時間、離線準確率。先導前寫進 IRB 計畫'),
]
stop = [s for s in prs.slides if title_shape(s) is not None and title_shape(s).text_frame.text.startswith('失敗條件')]
if not stop:
    new = prs.slides.add_slide(gs.slide_layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    for sh in gs.shapes:
        new.shapes._spTree.append(copy.deepcopy(sh._element))
    ns = new.notes_slide
    if ns.notes_text_frame is None:
        ns.shapes._spTree.append(copy.deepcopy(find('我想做的事').notes_slide.notes_placeholder._element))
    ids = prs.slides._sldIdLst
    el = ids[-1]
    ids.remove(el)
    ids.insert(list(prs.slides).index(gs) + 1, el)
    stop = [new]
ss = stop[0]
st_t = named(ss, 'Table log').table
if title_shape(ss).text_frame.text != STOP_TITLE or rows_text(st_t) != STOP_ROWS:
    set_text(title_shape(ss), STOP_TITLE)
    fill(st_t, STOP_HDR, STOP_ROWS)
    for r in list(st_t.rows)[1:]:
        run = r.cells[0].text_frame.paragraphs[0].runs[0]
        run.font.bold = True
        run.font.color.rgb = STATUS_COLOR[run.text]
    put(named(ss, 'Text 2'), '限制＝不主張；已做＝韌體或計畫裡已經有；部分／未做＝先導前要補。細節：VALIDATION_PLAN.md、report.md 第 20 節')
    ss.notes_slide.notes_text_frame.text = (
        '這頁回答「什麼情況下這套系統不該被相信」。偏移超過四分之一格不主張能解決；開機沒做完指定動作，韌體會回報、不改轉法，'
        '但還要在 PC 端加上提示重做、對齊成功前不送指令；一段時間只出現少數手勢時，自我校正會越學越差，所以預測少於 5 類就不更新；'
        '這條在第 1 天校正很差時會拉不回來，所以校正後先做驗證，認對不到七成就重做。正式試驗的主要終點是任務成功率和每分鐘誤觸發，離線準確率是次要。')
    n_rev += 1
if n_rev:
    done.append(f'review fixes ({n_rev})')

# ------------------------------------------------------------------ 2026-10-30: restructure (main deck + appendix)
# main deck: claim, questions, architecture, 4 key results, done / not done, answers to the reviews, stop rules,
# study design; the other result slides and the work logs move to the appendix (nothing is deleted)
LR = pd.read_csv(os.path.join(R, 'board_replay_longrun_phases.csv')).set_index('phase')
SM = pd.read_csv(os.path.join(R, 'stress_check_summary.csv')).set_index(['scen', 'var'])
VC = pd.read_csv(os.path.join(R, 'verify_check_summary.csv')).set_index('cal')
PW = pd.read_csv(os.path.join(R, 'power_calc.csv'))
dz = PW[PW.kind == 'dev effect'].set_index('scen').dz
mdz = PW[PW.kind == 'min detectable dz'].set_index('n').dz
la, ld = LR.loc['all'], LR.loc['during']
AS = pd.read_csv(os.path.join(R, 'arm_selfcal_size.csv'))
stack_static = AS[(AS.variant == 'board2') & (AS.opt == '-Os')].worst_stack_bytes.iloc[0]


def put_any(sh, text_):
    """put() that also works on an empty placeholder (no run yet)"""
    p = sh.text_frame.paragraphs[0]
    if not p.runs:
        if not text_:
            return 0
        p.add_run().text = text_
        return 1
    return put(sh, text_)


def ttl(s):
    """title of any slide (content slides: top Text 0; dark dividers: the first Text 0)"""
    for sh in s.shapes:
        if sh.name == 'Text 0' and sh.has_text_frame and sh.text_frame.text.strip():
            return sh.text_frame.text
    return ''


def by_title(pred):
    hits = [s for s in prs.slides if pred(ttl(s))]
    return hits[0] if hits else None


def new_from(src):
    new = prs.slides.add_slide(src.slide_layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    for sh in src.shapes:
        if sh.name != 'Version tag':
            new.shapes._spTree.append(copy.deepcopy(sh._element))
    return new


def notes(s, text_):
    ns = s.notes_slide
    if ns.notes_text_frame is None:
        ns.shapes._spTree.append(copy.deepcopy(find('我想做的事').notes_slide.notes_placeholder._element))
    if ns.notes_text_frame.text != text_:
        ns.notes_text_frame.text = text_
        return 1
    return 0


def table_slide(key, title_, hdr, rows, foot, note, colour=False):
    """a work-log-style table slide whose title starts with key; created once, content kept up to date"""
    s = by_title(lambda t: t.startswith(key))
    n = 0
    if s is None:
        s = new_from(lg)
        n = 1
    t = named(s, 'Table log').table
    if ttl(s) != title_ or rows_text(t) != rows or t.rows[0].cells[2].text != hdr[2]:
        set_text(title_shape(s), title_)
        fill(t, hdr, rows)
        n = 1
    if colour:
        for r in list(t.rows)[1:]:
            run = r.cells[0].text_frame.paragraphs[0].runs[0]
            run.font.bold = True
            run.font.color.rgb = STATUS_COLOR.get(run.text, RGBColor(0x33, 0x33, 0x33))
    n += put(named(s, 'Text 2'), foot)
    n += notes(s, note)
    return s, n


n_rs = 0
# dividers and title slide
div = by_title(lambda t: t in ('重現與前置結果', '主要結果'))
dsh = [sh for sh in div.shapes if sh.name == 'Text 0']
n_rs += put_any(dsh[0], '主要結果')
n_rs += put_any(dsh[1], '公開資料（開發集）上的方法驗證與板子實測；其餘結果在附錄')
app = by_title(lambda t: t == '附錄')
if app is None:
    app = new_from(div)
    n_rs += 1
ash = [sh for sh in app.shapes if sh.name == 'Text 0']
n_rs += put_any(ash[0], '附錄')
n_rs += put_any(ash[1], '前置實驗與工作紀錄（主簡報的數字都在 report.md 有來源）')
cover = prs.slides[0] if ttl(prs.slides[0]) == '研究方向' else by_title(lambda t: t == '研究方向')
csh = [sh for sh in cover.shapes if sh.name == 'Text 0']
n_rs += put_any(csh[1], '一次初始校正後、在 256 KB RAM 內免標籤適應的隨機森林肌電控制（STM32H7）；預計用 Kinova 閉迴路驗證')
old_rq = by_title(lambda t: t in ('研究問題', '舊版研究問題（RQ1–RQ3）'))
n_rs += put(title_shape(old_rq), '舊版研究問題（RQ1–RQ3）')

# new main slides
_, k = table_slide(
    '研究問題：', '研究問題：一個主問題，其他是解釋與可行性', ('層級', '問題', '怎麼回答／現在'),
    [('主問題', '第 2 天重新配戴後，完整系統是否比固定的第 1 天模型好？（閉迴路任務成功率）',
      f"先導＋正式實驗（兩天 AB／BA 交叉）；公開資料模擬 {f0:.2f}% → {a0:.2f}%（開發集）"),
     ('機制', '改善來自開機對齊、z-score 更新，還是換樹？',
      '公開資料拆解：固定 79.68 → 只 z-score 81.42 → 只自我校正 83.20 → 兩者 83.87%；真人用錄下的 EMG 離線回放'),
     ('工程', '能否在 256 KB RAM 與即時限制內運行？',
      f"已在板子上驗證：RAM {ram:.1f} KB、每視窗 {f_win:.2f} ms、33 分鐘串流不掉資料"),
     ('安全', '會不會把非控制動作當成指令？',
      '非控制動作段（8 項 × 60 秒）的誤觸發／分鐘：先導時收'),
     ('應用', '能不能用來控制 Kinova？', '第 2 天閉迴路任務；Kinova 不可用時改抓放遊戲（同一組離散指令）')],
    '主張：一次初始校正後，記憶體受限的 STM32H7 能否透過免標籤適應，改善重新配戴後的離散肌電控制，而不犧牲即時性與安全性？',
    '這頁把研究問題收斂成一個主問題：第二天重新戴上之後，完整系統是不是比只用第一天模型好，用閉迴路任務成功率回答。'
    '機制、工程、安全、應用都是用來解釋或支持這個主問題的。工程問題已經在板子上回答了；主問題和安全問題要等真人實驗。')
n_rs += k
_, k = table_slide(
    '韌體架構：', '韌體架構：中斷做即時分類，主迴圈做自我校正', ('執行時機', '做什麼', '板子實測'),
    [('UART 中斷', '最高優先：每個 byte 放進 4 KB 環形緩衝', f"33 分鐘最多用 {la.rx_ring_highwater_B:.0f} B（6%）、遺失 0"),
     ('1 kHz 中斷', '解封包 → 每 100 ms 算 80 維特徵 → 通道重排＋z-score → 100 棵樹投票 → 決策（τ、k）→ 回傳',
      f"每個視窗 {f_win:.2f} ms（預算的 {f_win / 100:.1%}）"),
     ('主迴圈', '每 300 個視窗：預測少於 5 類就跳過；否則更新 z-score → buffer 轉座標 → K-Means 偽標籤 → 換 20 棵樹',
      f"一次平均 {la.selfcal_ms_mean / 1000:.2f} s；更新期間延遲最大 {ld.latency_max:.1f} ms"),
     ('Flash', '程式＋50 棵預訓練樹；第 1 天的模型與校正資料（load 還原，學到的樹不寫回）',
      '板子重置後 load，和 PC 逐視窗 100% 相同'),
     ('RAM', 'buffer 375 筆＋RAM 樹 88 KB、校正工作區 40 KB、特徵 20 KB、建樹＋K-Means 12 KB、對齊 5 KB',
      f"{ram:.1f} KB（預算 256 KB）；stack 峰值 {la.stack_peak_B / 1024:.1f} KB")],
    'PC 只轉送 Trigno 樣本（TCP → UART）和 Kinova 指令；同一份 C 碼也編成 PC 版，用來和板子逐視窗比對。凍結版本 pilot-freeze-3',
    '韌體分三層執行時機。UART 中斷只收資料，不會掉 byte；一千赫茲的中斷做即時分類，每個視窗不到三毫秒；'
    '自我校正放在主迴圈，更新期間新進來的視窗照樣分類，只是不進 buffer。第一天的模型存在 Flash，斷電後可以還原；學到的樹只在 RAM。')
n_rs += k
_, k = table_slide(
    '板子上 33 分鐘', '板子上 33 分鐘連續串流：更新時不掉資料、不變慢', ('指標', '結果', '事先訂的門檻'),
    [('自我校正', f"{la.selfcal_n:.0f} 次；平均 {la.selfcal_ms_mean:.0f} ms、最長 {la.selfcal_ms_max:.0f} ms", '—'),
     ('遺失', f"封包 {la.lost_packets:.0f}、CRC 錯誤 {la.crc_errors:.0f}、UART 丟掉 {la.uart_overflow:.0f}；"
              f"{la.windows:.0f} 個視窗全部有輸出", '0'),
     ('更新期間', f"{ld.windows:.0f} 個視窗：全部有分類、有決策（不進 buffer）", '每個視窗都有輸出'),
     ('延遲', f"P50 {la.latency_p50:.1f}、P99 {la.latency_p99:.1f}、最大 {la.latency_max:.1f} ms；"
              f"更新期間最大 {ld.latency_max:.1f} ms", '< 100 ms'),
     ('緩衝', f"接收緩衝最多 {la.rx_ring_highwater_B:.0f} B（4 KB 的 {la.rx_ring_highwater_B / 4096:.0%}）", '< 50%'),
     ('stack', f"執行期峰值 {la.stack_peak_B:.0f} B（靜態上界 {stack_static:,.0f} B）", '—'),
     ('和 PC 一致', f"回放 2 個 block：{RS.board_acc[0]:.2f}%／{RS.board_acc[1]:.2f}%，逐視窗 100% 相同；關 FMA 逐位相同", '—')],
    '受試者 0 的錄音，11 個 block 重複 3 次、中間不 reset（像真實使用一樣連續），PC 照錄音時間即時送進板子。延遲＝傳輸＋運算，不是使用者反應時間',
    '這頁回答「背景更新會不會傷到即時控制」。三十三分鐘、六十五次更新，沒有掉任何資料，每個視窗都有輸出，'
    '更新期間最大延遲不到十毫秒，接收緩衝只用到百分之六。限制是只有一位受試者的錄音、重複三次。')
n_rs += k
s_ = SM
_, k = table_slide(
    '壓力測試：', '壓力測試：只出現少數手勢時會越學越差，所以加了停止規則', ('情況', '固定模型 → 韌體', '加「少於 5 類不更新」後'),
    [('正常', f"{s_.loc[('base', 'fixed'), 'focus']:.1f} → {s_.loc[('base', 'fw'), 'focus']:.1f}%",
      f"{s_.loc[('base', 'cls5'), 'focus']:.1f}%（不受影響）"),
     ('少數手勢', f"只有 Rest＋2 種：{s_.loc[('rest2', 'fixed'), 'focus']:.1f} → {s_.loc[('rest2', 'fw'), 'focus']:.1f}%"
                  f"（{s_.loc[('rest2', 'fw'), 'vs_fixed']:+.1f}，18／20 人變差）",
      f"{s_.loc[('rest2', 'cls5'), 'focus']:.1f}%（{s_.loc[('rest2', 'cls5'), 'vs_fixed']:+.1f}，不顯著）"),
     ('缺席再回來', f"Power 消失 6 個 block 後的召回率：{s_.loc[('absent', 'fixed'), 'focus']:.1f} → "
                    f"{s_.loc[('absent', 'fw'), 'focus']:.1f}%", f"{s_.loc[('absent', 'cls5'), 'focus']:.1f}%"),
     ('束帶滑掉', f"滑掉 4 個 block 再戴回：{s_.loc[('wrong', 'fixed'), 'focus']:.1f} → {s_.loc[('wrong', 'fw'), 'focus']:.1f}%"
                  f"，平均 {s_.loc[('wrong', 'fw'), 'recover_blocks_mean']:.1f} 個 block 恢復",
      f"{s_.loc[('wrong', 'cls5'), 'focus']:.1f}%"),
     ('校正一半', f"每個手勢只用一半視窗：{s_.loc[('half', 'fixed'), 'focus']:.1f} → {s_.loc[('half', 'fw'), 'focus']:.1f}%",
      f"{s_.loc[('half', 'cls5'), 'focus']:.1f}%"),
     ('出力弱', f"校正出力弱：{s_.loc[('low', 'fixed'), 'focus']:.1f} → {s_.loc[('low', 'fw'), 'focus']:.1f}%",
      f"{s_.loc[('low', 'cls5'), 'focus']:.1f}%（變差）→ 第 1 天 verify < 70% 重做：擋下 {100 - VC.loc['low', 'pass_70']:.0f}%")],
    '開發資料 20 人 × 3 seed，韌體 C 碼；用校正資料檢查的回退規則幾乎不觸發、沒有用（report 22）。規則和門檻都在這批資料上訂，先導只驗證',
    '最重要的發現是：一段時間只出現少數手勢時，自我校正會比不更新還差六點多，這正是真實使用會發生的情況。'
    '所以加了「預測少於五類就不更新」；它在第一天校正很差時會拉不回來，所以再加第一天的校正檢查。')
n_rs += k
_, k = table_slide(
    '還沒完成：', '還沒完成：接真機、定案實驗設計、送 IRB', ('狀態', '項目', '為什麼還沒／下一步'),
    [('未做', '接真的 Trigno（check、run 整條路）', 'TCU 協定照 pytrigno 寫、沒接過 → 先去實驗室跑 check.bat、run.bat'),
     ('未做', 'PROTOCOL 的待定值、任務定義', '成功判準、誤觸發界線、試次數、樣本數、問卷 → 和老師定案'),
     ('未做', 'IRB 送審', '定案後送；審查要幾個月，正式實驗排在之後'),
     ('未做', '先導 3–4 人（凍結版本，只驗證）', 'IRB 通過後；不合格就回開發資料改，新受試者重收'),
     ('未做', '正式 16 人：兩天交叉＋Kinova、非控制動作', '先導通過後'),
     ('部分', '開機對齊沒做完時，PC 提示重做、對齊前不送指令', '韌體會回 ALIGN_SHORT；PC 端還要補'),
     ('未做', '功耗', '要電流表（量法在 report 19.1）')],
    '已完成的事項在上一頁；細節：PROTOCOL.md、VALIDATION_PLAN.md',
    '還沒完成的事情，大多要等真的器材和 IRB。最急的是先去實驗室接真的 Trigno，確認資料能送進板子；'
    '同時和老師定案實驗設計裡的待定數值，然後送 IRB。', colour=True)
n_rs += k
QHDR = ('#', '審查問題', '回應與證據')
_, k = table_slide(
    '回答審查（1/2）', '回答審查（1/2）：評估有效性與方法', QHDR,
    [('1', '開機對齊是不是偷看了 block 0？', '是。改成前 6 秒只對齊、不計分：83.87 → 83.91%，偏半格 74.74 → 74.04%（report 20）'),
     ('2', 'z-score 更新後，buffer 和樹還在同一個座標嗎？', '不在。改成先更新、buffer 轉座標、再訓練：+0.78／偏半格 +1.36 點（20）'),
     ('3', '缺席類別或休息很多時，會不會越學越差？', '會（−6.4 點）。加「少於 5 類不更新」→ −1.3、不顯著（22）'),
     ('4', '開機隨便做幾個動作就能對齊嗎？', '不能：只做 Power 5／20 人估錯、只休息 13／20。規定 8 秒做 6 種手勢，少於 60 個視窗不轉（20）'),
     ('5', '更新期間會不會掉資料、變慢？', f"板子 33 分鐘 {la.selfcal_n:.0f} 次更新：遺失 0、更新期間最大延遲 {ld.latency_max:.1f} ms（21）"),
     ('6', '「免標籤」到底免了什麼？', '第 1 天一次有標籤校正（每個手勢 2 秒）＋校正檢查；之後免標籤；每次戴上 8 秒的開機流程'),
     ('7', '斷電後第 1 天的模型還在嗎？', '原本不在。現在存 Flash、load 還原；板子重置後和 PC 逐視窗 100% 相同（23）')],
    '括號是 report.md 的節號；全部是開發資料或板子實測，沒有真人資料',
    '這兩頁逐條回應兩輪審查。第一頁是評估與方法：審查指出的兩個漏洞，偷看 block 0 和座標不一致，都成立而且已經修正；'
    '少數手勢會越學越差也是真的，已經加了停止規則。')
n_rs += k
_, k = table_slide(
    '回答審查（2/2）', '回答審查（2/2）：統計、主張與實驗設計', QHDR,
    [('8', '同一批 20 人反覆調參？', f"是：{a0:.2f}% 是開發集結果。凍結 pilot-freeze-3，先導只驗證、不再調"),
     ('9', 'p ≥ 0.05 當作「一樣」？', '不再這樣用。移植正確看逐位比對；等效要事先訂界線做非劣性／TOST'),
     ('10', '系統邊界？', 'MCU 做所有 EMG 運算與更新；PC 只橋接 Trigno 與 Kinova。定位：wearable-ready 演算法原型'),
     ('11', '新穎性？', '不說「沒人做」：單核 Cortex-M7、256 KB 預算、分群偽標籤＋換樹、不靠任務目標（[8] 只對齊、[12] 靠任務目標）'),
     ('12', '人學會了還是模型學會了？', 'AB／BA 交叉；每個條件前 load 回到同一個第 1 天模型；練習段不分析（PROTOCOL）'),
     ('13', '主終點太多？', '只有一個：第 2 天閉迴路任務成功率；安全主終點：非控制動作誤觸發／分；其他是次要'),
     ('14', '樣本數？', f"開發資料效果 dz {dz.min():.2f}–{dz.max():.2f}（上限）；16 人可偵測 dz ≥ {mdz.loc[16]:.2f}；先導 3–4 人")],
    '健常受試者的技術驗證，不推論到截肢者；細節：PROTOCOL.md',
    '第二頁是統計、主張和實驗設計。主要的改變是：承認目前的數字是開發集結果、把版本凍結；'
    '主張收斂到單核 M7、記憶體預算和不靠任務目標；實驗用兩天交叉設計，每個條件都從同一個第一天模型開始。')
n_rs += k
_, k = table_slide(
    '正式實驗：', '正式實驗：兩天交叉、一個主終點（PROTOCOL.md 草案）', ('項目', '設計', '待老師確認'),
    [('對象', '健常受試者；先導 3–4 人，正式 16 人', '樣本數'),
     ('條件', 'F＝固定的第 1 天模型（adapt 0）；A＝完整系統（adapt 1＋開機對齊）；每個條件前 load', '—'),
     ('順序', '每天兩個條件，AB 或 BA，第 2 天相反；目標順序隨機；受試者單盲；練習不分析', '—'),
     ('主終點', '第 2 天閉迴路任務成功率（A − F，配對）', '成功判準、試次數、任務定義'),
     ('安全終點', '非控制動作段（8 項 × 60 秒）的誤觸發／分鐘', '非劣性界線（0.5／分？）、停止上限（3／分？）'),
     ('次要', '完成時間、延遲、離線準確率、開機對齊成功率與重試、同日重戴、主觀負擔', '問卷'),
     ('紀錄', '每次戴上：記號偏差、周長、孔位、照片、姿勢；EMG 與板子的所有輸出', '—')],
    '分析：配對差與 95% CI（主）、Wilcoxon（敏感度）、順序效果；機制用錄下的 EMG 離線回放。排除條件事先訂好（PROTOCOL.md 第 8 節）',
    '正式實驗是兩天的交叉設計，每天兩個條件都做、順序平衡，每個條件開始前都還原成同一個第一天模型。'
    '只有一個主終點，第二天閉迴路任務成功率，加上一個安全終點。右邊一欄是要請老師確認的數值。')
n_rs += k

# order: main deck, then the appendix
ORDER = [lambda t: t == '研究方向', lambda t: t == '我想做的事', lambda t: t.startswith('研究問題：'),
         lambda t: t.startswith('和最接近的研究'), lambda t: t.startswith('STM32 做'), lambda t: t.startswith('韌體架構：'),
         lambda t: t == '主要結果', lambda t: t.startswith('束帶情境'), lambda t: t.startswith('韌體 v2：'),
         lambda t: t.startswith('板子上 33 分鐘'), lambda t: t.startswith('壓力測試：'), lambda t: t.startswith('目前完成的目標'),
         lambda t: t.startswith('還沒完成：'), lambda t: t.startswith('回答審查（1/2）'), lambda t: t.startswith('回答審查（2/2）'),
         lambda t: t.startswith('失敗條件'), lambda t: t.startswith('正式實驗：'), lambda t: t.startswith('參考文獻（1/2）'),
         lambda t: t.startswith('參考文獻（2/2）'),
         lambda t: t == '附錄', lambda t: t.startswith('Flash 存預訓練'), lambda t: t.startswith('PC 基準'),
         lambda t: t.startswith('壓縮到'), lambda t: t.startswith('偽標籤不需要'), lambda t: t.startswith('z-score 跟著'),
         lambda t: '跨兩天 demo' in t, lambda t: t.startswith('6 個通道'), lambda t: t.startswith('電極轉一格'),
         lambda t: t.startswith('舊版研究問題'), lambda t: t.startswith('核心是嵌入式'), lambda t: t.startswith('工作紀錄（1/2）'),
         lambda t: t.startswith('工作紀錄（2/2）')]
slides = list(prs.slides)
ids = prs.slides._sldIdLst
els = list(ids)
order, used = [], set()
for pred in ORDER:
    hit = [i for i, s in enumerate(slides) if i not in used and pred(ttl(s))]
    assert len(hit) == 1, ('order', len(hit))
    used.add(hit[0])
    order.append(hit[0])
assert len(order) == len(slides), ('unplaced slides', [ttl(slides[i]) for i in range(len(slides)) if i not in used])
if order != list(range(len(slides))):
    for el in els:
        ids.remove(el)
    for i in order:
        ids.append(els[i])
    n_rs += 1
first_app = [ttl(s) for s in prs.slides].index('附錄')
for s in list(prs.slides)[first_app + 1:]:
    tags = [sh for sh in s.shapes if sh.name == 'Version tag']
    base = tags[0].text_frame.text.split('附錄｜')[-1] if tags else ''
    want = '附錄｜' + base if base and base != '附錄' else '附錄'
    if not tags or tags[0].text_frame.text != want:
        version_tag(s, want)
        n_rs += 1
if n_rs:
    done.append(f'restructure ({n_rs})')

# ------------------------------------------------------------------ save
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
tmp = deck + '.tmp.pptx'
prs.save(tmp)
shutil.move(tmp, deck)
print('updated' if done else 'nothing to do', deck, done)
