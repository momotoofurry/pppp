"""v14 = v13 (build13.py output, not edited by the user: written 2026-10-25 20:32:58) with the corrected electrode
rotation and the strap scenario. Numbers are read from results/, not typed.

- 電極轉一格 slide: numbers and curves from the raw-EMG rotation (shift_sweep.py --raw: rotate the raw signals,
  then features, then z-score with the calibration statistics; results/shift_sweep_raw*_uhc.csv). The v13 numbers
  came from the feature-level rotation, which z-scored before rotating (report.md 8, correction).
- NEW slide after it: strap scenario, fractional offsets and the label-free start-up alignment
  (results/shift_sweep_raw_summary.csv, shift_sweep_raw.csv).
- 我想做的事: the rotation bullet; speaker notes.
usage: python build14.py v13.pptx out.pptx
"""
import copy
import os
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


def notes(s, text_):
    s.notes_slide.notes_text_frame.text = text_


def neg(v, fmt='+.2f'):
    return format(v, fmt).replace('-', '−')


def pfmt(p):
    return 'p < 0.001' if p < 0.001 else f'p = {p:.3f}' if p < 0.01 else f'p = {p:.2f}'


def stats(s, items):
    for key, (value, label) in zip(['tail', 'gain', 'n'], items):
        set_para(named(s, f'Stat {key} value').text_frame.paragraphs[0], value)
        set_para(named(s, f'Stat {key} label').text_frame.paragraphs[0], label)


def new_like(like, title_):
    """copy of `like` without its chart, inserted right after it"""
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
    ids = prs.slides._sldIdLst
    el = ids[-1]
    ids.remove(el)
    ids.insert(list(prs.slides).index(like) + 1, el)
    return s


def line_chart(s, like_chart, cats, series, title_, ymin, ymax, xtitle):
    """series = [(name, values, colour, width)]; same look as build13's line charts"""
    cd_ = CategoryChartData()
    cd_.categories = cats
    for name, vals, _, _ in series:
        cd_.add_series(name, vals)
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, like_chart.left, like_chart.top, like_chart.width,
                            like_chart.height, cd_)
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


# ------------------------------------------------------------------ numbers
U = csv('shift_sweep_raw_summary_uhc.csv').set_index('shift')        # tsne + uhc, raw rotation, shifts 0 / +-1
A = csv('shift_sweep_raw_summary.csv').set_index('shift')            # tsne + align, fractional shifts
UB = csv('shift_sweep_raw_uhc.csv')
u0, u1, um1 = U.loc[0], U.loc[1], U.loc[-1]
assert abs(u0.tsne - A.loc[0].tsne) < 1e-6 and abs(u1.tsne - A.loc[1].tsne) < 1e-6, 'the two raw runs disagree'


def curve(shift, method, col):
    d = UB[(UB['shift'] == shift) & (UB.method == method)]
    return list(d.groupby('block')[col].mean() * 100)


# ------------------------------------------------------------------ 電極轉一格 (corrected)
sh = find('電極轉一格')
set_para(title_shape(sh).text_frame.paragraphs[0], '電極轉一格：自我校正只拉回一點，信心式自我訓練更差')
cd = CategoryChartData()
cd.categories = [str(b) for b in sorted(UB.block.unique())]
cd.add_series('沒轉：t-SNE 自我校正（參考）', curve(0, 'tsne', 'acc_adapt'))
cd.add_series('轉一格：固定模型', curve(1, 'tsne', 'acc_fixed'))
cd.add_series('轉一格：信心式自我訓練（UHC [11]）', curve(1, 'uhc', 'acc_adapt'))
cd.add_series('轉一格：t-SNE 自我校正（本研究）', curve(1, 'tsne', 'acc_adapt'))
chart15 = named(sh, 'Chart')
chart15.chart.replace_data(cd)
chart15.chart.value_axis.minimum_scale = 30
stats(sh, [
    (f"{u1.tsne_fixed:.1f}%", f"電極轉一格後的固定模型；沒轉 {u0.tsne_fixed:.1f}%（反方向轉 {um1.tsne_fixed:.1f}%）"),
    (f"+{u1.diff_tsne_vs_fixed:.2f}", f"t-SNE 自我校正的增益（{pfmt(u1.p_tsne_vs_fixed)}，{int(u1.better_tsne_vs_fixed)}／20 人）；"
                                      f"反方向 +{um1.diff_tsne_vs_fixed:.2f}（{pfmt(um1.p_tsne_vs_fixed)}）"),
    (neg(u1.diff_uhc_vs_fixed), f"信心式自我訓練（UHC）比固定模型還差（{pfmt(u1.p_uhc_vs_fixed)}）；和 Campbell [11] 的結論一致"),
])
set_para(named(sh, 'Footnote').text_frame.paragraphs[0],
         '第 1 天照原位置做 one-shot；測試時 8 個電極整圈轉一格（45°）：轉原始 EMG 再算特徵、用 calibration 統計值標準化，'
         '假設通道 1–8 依序繞前臂一圈（作者沒寫明）。66 人模型＋推薦 MCU 設定，20 人 × 11 block × 3 seed。'
         'UHC：用目前模型自己的預測當偽標籤，只取最高票比例 ≥ 0.6 的視窗。')
notes(sh, '這頁模擬穿戴時電極環轉了一格，也就是 45 度、大約 3 公分。固定模型從 '
      f"{u0.tsne_fixed:.0f}% 掉到 {u1.tsne_fixed:.0f}% 左右。我的 t-SNE 自我校正顯著拉回 {u1.diff_tsne_vs_fixed:.1f} 個百分點，"
      f"但最後幾個 block 也只有 {u1.tsne_late:.0f}%。Campbell 2024 的信心式自我訓練反而比固定模型更差，"
      '因為轉動後模型自己的預測大多是錯的，拿來重新訓練只會強化錯誤。所以單靠自我校正處理不了這麼大的偏移，下一頁是對策。')

# ------------------------------------------------------------------ NEW: strap, fractional offsets + start-up alignment
order = [-1, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1]
lab = {-1: '−1', -0.5: '−½', -0.25: '−¼', 0: '0', 0.25: '¼', 0.5: '½', 0.75: '¾', 1: '1'}
st = new_like(sh, '束帶情境：開機對齊救回整格轉動，半格最難')
line_chart(st, chart15, [lab[o] for o in order],
           [('固定模型', [A.loc[o].tsne_fixed for o in order], 'a5', 2.0),
            ('自我校正', [A.loc[o].tsne for o in order], 'a1', 2.0),
            ('開機對齊＋自我校正', [A.loc[o]['align'] for o in order], 'a2', 2.75)],
           '偏移量和準確率（%，20 人 × 3 seed 平均）', 40, 90, '電極環偏移（格；1 格 = 45°，約 3 cm）')
half = A.loc[[0.5, -0.5]]
k_int = int(min(A.loc[1].k_nearest, A.loc[-1].k_nearest))
stats(st, [
    (f"{A.loc[1]['align']:.1f}%", f"整格轉動時開機對齊 {k_int}／20 人都估對，回到沒轉的水準（只自我校正 {A.loc[1].tsne:.1f}%）"),
    (f"{half['align'].mean():.0f}%", f"偏半格最難：兩邊一樣像，對齊沒幫助（{pfmt(half.p_align_vs_tsne.min())}），"
                                  f"比沒轉低 {-half.diff_align_vs_noshift.mean():.0f} 個百分點"),
    ('≤ ¼ 格', f"配戴時對齊記號要做到的精度（約 0.7 cm），¼ 格只掉約 {-A.loc[[0.25, -0.25]].diff_align_vs_noshift.mean():.0f} 個百分點"),
])
set_para(named(st, 'Footnote').text_frame.paragraphs[0],
         '偏移 k + f 格：每個通道 = (1 − f) × 第 c + k 個電極 ＋ f × 第 c + k + 1 個電極的原始 EMG（相鄰電極線性內插，一階近似）。'
         '開機對齊：用第一個 block 每個通道 log RMS／MAV／WL 的平均，和 calibration 的輪廓比，選 8 種整數轉法中最像的，免標籤。'
         '資料是貼片不是束帶；沒有模擬使用中慢慢滑動。')
notes(st, '我之後會把感測器固定在束帶上給受試者戴，每天重戴時整圈轉動是真的會發生的，而且通常不是剛好一格。'
      '所以我把偏移做成連續的：四分之一格、半格、四分之三格，再加一個開機對齊的步驟：不用標籤，'
      '只拿第一段資料每個通道的訊號大小輪廓，跟第一天的校正資料比，找出轉了幾格、把通道排回去。'
      f"整格轉動時 20 個人都估對，準確率完全回到 {A.loc[1]['align']:.0f}%；四分之三格會對到最近的一格。"
      f"最難的是半格，兩邊一樣像，對齊沒有幫助，只有約 {half['align'].mean():.0f}%。"
      '所以實驗上要在束帶上做對齊記號，把偏移壓在四分之一格、大約 0.7 公分以內，剩下的整格轉動交給開機對齊。'
      '在 MCU 上只用到已經存著的校正平均值，計算量很小，但時間還沒有在板子上量。')

# ------------------------------------------------------------------ 我想做的事
w = find('我想做的事')
col0 = named(w, 'Col 0 list').text_frame
p = [p for p in col0.paragraphs if p.text.startswith('• 電極轉一格')][0]
set_para(p, f"• 束帶轉一格：開機對齊後回到 {A.loc[1]['align']:.1f}%；偏半格仍掉約 {-half.diff_align_vs_noshift.mean():.0f} 點")
nt = w.notes_slide.notes_text_frame.text
old = '電極轉一格時自我校正只拉回一部分，但比 Campbell 的信心式自我訓練好。'
assert old in nt, nt
notes(w, nt.replace(old, '束帶整圈轉一格時，單靠自我校正只拉回一部分，加上免標籤的開機對齊就能回到沒轉的水準；偏半格是目前的弱點。'))

# ------------------------------------------------------------------ page numbers
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
alltext = '\n'.join(s_.text_frame.text for sl in prs.slides for s_ in sl.shapes if s_.has_text_frame)
for stale in ('52.2%', '+5.90', '+0.21'):
    assert stale not in alltext, stale
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
