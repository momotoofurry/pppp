"""v8 = (user-edited v6 -> build7.py) + 前置結果⑧ (the whole self-calibration in C, PC-verified),
前置結果⑨ (Cortex-M7 build: linker-measured RAM) and 前置結果⑩ (two-day demo recording, 1 subject) right after ⑦;
⑥'s MCU card points to ⑧ / ⑨, the summary slide gets the C results, page references 11–18 -> 11–21.
usage: python build8.py v7_from_user_v6.pptx out.pptx nums6.json
"""
import copy
import json
import sys

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
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
    if expect:
        assert ''.join(r.text for r in p.runs).startswith(expect), (p.runs[0].text[:40], expect)
    p.runs[0].text = text_
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)


def named(slide, name):
    return [sh for sh in slide.shapes if sh.name == name][0]


def neg(v, fmt='+.2f'):
    return format(v, fmt).replace('-', '−')


def new_slide(like, title):
    title_src = [sh for sh in like.shapes if sh.has_text_frame and sh.text_frame.text.startswith('前置結果')][0]
    num_src = [sh for sh in like.shapes if sh.is_placeholder and sh.placeholder_format.type == 13][0]
    s = prs.slides.add_slide(like.slide_layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    s.shapes._spTree.append(copy.deepcopy(title_src._element))
    tr = s.shapes[-1].text_frame.paragraphs[0].runs
    tr[0].text = title
    for r in tr[1:]:
        r.text = ''
    s.shapes._spTree.append(copy.deepcopy(num_src._element))
    return s


def finish(s, like, notes):
    s.shapes._spTree.append(copy.deepcopy([sh for sh in like.shapes if sh.name.startswith('Rectangle')][0]._element))
    ns = s.notes_slide
    if ns.notes_placeholder is None:
        ns.shapes._spTree.append(copy.deepcopy(like.notes_slide.notes_placeholder._element))
    ns.notes_text_frame.text = notes


def style_chart(ch, title):
    ch.font.size = Pt(12)
    ch.font.color.rgb = RGBColor.from_string(HEX['dk1'])
    ch.has_title = True
    ch.chart_title.text_frame.text = title
    ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
    ch.chart_title.text_frame.paragraphs[0].runs[0].font.bold = True


C = {r['variant']: r for r in N['c_impl']}
ref = C['sklearn (reference), 500 it']
fw = C['C firmware logic (selfcal.c, end to end), 500 it']
feat = C['upstream pipeline on C features, 500 it']
c_rows = [r for r in N['c_impl'] if r['p'] is not None and '1000' not in r['variant']]
n_sig = sum(r['p'] < 0.05 for r in c_rows)
A_full, A_sc = N['arm']['full'], N['arm']['selfcal']
mis = N['feat_mismatch']
same, nblk = N['feat_oneshot_same_blocks']
t500 = N['tsne_c_time']['500']

# ------------------------------------------------------------------ 前置結果⑥: the MCU card points to ⑧ / ⑨
i6, s6 = find_slide('前置結果⑥')
set_para(named(s6, 'Stat mcu label').text_frame.paragraphs[0],
         'C 版 t-SNE 和整個自我校正已寫好、編譯好（第 18–19 頁）；cycle 數等板子實測', '要用 C 實作')
i7, s7 = find_slide('前置結果⑦')

# ------------------------------------------------------------------ 前置結果⑧: everything in C, same accuracy
s8 = new_slide(s7, '前置結果⑧：整條自我校正改用 C，準確率和 sklearn 相同')
labels = {'sklearn (reference), 500 it': 'sklearn（對照）', 'C t-SNE, 500 it': 'C 版 t-SNE',
          'C t-SNE + C K-Means, 500 it': '＋C 版 K-Means', 'C trees, 500 it': 'C 版建樹',
          'all C (Python loop), 500 it': '以上全部 C', 'C firmware logic (selfcal.c, end to end), 500 it': 'C 韌體邏輯（端到端）',
          'upstream pipeline on C features, 500 it': 'C 版特徵擷取'}
order = list(labels)[::-1]                       # bar charts draw the first category at the bottom
cd = CategoryChartData()
cd.categories = [labels[v] for v in order]
cd.add_series('自我校正準確率（%）', [C[v]['acc'] for v in order])
gf = s8.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.45), Inches(7.7), Inches(4.1), cd)
gf.name = 'Chart C variants'
ch = gf.chart
style_chart(ch, '自我校正後準確率（%）：用 C 取代各段 vs. sklearn')
ch.has_legend = False
pl = ch.plots[0]
pl.gap_width = 45
pl.has_data_labels = True
pl.data_labels.number_format, pl.data_labels.number_format_is_linked = '0.00', False
pl.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
pl.data_labels.font.size = Pt(12)
pl.data_labels.font.bold = True
va = ch.value_axis
va.minimum_scale, va.maximum_scale, va.major_unit = 82.0, 84.0, 0.5
va.tick_labels.number_format, va.tick_labels.number_format_is_linked = '0.0', False
va.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
va.format.line.fill.background()
ch.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
for i, v in enumerate(order):
    pt = pl.series[0].points[i]
    pt.format.fill.solid()
    col = HEX['a5'] if v.startswith('sklearn') else HEX['a2'] if v.startswith('C firmware') else HEX['a1']
    pt.format.fill.fore_color.rgb = RGBColor.from_string(col)
stat(s8, 8.55, 1.45, 4.15, 1.3, f"{fw['acc']:.2f}%",
     f"C 韌體邏輯端到端（sklearn {ref['acc']:.2f}%，差 {neg(fw['diff'])}，p = {fw['p']:.2f}）", name='Stat firmware')
stat(s8, 8.55, 2.85, 4.15, 1.3, f'{n_sig} / {len(c_rows)} 項',
     '有顯著差異（每一段單獨換成 C，和全部換成 C，都和 sklearn 配對檢定）', name='Stat sig')
stat(s8, 8.55, 4.25, 4.15, 1.3, f'{same} / {nblk}',
     f"個 block 的 one-shot 準確率在 C 版特徵下完全相同（自我校正 {feat['acc']:.2f}%）", dark=True, name='Stat feat')
card(s8, 0.6, 5.7, 12.1, 0.8, T.TEXT_2, name='Callout card')
text(s8, 0.85, 5.7, 11.6, 0.8,
     [[('特徵擷取、t-SNE、K-Means、建樹、整個自我校正迴圈都用 C 寫好（靜態記憶體、int16 資料），PC 上逐段驗證',
        {'color': T.BACKGROUND_1})],
      [('→ 上板前能做的都做了：板子到了只剩量時間、確認板上預測', {'color': T.ACCENT_2, 'bold': True})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE, name='Callout text')
text(s8, 0.6, 6.58, 12.1, 0.4,
     'Docker、20 人 × 11 block × 3 seed；100 棵、深度 10、int16、buffer 375 筆 int16、新樹 32 葉、t-SNE 500 次。配對檢定：seed 平均後 20 人'
     f"的 Wilcoxon。C 版特徵：每種特徵 {N['feat_values']:,} 個值中，SSC／ZC／MDF／PKF 只有 {mis['ssc']}／{mis['zc']}／{mis['mdf']}／{mis['pkf']} 個不同。",
     size=11, color=T.ACCENT_5, name='Footnote')
finish(s8, s7,
       '這一頁是上板前的主要工作：把整條自我校正都用 C 寫好，而且全部用靜態記憶體，資料都是 int16，跟 MCU 上一樣。'
       '每一段都在 PC 上用 ctypes 接回原本的 Python 流程，和 sklearn 做配對比較：t-SNE、K-Means、建樹、全部一起，都沒有顯著差異。'
       f"最下面兩條最重要：整個韌體邏輯用 C 從頭跑到尾是 {fw['acc']:.2f}%，sklearn 是 {ref['acc']:.2f}%，p = {fw['p']:.2f}；"
       f"特徵擷取換成 C 版之後，{nblk} 個 block 裡有 {same} 個的 one-shot 準確率完全一樣。"
       f"另外，C 版 t-SNE 在 PC 上一次 {t500['c']:.2f} 秒，sklearn {t500['sk']:.2f} 秒，但這是 PC 的時間，MCU 上的時間要上板量。")

# ------------------------------------------------------------------ 前置結果⑨: Cortex-M7 build, measured RAM
s9 = new_slide(s7, f"前置結果⑨：M7 編譯實測 RAM {A_full['total_KB']:.0f} KB，在預算內")


def parts(a):
    m = a['bss_modules']
    other = m['selfcal'] - a['buf'] - a['cal'] - a['trees'] + m.get('main_selfcal', 0)
    return [('buffer 375 筆＋calibration（int16）', a['buf'] + a['cal']), ('t-SNE', m['tsne']),
            ('RAM 樹（50 × ≤ 32 葉）', a['trees']), ('建樹＋K-Means＋工作陣列', m['rf_train'] + m['kmeans'] + other),
            ('特徵擷取', m.get('features', 0)), ('stack＋.data', a['stack'] + a['data'])]


cd9 = CategoryChartData()
cd9.categories = ['只有自我校正', '完整管線（含特徵擷取）']
P_sc, P_full = parts(A_sc), parts(A_full)
for (name, v1), (_, v2) in zip(P_sc, P_full):
    cd9.add_series(name, [v1 / 1024, v2 / 1024])
gf9 = s9.shapes.add_chart(XL_CHART_TYPE.BAR_STACKED, Inches(0.6), Inches(1.45), Inches(7.7), Inches(4.1), cd9)
gf9.name = 'Chart RAM'
ch9 = gf9.chart
style_chart(ch9, 'RAM 組成（KB，arm-none-eabi-gcc 連結後實測）')
ch9.has_legend = True
ch9.legend.position = XL_LEGEND_POSITION.BOTTOM
ch9.legend.include_in_layout = False
ch9.legend.font.size = Pt(11)
pl9 = ch9.plots[0]
pl9.gap_width = 55
pl9.overlap = 100
va9 = ch9.value_axis
va9.minimum_scale, va9.maximum_scale, va9.major_unit = 0, 256, 64
va9.tick_labels.number_format, va9.tick_labels.number_format_is_linked = '0', False
va9.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
ch9.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
cols = [HEX['dk2'], HEX['a1'], HEX['a2'], HEX['a5'], HEX['a6'], HEX['lt2']]
for s_, col in zip(pl9.series, cols):
    s_.format.fill.solid()
    s_.format.fill.fore_color.rgb = RGBColor.from_string(col)
    s_.format.line.color.rgb = RGBColor.from_string('FFFFFF')
stat(s9, 8.55, 1.45, 4.15, 1.3, f"{A_full['total_KB']:.1f} KB",
     f"完整管線的 RAM（只有自我校正 {A_sc['total_KB']:.1f} KB；預算 256 KB）", name='Stat ram')
stat(s9, 8.55, 2.85, 4.15, 1.3, f"{A_sc['total_KB']:.0f} vs 219",
     '自我校正 RAM：實測 vs 之前的估算（KB），相差約 2%，估算方法可信', name='Stat est')
stat(s9, 8.55, 4.25, 4.15, 1.3, 'MCU 時間：待上板',
     '韌體已包好 DWT cycle 計數（每筆推論、每次自我校正、每個特徵）', dark=True, big_size=24, name='Stat time')
card(s9, 0.6, 5.7, 12.1, 0.8, T.TEXT_2, name='Callout card')
text(s9, 0.85, 5.7, 11.6, 0.8,
     [[(f"之前的 RAM 都是估算；現在是 linker 實測：全部靜態配置，{A_full['total_KB']:.0f} KB 放進 512 KB 的 AXI SRAM 還有餘裕",
        {'color': T.BACKGROUND_1})],
      [('→ RQ2 的記憶體預算已有實測支持；RQ3（時間、功耗）要等板子', {'color': T.ACCENT_2, 'bold': True})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE, name='Callout text')
text(s9, 0.6, 6.58, 12.1, 0.4,
     f"arm-none-eabi-gcc 10.3.1，-Os，Cortex-M7（FPv5-D16）；.bss 在 AXI SRAM，stack 在 DTCM；stack 為呼叫圖上最深路徑。Flash {A_full['flash_KB']:.0f} KB"
     '（含 88 KB 模型；另含 64 KB 原始 EMG、9.6 KB calibration 範例資料，正式版不需要）。一次性模型每次 calibration 只寫一次 Flash。',
     size=11, color=T.ACCENT_5, name='Footnote')
finish(s9, s7,
       '之前所有 RAM 的數字都是依設計算的估算。這一頁是實際交叉編譯成 Cortex-M7 韌體之後，由 linker 量出來的數字。'
       f"只有自我校正是 {A_sc['total_KB']:.1f} KB，之前估算 219 KB，只差約 2%；再加上特徵擷取的完整管線是 {A_full['total_KB']:.1f} KB，"
       '還在 256 KB 以內。最大的兩塊是 buffer 和 t-SNE。全部都是靜態配置，沒有 malloc，所以不會有執行時才發現記憶體不夠的問題。'
       '一次性模型在 calibration 時寫進 Flash 一次，自我校正的新樹都放在 RAM，所以不會一直寫 Flash。'
       '時間的部分我沒有估數字：韌體裡已經用 DWT 計數器包好，板子到了燒進去就能量。')

# ------------------------------------------------------------------ 前置結果⑩: two-day demo, 1 subject
D = {r['variant']: r for r in N['demo']}
d_full, d_fw = D['full model (paper), sklearn'], D['MCU setting, C firmware logic']
B = N['demo_blocks']
s10 = new_slide(s7, f"前置結果⑩：跨兩天 demo，第 2 天拉回 {D['MCU setting, C firmware logic']['tail_sc']:.0f}%")
cd10 = CategoryChartData()
cd10.categories = [str(b) for b in range(len(B['mcu_c']['oneshot']))]
cd10.add_series('固定模型（one-shot，MCU 設定）', B['mcu_c']['oneshot'])
cd10.add_series('自我校正：完整模型（論文設定，sklearn）', B['full']['selfcal'])
cd10.add_series('自我校正：MCU 設定，C 韌體邏輯', B['mcu_c']['selfcal'])
gf10 = s10.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.6), Inches(1.45), Inches(7.7), Inches(4.1), cd10)
gf10.name = 'Chart demo'
ch10 = gf10.chart
style_chart(ch10, '每個 block 的準確率（%，10 個 seed 平均）')
ch10.has_legend = True
ch10.legend.position = XL_LEGEND_POSITION.BOTTOM
ch10.legend.include_in_layout = False
ch10.legend.font.size = Pt(11)
va10 = ch10.value_axis
va10.minimum_scale, va10.maximum_scale, va10.major_unit = 60, 100, 10
va10.tick_labels.number_format, va10.tick_labels.number_format_is_linked = '0', False
va10.major_gridlines.format.line.color.rgb = RGBColor.from_string(HEX['lt2'])
ch10.category_axis.format.line.color.rgb = RGBColor.from_string(HEX['a6'])
ch10.category_axis.has_title = True
ch10.category_axis.axis_title.text_frame.text = 'block（依時間順序，跨兩天）'
ch10.category_axis.axis_title.text_frame.paragraphs[0].runs[0].font.size = Pt(11)
ch10.category_axis.axis_title.text_frame.paragraphs[0].runs[0].font.bold = False
for s_, col, w in zip(ch10.plots[0].series, [HEX['a5'], HEX['a6'], HEX['a2']], [2.0, 2.0, 2.75]):
    s_.smooth = False
    s_.format.line.color.rgb = RGBColor.from_string(col)
    s_.format.line.width = Pt(w)
    s_.marker.style = XL_MARKER_STYLE.CIRCLE
    s_.marker.size = 7
    s_.marker.format.fill.solid()
    s_.marker.format.fill.fore_color.rgb = RGBColor.from_string(col)
    s_.marker.format.line.color.rgb = RGBColor.from_string(col)
stat(s10, 8.55, 1.45, 4.15, 1.3, f"{d_fw['tail_sc']:.1f}%",
     f"第 2 天後段（block 7–9）C 韌體自我校正；固定模型 {d_fw['tail_os']:.1f}%", name='Stat tail')
stat(s10, 8.55, 2.85, 4.15, 1.3, f"+{d_fw['gain']:.2f}",
     f"C 韌體邏輯的平均增益（{d_fw['oneshot']:.1f} → {d_fw['acc']:.1f}%）；完整模型 +{d_full['gain']:.2f}", name='Stat gain')
stat(s10, 8.55, 4.25, 4.15, 1.3, '只有 1 人',
     '趨勢一致，但不能當統計結論 → 正式實驗：每人兩天（RQ2）', dark=True, name='Stat n')
card(s10, 0.6, 5.7, 12.1, 0.8, T.TEXT_2, name='Callout card')
text(s10, 0.85, 5.7, 11.6, 0.8,
     [[('第 2 天固定模型掉到約 75%，記憶體預算內的 C 韌體邏輯把它拉回約 92%，和完整模型一樣', {'color': T.BACKGROUND_1})],
      [('→ 跨日的效果要在正式實驗中、在板子上驗證', {'color': T.ACCENT_2, 'bold': True})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE, name='Callout text')
text(s10, 0.6, 6.58, 12.1, 0.4,
     f"JNE 2025 的 demo 錄音（1 位受試者、10 個 block、跨兩天；上游的預訓練模型 model_pretrain.joblib），Docker，{B['mcu_c']['seeds']} 個 seed。"
     'MCU 設定：100 棵、深度 10、int16、buffer 375 筆 int16、新樹 32 葉、t-SNE 500 次。',
     size=11, color=T.ACCENT_5, name='Footnote')
finish(s10, s7,
       '這頁用作者公開的另一份資料：同一個人在兩天內錄了 10 個 block，可以看跨日的情況。'
       f"固定模型到了第 2 天後段只剩約 {d_fw['tail_os']:.0f}%；用 MCU 設定、而且是 C 韌體邏輯做自我校正，"
       f"可以拉回 {d_fw['tail_sc']:.0f}% 左右，整體增益 +{d_fw['gain']:.1f}，和完整模型的趨勢一樣。"
       '但這只有 1 個人，所以我只說趨勢一致，跨日的效果要靠正式實驗、每人兩天來驗證，這就是 RQ2。')

# ------------------------------------------------------------------ summary slide
_, ss = find_slide('前置結果總結')
done = named(ss, 'Done list').text_frame
paras = done.paragraphs
set_para(paras[1], '• 壓縮：100 棵、深度 10、int16 → Flash 88.1 KB、推論 RAM 552 B，自我校正只差 0.47 個百分點', '• 壓縮')
paras[2]._p.getparent().remove(paras[2]._p)                  # 推論 merged into 壓縮 (keeps six bullets)
paras = done.paragraphs
mem = [p for p in paras if ''.join(r.text for r in p.runs).startswith('• 記憶體')][0]
set_para(mem, f"• 記憶體：t-SNE＋375 筆 int16 buffer＋32 葉保住約 87% 增益；M7 實測 RAM {A_full['total_KB']:.0f} KB（含特徵）",
         '• 記憶體')
new_p = copy.deepcopy(paras[-1]._p)
paras[-1]._p.addnext(new_p)
set_para(done.paragraphs[-1], '• C 實作：特徵到自我校正全用 C（靜態記憶體），PC 上準確率不變', '• 運算')
for p_ in done.paragraphs:                                   # the edited bullets keep the list's regular weight
    for r_ in p_.runs:
        r_.font.bold = False
foot = [sh for sh in ss.shapes if sh.has_text_frame and sh.text_frame.text.startswith('PC 模擬為')][0]
set_para(foot.text_frame.paragraphs[0], 'PC 模擬為 20 人 × 11 block × 3 seed（Windows／Docker，各頁註明）；RAM 與 Flash 為 Cortex-M7 編譯後 linker 實測'
         '（第 19 頁之前的 RAM 為估算）；MCU 上的時間尚未量測。', 'PC 模擬為')
opn = named(ss, 'Open list').text_frame
set_para(opn.paragraphs[0], '• t-SNE＋重新訓練樹在 Cortex-M7 上的時間（韌體已備好，等板子）→ RQ3', '• t-SNE')

# ------------------------------------------------------------------ page references: results are now slides 11–21
for sl in prs.slides:
    for sh in sl.shapes:
        if sh.has_text_frame:
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    r.text = r.text.replace('第 11–18 頁', '第 11–21 頁')
    if sl.has_notes_slide:
        for p in sl.notes_slide.notes_text_frame.paragraphs:
            for r in p.runs:
                r.text = r.text.replace('第 11 到 18 頁', '第 11 到 21 頁')

# ------------------------------------------------------------------ order: ⑧ ⑨ ⑩ right after ⑦
ids = prs.slides._sldIdLst
new_els = list(ids)[-3:]
for el in new_els:
    ids.remove(el)
for k, el in enumerate(new_els):
    ids.insert(i7 + 1 + k, el)
for pos, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(pos)
left = [sl for sl in prs.slides for sh in sl.shapes if sh.has_text_frame and '11–18' in sh.text_frame.text]
assert not left, 'page reference split across runs'
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides), '| significant:', n_sig, 'of', len(c_rows))
