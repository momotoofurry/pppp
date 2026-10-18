"""Add the preliminary-results slides to 碩論題目討論_MOMO.pptx and update slides 15/16/18.

Numbers come from nums.json (pulled from ~/model/results) — nothing is typed in by hand except
values quoted from report.md that are not in those CSVs (paper ablation numbers).
usage: python build.py orig.pptx out.pptx nums.json
"""
import copy
import json
import sys

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION, XL_TICK_LABEL_POSITION
from pptx.enum.dml import MSO_THEME_COLOR as T, MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

src, dst, nums_path = sys.argv[1:4]
N = json.load(open(nums_path, encoding='utf8'))
prs = Presentation(src)
CONTENT = [l for l in prs.slide_layouts if l.name == 'CONTENT'][0]
# hex values of the deck theme, for chart parts that only take RGB
HEX = dict(dk1='1F2A30', dk2='0B3C49', lt2='E1EEF1', a1='1F7A8C', a2='F2A541', a5='5B6770', a6='C9D6DA')

slide_num_src = [sh for sh in prs.slides[5].shapes if sh.name.startswith('Slide Number')][0]
# the CONTENT layout has no title placeholder: every slide carries its own title shape (ph type=title)
title_src = [sh for sh in prs.slides[5].shapes if sh.is_placeholder and sh.placeholder_format.type == 1][0]


def text(slide, x, y, w, h, runs, size=14, color=T.TEXT_1, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, name=None):
    """runs: str, or list of paragraphs; a paragraph is str or list of (text, {size,color,bold})."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
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
    if name:
        s.name = name
    return s


def stat(slide, x, y, w, h, big, label, dark=False, big_size=36, name=''):
    card(slide, x, y, w, h, T.TEXT_2 if dark else T.BACKGROUND_2, name=f'{name} card')
    text(slide, x + 0.25, y + 0.18, w - 0.5, 0.7, big, size=big_size, bold=True,
         color=T.ACCENT_2 if dark else T.TEXT_2, name=f'{name} value')
    text(slide, x + 0.25, y + 0.18 + big_size / 72 * 1.25, w - 0.5, h - 0.3 - big_size / 72 * 1.25, label,
         size=13, color=T.BACKGROUND_1 if dark else T.TEXT_1, name=f'{name} label')


def new_slide(title, notes):
    s = prs.slides.add_slide(CONTENT)
    s.shapes._spTree.append(copy.deepcopy(title_src._element))
    tr = s.shapes[-1].text_frame.paragraphs[0].runs
    tr[0].text = title
    for r in tr[1:]:
        r.text = ''
    s.shapes._spTree.append(copy.deepcopy(slide_num_src._element))   # page-number field, as on every slide
    s.notes_slide.notes_text_frame.text = notes
    return s


def style_chart_text(chart, size=12):
    chart.font.size = Pt(size)
    chart.font.color.rgb = RGBColor.from_string(HEX['dk1'])


def footnote(slide, y, s):
    text(slide, 0.6, y, 12.1, 0.45, s, size=11, color=T.ACCENT_5, name='Footnote')


# ---------------------------------------------------------------- slide A: reproduction
allm = N['all']
sA = new_slide('前置結果①：PC 基準已重現，數字和論文一致',
               '先報告已經完成的前置研究。用作者在 GitHub 公開的程式和 arm_position 資料（20 人、5 種手臂姿勢）'
               '加上作者給的 66 人預訓練模型，重現出自我校正 RF 84.63%，論文是 84.6%；所有能對照的數字差距都在 1 個百分點內。'
               '右圖是 11 個 testing block 的平均準確率：固定的 one-shot 模型隨姿勢變化往下掉，自我校正會慢慢拉回來。'
               '另外讀程式碼時發現 4 處程式和論文描述不一樣，之後移植到 MCU 時要照程式的行為做。')
stat(sA, 0.6, 1.45, 3.6, 1.45, f"{allm['self-calibrating RF']:.2f}%",
     '自我校正 RF（論文 84.6%）', dark=True, name='Stat selfcal')
stat(sA, 0.6, 3.05, 3.6, 1.45, f"{allm['fixed: one-shot RF']:.2f}%", '固定的 one-shot 模型（不再更新）',
     name='Stat oneshot')
stat(sA, 0.6, 4.65, 3.6, 1.45, f"{N['n_better']} / 20 人", '自我校正後準確率比固定模型高', name='Stat subjects')
cd = CategoryChartData()
cd.categories = [str(i + 1) for i in range(11)]
series = [('自我校正 RF', 'self-calibrating RF', HEX['dk2'], None),
          ('固定 one-shot', 'fixed: one-shot RF', HEX['a2'], None),
          ('LDA（只用校正資料）', 'LDA (calib only)', HEX['a5'], MSO_LINE_DASH_STYLE.DASH)]
for label, key, _, _ in series:
    cd.add_series(label, N['blocks'][key])
gf = sA.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(4.5), Inches(1.45), Inches(8.2), Inches(4.65), cd)
gf.name = 'Chart blocks'
ch = gf.chart
style_chart_text(ch)
ch.has_title = True
ch.chart_title.text_frame.text = '各 testing block 的平均準確率（%）'
ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
ch.chart_title.text_frame.paragraphs[0].runs[0].font.bold = True
ch.has_legend = True
ch.legend.position = XL_LEGEND_POSITION.BOTTOM
ch.legend.include_in_layout = False
va = ch.value_axis
va.minimum_scale, va.maximum_scale, va.major_unit = 65, 90, 5
va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
va.format.line.fill.background()
ca = ch.category_axis
ca.has_title = True
ca.axis_title.text_frame.text = 'testing block（每個 block 換一種手臂姿勢）'
ca.axis_title.text_frame.paragraphs[0].runs[0].font.size = Pt(11)
ca.axis_title.text_frame.paragraphs[0].runs[0].font.bold = False
ca.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
for s, (_, _, color, dash) in zip(ch.plots[0].series, series):
    s.smooth = False
    s.format.line.color.rgb = RGBColor.from_string(color)
    s.format.line.width = Pt(2.25 if dash is None else 1.5)
    if dash:
        s.format.line.dash_style = dash
    s.marker.size = 6
    s.marker.format.fill.solid()
    s.marker.format.fill.fore_color.rgb = RGBColor.from_string(color)
    s.marker.format.line.color.rgb = RGBColor.from_string(color)
footnote(sA, 6.3, '資料：作者 GitHub 公開的 arm_position（20 人 × 11 block × 3 seed）＋ 66 人預訓練模型。'
               '讀程式碼另發現 4 處和論文描述不一致：剪枝條件（≤ vs >）、偽標籤初始化用的模型、< 與 <= 比較方向、bootstrap 比例（7% vs 1–2%）。')

# ---------------------------------------------------------------- slide B: compression
sel = {r[0]: r for r in N['selfcal']}
arm = {(r[0], r[1]): r for r in N['arm']}
full = sel['N400_dnone_float64'][2]
sB = new_slide('前置結果②：壓縮到 88 KB，自我校正後只差 0.47 個百分點',
               '把模型壓縮後，在同樣的資料上重跑 one-shot 和自我校正。推薦設定是 100 棵樹、深度 10、門檻用 int16，'
               '實際編譯後 Flash 88.1 KB，自我校正後 83.96%，和完整模型 84.43% 只差 0.47 個百分點。'
               'int16 量化幾乎沒有損失；而且不論模型多小，自我校正都能帶來 4 到 5 個百分點的提升。')
rows = [('400 棵、深度不限、float32（論文原樣）', f"{arm[('full_f32', 'table')][2]:.1f} KB", 'N400_dnone_float32'),
        ('400 棵、深度 10、int16', f"{arm[('d10_n400_i16', 'table')][2]:.1f} KB", 'N400_d10_int16'),
        ('100 棵、深度 10、int16（推薦）', f"{arm[('d10_n100_i16', 'table')][2]:.1f} KB", 'N100_d10_int16'),
        ('50 棵、深度 8、int16', '約 23 KB *', 'N50_d8_int16'),
        ('20 棵、深度 10、int16', '約 17 KB *', 'N20_d10_int16')]
hdr = ['設定（樹數、深度、門檻精度）', 'Flash', 'one-shot', '自我校正後', '和完整模型比']
tbs = sB.shapes.add_table(len(rows) + 1, 5, Inches(0.6), Inches(1.45), Inches(12.1), Inches(0.42 * 6))
tbs.name = 'Table configs'
tb = tbs.table
for i, wdt in enumerate([4.3, 1.9, 1.9, 2.0, 2.0]):
    tb.columns[i].width = Inches(wdt)
oneshot_override = {'N50_d8_int16': 78.77}   # report.md / summary use 78.77 (78.765 rounded half up)


def cell(c, s, fill, color, bold=False, align=PP_ALIGN.LEFT):
    c.text = s
    c.fill.solid()
    c.fill.fore_color.theme_color = fill
    c.vertical_anchor = MSO_ANCHOR.MIDDLE
    c.margin_left = c.margin_right = Inches(0.12)
    p = c.text_frame.paragraphs[0]
    p.alignment = align
    r = p.runs[0]
    r.font.size = Pt(14)
    r.font.bold = bold
    r.font.color.theme_color = color


for j, h in enumerate(hdr):
    cell(tb.cell(0, j), h, T.TEXT_2, T.BACKGROUND_1, True, PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER)
for i, (name, flash, key) in enumerate(rows, start=1):
    _, os_, sc, _ = sel[key]
    os_ = oneshot_override.get(key, os_)
    rec = key == 'N100_d10_int16'
    vals = [name, flash, f'{os_:.2f}%', f'{sc:.2f}%', f'{sc - full:+.2f}'.replace('-', '−')]
    for j, v in enumerate(vals):
        cell(tb.cell(i, j), v, T.BACKGROUND_2 if rec else T.BACKGROUND_1, T.TEXT_2 if rec else T.TEXT_1,
             bold=rec, align=PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER)
for r_ in tb.rows:
    r_.height = Inches(0.42)
stat(sB, 0.6, 4.3, 3.9, 1.65, '≤ 0.02', 'int16 定點量化的準確率損失（個百分點）', name='Stat int16')
stat(sB, 4.7, 4.3, 3.9, 1.65, '−36%', '深度 10 的模型大小；準確率和不限深度差 ≤ 0.1 個百分點', name='Stat depth')
stat(sB, 8.8, 4.3, 3.9, 1.65, '+4.3～+4.8', '自我校正帶來的增益（個百分點）；模型大小不影響', dark=True, name='Stat gain')
footnote(sB, 6.2, f'完整模型 = 400 棵、深度不限、float64，自我校正 {full:.2f}%。Flash：arm-none-eabi-gcc -Os 實際編譯的 text + data；* 依儲存格式計算，未實際編譯。'
               '準確率：20 人 × 11 block × 3 seed（5 seed 的 one-shot 掃描和此表差 ≤ 0.1 個百分點）。')

# ---------------------------------------------------------------- slide C: RAM bottleneck
R = N['ram_KB']
sC = new_slide('前置結果③：推論只要 552 B，瓶頸在自我校正的 RAM',
               '推論本身很省：88 KB Flash、552 B RAM，C 版和 Python 版預測 100% 一致。真正的問題是自我校正：'
               '照論文原樣做（float32 buffer 加 t-SNE）估計要 1.2 MB，連整顆晶片的 SRAM 都放不下；光 t-SNE 就要 401 KB。'
               '放得進 512 KB 的只有不做 t-SNE 的 C 和 E，但論文的 ablation 裡它們是準確率最低的版本。'
               '所以想把論文收斂成：在固定 RAM 預算內，用低記憶體的偽標籤方法保住 t-SNE 的增益。也想請老師決定 RAM 預算要訂多少。'
               '注意 RAM 是依設計計算的估算，C、D、E 的準確率是論文完整模型的數字，壓縮版還沒量。')
cats = [('A', '論文原樣、t-SNE', '84.6%'),
        ('D', '論文原樣、不分群', '82.7%†'),
        ('B', 'int16・100 棵、t-SNE', '83.96%'),
        ('C', 'int16・100 棵、只用 K-Means', '81.0%†'),
        ('E', 'int16・100 棵、不分群', '82.7%†')]
cd = CategoryChartData()
cd.categories = [f'{k}  {d}｜{acc}' for k, d, acc in reversed(cats)]   # bar charts draw the first category at the bottom
cd.add_series('RAM（KB）', [R[k] for k, _, _ in reversed(cats)])
gf = sC.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.45), Inches(7.7), Inches(4.1), cd)
gf.name = 'Chart RAM'
ch = gf.chart
style_chart_text(ch, 12)
ch.has_title = True
ch.chart_title.text_frame.text = '自我校正需要的 RAM（KB，估算）｜格線 512 KB = AXI SRAM'
ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
ch.chart_title.text_frame.paragraphs[0].runs[0].font.bold = True
ch.has_legend = False
pl = ch.plots[0]
pl.gap_width = 60
pl.has_data_labels = True
dl = pl.data_labels
dl.number_format = '0" KB"'
dl.number_format_is_linked = False
dl.position = XL_LABEL_POSITION.INSIDE_END
dl.font.size = Pt(12)
dl.font.bold = True
va = ch.value_axis
va.minimum_scale, va.maximum_scale, va.major_unit = 0, 1536, 512
va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['a5'])
va.major_gridlines.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
va.format.line.fill.background()
va.tick_label_position = XL_TICK_LABEL_POSITION.LOW
ch.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
for i, (k, _, _) in enumerate(reversed(cats)):
    pt = pl.series[0].points[i]
    pt.format.fill.solid()
    pt.format.fill.fore_color.rgb = RGBColor.from_string(HEX['a1'] if R[k] <= 512 else HEX['a6'])
    pt.data_label.font.size = Pt(12)
    pt.data_label.font.bold = True
    pt.data_label.font.color.rgb = RGBColor.from_string('FFFFFF' if R[k] <= 512 else HEX['dk2'])
    pt.data_label.position = XL_LABEL_POSITION.INSIDE_END
    # a per-point label drops the series number format: give it its own <c:numFmt> right after <c:idx>
    dlbl = pt.data_label._dLbl
    nf = dlbl.makeelement('{http://schemas.openxmlformats.org/drawingml/2006/chart}numFmt',
                          {'formatCode': '0" KB"', 'sourceLinked': '0'})
    dlbl.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}idx').addnext(nf)
stat(sC, 8.55, 1.45, 4.15, 1.25, '552 B', '推論 RAM（實測；推薦設定 Flash 88.1 KB）', big_size=30, name='Stat infer')
stat(sC, 8.55, 2.85, 4.15, 1.25, f"{N['tsne_KB']:.0f} KB", 't-SNE 一項就要的 RAM（估算）', big_size=30, name='Stat tsne')
stat(sC, 8.55, 4.25, 4.15, 1.25, '512 KB', '最大連續 SRAM（AXI）；全晶片約 1 MB', big_size=30, dark=True, name='Stat axi')
card(sC, 0.6, 5.68, 12.1, 0.82, T.TEXT_2, name='Callout card')
text(sC, 0.85, 5.68, 11.6, 0.82,
     [[('放得進 512 KB 的只有 C、E，但它們在論文 ablation 裡準確率最低 → ', {'color': T.BACKGROUND_1}),
       ('研究問題：在 RAM 預算內保住 t-SNE 的增益', {'color': T.ACCENT_2, 'bold': True})],
      [('想請老師決定：RAM 預算訂 512 KB 還是 256 KB？', {'color': T.BACKGROUND_1, 'bold': True})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE, name='Callout text')
footnote(sC, 6.56, '論文原樣 = float32 buffer、400 棵、深度不限；t-SNE = t-SNE＋K-Means；RAM 為依設計計算的估算（附加樹用實測最大值）。'
               '準確率：A 為論文值（我們重現 84.63%），B 為我們實測，† 為論文 ablation（完整模型），壓縮版尚未量測。')

# ---------------------------------------------------------------- move new slides after slide 12
ids = prs.slides._sldIdLst
new = list(ids)[-3:]
for el in new:
    ids.remove(el)
for k, el in enumerate(new):
    ids.insert(12 + k, el)


def find_shape(pred):
    for s in prs.slides:
        for sh in s.shapes:
            if pred(sh):
                return s, sh
    raise SystemExit('shape not found')


# ---------------------------------------------------------------- slide 16 (now 19): equipment
s16, tbl = find_shape(lambda sh: sh.has_table and any('NUCLEO-H743ZI2' in c.text for c in sh.table.rows[1].cells))
c = [c for c in tbl.table.rows[1].cells if '1 MB RAM' in c.text][0]
run = [r for r in c.text_frame.paragraphs[0].runs if '1 MB RAM' in r.text][0]
run.text = run.text.replace('約 1 MB RAM、2 MB Flash', '1 MB RAM（最大連續 512 KB）、2 MB Flash')

# ---------------------------------------------------------------- slide 18 (now 21): next steps
s18, box = find_shape(lambda sh: sh.has_text_frame and '下載 Jiang' in sh.text_frame.text)
paras = box.text_frame.paragraphs
p2 = [p for p in paras if '下載 Jiang' in p.text][0]
p2.runs[0].text = '2　在 PC 上比較低記憶體偽標籤方法（不分群、K-Means、LDA 投影＋K-Means）的準確率與 RAM'
for r in p2.runs[1:]:
    r.text = ''
done = copy.deepcopy(paras[0]._p)
box.text_frame._txBody.insert(list(box.text_frame._txBody).index(paras[0]._p), done)
from pptx.text.text import _Paragraph   # noqa: E402
dp = _Paragraph(done, box.text_frame)
dp.runs[0].text = '✓ 已完成：PC 基準重現、模型壓縮、MCU 編譯（第 13–15 頁）'
for r in dp.runs[1:]:
    r.text = ''
dp.runs[0].font.color.theme_color = T.ACCENT_2

# ---------------------------------------------------------------- slide 15 (now 18): timeline progress
s15, _ = find_shape(lambda sh: sh.has_text_frame and sh.text_frame.text.startswith('時程規劃'))
for label, msg in [('1 PC 基準重現', '✓ 已完成'), ('2 方法模擬・預算分析', '進行中')]:
    row = [sh for sh in s15.shapes if sh.has_text_frame and sh.text_frame.text == label][0]
    bar = [sh for sh in s15.shapes if not sh.has_text_frame or sh.text_frame.text == ''
           if abs((sh.top + sh.height / 2) - (row.top + row.height / 2)) < Inches(0.05) and sh.width > Inches(0.3)][0]
    x = (bar.left + bar.width) / 914400 + 0.08
    text(s15, x, (row.top / 914400) + 0.07, 1.2, 0.26, msg, size=11, bold=True,
         color=T.ACCENT_2 if msg.startswith('✓') else T.TEXT_2, name=f'Progress {label[:1]}')

# cached text of the copied page-number fields (PowerPoint recomputes them; other viewers may not)
for pos, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}fld'):
        if f.get('type') == 'slidenum':
            f.find('{http://schemas.openxmlformats.org/drawingml/2006/main}t').text = str(pos)

prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
