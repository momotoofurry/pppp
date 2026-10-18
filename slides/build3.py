"""Update the user's edited deck (碩論題目討論_MOMO_v2.pptx) with the measured pseudo-label results.

- 前置結果③: RAM chart rebuilt with the 6 measured combinations (2 models x 3 pseudo-label methods,
  Docker runs, accuracies measured instead of the paper's ablation), callout and notes updated
- new slide 前置結果④ right after it: self-calibration gain per method, reproduction of the ablation
Everything else in the user's version is left as it is.
usage: python build3.py user_v2.pptx out.pptx nums2.json
"""
import copy
import math
import json
import sys

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_TICK_LABEL_POSITION
from pptx.enum.dml import MSO_THEME_COLOR as T, MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

src, dst, nums_path = sys.argv[1:4]
N = json.load(open(nums_path, encoding='utf8'))
P, RAM = N['pseudo'], N['ram']
prs = Presentation(src)
HEX = dict(dk1='1F2A30', dk2='0B3C49', lt2='E1EEF1', a1='1F7A8C', a2='F2A541', a5='5B6770', a6='C9D6DA')
C_NS = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'
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


def chart_title(ch, s):
    ch.has_title = True
    ch.chart_title.text_frame.text = s
    r = ch.chart_title.text_frame.paragraphs[0].runs[0]
    r.font.size = Pt(14)
    r.font.bold = True


def label_numfmt(point, fmt):
    """a per-point data label drops the series number format: add <c:numFmt> right after <c:idx>"""
    d = point.data_label._dLbl
    nf = d.makeelement(C_NS + 'numFmt', {'formatCode': fmt, 'sourceLinked': '0'})
    d.find(C_NS + 'idx').addnext(nf)


def pct(v):
    return f'{v:.2f}%'


# ------------------------------------------------------------------ 前置結果③: measured RAM x accuracy
i3, s3 = find_slide('前置結果③')
old = [sh for sh in s3.shapes if sh.has_chart][0]
x, y, w, h = old.left, old.top, old.width, old.height
old._element.getparent().remove(old._element)
rows = [('400 棵・t-SNE＋K-Means', 'full_tsne'), ('400 棵・只用 K-Means', 'full_kmeans'), ('400 棵・不分群', 'full_none'),
        ('100 棵 int16・t-SNE＋K-Means', 'c3_tsne'), ('100 棵 int16・只用 K-Means', 'c3_kmeans'),
        ('100 棵 int16・不分群', 'c3_none')]
cd = CategoryChartData()
cd.categories = [f"{lab}｜{pct(P[k]['acc_selfcal'])}" for lab, k in reversed(rows)]   # first category is drawn at the bottom
cd.add_series('RAM（KB）', [RAM[k] for _, k in reversed(rows)])
gf = s3.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, x, y, w, h, cd)
gf.name = 'Chart RAM'
ch = gf.chart
ch.font.size = Pt(12)
ch.font.color.rgb = RGBColor.from_string(HEX['dk1'])
chart_title(ch, '自我校正需要的 RAM（KB，估算）｜格線 512 KB = AXI SRAM')
ch.has_legend = False
pl = ch.plots[0]
pl.gap_width = 50
pl.has_data_labels = True
va = ch.value_axis
va.minimum_scale, va.maximum_scale, va.major_unit = 0, 1536, 512
va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['a5'])
va.major_gridlines.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
va.format.line.fill.background()
va.tick_label_position = XL_TICK_LABEL_POSITION.LOW
ch.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
for idx, (_, k) in enumerate(reversed(rows)):
    fits = RAM[k] <= 512
    pt = pl.series[0].points[idx]
    pt.format.fill.solid()
    pt.format.fill.fore_color.rgb = RGBColor.from_string(HEX['a1'] if fits else HEX['a6'])
    pt.data_label.font.size = Pt(12)
    pt.data_label.font.bold = True
    pt.data_label.font.color.rgb = RGBColor.from_string('FFFFFF' if fits else HEX['dk2'])
    pt.data_label.position = XL_LABEL_POSITION.INSIDE_END
    label_numfmt(pt, '0" KB"')
# move the new chart frame back to where the old one was in z-order (behind nothing in particular: keep it first)
s3.shapes._spTree.remove(gf._element)
s3.shapes._spTree.insert(2, gf._element)

callout = [sh for sh in s3.shapes if sh.has_text_frame and sh.text_frame.text.startswith('放得進 512 KB')][0]
p0 = callout.text_frame.paragraphs[0]
for r in list(p0.runs):              # PowerPoint split the text into many runs: rebuild it as two
    p0._p.remove(r._r)
k3, kn = P['c3_kmeans'], P['c3_none']
p1 = copy.deepcopy(p0._p)            # second line for the research question
p0._p.addnext(p1)
from pptx.text.text import _Paragraph   # noqa: E402
for para, (t, col, b) in zip([p0, _Paragraph(p1, p0._parent)],
                             [(f"放得進 512 KB 的只有 100 棵的「只用 K-Means」「不分群」，但增益只剩 "
                               f"+{k3['gain']:.2f}／+{kn['gain']:.2f}（t-SNE 版 +{P['c3_tsne']['gain']:.2f}）", T.BACKGROUND_1, False),
                              ('→ 研究問題：在 RAM 預算內保住 t-SNE 的增益', T.ACCENT_2, True)]):
    r = para.add_run()
    r.text = t
    r.font.size = Pt(14)
    r.font.bold = b
    r.font.color.theme_color = col
s3.notes_slide.notes_text_frame.text = (
    '推論本身很省：88 KB Flash、552 B RAM，C 版和 Python 版預測 100% 一致。瓶頸在自我校正：'
    f"照論文原樣做（float32 buffer 加 t-SNE）估計要 {RAM['full_tsne']:.0f} KB，連整顆晶片的 SRAM 都放不下；光 t-SNE 就要 401 KB。"
    f"這一版的準確率全部是我們實測的：放得進 512 KB 的只有推薦設定的「只用 K-Means」（{RAM['c3_kmeans']:.0f} KB，{pct(k3['acc_selfcal'])}）"
    f"和「不分群」（{RAM['c3_none']:.0f} KB，{pct(kn['acc_selfcal'])}），比 t-SNE 版（{pct(P['c3_tsne']['acc_selfcal'])}）低 2–3 個百分點。"
    'RAM 是依設計計算的估算，可替換附加樹用各方法實測的大小。這頁和下一頁的準確率是在 Docker（Linux）上跑的，'
    '和前一頁（Windows）分開比較，同平台內才互相比。')

# ------------------------------------------------------------------ new slide 前置結果④ right after ③
s4 = prs.slides.add_slide(s3.slide_layout)
title_src = [sh for sh in s3.shapes if sh.is_placeholder and sh.placeholder_format.type == 1
             and sh.text_frame.text.startswith('前置結果③')][0]
num_src = [sh for sh in s3.shapes if sh.is_placeholder and sh.placeholder_format.type == 13][0]
cover_src = [sh for sh in s3.shapes if sh.name.startswith('Rectangle')][0]   # the user's footer cover
for ph in list(s4.placeholders):     # the layout's own (empty) title placeholder: use a copy of slide 13's title instead
    ph._element.getparent().remove(ph._element)
s4.shapes._spTree.append(copy.deepcopy(title_src._element))
tr = s4.shapes[-1].text_frame.paragraphs[0].runs
tr[0].text = '前置結果④：拿掉 t-SNE，自我校正的增益少一半以上'
for r in tr[1:]:
    r.text = ''
s4.shapes._spTree.append(copy.deepcopy(num_src._element))
s4.shapes._spTree.append(copy.deepcopy(cover_src._element))

cd = CategoryChartData()
methods = [('tsne', 't-SNE＋K-Means'), ('kmeans', '只用 K-Means'), ('none', '不分群')]
cd.categories = [lab for _, lab in methods]
cd.add_series('400 棵（完整模型）', [P[f'full_{m}']['gain'] for m, _ in methods])
cd.add_series('100 棵、深度 10、int16（推薦）', [P[f'c3_{m}']['gain'] for m, _ in methods])
gf = s4.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.45), Inches(7.7), Inches(4.1), cd)
gf.name = 'Chart gain'
ch = gf.chart
ch.font.size = Pt(12)
ch.font.color.rgb = RGBColor.from_string(HEX['dk1'])
chart_title(ch, '自我校正帶來的增益（個百分點，自我校正 − one-shot）')
ch.has_legend = True
ch.legend.position = XL_LEGEND_POSITION.BOTTOM
ch.legend.include_in_layout = False
pl = ch.plots[0]
pl.gap_width = 80
pl.overlap = -10
pl.has_data_labels = True
pl.data_labels.number_format = '+0.00'
pl.data_labels.number_format_is_linked = False
pl.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
pl.data_labels.font.size = Pt(12)
pl.data_labels.font.bold = True
va = ch.value_axis
va.minimum_scale, va.maximum_scale, va.major_unit = 0, 5, 1
va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
va.format.line.fill.background()
ch.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
for s, col in zip(pl.series, [HEX['dk2'], HEX['a1']]):
    s.format.fill.solid()
    s.format.fill.fore_color.rgb = RGBColor.from_string(col)

ft, fk, fn = P['full_tsne'], P['full_kmeans'], P['full_none']
dev = max(abs(ft['acc_selfcal'] - 84.6), abs(fk['acc_selfcal'] - 81.0), abs(fn['acc_selfcal'] - 82.7))
stat(s4, 8.55, 1.45, 4.15, 1.3, f'差 ≤ {math.ceil(dev * 10) / 10:.1f}',   # round up: never understate the gap

     f"重現論文 ablation：{ft['acc_selfcal']:.2f}／{fk['acc_selfcal']:.2f}／{fn['acc_selfcal']:.2f}%（論文 84.6／81.0／82.7）",
     name='Stat ablation')
nb = sorted([int(P['c3_kmeans']['n_subjects_better']), int(P['c3_none']['n_subjects_better'])])
stat(s4, 8.55, 2.85, 4.15, 1.3, f'{nb[0]}–{nb[1]} / 20 人',
     '推薦設定拿掉 t-SNE 後，比 t-SNE 版好的人數（配對檢定 p < 0.001）', name='Stat subjects')
stat(s4, 8.55, 4.25, 4.15, 1.3, f"{RAM['c3_none']:.0f} KB",
     f"最省的做法（不分群）：自我校正 {pct(kn['acc_selfcal'])}，t-SNE 版 {pct(P['c3_tsne']['acc_selfcal'])}",
     dark=True, name='Stat cheapest')
card(s4, 0.6, 5.7, 12.1, 0.8, T.TEXT_2, name='Callout card')
text(s4, 0.85, 5.7, 11.6, 0.8,
     [[('放得進 512 KB 的做法，只留下不到一半的增益 → ', {'color': T.BACKGROUND_1}),
       ('下一步：找 ≤ 512 KB、能把增益拉回 +4 個百分點的偽標籤方法', {'color': T.ACCENT_2, 'bold': True})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE, name='Callout text')
text(s4, 0.6, 6.58, 12.1, 0.4,
     'Docker（Linux）上的結果：20 人 × 11 block × 3 seed；配對檢定為 seed 平均後 20 人的 Wilcoxon。'
     '不分群 = 直接用 one-shot 模型的預測當偽標籤（只做類別平衡）。',
     size=11, color=T.ACCENT_5, name='Footnote')
ns4 = s4.notes_slide
if ns4.notes_placeholder is None:   # the deck's notes master lost its body placeholder: copy slide 13's notes body
    ns4.shapes._spTree.append(copy.deepcopy(s3.notes_slide.notes_placeholder._element))
ns4.notes_text_frame.text = (
    '這頁是剛跑完的實驗：把論文的偽標籤方法（t-SNE 加 K-Means）換成兩種低記憶體做法。'
    f"先確認做法正確：完整模型的三個結果 {ft['acc_selfcal']:.2f}、{fk['acc_selfcal']:.2f}、{fn['acc_selfcal']:.2f}%，"
    '和論文 ablation 的 84.6、81.0、82.7% 高低順序一樣，差距不到 1 個百分點。'
    f"在推薦設定上，自我校正的增益從 +{P['c3_tsne']['gain']:.2f} 掉到只用 K-Means 的 +{k3['gain']:.2f}、"
    f"不分群的 +{kn['gain']:.2f}，20 人中只有 {nb[0]} 到 {nb[1]} 人比 t-SNE 版好，配對檢定 p 小於 0.001。"
    '所以研究問題成立：要在 512 KB 內找到能保住增益的偽標籤方法，下一步會試 LDA 投影加 K-Means、小 buffer 的 t-SNE 和信心門檻。')

cov = [sh for sh in s4.shapes if sh.name.startswith('Rectangle')][0]
s4.shapes._spTree.remove(cov._element)
s4.shapes._spTree.append(cov._element)

# move the new slide right after 前置結果③
ids = prs.slides._sldIdLst
el = list(ids)[-1]
ids.remove(el)
ids.insert(i3 + 1, el)
for pos, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(pos)
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
