"""v9 = v8 (unchanged since build8.py, md5 27d8eb68...) + the converged direction:
embedded label-free self-calibration stays the core; the Kinova Gen3 discrete-command task (gripper close /
open, 2-3 preset positions, low speed) becomes the main closed-loop evaluation, with the STM32 deciding and a
thin PC Python Kortex bridge only forwarding; rejection of low-confidence commands; Zanghieri PCA alignment
[19] as a baseline; elderly group -> future work, int8 CNN -> optional, no custom EMG front end.
RQ2 / RQ3, novelty contribution 3, the summary, experiment design and equipment slides are updated; three
new slides: scope (after the RQs), closed-loop architecture (after the system figure), one-year plan (after
the flow figure).
usage: python build9.py v8.pptx out.pptx nums6.json
"""
import copy
import json
import re
import sys

from pptx import Presentation
from pptx.enum.dml import MSO_THEME_COLOR as T
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

src, dst, nums_path = sys.argv[1:4]
N = json.load(open(nums_path, encoding='utf8'))
prs = Presentation(src)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
RAM_FULL = N['arm']['full']['total_KB']
IT500 = [r for r in N['tsne_iter'] if r['it'] == 500][0]
IT_REL = IT500['rel']
IT_DIFF = format(IT500['diff'], '+.2f').replace('-', '−')


def find_slide(prefix):
    for i, s in enumerate(prs.slides):
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.startswith(prefix):
                return i, s
    raise SystemExit(f'slide not found: {prefix}')


def named(slide, name):
    return [sh for sh in slide.shapes if sh.name == name][0]


def set_para(p, text_, expect=None):
    full = ''.join(r.text for r in p.runs)
    if expect:
        assert full.startswith(expect), (full[:40], expect)
    p.runs[0].text = text_
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)


def set_paras(tf, texts, expect=None):
    """Keep the first len(texts) paragraphs' formatting (copying the last one if more are needed)."""
    ps = tf.paragraphs
    if expect:
        assert tf.text.startswith(expect), (tf.text[:40], expect)
    while len(tf.paragraphs) < len(texts):
        tf._txBody.append(copy.deepcopy(tf.paragraphs[-1]._p))
    for p in list(tf.paragraphs)[len(texts):]:
        p._p.getparent().remove(p._p)
    for p, t in zip(tf.paragraphs, texts):
        set_para(p, t)


def text(slide, x, y, w, h, paras, size=14, color=T.TEXT_1, bold=False, anchor=MSO_ANCHOR.TOP, name=None,
         align=None, space=4):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.name = name or tb.name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, para in enumerate(paras if isinstance(paras, list) else [paras]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if align:
            p.alignment = align
        if i:
            p.space_before = Pt(space)
        for t, o in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            r.font.size = Pt(o.get('size', size))
            r.font.bold = o.get('bold', bold)
            r.font.color.theme_color = o.get('color', color)
    return tb


def card(slide, x, y, w, h, fill=T.BACKGROUND_2, name=None, kind=MSO_SHAPE.ROUNDED_RECTANGLE, line=None):
    s = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.05217
    s.fill.solid()
    s.fill.fore_color.theme_color = fill
    s.line.color.theme_color = line or fill
    s.line.width = Pt(1)
    s.shadow.inherit = False
    s.name = name or s.name
    return s


def new_slide(like, title):
    title_src = [sh for sh in like.shapes if sh.name == 'Text 0' and sh.has_text_frame and sh.text_frame.text][0]
    num_src = [sh for sh in like.shapes if sh.is_placeholder and sh.placeholder_format.type == 13][0]
    s = prs.slides.add_slide(like.slide_layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    s.shapes._spTree.append(copy.deepcopy(title_src._element))
    tr = s.shapes[-1].text_frame.paragraphs[0].runs
    tr[0].text = title
    for r in tr[1:]:
        r._r.getparent().remove(r._r)
    s.shapes._spTree.append(copy.deepcopy(num_src._element))
    return s


def finish(s, like, notes):
    """Footer cover on top (moved below the footnote line), notes body copied from an existing slide."""
    rect = copy.deepcopy([sh for sh in like.shapes if sh.name.startswith('Rectangle')][0]._element)
    s.shapes._spTree.append(rect)
    shrink_cover(s)
    ns = s.notes_slide
    if ns.notes_placeholder is None:
        ns.shapes._spTree.append(copy.deepcopy(like.notes_slide.notes_placeholder._element))
    ns.notes_text_frame.text = notes


def shrink_cover(s):
    r = [sh for sh in s.shapes if sh.name.startswith('Rectangle')][-1]
    r.top, r.height = Inches(6.95), Inches(0.35)


def set_notes(s, like, notes):
    ns = s.notes_slide
    if ns.notes_placeholder is None:
        ns.shapes._spTree.append(copy.deepcopy(like.notes_slide.notes_placeholder._element))
    ns.notes_text_frame.text = notes


def bullets(items):
    return ['• ' + t for t in items]


# ------------------------------------------------------------------ RQ slide: RQ2 gets the baseline, RQ3 the robot task
i_rq, s_rq = find_slide('RQ1')
set_para(named(s_rq, 'Text 9').text_frame.paragraphs[0],
         '在 ≤ 256 KB RAM 內做免標籤自我校正，能否保住 PC 版的增益（PC 模擬：約 87%），'
         '並在跨日、跨姿勢下勝過 PCA 特徵對齊基準 [19]？', '在 ≤ 256 KB')
set_para(named(s_rq, 'Text 10').text_frame.paragraphs[0], '[1][2][19]', '[1][2]')
set_para(named(s_rq, 'Text 13').text_frame.paragraphs[0],
         'STM32 輸出離散指令控制 Kinova Gen3（夾爪開合、預設位置）：自我校正＋低信心拒絕'
         '能否提高第 2 天的任務成功率、降低誤觸發？一次自我校正在 M7 上要多久？', '和同一塊板子')
set_para(named(s_rq, 'Text 14').text_frame.paragraphs[0], '[15][16]', '[5][6]')
set_notes(s_rq, s_rq,
          'RQ1 是 one-shot 校正搬上 MCU 後準確率有沒有掉。RQ2 是核心：在 256 KB RAM 以內做免標籤自我校正，'
          'PC 模擬保住約 87% 的增益；要在受試者身上驗證跨日和跨姿勢，並且和 Zanghieri 2023 的 PCA 特徵對齊比較。'
          'RQ3 把結果接到機器人：STM32 判斷手勢後送離散指令給 Kinova，看自我校正加上低信心拒絕，能不能提高第二天的任務'
          '成功率、降低誤觸發，同時量自我校正在 M7 上要多久。int8 CNN 的比較改成選做。')

# ------------------------------------------------------------------ novelty slide: contribution 3 and the last table row
i_nv, s_nv = find_slide('創新點')
for sh in s_nv.shapes:
    if sh.has_text_frame and '③ 實證' in sh.text_frame.text:
        r = [r for r in sh.text_frame.paragraphs[0].runs if '③ 實證' in r.text][0]
        old = '③ 實證：全部在 MCU 上的跨日受試者驗證＋開源韌體'
        assert old in r.text
        r.text = r.text.replace(old, '③ 實證：MCU 上跨日受試者＋Kinova 閉迴路任務＋開源韌體')
    if sh.has_table:
        c = sh.table.cell(5, 3)
        set_para(c.text_frame.paragraphs[0], '目標：EMG 運算全在 MCU 上＋Kinova 任務', '目標：全部在 MCU 上')

# ------------------------------------------------------------------ system figure: the title no longer claims "everything"
i_sys, s_sys = find_slide('系統架構')
set_para([sh for sh in s_sys.shapes if sh.has_text_frame and sh.text_frame.text.startswith('系統架構')][0]
         .text_frame.paragraphs[0], '系統架構：推論與自我校正都在 STM32 上', '系統架構')

# the figure is a picture from the original deck (no source): a caption says what changed
text(s_sys, 0.6, 6.55, 12.1, 0.3, '收斂後（見下一頁）：不做自製前端（ADS1299），EMG 用 Trigno；Kinova 從選做改成主要任務；'
     'PC 只負責 EMG 串流（備案）與轉送指令，不做 EMG 運算', size=11, color=T.ACCENT_5, name='Caption v9')
shrink_cover(s_sys)

# ------------------------------------------------------------------ summary slide: what is still open
i_sum, s_sum = find_slide('前置結果總結')
set_paras(named(s_sum, 'Open list').text_frame, bullets([
    't-SNE＋重新訓練樹在 Cortex-M7 上的時間（韌體已備好，等板子）→ RQ3',
    'MCU 上的跨日、跨姿勢受試者實驗，和 PCA 對齊 [19] 比較 → RQ2',
    'Kinova 閉迴路任務：成功率、誤觸發、端到端延遲 → RQ3',
    '樹池挑選、汰換策略、Flash 寫入次數 → 方法',
    '系統檢索新穎性（目前最接近：Zanghieri 2023 [19]）',
]), '• t-SNE')

nt = s_sum.notes_slide.notes_text_frame
old = '、以及和同一塊板子上的 CNN 比較'
assert old in nt.text
for para in nt.paragraphs:
    for r in para.runs:
        r.text = r.text.replace(old, '、和 PCA 對齊基準比較，以及接上 Kinova 的閉迴路任務')

# ------------------------------------------------------------------ experiment design
i_ex, s_ex = find_slide('實驗設計')
set_para(named(s_ex, 'Text 0').text_frame.paragraphs[0], '實驗設計：每人兩天，第 2 天不重新校正、直接控制 Kinova', '實驗設計')
set_paras(named(s_ex, 'Text 3').text_frame, [
    '貼片（Trigno 8 通道，參考 [1]）',
    'one-shot 校正：6 種手勢＋休息，每個做 1 次',
    '2–3 種手臂姿勢下即時測試；定拒絕門檻',
], '貼片')
set_paras(named(s_ex, 'Text 6').text_frame, [
    '重新貼片，不重新校正',
    '固定模型 vs. PCA 對齊 [19] vs. 自我校正（順序平衡）',
    'Kinova 任務：夾爪開合＋2–3 個預設位置，低速',
], '重新貼片')
set_paras(named(s_ex, 'Text 8').text_frame, ['健康成人 12–16 人', '高齡者列為未來工作'], '健康成人')
set_paras(named(s_ex, 'Text 10').text_frame, ['任務成功率、完成時間', '誤觸發／分鐘、macro-F1'], '準確率')
set_paras(named(s_ex, 'Text 12').text_frame, ['端到端延遲 P95/P99', '自我校正時間、RAM/Flash'], '延遲')
set_para(named(s_ex, 'Text 15').text_frame.paragraphs[0],
         '資料切分：訓練與測試受試者分開；校正資料不拿來評分；全部採因果前處理。選做：同一塊板子上的 int8 1D-CNN 比較',
         '資料切分')
shrink_cover(s_ex)
set_notes(s_ex, s_rq,
          '每人兩天。第一天貼片、one-shot 校正，在不同手臂姿勢下做即時測試，同時用這天的資料決定低信心拒絕的門檻。'
          '第二天重新貼片但不重新校正，比較固定模型、Zanghieri 的 PCA 對齊、和我們的自我校正，順序平衡；每個條件都用 '
          'Kinova 做同一個離散指令任務。主要指標改成任務成功率、完成時間和誤觸發，準確率當輔助。高齡者列為未來工作，'
          'int8 CNN 比較改成選做，讓一年內做得完。')

# ------------------------------------------------------------------ equipment
i_eq, s_eq = find_slide('設備需求')
tb = [sh for sh in s_eq.shapes if sh.has_table][0]
tbl = tb.table
assert tbl.cell(4, 0).text == 'Kinova Gen3'
set_para(tbl.cell(2, 1).text_frame.paragraphs[0], '選做', '建議採購')
set_para(tbl.cell(2, 2).text_frame.paragraphs[0], '自我校正的能耗、續航', 'RQ3')
set_para(tbl.cell(3, 2).text_frame.paragraphs[0], 'EMG 來源：類比輸出接 STM32 ADC（若支援），否則 PC 串流', '即時 EMG')
set_para(tbl.cell(4, 2).text_frame.paragraphs[0], '主要閉迴路任務（離散指令、低速）；PC 以 Kortex API 轉送', '抓握任務')
tr = copy.deepcopy(tbl._tbl.tr_lst[-1])
tbl._tbl.append(tr)
for c, t in zip(tbl.rows[len(tbl.rows) - 1].cells, ['伺服夾爪', '備案時採購', 'Kinova 無法使用時的備案（STM32 PWM 直接控制）']):
    set_para(c.text_frame.paragraphs[0], t)
tb.height = sum(r.height for r in tbl.rows)
set_para(named(s_eq, 'Text 1').text_frame.paragraphs[0],
         '不需要樹莓派或 Jetson：EMG 運算都在 STM32 上，PC 只把指令轉給 Kinova（Kortex 不移植到 MCU）', '不需要樹莓派')
shrink_cover(s_eq)

# ------------------------------------------------------------------ new slide: scope
sc = new_slide(s_ex, '研究範圍：核心是嵌入式自我校正，Kinova 做閉迴路驗證')
card(sc, 0.6, 1.45, 5.95, 4.75, T.TEXT_2, name='Card in')
text(sc, 0.9, 1.65, 5.4, 0.5, '做（一年內完成）', size=20, bold=True, color=T.ACCENT_2, name='In title')
text(sc, 0.9, 2.3, 5.4, 3.8, bullets([
    '核心：≤ 256 KB RAM 的免標籤自我校正 RF，在 STM32H7 上執行',
    '主要任務：STM32 輸出離散指令控制 Kinova Gen3（夾爪開合、2–3 個預設位置、低速）',
    '低信心拒絕：信心不夠就不送指令，壓低誤觸發',
    '比較：固定模型、PCA 特徵對齊 [19]、PC 版',
    '指標：任務成功率、完成時間、誤觸發／分鐘、端到端延遲',
]), size=17, color=T.BACKGROUND_1, name='In list', space=10)
card(sc, 6.75, 1.45, 5.95, 4.75, T.BACKGROUND_2, name='Card out')
text(sc, 7.05, 1.65, 5.4, 0.5, '不做或延後（理由）', size=20, bold=True, color=T.TEXT_2, name='Out title')
text(sc, 7.05, 2.3, 5.4, 3.8, bullets([
    '高齡者 → 未來工作（IRB 與招募時間不夠）',
    'int8 1D-CNN 比較 → 選做（不影響主要貢獻）',
    '自製 EMG 前端 → 不做：用 Trigno；類比輸出能接 ADC 就接，不能就 PC 串流並註明限制',
    'Kortex 搬上 MCU → 不做：要 LwIP＋protobuf，會吃掉自我校正的記憶體預算',
    '連續速度控制 → 不做：準確率約 83%，只適合離散、低速指令',
]), size=17, color=T.TEXT_1, name='Out list', space=10)
text(sc, 0.6, 6.4, 12.1, 0.4, '取捨原則：韌體為主、一年內完成；機器人部分用 Kinova 官方 API，風險最低；Kinova 不可用時改用伺服夾爪',
     size=11, color=T.ACCENT_5, name='Footnote')
finish(sc, s_ex,
       '這頁說明題目收斂後的範圍。核心不變，是在 256 KB 以內做免標籤的自我校正隨機森林。機器人部分把 Kinova 從選做'
       '改成主要的閉迴路任務，但只用離散指令和低速，因為 PC 模擬的準確率大約 83%，不夠做連續控制。右邊是砍掉或延後的：'
       '高齡者、CNN 比較、自製前端、把 Kortex 搬上 MCU，理由都是一年內做不完或不影響主要貢獻。')

# ------------------------------------------------------------------ new slide: closed-loop architecture
ar = new_slide(s_ex, '閉迴路架構：STM32 做決策，PC 只轉送指令')
boxes = [  # x, w, title, lines, dark
    (0.6, 2.3, 'Delsys Trigno', ['8 通道、2 kHz', '優先：類比輸出→ADC', '備案：PC 串流', '（備案時註明限制）'], False),
    (3.73, 3.3, 'STM32H7', ['特徵→RF 推論（100 棵、深度 10）', '低信心不送指令', '背景：免標籤自我校正',
                            f'M7 編譯 RAM {RAM_FULL:.0f} KB（含特徵）'], True),
    (7.87, 2.1, 'PC 橋接', ['Python＋Kortex API', '只轉送指令', '不做 EMG 運算', '記錄時間戳（量延遲）'], False),
    (10.8, 1.9, 'Kinova Gen3', ['夾爪閉合／張開', '2–3 個預設位置', '低速'], False),
]
for k, (x, w, ttl, lines, dark) in enumerate(boxes):
    card(ar, x, 1.55, w, 2.2, T.TEXT_2 if dark else T.BACKGROUND_2, name=f'Box {k}')
    text(ar, x + 0.2, 1.7, w - 0.4, 0.45, ttl, size=16, bold=True, color=T.ACCENT_2 if dark else T.TEXT_2,
         name=f'Box {k} title')
    text(ar, x + 0.2, 2.2, w - 0.4, 1.5, lines, size=12, color=T.BACKGROUND_1 if dark else T.TEXT_1,
         name=f'Box {k} body')
for k, lab in enumerate(['EMG', 'UART', 'Ethernet']):
    x0 = boxes[k][0] + boxes[k][1]
    gap = boxes[k + 1][0] - x0
    a = card(ar, x0 + 0.1, 2.5, gap - 0.2, 0.3, T.ACCENT_1, name=f'Arrow {k}', kind=MSO_SHAPE.RIGHT_ARROW)
    text(ar, x0, 2.85, gap, 0.5, lab, size=10, color=T.ACCENT_5, align=PP_ALIGN.CENTER, name=f'Arrow {k} label')
lower = [
    ('低信心拒絕（方法的一部分）', ['RF 投票比例低於門檻 → 不送指令', '連續 k 個視窗同一手勢才觸發', '門檻和 k 用第 1 天資料決定（待定）']),
    ('安全', ['只用離散指令、低速', '受試者在手臂工作空間外', '實驗者手持急停']),
    ('任務指標', ['成功率、完成時間', '誤觸發／分鐘', '端到端延遲：動作開始到手臂開始動']),
]
for k, (ttl, lines) in enumerate(lower):
    x = 0.6 + k * 4.1
    card(ar, x, 4.05, 3.9, 2.2, T.BACKGROUND_2, name=f'Card {k}')
    text(ar, x + 0.25, 4.2, 3.4, 0.45, ttl, size=16, bold=True, color=T.TEXT_2, name=f'Card {k} title')
    text(ar, x + 0.25, 4.7, 3.4, 1.5, bullets(lines), size=13, name=f'Card {k} body')
text(ar, 0.6, 6.4, 12.1, 0.4, 'Kortex 不移植到 MCU（要 LwIP＋protobuf）；PC 端只有轉送程式。備案：Kinova 無法使用時改用伺服夾爪，由 STM32 PWM 直接控制',
     size=11, color=T.ACCENT_5, name='Footnote')
finish(ar, s_ex,
       '閉迴路的分工。EMG 從 Trigno 進來，能用類比輸出接 STM32 的 ADC 最好；不行就由 PC 串流給 STM32，論文裡註明這個限制。'
       '特徵、推論、低信心拒絕和自我校正都在 STM32 上。STM32 只送一個指令碼給 PC，PC 用 Kinova 官方的 Kortex API 轉送，'
       '不做任何 EMG 運算。Kortex 不搬上 MCU，因為要網路堆疊和 protobuf，會吃掉自我校正的記憶體。安全上只用離散指令和低速，'
       '受試者站在工作空間外，實驗者拿急停。')

_, s_flow = find_slide('研究流程')
text(s_flow, 0.6, 6.3, 12.1, 0.3, '更新：IRB 提前到現在送（圖中原排 2026/12）；步驟 4 的 Kinova Gen3 改為主要任務；一年時程見下一頁',
     size=11, color=T.ACCENT_5, name='Caption v9')
shrink_cover(s_flow)

# ------------------------------------------------------------------ new slide: one-year plan
tl = new_slide(s_ex, '一年時程：IRB 現在送，第 5 個月打通閉迴路')
LX, LW, GX, GW, M = 0.6, 4.0, 4.7, 8.0, 13
cw = GW / M
for m in range(M):
    text(tl, GX + m * cw, 1.45, cw, 0.35, f'M{m}', size=12, bold=True, color=T.TEXT_2, align=PP_ALIGN.CENTER,
         name=f'Month {m}')
rows = [
    ('IRB 送審、採購 NUCLEO', 0, 1, False),
    ('韌體上板：特徵、推論、量 cycle（RQ1）', 1, 3, False),
    ('MCU 上自我校正時間＋PCA 對齊基準 [19]', 3, 5, False),
    ('Trigno 輸入、Kortex 橋接、拒絕機制、先導', 5, 6, False),
    ('正式實驗：12–16 人 × 2 天（RQ2、RQ3）', 6, 9, False),
    ('分析＋研討會論文', 9, 11, False),
    ('論文撰寫、口試', 11, 13, False),
    ('選做：int8 1D-CNN 比較', 7, 10, True),
]
for k, (lab, a, b, opt) in enumerate(rows):
    y = 1.9 + k * 0.5
    if k % 2 == 0:
        card(tl, LX, y - 0.04, LW + GW + 0.1, 0.48, T.BACKGROUND_2, name=f'Band {k}', kind=MSO_SHAPE.RECTANGLE)
    text(tl, LX + 0.1, y, LW - 0.1, 0.4, lab, size=13, color=T.ACCENT_5 if opt else T.TEXT_1,
         anchor=MSO_ANCHOR.MIDDLE, name=f'Task {k}')
    bar = card(tl, GX + a * cw + 0.04, y + 0.06, (b - a) * cw - 0.08, 0.28, T.ACCENT_6 if opt else T.ACCENT_1,
               name=f'Bar {k}')
text(tl, 0.6, 6.0, 12.1, 0.9, [
    [('風險與備案　', {'bold': True, 'color': T.TEXT_2}),
     (f'MCU 自我校正太慢 → t-SNE 減到 500 次（PC 上時間 {IT_REL * 100:.0f}%、準確率差 '
      + IT_DIFF + ' 個百分點，無顯著差異）', {})],
    [('　　　　　　', {}), ('Trigno 類比輸出不可用 → PC 串流並註明限制；Kinova 不可用 → 伺服夾爪', {})],
], size=12, name='Risks')
finish(tl, s_ex,
       '一年的時程。IRB 現在就送，因為審查要時間，正式實驗排在第六到第九個月。前五個月做韌體：先把推論和特徵搬上板子量 cycle，'
       '再量自我校正在 M7 上的時間，同時做 PCA 對齊的基準。第五個月把 Trigno 輸入、Kortex 橋接和拒絕機制接起來做先導。'
       'CNN 比較是選做，有時間才做。下面是主要風險和備案。')

# ------------------------------------------------------------------ page references follow the old -> new numbering
old_pos = {sl.part: k for k, sl in enumerate(prs.slides, start=1) if sl.part not in (sc.part, ar.part, tl.part)}
ids = prs.slides._sldIdLst
els = list(ids)
for el in els[-3:]:
    ids.remove(el)
_, s_flow = find_slide('研究流程')


def insert_after(slide, el):
    for k, e in enumerate(ids):
        if prs.part.related_part(e.rId) is slide.part:
            ids.insert(k + 1, el)
            return
    raise SystemExit('anchor slide not found')


insert_after(s_rq, els[-3])
insert_after(s_sys, els[-2])
insert_after(s_flow, els[-1])
new_of = {old_pos[sl.part]: k for k, sl in enumerate(prs.slides, start=1) if sl.part in old_pos}
REF = re.compile(r'第 (\d+)(–| 到 )?(\d+)? 頁')


def remap(t):
    return REF.sub(lambda m: '第 ' + str(new_of[int(m[1])]) + (m[2] + str(new_of[int(m[3])]) if m[3] else '') + ' 頁', t)


changed = []
for sl in prs.slides:
    frames = [sh.text_frame for sh in sl.shapes if sh.has_text_frame]
    frames += [c.text_frame for sh in sl.shapes if sh.has_table for r in sh.table.rows for c in r.cells]
    if sl.has_notes_slide and sl.notes_slide.notes_placeholder is not None:
        frames.append(sl.notes_slide.notes_text_frame)
    for tf in frames:
        for p in tf.paragraphs:
            whole = ''.join(r.text for r in p.runs)
            if '頁' in whole and REF.search(whole):
                hits = [r for r in p.runs if REF.search(r.text)]
                assert len(REF.findall(whole)) == sum(len(REF.findall(r.text)) for r in hits), ('split ref', whole)
                for r in hits:
                    new = remap(r.text)
                    changed += [(m0, m1) for m0, m1 in zip(REF.findall(r.text), REF.findall(new)) if m0 != m1]
                    r.text = new
print('page refs remapped:', changed)
for pos, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(pos)
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides), '| RAM', round(RAM_FULL, 1), '| 500 it rel', round(IT_REL, 3),
      'diff', round(IT500['diff'], 3), 'p', round(IT500['p'], 3))
