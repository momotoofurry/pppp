"""v5 = v3 + 前置結果⑤ (buffer size, int16 buffer, 32-leaf trees, below 256 KB) + 前置結果⑥ (t-SNE cost on the PC);
the 前置結果④ callout points to ⑤. Everything else in v3 is unchanged.
usage: python build5.py v3.pptx out.pptx nums4.json
"""
import copy
import json
import sys

from pptx import Presentation
from pptx.chart.data import XyChartData, CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.dml import MSO_THEME_COLOR as T, MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.text.text import _Paragraph
from pptx.util import Inches, Pt

src, dst, nums_path = sys.argv[1:4]
N = json.load(open(nums_path, encoding='utf8'))
prs = Presentation(src)
HEX = dict(dk1='1F2A30', dk2='0B3C49', lt2='E1EEF1', a1='1F7A8C', a2='F2A541', a5='5B6770', a6='C9D6DA')
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


def find_slide(prefix):
    for i, s in enumerate(prs.slides):
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.startswith(prefix):
                return i, s
    raise SystemExit(f'slide not found: {prefix}')


def text(slide, x, y, w, h, paras, size=14, color=T.TEXT_1, bold=False, anchor=MSO_ANCHOR.TOP, name=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.name = name or tb.name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, para in enumerate(paras if isinstance(paras, list) else [paras]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        for t, o in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            r.font.size = Pt(o.get('size', size))
            r.font.bold = o.get('bold', bold)
            r.font.color.theme_color = o.get('color', color)
    return tb


def card(slide, x, y, w, h, fill=T.BACKGROUND_2, name=None):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = 0.05217
    s.fill.solid()
    s.fill.fore_color.theme_color = fill
    s.line.color.theme_color = fill
    s.line.width = Pt(1)
    s.shadow.inherit = False
    s.name = name or s.name
    return s


def stat(slide, x, y, w, h, big, label, dark=False, big_size=30, name=''):
    card(slide, x, y, w, h, T.TEXT_2 if dark else T.BACKGROUND_2, name=f'{name} card')
    text(slide, x + 0.25, y + 0.15, w - 0.5, 0.6, big, size=big_size, bold=True,
         color=T.ACCENT_2 if dark else T.TEXT_2, name=f'{name} value')
    text(slide, x + 0.25, y + 0.15 + big_size / 72 * 1.25, w - 0.5, h - 0.25 - big_size / 72 * 1.25, label,
         size=13, color=T.BACKGROUND_1 if dark else T.TEXT_1, name=f'{name} label')


def set_runs(p, parts):
    for r in list(p.runs):
        p._p.remove(r._r)
    for t, col, b in parts:
        r = p.add_run()
        r.text = t
        r.font.size = Pt(14)
        r.font.bold = b
        r.font.color.theme_color = col


tsne = N['tsne']
t750 = [t for t in tsne if t['n'] == 750][0]
t500 = [t for t in tsne if t['n'] == 500][0]
t1500 = [t for t in tsne if t['n'] == 1500][0]

# ------------------------------------------------------------------ 前置結果④: callout points to the next slide
i4, s4 = find_slide('前置結果④')
co = [sh for sh in s4.shapes if sh.has_text_frame and sh.text_frame.text.startswith('放得進 512 KB 的做法')][0]
set_runs(co.text_frame.paragraphs[0],
         [('拿掉 t-SNE 只留下不到一半的增益 → ', T.BACKGROUND_1, False),
          ('那能不能保留 t-SNE、改把 buffer 縮小？見下一頁', T.ACCENT_2, True)])

# ------------------------------------------------------------------ new slide 前置結果⑤
title_src = [sh for sh in s4.shapes if sh.is_placeholder and sh.placeholder_format.type == 1
             and sh.text_frame.text.startswith('前置結果④')][0]
num_src = [sh for sh in s4.shapes if sh.is_placeholder and sh.placeholder_format.type == 13][0]
cover_src = [sh for sh in s4.shapes if sh.name.startswith('Rectangle')][0]
s5 = prs.slides.add_slide(s4.slide_layout)
for ph in list(s5.placeholders):
    ph._element.getparent().remove(ph._element)
s5.shapes._spTree.append(copy.deepcopy(title_src._element))
tr = s5.shapes[-1].text_frame.paragraphs[0].runs
tr[0].text = '前置結果⑤：保留 t-SNE、縮小 buffer，壓到 256 KB 以下'
for r in tr[1:]:
    r.text = ''
s5.shapes._spTree.append(copy.deepcopy(num_src._element))

cd = XyChartData()
st = cd.add_series('t-SNE＋K-Means（buffer 1500 → 500 筆，int16）')
for t in tsne:
    st.add_data_point(t['ram'], t['acc'])
sc = cd.add_series('t-SNE＋K-Means＋新樹 32 葉（buffer 750 → 250 筆，int16）')
for t in N['combo']:
    sc.add_data_point(t['ram'], t['acc'])
sn = cd.add_series('拿掉 t-SNE（buffer 1500 筆）')
sn.add_data_point(N['nocluster']['ram'], N['nocluster']['acc'])
sn.add_data_point(N['kmeans']['ram'], N['kmeans']['acc'])
sr = cd.add_series('RAM 預算線：512 KB（AXI SRAM）、256 KB')
sr.add_data_point(512, 80.5)
sr.add_data_point(512, 84.15)   # stop below the point labels at the top
sr2 = cd.add_series('256 KB')
sr2.add_data_point(256, 80.5)
sr2.add_data_point(256, 84.15)
gf = s5.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER_LINES, Inches(0.6), Inches(1.45), Inches(7.7), Inches(4.1), cd)
gf.name = 'Chart RAM vs accuracy'
ch = gf.chart
ch.font.size = Pt(12)
ch.font.color.rgb = RGBColor.from_string(HEX['dk1'])
ch.has_title = True
ch.chart_title.text_frame.text = '自我校正 RAM（KB，估算） vs. 自我校正後準確率（%）'
ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
ch.chart_title.text_frame.paragraphs[0].runs[0].font.bold = True
ch.has_legend = True
ch.legend.position = XL_LEGEND_POSITION.BOTTOM
ch.legend.include_in_layout = False
va, ca = ch.value_axis, ch.category_axis
va.minimum_scale, va.maximum_scale, va.major_unit = 80.5, 84.5, 1
ca.minimum_scale, ca.maximum_scale, ca.major_unit = 100, 800, 100
va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
ca.has_major_gridlines = False
va.tick_labels.number_format, va.tick_labels.number_format_is_linked = '0.0', False
ca.tick_labels.number_format, ca.tick_labels.number_format_is_linked = '0', False
ca.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
va.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
s_t, s_c, s_n, s_r, s_r2 = ch.plots[0].series
for s, col, line, marker in [(s_t, HEX['dk2'], True, XL_MARKER_STYLE.CIRCLE), (s_c, HEX['a1'], True, XL_MARKER_STYLE.DIAMOND),
                             (s_n, HEX['a2'], False, XL_MARKER_STYLE.SQUARE),
                             (s_r, HEX['a5'], True, XL_MARKER_STYLE.NONE), (s_r2, HEX['a5'], True, XL_MARKER_STYLE.NONE)]:
    s.smooth = False
    if line:
        s.format.line.color.rgb = RGBColor.from_string(col)
        s.format.line.width = Pt(2.25 if s in (s_t, s_c) else 1.25)
        if s in (s_r, s_r2):
            s.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    else:
        s.format.line.fill.background()
    s.marker.style = marker
    if marker != XL_MARKER_STYLE.NONE:
        s.marker.size = 9
        s.marker.format.fill.solid()
        s.marker.format.fill.fore_color.rgb = RGBColor.from_string(col)
        s.marker.format.line.color.rgb = RGBColor.from_string(col)


def label(series, idx, s, pos):
    dl = series.points[idx].data_label
    dl.has_text_frame = True
    dl.text_frame.text = s
    dl.position = pos
    r = dl.text_frame.paragraphs[0].runs[0]
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.color.rgb = RGBColor.from_string(HEX['dk1'])


for i, t in enumerate(tsne):   # 500 sits on top of the 32-leaf 500 point, which carries the label
    if t['n'] != 500:
        label(s_t, i, f"{t['n']} 筆", XL_LABEL_POSITION.ABOVE)
for i, t in enumerate(N['combo']):
    label(s_c, i, f"{t['n']} 筆", XL_LABEL_POSITION.BELOW)
label(s_n, 0, '不分群', XL_LABEL_POSITION.LEFT)
label(s_n, 1, '只用 K-Means', XL_LABEL_POSITION.RIGHT)

c375 = [t for t in N['combo'] if t['n'] == 375][0]
c250 = [t for t in N['combo'] if t['n'] == 250][0]
stat(s5, 8.55, 1.45, 4.15, 1.3, '0 損失', f"buffer 存成 int16：{t1500['acc']:.2f}%（float 版 {N['base']['acc']:.2f}%）", name='Stat int16')
stat(s5, 8.55, 2.85, 4.15, 1.3, f"{c375['ram']:.0f} KB",
     f"375 筆＋32 葉＋t-SNE：增益 +{c375['gain']:.2f}，和基準無顯著差異（p = {c375['p']:.2f}）",
     name='Stat 375')
stat(s5, 8.55, 4.25, 4.15, 1.3, f"≤ {N['leaf32']['bound']:.1f} KB",
     f"新樹限制 32 葉：附加樹的保證上限，準確率 {N['leaf32']['acc']:.2f}%（無顯著差異）", dark=True, name='Stat leaf')
card(s5, 0.6, 5.7, 12.1, 0.8, T.TEXT_2, name='Callout card')
text(s5, 0.85, 5.7, 11.6, 0.8,
     [[(f"t-SNE 不必拿掉：375 筆＋32 葉只要 {c375['ram']:.0f} KB、增益 +{c375['gain']:.2f}"
        f"（拿掉 t-SNE：{N['nocluster']['ram']:.0f} KB、+{N['nocluster']['gain']:.2f}）", {'color': T.BACKGROUND_1})],
      [('→ 下一個瓶頸：t-SNE 在 MCU 上要算多久（見下一頁）', {'color': T.ACCENT_2, 'bold': True})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE, name='Callout text')
text(s5, 0.6, 6.58, 12.1, 0.4,
     'Docker、20 人 × 11 block × 3 seed，推薦設定（100 棵、深度 10、int16）。RAM 為估算（附加樹用實測最大值）；'
     f"250 筆時明顯變差（{c250['acc']:.2f}%，p < 0.01）；拿掉 t-SNE 的兩點是 float buffer 實測、RAM 以 int16 buffer 計算。",
     size=11, color=T.ACCENT_5, name='Footnote')
s5.shapes._spTree.append(copy.deepcopy(cover_src._element))   # the user's footer cover, on top

# legend: one entry for the two budget lines (hide the 5th series, '256 KB')
C_NS = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'
leg = ch.legend._element
le = leg.makeelement(C_NS + 'legendEntry', {})
le.append(le.makeelement(C_NS + 'idx', {'val': '4'}))
le.append(le.makeelement(C_NS + 'delete', {'val': '1'}))
leg.insert(1, le)

ns5 = s5.notes_slide
if ns5.notes_placeholder is None:
    ns5.shapes._spTree.append(copy.deepcopy(s4.notes_slide.notes_placeholder._element))
ns5.notes_text_frame.text = (
    '上一頁看到拿掉 t-SNE 會失去一半以上的增益，所以反過來試：保留 t-SNE，把 buffer 縮小、存成 int16，並限制新樹的大小。'
    f"int16 完全沒有損失（{t1500['acc']:.2f}% 對 {N['base']['acc']:.2f}%）。深色線是只縮 buffer：750 筆約 {t750['ram']:.0f} KB，"
    f"增益 +{t750['gain']:.2f}。淺色線再加上新樹 32 葉的限制：375 筆時估計 {c375['ram']:.0f} KB，已經低於 256 KB，"
    f"增益還有 +{c375['gain']:.2f}，和不壓縮的基準沒有顯著差異；縮到 250 筆才明顯變差。"
    f"相比之下拿掉 t-SNE 的做法用 {N['nocluster']['ram']:.0f} KB 卻只有 +{N['nocluster']['gain']:.2f}。"
    '所以記憶體的問題基本上解決了，接下來的瓶頸是 t-SNE 的運算時間，下一頁說明。RAM 是依設計計算的估算。')

# ------------------------------------------------------------------ new slide 前置結果⑥: t-SNE cost
s6 = prs.slides.add_slide(s4.slide_layout)
for ph in list(s6.placeholders):
    ph._element.getparent().remove(ph._element)
s6.shapes._spTree.append(copy.deepcopy(title_src._element))
tr = s6.shapes[-1].text_frame.paragraphs[0].runs
tr[0].text = '前置結果⑥：下一個瓶頸是 t-SNE 的運算時間'
for r in tr[1:]:
    r.text = ''
s6.shapes._spTree.append(copy.deepcopy(num_src._element))
cost = N['tsne_cost']
cd6 = CategoryChartData()
cd6.categories = [f"{c['buffer']} 筆" for c in cost]
cd6.add_series('PC 上每次 t-SNE 的 CPU 時間（秒）', [c['cpu'] for c in cost])
gf6 = s6.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.45), Inches(7.7), Inches(4.1), cd6)
gf6.name = 'Chart tsne cost'
ch6 = gf6.chart
ch6.font.size = Pt(12)
ch6.font.color.rgb = RGBColor.from_string(HEX['dk1'])
ch6.has_title = True
ch6.chart_title.text_frame.text = '每次自我校正的 t-SNE：PC 單執行緒 CPU 時間（秒）'
ch6.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
ch6.chart_title.text_frame.paragraphs[0].runs[0].font.bold = True
ch6.has_legend = False
pl6 = ch6.plots[0]
pl6.gap_width = 60
pl6.has_data_labels = True
pl6.data_labels.number_format, pl6.data_labels.number_format_is_linked = '0.0" s"', False
pl6.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
pl6.data_labels.font.size = Pt(12)
pl6.data_labels.font.bold = True
va6 = ch6.value_axis
va6.minimum_scale, va6.maximum_scale, va6.major_unit = 0, 10, 2
va6.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
va6.format.line.fill.background()
ch6.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
ch6.category_axis.has_title = True
ch6.category_axis.axis_title.text_frame.text = 'buffer 大小（類別平衡後實際進 t-SNE 的點數約為 0.7–1.0 倍）'
ch6.category_axis.axis_title.text_frame.paragraphs[0].runs[0].font.size = Pt(11)
ch6.category_axis.axis_title.text_frame.paragraphs[0].runs[0].font.bold = False
for i, c in enumerate(cost):
    pt = pl6.series[0].points[i]
    pt.format.fill.solid()
    pt.format.fill.fore_color.rgb = RGBColor.from_string(HEX['a1'] if c['buffer'] == 375 else HEX['a6'])
c375c = [c for c in cost if c['buffer'] == 375][0]
c1500c = [c for c in cost if c['buffer'] == 1500][0]
stat(s6, 8.55, 1.45, 4.15, 1.3, f"{c375c['cpu']:.1f} s",
     f"375 筆在 PC 上一次 t-SNE（1500 筆 {c1500c['cpu']:.1f} s，時間約和點數成正比）", name='Stat pc')
stat(s6, 8.55, 2.85, 4.15, 1.3, f"{int(round(c375c['iters']))} 次",
     '每次都跑滿迭代上限（1000），沒有提早停止 → 減少迭代次數可能可以省', name='Stat iters')
stat(s6, 8.55, 4.25, 4.15, 1.3, 'MCU：未量',
     '要用 C 實作 Barnes-Hut t-SNE，在 H743 上實測；PC 時間不能直接換算', dark=True, name='Stat mcu')
card(s6, 0.6, 5.7, 12.1, 0.8, T.TEXT_2, name='Callout card')
text(s6, 0.85, 5.7, 11.6, 0.8,
     [[('自我校正每個 block（30 個 trial）才做一次，能接受的時間比即時推論寬鬆得多', {'color': T.BACKGROUND_1})],
      [('→ 下一步：C 版 t-SNE 上板實測時間，並測減少迭代次數對準確率的影響', {'color': T.ACCENT_2, 'bold': True})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE, name='Callout text')
text(s6, 0.6, 6.58, 12.1, 0.4,
     f"PC 單執行緒 CPU 時間：sklearn TSNE（3 維、perplexity 10、Barnes-Hut、init=random），{c375c['subjects']} 位受試者平均；"
     'buffer 和自我校正時一樣（int16、類別平衡後才進 t-SNE）。這是 x86 PC 的時間，不是 MCU 的時間。',
     size=11, color=T.ACCENT_5, name='Footnote')
s6.shapes._spTree.append(copy.deepcopy(cover_src._element))
ns6 = s6.notes_slide
if ns6.notes_placeholder is None:
    ns6.shapes._spTree.append(copy.deepcopy(s4.notes_slide.notes_placeholder._element))
ns6.notes_text_frame.text = (
    'RAM 的問題解決後，下一個問題是運算時間。我在 PC 上用單執行緒量了每次 t-SNE 的時間：'
    f"1500 筆要 {c1500c['cpu']:.1f} 秒，375 筆 {c375c['cpu']:.1f} 秒，大致和點數成正比。"
    '而且每次都跑滿 1000 次迭代，沒有提早收斂，所以減少迭代次數可能是省時間的方法，但對準確率的影響還沒量。'
    '這是 PC 的時間，Cortex-M7 一定慢很多，但慢多少一定要用 C 實作之後上板量，我現在不估數字。'
    '好消息是自我校正每個 block 才做一次，不需要即時完成，可以在背景慢慢算。')

ids = prs.slides._sldIdLst
new_els = list(ids)[-2:]          # ⑤ then ⑥, right after ④
for el in new_els:
    ids.remove(el)
for k, el in enumerate(new_els):
    ids.insert(i4 + 1 + k, el)
for pos, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(pos)
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
