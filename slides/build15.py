"""v15 = v14 (build14.py output, not edited by the user: written 2026-10-25 21:41) with firmware v2. Numbers are read
from results/, not typed.

- slide 10 (was: keep t-SNE, RAM estimate): pseudo-labels without t-SNE (results/embed_sweep_summary*.csv).
- slide 11 (was: t-SNE iterations): class-balanced online z-score update (results/zscore_sweep_summary_bal.csv).
- slide 12 (was: M7 RAM 224 KB): firmware v2 RAM history (results/ram_history.csv, arm_selfcal_size.csv) and the
  C vs Python check (results/adapt_c_check*.csv).
- 我想做的事, 和最接近的研究, 研究問題, 架構, 方法, demo, 束帶情境: the 223.8 KB / t-SNE / 87% texts.
usage: python build15.py v14.pptx out.pptx
"""
import os
import sys

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls
from pptx.util import Inches, Pt

src, dst = sys.argv[1:3]
R = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
prs = Presentation(src)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
HEX = dict(dk1='1F2A30', dk2='0B3C49', lt2='E1EEF1', a1='1F7A8C', a2='F2A541', a5='5B6770', a6='C9D6DA', mid='6FA3AE')


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


def para(s, name, start):
    """the paragraph of shape `name` that starts with `start`"""
    hits = [p for p in named(s, name).text_frame.paragraphs if ''.join(r.text for r in p.runs).startswith(start)]
    assert len(hits) == 1, (name, start, len(hits))
    return hits[0]


def notes(s, text_):
    s.notes_slide.notes_text_frame.text = text_


def notes_replace(s, old, new):
    nt = s.notes_slide.notes_text_frame.text
    assert old in nt, (old, nt[:80])
    notes(s, nt.replace(old, new))


def run_replace(s, name, old, new):
    """replace text inside one run of shape `name` (keeps the run formatting)"""
    hits = [r for p in named(s, name).text_frame.paragraphs for r in p.runs if old in r.text]
    assert len(hits) == 1, (name, old, len(hits))
    hits[0].text = hits[0].text.replace(old, new)


def neg(v, fmt='+.2f'):
    return format(v, fmt).replace('-', '−')


def pfmt(p):
    return 'p < 0.001' if p < 0.001 else f'p = {p:.3f}' if p < 0.01 else f'p = {p:.2f}'


def stats(s, keys, items):
    for key, (value, label) in zip(keys, items):
        set_para(named(s, f'Stat {key} value').text_frame.paragraphs[0], value)
        set_para(named(s, f'Stat {key} label').text_frame.paragraphs[0], label)


def bar_chart(s, old, cats, series, title_, kind, ymin=None, ymax=None, major=None, fmt='0.0', hide_below=None):
    """replace chart shape `old` by a bar chart; series = [(name, values, colour)]"""
    cd_ = CategoryChartData()
    cd_.categories = cats
    for name, vals, _ in series:
        cd_.add_series(name, vals)
    gf = s.shapes.add_chart(kind, old.left, old.top, old.width, old.height, cd_)
    gf.name = old.name
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
    if ymin is not None:
        va.minimum_scale, va.maximum_scale, va.major_unit = ymin, ymax, major
    va.tick_labels.number_format, va.tick_labels.number_format_is_linked = '0', False
    va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
    va.format.line.fill.background()
    c.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
    c.category_axis.tick_labels.font.size = Pt(11)
    plot = c.plots[0]
    plot.gap_width = 60 if kind == XL_CHART_TYPE.BAR_STACKED else 80
    if kind == XL_CHART_TYPE.BAR_STACKED:
        plot.overlap = 100
    stacked = kind == XL_CHART_TYPE.BAR_STACKED
    for s_, (_, vals, col) in zip(plot.series, series):
        s_.format.fill.solid()
        s_.format.fill.fore_color.rgb = RGBColor.from_string(HEX[col])
        s_.format.line.color.rgb = RGBColor.from_string('FFFFFF')
        # per-series value labels, written out (python-pptx's series dLbls default to showVal = 0)
        hide = ''.join(f'<c:dLbl><c:idx val="{i}"/><c:delete val="1"/></c:dLbl>' for i, v in enumerate(vals)
                       if hide_below is not None and v < hide_below)
        lbl_col = 'FFFFFF' if stacked else HEX['dk1']
        new = parse_xml(
            f'<c:dLbls {nsdecls("c", "a")}>{hide}<c:numFmt formatCode="{fmt}" sourceLinked="0"/>'
            '<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
            f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="1000"><a:solidFill><a:srgbClr val="{lbl_col}"/>'
            '</a:solidFill></a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>'
            f'<c:dLblPos val="{"ctr" if stacked else "outEnd"}"/><c:showLegendKey val="0"/><c:showVal val="1"/>'
            '<c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>')
        old_dl = s_._element.get_or_add_dLbls()
        old_dl.getparent().replace(old_dl, new)
    sp = s.shapes._spTree                                                # same z-order as the old chart
    idx = list(sp).index(old._element)
    sp.remove(gf._element)
    sp.insert(idx, gf._element)
    sp.remove(old._element)
    return gf


# ------------------------------------------------------------------ numbers
E = csv('embed_sweep_summary.csv').set_index(['dataset', 'shift', 'embed'])
EB = csv('embed_sweep_summary_buf.csv').set_index(['dataset', 'shift', 'embed'])
ZB = csv('zscore_sweep_summary_bal.csv').set_index(['dataset', 'shift', 'zs'])
AC = csv('adapt_c_check.csv')
ACS = csv('adapt_c_check_summary.csv').set_index(['shift', 'update'])
RH = csv('ram_history.csv')
SZ = csv('arm_selfcal_size.csv').set_index(['variant', 'opt'])
e0, eh = E.loc[('arm_position', 0, 'none')], E.loc[('arm_position', 0.5, 'none')]
t0 = E.loc[('arm_position', 0, 'tsne')]
b1000 = EB.loc[('arm_position', 0, 'none_b1000')]
z = {sh: ZB.loc[('arm_position', sh)] for sh in (0, 0.25, 0.5)}
c_ps = AC[AC.impl == 'c'].groupby(['shift', 'update', 'subject']).acc_adapt.mean().groupby(level=[0, 1]).mean() * 100
p_ps = AC[AC.impl == 'python'].groupby(['shift', 'update', 'subject']).acc_adapt.mean().groupby(level=[0, 1]).mean() * 100
fx = ACS.loc[(0, 0)].c_fixed                                             # one-shot model, no offset (= Python)
assert abs(fx - e0.fixed) < 0.01, (fx, e0.fixed)
v2, v2h, v2py = c_ps.loc[(0, 1)], c_ps.loc[(0.5, 1)], p_ps.loc[(0, 1)]
v2p = ACS.loc[(0, 1)].p
cpu = AC[AC.impl == 'c'].update_cpu_s.mean()
ram_old, ram_v2 = RH.iloc[-2], RH.iloc[-1]
assert ram_v2.variant == 'board2' and ram_old.variant == 'board'
flash_v2 = SZ.loc[('board2', '-Os')].flash_KB
margin = 256 - ram_v2.ram_KB

# ------------------------------------------------------------------ 10: pseudo-labels without t-SNE
s10 = find('保留 t-SNE')
set_para(title_shape(s10).text_frame.paragraphs[0], '偽標籤不需要 t-SNE：小 buffer 時 K-Means 直接分就夠')
emb = [('tsne', 't-SNE（原本）'), ('none', '不嵌入'), ('ldacal5', 'LDA 5 維（第 1 天）'), ('ldabuf5', 'LDA（buffer 交替）'),
       ('pca5', 'PCA 5 維')]
bar_chart(s10, named(s10, 'Chart RAM vs accuracy'), [n for _, n in emb],
          [('電極沒偏移', [E.loc[('arm_position', 0, k)].adapt for k, _ in emb], 'dk2'),
           ('偏 ½ 格（最難）', [E.loc[('arm_position', 0.5, k)].adapt for k, _ in emb], 'a2')],
          '偽標籤前的嵌入和自我校正後的準確率（%）', XL_CHART_TYPE.COLUMN_CLUSTERED, 60, 90, 10)
stats(s10, ['int16', '375', 'leaf'], [
    (neg(e0.vs_tsne), f"不嵌入（K-Means 直接分 80 維）vs t-SNE（{pfmt(e0.vs_tsne_p)}）；偏半格 {neg(eh.vs_tsne)}（{pfmt(eh.vs_tsne_p)}）"),
    (f"{b1000.adapt:.1f}%", f"不嵌入時 buffer 加到 1,000 筆反而變差（375 筆 {e0.adapt:.1f}%）→ 維持 375 筆"),
    (f"−{ram_old.tsne_KB:.1f} KB", f"t-SNE 工作區不再需要；PC 上每個 block 也省下約 {t0.embed_cpu_s:.1f} s 的 t-SNE"),
])
set_para(named(s10, 'Footnote').text_frame.paragraphs[0],
         'Docker、20 人 × 11 block × 3 seed（偏移加開機對齊），推薦 MCU 設定：375 筆 int16 buffer、新樹 ≤ 32 葉，z-score 不更新。'
         '舊的比較（1,500 筆 float buffer）只用 K-Means 增益 +1.35、t-SNE +4.30：t-SNE 的好處只在大 buffer 時出現。'
         f"第 1 天擬合的 LDA 在偏移時顯著變差（{pfmt(E.loc[('arm_position', 0.5, 'ldacal5')].vs_tsne_p)}）。")
notes(s10, '之前我認為 t-SNE 不能省，因為在 1,500 筆的大 buffer 上，拿掉 t-SNE 只剩三分之一的增益。'
      '但現在 MCU 設定的 buffer 只有 375 筆，我重新比了 t-SNE、不嵌入、LDA 和 PCA：'
      f"不嵌入、直接在 80 個特徵上做 K-Means 是 {e0.adapt:.1f}%，t-SNE 是 {t0.adapt:.1f}%，沒有顯著差異，偏半格時也一樣。"
      '用第 1 天擬合的 LDA 在電極偏移時反而變差，因為投影是第 1 天的。'
      '我也試了把省下的記憶體拿去加大 buffer，結果越大越差，因為混了更舊的資料。'
      f"所以韌體 v2 拿掉 t-SNE、維持 375 筆，省下 {ram_old.tsne_KB:.0f} KB，也省掉每次好幾秒的運算。")

# ------------------------------------------------------------------ 11: class-balanced z-score update
s11 = find('t-SNE 迭代減半')
set_para(title_shape(s11).text_frame.paragraphs[0], 'z-score 跟著更新：偏半格再拉回 3 點，休息多也不受影響')
shifts = [(0, '沒偏移'), (0.25, '偏 ¼ 格'), (0.5, '偏 ½ 格')]
bar_chart(s11, named(s11, 'Chart tsne iterations'), [n for _, n in shifts],
          [('只自我校正', [z[sh].loc['none'].adapt for sh, _ in shifts], 'a5'),
           ('＋直接用整個 block 更新（休息佔一半）', [z[sh].loc['ema0.3rest'].adapt for sh, _ in shifts], 'a6'),
           ('＋類別平衡更新（休息佔一半）', [z[sh].loc['bal0.3rest'].adapt for sh, _ in shifts], 'a1')],
          '自我校正後的準確率（%，20 人 × 3 seed 平均）', XL_CHART_TYPE.COLUMN_CLUSTERED, 50, 90, 10)
bh, bq, b0 = z[0.5].loc['bal0.3rest'], z[0.25].loc['bal0.3rest'], z[0].loc['bal0.3rest']
stats(s11, ['time', 'diff', 'floor'], [
    (neg(bh.adapt_vs_none), f"偏半格時類別平衡更新的增益（{pfmt(bh.adapt_p)}，{int(bh.adapt_better)}／20 人）；¼ 格 {neg(bq.adapt_vs_none)}（{pfmt(bq.adapt_p)}）"),
    (neg(z[0].loc['ema0.3rest'].adapt_vs_none), '直接用整個 block 的平均更新，休息佔一半時的損失；類別平衡後沒有這個問題'),
    (f"{ram_v2.adapt_KB:.1f} KB", 'adapt.c（開機對齊＋每類累積 6 × 80 的平均與變異數）的 RAM，不需要標籤'),
])
set_para(named(s11, 'Footnote').text_frame.paragraphs[0],
         '每個 block 結束後，依自我校正模型的預測類別分組（每類 ≥ 5 個視窗），6 類等權合成平均與變異數，μ ← 0.7 μ ＋ 0.3 新值（只影響下一個 block）。'
         '休息佔一半：統計值只用 Rest＋等量其他視窗算，準確率照全部視窗。t-SNE 版，20 人 × 11 block × 3 seed（加開機對齊）；'
         f"沒偏移時增益 {neg(b0.adapt_vs_none)} 不顯著（{pfmt(b0.adapt_p)}）。")
notes(s11, '特徵的 z-score 原本一直用第一天校正時的平均和標準差。這頁讓它在使用中慢慢跟著更新，一樣不用標籤。'
      '最直接的做法是用每個 block 的平均更新，但日常使用時休息會佔大部分，統計值會被休息拉走，'
      f"模擬休息佔一半時反而掉了 {-z[0].loc['ema0.3rest'].adapt_vs_none:.0f} 個百分點。"
      '所以我改成類別平衡：用模型預測的類別分組，各類算自己的平均，再等權合起來。'
      f"這樣休息佔一半也沒問題，偏半格時再拉回 {bh.adapt_vs_none:.1f} 個百分點、有顯著差異；沒偏移時增益小、不顯著。"
      '這個步驟已經寫進韌體 v2 的 adapt.c。')

# ------------------------------------------------------------------ 12: firmware v2 RAM
s12 = find('Cortex-M7 編譯後')
set_para(title_shape(s12).text_frame.paragraphs[0], f"韌體 v2：Cortex-M7 RAM {ram_v2.ram_KB:.0f} KB，餘裕 {margin:.0f} KB")
cats = {'board layer added': '加上硬體層', 'octree 2.5 n cells': 'octree 只配 2.5n', '16-bit P, shared workspace': 'P 存 16 位元',
        'v2: no t-SNE, adapt.c': 'v2：不做 t-SNE'}
H = RH.iloc[::-1]                                                        # bar charts draw the first category at the bottom
bar_chart(s12, named(s12, 'Chart RAM'), [f"{cats[r.step]}（{r.ram_KB:.1f}）" for r in H.itertuples()],
          [('buffer＋calibration＋RAM 樹', list(H.selfcal_KB), 'dk2'),
           ('t-SNE 工作區', list(H.tsne_KB), 'a1'),
           ('one-shot 工作區', list(H.oneshot_KB), 'mid'),
           ('特徵擷取', list(H.features_KB), 'a2'),
           ('建樹、K-Means、adapt、UART、stack 等', list(H.adapt_KB + H.other_KB), 'a5')],
          'RAM 組成（KB，含 one-shot＋UART 的完整韌體，linker 實測）', XL_CHART_TYPE.BAR_STACKED, fmt='0.0', hide_below=8)
c12 = named(s12, 'Chart RAM').chart
c12.value_axis.minimum_scale, c12.value_axis.maximum_scale, c12.value_axis.major_unit = 0, 260, 50
stats(s12, ['ram', 'est', 'time'], [
    (f"{ram_v2.ram_KB:.1f} KB", f"完整韌體的 RAM（舊版 {ram_old.ram_KB:.1f} KB）；拿掉 t-SNE {ram_old.tsne_KB:.1f} KB，"
                               f"one-shot 改用自己的 {ram_v2.oneshot_KB:.0f} KB 工作區"),
    (f"{v2:.2f}%", f"C 版完整流程（開機對齊＋不嵌入＋z-score 更新）；Python {v2py:.2f}%（{pfmt(v2p)}）；偏半格 {v2h:.2f}%"),
    ('MCU 時間：待上板', f"PC 上一次自我校正 {cpu:.3f} s（t-SNE 版約 1 s）；韌體已包好 DWT cycle 計數"),
])
set_para(named(s12, 'Footnote').text_frame.paragraphs[0],
         'arm-none-eabi-gcc 10.3.1，-Os，Cortex-M7；RAM = .data＋.bss＋最深 stack；硬體層只編譯、還沒對照 RM0433。'
         f"C vs Python：20 人 × 11 block × 3 seed，開機對齊估到的轉法 {int(ACS.loc[(0.5, 1)].k_same)}／{int(ACS.loc[(0.5, 1)].k_runs)} 相同。"
         f"Flash {flash_v2:.0f} KB（含 88 KB 模型）。舊版（t-SNE）仍可用編譯選項編出。")
notes(s12, '這頁是韌體 v2 實際交叉編譯成 Cortex-M7 之後 linker 量出來的 RAM，一樣包含 one-shot、自我校正、特徵擷取和 UART 硬體層。'
      f"從上往下是四個版本：加上硬體層時 {RH.iloc[0].ram_KB:.1f} KB，改 t-SNE 兩處降到 {ram_old.ram_KB:.1f} KB；"
      f"v2 拿掉 t-SNE，one-shot 原本借 t-SNE 的工作區，所以另外給它 {ram_v2.oneshot_KB:.0f} KB，再加上開機對齊和 z-score 更新的 adapt.c，"
      f"總共 {ram_v2.ram_KB:.1f} KB，離 256 KB 還有 {margin:.0f} KB。"
      f"C 版和 Python 版的整條流程對照，準確率 {v2:.2f}% 對 {v2py:.2f}%，沒有顯著差異。"
      '時間要等板子到了用 DWT 計數器量。')

# ------------------------------------------------------------------ 我想做的事
w = find('我想做的事')
set_para(para(w, 'Col 0 list', '• one-shot 和自我校正'),
         f"• 韌體 v2（C）：{v2:.1f}%，M7 RAM {ram_v2.ram_KB:.1f} KB")
set_para(para(w, 'Col 0 list', '• 束帶轉一格'), f"• 束帶轉一格：開機對齊後回到原水準；偏半格 {v2h:.1f}%")
notes_replace(w, '在 Cortex-M7 上編譯是 223.8 KB',
              f"現在的韌體 v2 不做 t-SNE、加上 z-score 線上更新，準確率 {v2:.1f}%，在 Cortex-M7 上編譯是 {ram_v2.ram_KB:.1f} KB")

# ------------------------------------------------------------------ 和最接近的研究
c3 = find('和最接近的研究')
run_replace(c3, 'Text 1', '前置：M7 編譯 RAM 223.8 KB，保住約 87%增益',
            f"前置：M7 編譯 RAM {ram_v2.ram_KB:.1f} KB，PC 模擬 {v2:.1f}%，比固定模型 +{v2 - fx:.1f}")
notes_replace(c3, '前置結果估計 219 KB、保住約 87%的增益',
              f"前置結果是韌體 v2 實測 {ram_v2.ram_KB:.1f} KB，PC 模擬 {v2:.1f}%，比固定模型高 {v2 - fx:.1f} 個百分點")

# ------------------------------------------------------------------ 研究問題
rq = find('研究問題')
run_replace(rq, 'Text 9', '（PC 模擬：約 87%）', f"（PC 模擬：{v2:.1f}%，固定模型 {fx:.1f}%）")
notes_replace(rq, 'PC 模擬保住約 87% 的增益', f"PC 模擬是 {v2:.1f}%，比固定模型高 {v2 - fx:.1f} 個百分點")

# ------------------------------------------------------------------ 架構
ar = find('STM32 做決策')
set_para(para(ar, 'Box 1 body', '背景：免標籤自我校正'), '背景：自我校正＋z-score 更新')
set_para(para(ar, 'Box 1 body', 'M7 編譯 RAM'), f"M7 編譯 RAM {ram_v2.ram_KB:.0f} KB（含 one-shot）")

# ------------------------------------------------------------------ 方法
me = find('Flash 存預訓練樹池')
set_para(named(me, 'Text 17').text_frame.paragraphs[0],
         '小 buffer（375 筆，int16）＋ K-Means（80 維，不需 t-SNE）產生偽標籤，定期汰換附加樹（每棵 ≤ 32 葉）；z-score 同步更新',
         expect='小 buffer')
set_para(named(me, 'Text 29').text_frame.paragraphs[0],
         '產出：準確率 vs. 記憶體的取捨（第 10–12 頁已有 PC 模擬與 linker 實測的初版）→ 先投研討會', expect='產出')
notes_replace(me, '375 筆 int16 buffer 加 t-SNE 和 K-Means，附加樹限制 32 葉，估計 219 KB',
              f"375 筆 int16 buffer 直接做 K-Means、不需要 t-SNE，附加樹限制 32 葉，韌體 v2 實測 {ram_v2.ram_KB:.1f} KB")

# ------------------------------------------------------------------ demo (old firmware)
de = find('跨兩天 demo')
fn = named(de, 'Footnote').text_frame.paragraphs[0]
set_para(fn, ''.join(r.text for r in fn.runs) + '（舊版韌體邏輯，含 t-SNE；v2 還沒在這份資料上跑）', expect='JNE 2025')

# ------------------------------------------------------------------ 束帶情境
st = find('束帶情境')
set_para(named(st, 'Stat gain label').text_frame.paragraphs[0],
         f"偏半格最難：兩邊一樣像，對齊沒幫助；韌體 v2 加上 z-score 更新後 {v2h:.1f}%", expect='偏半格最難')
notes_replace(st, '所以實驗上要在束帶上做對齊記號',
              f"韌體 v2 再加上 z-score 線上更新，半格可以拉到 {v2h:.0f}%。所以實驗上還是要在束帶上做對齊記號")

# ------------------------------------------------------------------ checks
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
for sl in prs.slides:
    if sl is s12:
        continue                                                         # RAM history keeps the old versions
    nf = sl.notes_slide.notes_text_frame if sl.has_notes_slide else None
    txt = '\n'.join(s_.text_frame.text for s_ in sl.shapes if s_.has_text_frame) + (nf.text if nf is not None else '')
    for stale in ('223.8', '224 KB', '219 KB', '87%', '迭代'):
        assert stale not in txt, (stale, title_shape(sl).text_frame.text if title_shape(sl) else '')
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
