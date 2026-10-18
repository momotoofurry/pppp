"""v7 = v6 + 前置結果⑦ (fewer t-SNE iterations: accuracy vs. PC t-SNE time) right after ⑥; ⑥ points to ⑦,
the summary slide gets the result, page references 11–17 -> 11–18. Everything else in v6 is unchanged.
usage: python build7.py v6.pptx out.pptx nums5.json
"""
import copy
import json
import sys

from pptx import Presentation
from pptx.chart.data import XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_MARKER_STYLE
from pptx.enum.dml import MSO_THEME_COLOR as T
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
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


def set_para(p, text_, expect=None):
    """replace a paragraph's text, keeping its first run's formatting"""
    if expect:
        assert ''.join(r.text for r in p.runs).startswith(expect), (p.runs[0].text[:40], expect)
    p.runs[0].text = text_
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)


def named(slide, name):
    return [sh for sh in slide.shapes if sh.name == name][0]


it = {t['it']: t for t in N['tsne_iter']}
t500, t400, t250, t1000 = it[500], it[400], it[250], it[1000]
sig = [t for t in N['tsne_iter'] if t['it'] < 1000 and t['p'] < 0.05]
lowest_ok = min(t['it'] for t in N['tsne_iter'] if t['p'] >= 0.05)
assert lowest_ok == 500 and max(t['it'] for t in sig) == 400, (lowest_ok, sig)

# ------------------------------------------------------------------ 前置結果⑥: point to ⑦
i6, s6 = find_slide('前置結果⑥')
set_para(named(s6, 'Stat iters label').text_frame.paragraphs[0],
         '每次都跑滿迭代上限（1000），沒有提早停止 → 減到 500 次的結果見下一頁', '每次都跑滿')
set_para(named(s6, 'Callout text').text_frame.paragraphs[1],
         '→ 下一步：C 版 t-SNE 上板實測；迭代次數已確認可減半（下一頁），其他備案：降低 perplexity、換更省的嵌入方法',
         '→ 下一步')

# ------------------------------------------------------------------ new slide 前置結果⑦
title_src = [sh for sh in s6.shapes if sh.has_text_frame and sh.text_frame.text.startswith('前置結果⑥')][0]
num_src = [sh for sh in s6.shapes if sh.is_placeholder and sh.placeholder_format.type == 13][0]
cover_src = [sh for sh in s6.shapes if sh.name.startswith('Rectangle')][0]
s7 = prs.slides.add_slide(s6.slide_layout)
for ph in list(s7.placeholders):
    ph._element.getparent().remove(ph._element)
s7.shapes._spTree.append(copy.deepcopy(title_src._element))
tr = s7.shapes[-1].text_frame.paragraphs[0].runs
tr[0].text = '前置結果⑦：t-SNE 迭代減半，準確率無顯著差異'
for r in tr[1:]:
    r.text = ''
s7.shapes._spTree.append(copy.deepcopy(num_src._element))

cd = XyChartData()
se = cd.add_series('t-SNE 迭代 250 → 1000 次（buffer 375 筆 int16＋32 葉）')
for t in N['tsne_iter']:
    se.add_data_point(t['cpu'], t['gain'])
gf = s7.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER_LINES, Inches(0.6), Inches(1.45), Inches(7.7), Inches(4.1), cd)
gf.name = 'Chart tsne iterations'
ch = gf.chart
ch.font.size = Pt(12)
ch.font.color.rgb = RGBColor.from_string(HEX['dk1'])
ch.has_title = True
ch.chart_title.text_frame.text = 'PC 上每次 t-SNE 的 CPU 時間（秒） vs. 自我校正增益（個百分點）'
ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
ch.chart_title.text_frame.paragraphs[0].runs[0].font.bold = True
ch.has_legend = False
va, ca = ch.value_axis, ch.category_axis
va.minimum_scale, va.maximum_scale, va.major_unit = 0, 4.5, 1
ca.minimum_scale, ca.maximum_scale, ca.major_unit = 0, 2.2, 0.5
va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
ca.has_major_gridlines = False
va.tick_labels.number_format, va.tick_labels.number_format_is_linked = '"+"0', False
ca.tick_labels.number_format, ca.tick_labels.number_format_is_linked = '0.0" s"', False
ca.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
va.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
s_ = ch.plots[0].series[0]
s_.smooth = False
s_.format.line.color.rgb = RGBColor.from_string(HEX['a1'])
s_.format.line.width = Pt(2.25)
s_.marker.style = XL_MARKER_STYLE.CIRCLE
s_.marker.size = 9
s_.marker.format.fill.solid()
s_.marker.format.fill.fore_color.rgb = RGBColor.from_string(HEX['a1'])
s_.marker.format.line.color.rgb = RGBColor.from_string(HEX['a1'])
for i, t in enumerate(N['tsne_iter']):
    pt = s_.points[i]
    if t['it'] == 500:                      # the chosen point: larger, accent colour
        pt.marker.style = XL_MARKER_STYLE.CIRCLE
        pt.marker.size = 13
        pt.marker.format.fill.solid()
        pt.marker.format.fill.fore_color.rgb = RGBColor.from_string(HEX['a2'])
        pt.marker.format.line.color.rgb = RGBColor.from_string(HEX['a2'])
    dl = pt.data_label
    dl.has_text_frame = True
    dl.text_frame.text = f"{t['it']} 次" + (f"（+{t['gain']:.2f}）" if t['it'] in (250, 500, 1000) else '')
    dl.position = {250: XL_LABEL_POSITION.RIGHT, 500: XL_LABEL_POSITION.ABOVE, 750: XL_LABEL_POSITION.BELOW,
                   1000: XL_LABEL_POSITION.ABOVE}.get(t['it'], XL_LABEL_POSITION.LEFT)   # 300-400: steep part
    r = dl.text_frame.paragraphs[0].runs[0]
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.color.rgb = RGBColor.from_string(HEX['dk1'])

stat(s7, 8.55, 1.45, 4.15, 1.3, f"{t500['cpu']:.2f} s",
     f"500 次在 PC 上一次 t-SNE（1000 次 {t1000['cpu']:.2f} s，時間約和迭代次數成正比）", name='Stat time')
stat(s7, 8.55, 2.85, 4.15, 1.3, f"{t500['diff']:+.2f}".replace('-', '−'),
     f"500 次 vs. 1000 次的自我校正準確率（個百分點），p = {t500['p']:.2f}，無顯著差異", name='Stat diff')
stat(s7, 8.55, 4.25, 4.15, 1.3, '≤ 400 次',
     f"顯著變差（400 次 {t400['diff']:+.2f}，p = {t400['p']:.3f}）；250 次增益只剩 +{t250['gain']:.2f}".replace('-', '−'),
     dark=True, name='Stat floor')
card(s7, 0.6, 5.7, 12.1, 0.8, T.TEXT_2, name='Callout card')
text(s7, 0.85, 5.7, 11.6, 0.8,
     [[(f"t-SNE 迭代 1000 → 500 次：PC 上時間減半（{t1000['cpu']:.2f} → {t500['cpu']:.2f} s），"
        f"增益 +{t1000['gain']:.2f} → +{t500['gain']:.2f}", {'color': T.BACKGROUND_1})],
      [('→ MCU 上預期也大致減半，但仍要 C 版 t-SNE 上板實測；500 次以下不建議', {'color': T.ACCENT_2, 'bold': True})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE, name='Callout text')
text(s7, 0.6, 6.58, 12.1, 0.4,
     'Docker、20 人 × 11 block × 3 seed，100 棵、深度 10、int16、buffer 375 筆 int16、新樹 32 葉；只改 sklearn TSNE 的 max_iter。'
     f"配對檢定：seed 平均後 20 人的 Wilcoxon，對照 1000 次。時間：PC 單執行緒，{t500['subjects']} 位受試者平均，不是 MCU 的時間。",
     size=11, color=T.ACCENT_5, name='Footnote')
s7.shapes._spTree.append(copy.deepcopy(cover_src._element))   # the user's footer cover, on top
ns7 = s7.notes_slide
if ns7.notes_placeholder is None:
    ns7.shapes._spTree.append(copy.deepcopy(s6.notes_slide.notes_placeholder._element))
ns7.notes_text_frame.text = (
    '上一頁看到 t-SNE 每次都跑滿 1000 次迭代，所以我把迭代次數從 250 到 1000 都跑了一遍，其他設定和 256 KB 以下的版本一樣。'
    f"500 次時 PC 上的時間從 {t1000['cpu']:.2f} 秒降到 {t500['cpu']:.2f} 秒，大約減半；準確率差 {t500['diff']:.2f} 個百分點，"
    f"配對檢定 p = {t500['p']:.2f}，沒有顯著差異。但 20 人裡有 {t500['worse']} 人略差，所以我說的是差異小於 seed 之間的變動，不是完全無損。"
    f"400 次以下就顯著變差，250 次幾乎沒有增益（+{t250['gain']:.2f}），因為 sklearn 的前 250 次是 early exaggeration 階段，"
    '嵌入還沒收斂。這些都是 PC 的時間，MCU 上預期也大致和迭代次數成正比，但要等 C 版 t-SNE 上板才知道實際秒數。')

# ------------------------------------------------------------------ summary: add the result
_, ss = find_slide('前置結果總結')
done = named(ss, 'Done list').text_frame
last = done.paragraphs[-1]
new_p = copy.deepcopy(last._p)
last._p.addnext(new_p)
p_new = done.paragraphs[-1]
diff500 = f"{t500['diff']:+.2f}".replace('-', '−')
set_para(p_new, f'• 運算：t-SNE 迭代減到 500 次，PC 上時間減半，準確率無顯著差異（{diff500}）', '• 記憶體')
for r_ in p_new.runs:
    r_.font.bold = False

# ------------------------------------------------------------------ page references: results are now slides 11–18
for sl in prs.slides:
    for sh in sl.shapes:
        if sh.has_text_frame:
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if '第 11–17 頁' in r.text:
                        r.text = r.text.replace('第 11–17 頁', '第 11–18 頁')
    if sl.has_notes_slide and '第 11 到 17 頁' in sl.notes_slide.notes_text_frame.text:
        for p in sl.notes_slide.notes_text_frame.paragraphs:
            for r in p.runs:
                r.text = r.text.replace('第 11 到 17 頁', '第 11 到 18 頁')

# ------------------------------------------------------------------ order: ⑦ right after ⑥
ids = prs.slides._sldIdLst
el = list(ids)[-1]
ids.remove(el)
ids.insert(i6 + 1, el)
for pos, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(pos)
left = [sl for sl in prs.slides for sh in sl.shapes if sh.has_text_frame and '11–17' in sh.text_frame.text]
assert not left, 'page reference split across runs'
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
