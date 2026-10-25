"""v13 = the user's v12 (2026-10-20 00:07, md5 577fc746..., 16 slides; the user only edited slide 2's third column)
+ the experiments after it. Numbers are read from results/, not typed.

- 我想做的事: RAM 245.0 KB -> current board build (one-shot + self-calibration + features + UART), demo tail -> current;
  one new bullet each in the first two columns (electrode rotation; Orlandi [12]); the board line of the ask.
  The third column ("要做", edited by the user) is kept as it is.
- closest work / architecture: RAM numbers.
- RAM slide: title, stacked chart of the three board builds (results/ram_history.csv), C accuracy (c_impl_summary).
- two-day demo: curves and numbers after the 16-bit P change (selfcal_c_check_demo, c_impl_demo).
- NEW after the demo: channel count (channel_greedy_summary, channel_sweep_summary_posthoc) and electrode rotation
  (shift_sweep*), in the v10 style (chart left, three plain numbers right, footnote).
- references: + [11] Campbell 2024 (UHC baseline), [12] Orlandi 2026 (poster) on the second page.
usage: python build13.py user_v12.pptx out.pptx
"""
import copy
import os
import re
import sys

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.util import Inches, Pt

src, dst = sys.argv[1:3]
R = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
prs = Presentation(src)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
HEX = dict(dk1='1F2A30', dk2='0B3C49', lt2='E1EEF1', a1='1F7A8C', a2='F2A541', a5='5B6770', a6='C9D6DA')


def csv(name):
    return pd.read_csv(os.path.join(R, name))


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


def set_para(p, text_, expect=None):
    full = ''.join(r.text for r in p.runs)
    if expect:
        assert full.startswith(expect), (full[:40], expect)
    p.runs[0].text = text_
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)


def sub(sh, old, new):
    """replace text inside one run of a shape (or table); exactly one hit"""
    fs = [c.text_frame for r_ in sh.table.rows for c in r_.cells] if sh.has_table else [sh.text_frame]
    n = 0
    for tf in fs:
        for p_ in tf.paragraphs:
            for r_ in p_.runs:
                if old in r_.text:
                    r_.text = r_.text.replace(old, new)
                    n += 1
    assert n == 1, (sh.name, old, n)


def add_para_like(tf, text_):
    """new last paragraph with the formatting of the current last one"""
    el = copy.deepcopy(tf.paragraphs[-1]._p)
    tf.paragraphs[-1]._p.addnext(el)
    set_para(tf.paragraphs[-1], text_)


def notes(s, text_):
    s.notes_slide.notes_text_frame.text = text_


def kb(b):
    return f'{b / 1024:.1f} KB'


def neg(v, fmt='+.2f'):
    return format(v, fmt).replace('-', '−')


def pfmt(p):
    return 'p < 0.001' if p < 0.001 else f'p = {p:.3f}' if p < 0.01 else f'p = {p:.2f}'


S = dict(what=find('我想做的事'), novelty=find('和最接近的研究'), arch=find('STM32 做決策'), ram=find('Cortex-M7 編譯後 RAM'),
         demo=find('跨兩天 demo'), scope=find('核心是嵌入式自我校正'), ref2=find('參考文獻（2/2）'))

# ------------------------------------------------------------------ numbers
H = csv('ram_history.csv')
ram_now = H.iloc[-1]
RAM = f"{ram_now.ram_KB:.1f} KB"                                              # 223.8 KB
MARGIN = f"{256 - ram_now.ram_KB:.1f} KB"
sz = csv('arm_selfcal_size.csv').set_index(['variant', 'opt'])
board = sz.loc[('board', '-Os')]
assert int(board.data) + int(board.bss) + int(board.worst_stack_bytes) == int(ram_now.ram_B), 'ram_history is stale'
C = csv('c_impl_summary.csv').set_index('variant')
c_fw = C.loc['C firmware logic (selfcal.c, end to end), 500 it']
c_sk = C.loc['sklearn (reference), 500 it']
D = csv('c_impl_demo.csv').set_index('variant')
d_fw, d_full = D.loc['MCU setting, C firmware logic'], D.loc['full model (paper), sklearn']
G = csv('channel_greedy_summary.csv').set_index('n_channels')
PH = csv('channel_sweep_summary_posthoc.csv').set_index('set')
SH = csv('shift_sweep_summary.csv').set_index('shift')
SB = csv('shift_sweep.csv')
s0, s1, sm1 = SH.loc[0], SH.loc[1], SH.loc[-1]

# ------------------------------------------------------------------ 我想做的事
w = S['what']
col0 = named(w, 'Col 0 list').text_frame
p3 = [p for p in col0.paragraphs if p.text.startswith('• 自我校正全用 C')][0]
set_para(p3, f'• one-shot 和自我校正全用 C 寫好，M7 編譯 RAM {RAM}')
p4 = [p for p in col0.paragraphs if p.text.startswith('• 跨兩天 demo')][0]
set_para(p4, f"• 跨兩天 demo：第 2 天 {d_fw.selfcal_blocks7_9:.1f}%，固定模型 {d_fw.oneshot_blocks7_9:.1f}%")
add_para_like(col0, f"• 電極轉一格：自我校正 +{s1.tsne_minus_fixed:.1f}，信心式自我訓練 {neg(s1.uhc_minus_fixed, '+.1f')}")
add_para_like(named(w, 'Col 1 list').text_frame, '• Orlandi [12]：GAP9 上裝置端重訓，但偽標籤要靠已知任務目標')
sub(named(w, 'Ask'), '、採購 NUCLEO-H743ZI2', '；開發板 NUCLEO-H753ZI 已訂購')
nt = w.notes_slide.notes_text_frame.text
assert '並在 Cortex' in nt, nt
notes(w, nt.replace('整條自我校正改寫成 C 並在 Cortex-M7 上編譯', f'one-shot 和整條自我校正改寫成 C、在 Cortex-M7 上編譯是 {RAM}')
      .replace('跨兩天的 demo 也有效。', '跨兩天的 demo 也有效；電極轉一格時自我校正只拉回一部分，'
               '但比 Campbell 的信心式自我訓練好。另外 Orlandi 2026 在 GAP9 上做了裝置端重訓，不過要知道任務目標，我的方法不需要。'))

# ------------------------------------------------------------------ closest work, architecture
sub(named(S['novelty'], 'Text 1'), 'RAM 估算 219 KB', f'M7 編譯 RAM {RAM}')
sub(named(S['novelty'], 'Text 2'), '；免標籤適應但沒有上 MCU', '；Orlandi 2026 [12]（GAP9、裝置端重訓，偽標籤要靠任務目標）；免標籤適應但沒有上 MCU')
sub(named(S['arch'], 'Box 1 body'), 'M7 編譯 RAM 245 KB（含特徵）', f"M7 編譯 RAM {ram_now.ram_KB:.0f} KB（含 one-shot）")

# ------------------------------------------------------------------ RAM slide
r = S['ram']
set_para(title_shape(r).text_frame.paragraphs[0], f"Cortex-M7 編譯後 RAM {ram_now.ram_KB:.0f} KB，餘裕 {256 - ram_now.ram_KB:.0f} KB")
ch = named(r, 'Chart RAM').chart
cd = CategoryChartData()
cd.categories = ['P 存 16 位元（現在）', 'octree 只配 2.5n', '加上硬體層']           # bar charts draw the first category at the bottom
rows = H.iloc[::-1]
assert list(rows.commit) == ['5519744', 'f15cf9e', 'e6b1bcd'], list(rows.commit)
cd.add_series('buffer＋calibration＋RAM 樹', list(rows.selfcal_KB))
cd.add_series('t-SNE 工作區', list(rows.tsne_KB))
cd.add_series('特徵擷取', list(rows.features_KB))
cd.add_series('建樹、K-Means、UART、stack 等', list(rows.other_KB))
ch.replace_data(cd)
set_para(ch.chart_title.text_frame.paragraphs[0], 'RAM 組成（KB，含 one-shot＋UART 的完整韌體，linker 實測）', 'RAM 組成')
set_para(named(r, 'Stat ram value').text_frame.paragraphs[0], RAM)
set_para(named(r, 'Stat ram label').text_frame.paragraphs[0],
         f"完整韌體的 RAM（原本 {H.iloc[0].ram_KB:.1f} KB）；t-SNE 改兩處省 {H.iloc[0].tsne_KB - ram_now.tsne_KB:.1f} KB")
set_para(named(r, 'Stat est value').text_frame.paragraphs[0], f"{c_fw.acc_selfcal:.2f}%")
set_para(named(r, 'Stat est label').text_frame.paragraphs[0],
         f"整條自我校正改用 C 的端到端準確率；sklearn {c_sk.acc_selfcal:.2f}%，p = {c_fw.wilcoxon_p:.2f}")
set_para(named(r, 'Footnote').text_frame.paragraphs[0],
         f"arm-none-eabi-gcc 10.3.1，-Os，Cortex-M7；RAM = .data＋.bss＋最深 stack；硬體層只編譯、還沒對照 RM0433。"
         f"octree 只配 2.5n 個節點（逐列準確率相同）、P 存 16 位元定點（無顯著差異）。Flash {board.flash_KB:.0f} KB（含 88 KB 模型）。")
notes(r, '這頁是實際交叉編譯成 Cortex-M7 韌體之後 linker 量出來的 RAM，現在包含 one-shot、自我校正、特徵擷取和 UART 硬體層。'
      f"加上硬體層時是 {H.iloc[0].ram_KB:.1f} KB，離 256 KB 太近；我把 t-SNE 改了兩處：octree 只配 2.5n 個節點，"
      f"條件機率改存 16 位元，降到 {RAM}，還有 {MARGIN} 餘裕。兩個改動在 PC 上驗證過，準確率沒有顯著差異。"
      f"整條自我校正用 C 跑是 {c_fw.acc_selfcal:.2f}%，sklearn 是 {c_sk.acc_selfcal:.2f}%。時間要等板子到了用 DWT 計數器量。")

# ------------------------------------------------------------------ demo slide
dm = S['demo']
ref_ = csv('selfcal_sweep_demo_ref.csv')
full = ref_[ref_.config == 'N400_dnone_float64']
mcu = csv('selfcal_c_check_demo.csv')
cd = CategoryChartData()
cd.categories = [str(b) for b in sorted(mcu.block.unique())]
cd.add_series('固定模型（one-shot，MCU 設定）', list(mcu.groupby('block').acc_oneshot.mean() * 100))
cd.add_series('自我校正：完整模型（論文設定，sklearn）', list(full.groupby('block').acc_selfcal.mean() * 100))
cd.add_series('自我校正：MCU 設定，C 韌體邏輯', list(mcu.groupby('block').acc_selfcal.mean() * 100))
named(dm, 'Chart demo').chart.replace_data(cd)
assert abs(mcu[mcu.block >= 7].acc_selfcal.mean() * 100 - d_fw.selfcal_blocks7_9) < 0.01
set_para(named(dm, 'Stat tail value').text_frame.paragraphs[0], f"{d_fw.selfcal_blocks7_9:.1f}%")
set_para(named(dm, 'Stat tail label').text_frame.paragraphs[0],
         f"第 2 天後段（block 7–9）C 韌體自我校正；固定模型 {d_fw.oneshot_blocks7_9:.1f}%")
set_para(named(dm, 'Stat gain value').text_frame.paragraphs[0], f"+{d_fw.gain:.2f}")
set_para(named(dm, 'Stat gain label').text_frame.paragraphs[0],
         f"C 韌體邏輯的平均增益（{d_fw.acc_oneshot:.1f} → {d_fw.acc_selfcal:.1f}%）；完整模型 +{d_full.gain:.2f}")
nt = dm.notes_slide.notes_text_frame.text
nt = re.sub(r'可以拉回 \d+% 左右，整體增益 \+[\d.]+', f"可以拉回 {d_fw.selfcal_blocks7_9:.0f}% 左右，整體增益 +{d_fw.gain:.1f}", nt)
assert f"+{d_fw.gain:.1f}" in nt, nt
notes(dm, nt)


# ------------------------------------------------------------------ new slides (copy the demo slide's look)
def new_like(like, title_, before):
    s = prs.slides.add_slide(like.slide_layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    for sh in like.shapes:
        if not sh.has_chart:
            s.shapes._spTree.append(copy.deepcopy(sh._element))
    set_para(title_shape(s).text_frame.paragraphs[0], title_)
    ns = s.notes_slide
    if ns.notes_placeholder is None:
        ns.shapes._spTree.append(copy.deepcopy(like.notes_slide.notes_placeholder._element))
    ids = prs.slides._sldIdLst                                           # move right after `before`
    el = ids[-1]
    ids.remove(el)
    ids.insert(list(prs.slides).index(before) + 1, el)
    return s


def line_chart(s, cats, series, title_, ymin, ymax, xtitle):
    """series = [(name, values, colour, width)]; same look as the demo chart"""
    old = named(S['demo'], 'Chart demo')
    cd_ = CategoryChartData()
    cd_.categories = cats
    for name, vals, _, _ in series:
        cd_.add_series(name, vals)
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, old.left, old.top, old.width, old.height, cd_)
    gf.name = 'Chart'
    c = gf.chart
    c.font.size = Pt(12)
    c.font.color.rgb = RGBColor.from_string(HEX['dk1'])
    c.has_title = True
    c.chart_title.text_frame.text = title_
    c.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
    c.chart_title.text_frame.paragraphs[0].runs[0].font.bold = True
    c.has_legend = True
    c.legend.position = XL_LEGEND_POSITION.BOTTOM
    c.legend.include_in_layout = False
    c.legend.font.size = Pt(11)
    va = c.value_axis
    va.minimum_scale, va.maximum_scale, va.major_unit = ymin, ymax, 10
    va.tick_labels.number_format, va.tick_labels.number_format_is_linked = '0', False
    va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
    va.format.line.fill.background()
    c.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
    c.category_axis.has_title = True
    c.category_axis.axis_title.text_frame.text = xtitle
    c.category_axis.axis_title.text_frame.paragraphs[0].runs[0].font.size = Pt(11)
    c.category_axis.axis_title.text_frame.paragraphs[0].runs[0].font.bold = False
    for s_, (_, _, col, wd) in zip(c.plots[0].series, series):
        s_.smooth = False
        s_.format.line.color.rgb = RGBColor.from_string(HEX[col])
        s_.format.line.width = Pt(wd)
        s_.marker.style = XL_MARKER_STYLE.CIRCLE
        s_.marker.size = 7
        s_.marker.format.fill.solid()
        s_.marker.format.fill.fore_color.rgb = RGBColor.from_string(HEX[col])
        s_.marker.format.line.color.rgb = RGBColor.from_string(HEX[col])
    sp = s.shapes._spTree                                                # chart below the footer cover rectangle
    sp.remove(gf._element)
    sp.insert(3, gf._element)
    return gf


def stats(s, items):
    for key, (value, label) in zip(['tail', 'gain', 'n'], items):
        set_para(named(s, f'Stat {key} value').text_frame.paragraphs[0], value)
        set_para(named(s, f'Stat {key} label').text_frame.paragraphs[0], label)


# channel count
g6, g7, g5, g4 = G.loc[6], G.loc[7], G.loc[5], G.loc[4]
assert g6.channels == '1 2 3 5 6 7' and G.loc[8].set == 'all8'
order = []
for n in range(7, 1, -1):
    order.append(sorted(set(G.loc[n + 1].channels.split()) - set(G.loc[n].channels.split()))[0])
chs = new_like(S['demo'], '6 個通道就夠？拿掉第 4、8 通道無顯著差異', S['demo'])
ns_ = list(range(8, 1, -1))
line_chart(chs, [str(n) for n in ns_],
           [('自我校正', [G.loc[n].acc_selfcal for n in ns_], 'a2', 2.75),
            ('固定模型（one-shot）', [G.loc[n].acc_oneshot for n in ns_], 'a5', 2.0)],
           '每次拿掉一個通道的準確率（%，20 人平均）', 60, 90, '通道數（依序拿掉 ' + '→'.join(order) + '）')
stats(chs, [
    (f"{g6.acc_selfcal:.2f}%", f"6 通道（拿掉 4、8）自我校正；8 通道 {G.loc[8].acc_selfcal:.2f}%，p = {g6.acc_selfcal_p_vs_all8:.2f}"),
    (f"−{g6.ram_saved_vs_8ch_KB:.1f} KB", '6 通道省下的 RAM（buffer、calibration 等隨特徵數變的部分，估算）'),
    ('要再確認', '通道是在同一份資料上挑的，有選擇偏差 → 用獨立資料（PhysioNet 或先導資料）確認'),
])
set_para(named(chs, 'Footnote').text_frame.paragraphs[0],
         'arm_position 資料，2 折交叉驗證：每組通道用 10 人重新預訓練、測另外 10 人（20 人 × 11 block × 3 seed），推薦 MCU 設定；'
         '預訓練只有 10 人，所以 8 通道比 66 人模型低。每步拿掉讓自我校正最高的通道。'
         f"5 通道 one-shot 已顯著變差（{neg(g5.acc_oneshot_diff_vs_all8)}，{pfmt(g5.acc_oneshot_p_vs_all8)}）；"
         f"只拿掉 4、5：one-shot {neg(PH.loc['drop4-5'].acc_oneshot_diff_vs_all8)}（{pfmt(PH.loc['drop4-5'].acc_oneshot_p_vs_all8)}）。")
notes(chs, '這頁回答感測器要幾個。作者的 66 人模型用到全部 80 個特徵，不能直接拿掉通道，所以我每一組通道都用 10 個人重新預訓練、'
      '測另外 10 個人，兩組互換。每一步拿掉讓自我校正最好的那個通道：先拿 4，再拿 8，到 6 通道時是 '
      f"{g6.acc_selfcal:.2f}%，和 8 通道 {G.loc[8].acc_selfcal:.2f}% 沒有顯著差異；5 通道開始 one-shot 就顯著變差。"
      '但是通道是在同一份資料上挑的，會有選擇偏差，所以我只把它當假設，之後要用獨立的資料確認；正式實驗還是先用 8 通道。')

# electrode rotation
shs = new_like(S['demo'], '電極轉一格：自我校正只拉回一部分，信心式自我訓練無效', chs)
blk = sorted(SB.block.unique())


def curve(shift, method, col):
    d = SB[(SB['shift'] == shift) & (SB.method == method)]
    return list(d.groupby('block')[col].mean() * 100)


line_chart(shs, [str(b) for b in blk],
           [('沒轉：t-SNE 自我校正（參考）', curve(0, 'tsne', 'acc_adapt'), 'a6', 2.0),
            ('轉一格：固定模型', curve(1, 'tsne', 'acc_fixed'), 'a5', 2.0),
            ('轉一格：信心式自我訓練（UHC [11]）', curve(1, 'uhc', 'acc_adapt'), 'dk2', 2.0),
            ('轉一格：t-SNE 自我校正（本研究）', curve(1, 'tsne', 'acc_adapt'), 'a2', 2.75)],
           '每個 block 的準確率（%，20 人 × 3 seed 平均）', 40, 90, 'block（所有測試 block 都轉一格）')
stats(shs, [
    (f"{s1.fixed:.1f}%", f"電極轉一格後的固定模型；沒轉 {s0.fixed:.1f}%（反方向轉 {sm1.fixed:.1f}%）"),
    (f"+{s1.tsne_minus_fixed:.2f}", f"t-SNE 自我校正的增益（{pfmt(s1.tsne_p_vs_fixed)}，{int(s1.tsne_better_than_fixed)}／20 人）；"
                                    f"反方向 +{sm1.tsne_minus_fixed:.2f}（{pfmt(sm1.tsne_p_vs_fixed)}）"),
    (neg(s1.uhc_minus_fixed), f"信心式自我訓練（UHC）的增益，不顯著（p = {s1.uhc_p_vs_fixed:.2f}），和 Campbell [11] 一致"),
])
set_para(named(shs, 'Footnote').text_frame.paragraphs[0],
         '第 1 天照原位置做 one-shot；測試時 8 個電極整圈轉一格（45°），假設通道 1–8 依序繞前臂一圈（作者沒寫明）。66 人模型＋推薦 MCU 設定。'
         'UHC：用目前模型自己的預測當偽標籤，只取最高票比例 ≥ 0.6 的視窗。配對 Wilcoxon，seed 平均後 20 人。')
notes(shs, '這頁是模擬穿戴時電極環轉了一格，也就是 45 度。固定模型從 '
      f"{s0.fixed:.0f}% 掉到 {s1.fixed:.0f}% 左右。我的 t-SNE 自我校正顯著拉回 {s1.tsne_minus_fixed:.1f} 個百分點，"
      f"但最後幾個 block 也只有 {s1.tsne_late_blocks:.0f}%，離沒轉時差很遠。Campbell 2024 的信心式自我訓練完全沒有效果，"
      '因為轉動後模型自己的預測大多是錯的，拿來重新訓練只會強化錯誤。結論是自我校正處理得了小幅的日間變化，'
      '處理不了這麼大的偏移，所以正式實驗會在皮膚上標記電極位置。')

# ------------------------------------------------------------------ references [11][12]
body = [sh for sh in S['ref2'].shapes if sh.has_text_frame and sh.text_frame.text.startswith('[')][0].text_frame
assert body.paragraphs[-1].text.startswith('[10]'), body.paragraphs[-1].text[:8]
add_para_like(body, '[11]  E. Campbell, E. Eddy, S. Bateman, U. Côté-Allard, E. Scheme, “Context-informed incremental learning improves '
                    'both the performance and resilience of myoelectric control,” J. NeuroEng. Rehabil., vol. 21, 70, 2024.')
add_para_like(body, '[12]  M. Orlandi et al., “On-device context-informed incremental learning for myoelectric control on '
                    'RISC-V-based wearable platform,” poster, RISC-V Summit Europe, Bologna, 2026.＊')

# ------------------------------------------------------------------ page numbers, leftovers
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
alltext = '\n'.join(sh.text_frame.text for sl in prs.slides for sh in sl.shapes if sh.has_text_frame)
for stale in ('245.0 KB', '245 KB', '92.2%', '83.04%', 'H743'):
    assert stale not in alltext, stale
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
