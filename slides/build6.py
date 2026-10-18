"""v6 = v5 + argument review: corrected novelty (Zanghieri 2023 does label-free adaptation on GAP9),
evidence-backed importance (calibration burden review, original authors' MCU motivation), RQs and method
updated to the preliminary results, wording that does not overclaim, a summary slide and references 17-21.
usage: python build6.py v5.pptx out.pptx nums4.json
"""
import copy
import json
import math
import sys

from pptx import Presentation
from pptx.enum.dml import MSO_THEME_COLOR as T
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Inches, Pt

src, dst, nums_path = sys.argv[1:4]
N = json.load(open(nums_path, encoding='utf8'))
prs = Presentation(src)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
S = list(prs.slides)                       # 0-based: S[1] is slide 2


def shape(slide, sid):
    return [sh for sh in slide.shapes if sh.shape_id == sid][0]


def set_text(tf_owner, text, expect=None):
    """replace the text of a shape or table cell, keeping the first run's formatting"""
    tf = tf_owner.text_frame
    if expect:
        assert tf.text.startswith(expect), (tf.text[:40], expect)
    p0 = tf.paragraphs[0]
    for extra in tf.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    runs = p0.runs
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def set_run(shape_, idx, text, expect=None):
    r = shape_.text_frame.paragraphs[0].runs[idx]
    if expect:
        assert r.text.startswith(expect), (r.text[:40], expect)
    r.text = text


c375 = [t for t in N['combo'] if t['n'] == 375][0]
keep = c375['gain'] / N['base']['gain'] * 100          # share of the self-calibration gain kept (Docker runs)
KEEP = f'約 {math.floor(keep):d}%'                       # floor: never overstate

# ------------------------------------------------------------------ slide 2: importance with evidence
s2 = S[1]
set_text(shape(s2, 7), '每次使用都要重新收資料校正，使用者負擔重，也是放棄使用的主因之一', '每次使用')
set_text(shape(s2, 8), '[1][3][17]', '[1][3]')
set_text(shape(s2, 13), '跨使用者、自我校正的方法都在 PC 或 GPU 上執行；原作者也以「放進 MCU」為目標，但沒有實作', '跨使用者')
set_text(shape(s2, 14), '[1][2][8][18]', '[1][2][8]')

# ------------------------------------------------------------------ slide 4: corrected gap table
s4 = S[3]
tb = [sh for sh in s4.shapes if sh.has_table][0].table
set_text(tb.cell(5, 0), 'Zanghieri／Benatti [10][11][19]', 'Zanghieri')
tri = tb.cell(2, 2).text_frame.paragraphs[0].runs[0]._r          # the △ run, with its colour
cell = tb.cell(5, 2).text_frame.paragraphs[0]
assert cell.runs[0].text == '✗'
old = cell.runs[0]._r
new = copy.deepcopy(tri)
old.addprevious(new)
old.getparent().remove(old)
set_text(tb.cell(6, 0), '本研究（目標）', '本研究')
leg = shape(s4, 4)
set_text(leg, '✓ 有做到　△ 部分（遷移學習需標籤；或用 RPi／TPU／並行 RISC-V；或只做特徵層對齊、不更新分類器 [19]）　✗ 沒有　'
              '本研究為目標，前置結果見第 11–17 頁', '✓ 有做到')
leg.height = Inches(0.6)
s4.notes_slide.notes_text_frame.text = (
    '這張是整個題目的核心邏輯：每條研究線都只做到一部分。要特別說明 Zanghieri 2023 [19]：'
    '他們在 GAP9 上做到免標籤的手臂姿勢適應，但方法是特徵層的主成分對齊，不更新分類器，'
    '而且用的是 9 核並行 RISC-V。本研究是在一般單核 Cortex-M 上用偽標籤重新訓練分類器，並且有記憶體預算。'
    '本研究那一列是目標，跨日受試者實驗還沒做，前置結果在第 11 到 17 頁。')

# ------------------------------------------------------------------ slide 5: link literature to own evidence
set_text(shape(S[4], 27), '另外：106 人資料與程式碼都已公開 [2]（前置研究先用 GitHub 上的 20 人資料）；'
                          '我們自己的前置結果：第 11–17 頁', '另外')

# ------------------------------------------------------------------ slide 7: RQs matched to the evidence
s7 = S[6]
set_text(shape(s7, 11), f'在 ≤ 256 KB RAM 內做免標籤自我校正，能否保住 PC 版的增益（PC 模擬：{KEEP}），'
                        '並撐住跨日和手臂姿勢變化？', '在 RAM')
set_text(shape(s7, 15), '和同一塊板子上的 int8 1D-CNN 相比，延遲、功耗與續航如何？'
                        '自我校正（t-SNE＋重新訓練樹）在 Cortex-M7 上要多久？', '和同一塊')

# ------------------------------------------------------------------ slide 8: novelty vs the closest work
s8 = S[7]
t8 = [sh for sh in s8.shapes if sh.has_table][0].table
set_text(t8.cell(0, 2), 'Zanghieri／Benatti [10][11][19]', 'Zanghieri')
set_text(t8.cell(3, 2), '[10][11] 需要；[19] 不需要（只做特徵層對齊）', '需要')
set_text(t8.cell(3, 3), '不需要（偽標籤，重新訓練分類器）', '不需要')
set_text(t8.cell(4, 3), '有（小 buffer＋有上限的樹替換，第 15 頁）', '有（樹池')
set_text(t8.cell(5, 3), '目標：全部在 MCU 上', '有（全部')
contrib = shape(s8, 4)
set_run(contrib, 1, f'① 方法：記憶體預算內的免標籤自我校正 RF（前置：RAM 估算 {c375["ram"]:.0f} KB，保住{KEEP}增益）　'
                    '② 系統：偽標籤＋重新訓練分類器在單核 Cortex-M 上執行（[19] 只做特徵層對齊）　'
                    '③ 實證：全部在 MCU 上的跨日受試者驗證＋開源韌體', '① 方法')
contrib.top = Inches(5.62)
set_text(shape(s8, 5), '初步檢索（2026/10）：最接近的是 Zanghieri 2023 [19]（GAP9、免標籤特徵層對齊）；'
                       '免標籤適應但沒有上 MCU：[20][21]。定題前仍要用 Scholar／Scopus 系統檢索', '待辦')
s8.notes_slide.notes_text_frame.text = (
    '和最接近的研究比。Jiang 的方法只在 PC 上跑；Zanghieri 2023 [19] 在 GAP9 上做到免標籤，'
    '但只做特徵層的主成分對齊、不更新分類器；Touko 2026 [20] 和 EMG-UP [21] 也是免標籤，但沒有在 MCU 上跑。'
    f'本研究的差別是在一般單核 Cortex-M 上，用偽標籤重新訓練分類器，並且在記憶體預算內完成；前置結果估計 {c375["ram"]:.0f} KB、'
    f'保住{KEEP}的增益。這是初步檢索的結果，定題前還要做系統檢索。')

# ------------------------------------------------------------------ slide 10: method updated to what was verified
s10 = S[9]
set_text(shape(s10, 13), '新使用者每個手勢做 1 次：剪枝預訓練樹（Flash）＋附加新樹（RAM）；從樹池挑子集：待驗證', '新使用者')
set_text(shape(s10, 19), '小 buffer（375 筆，int16）＋ t-SNE＋K-Means 產生偽標籤，定期汰換附加樹（每棵 ≤ 32 葉，RAM 有上限）',
         '高信心')
set_text(shape(s10, 20), '要系統化分析的設計參數（前人沒有針對 RF 自我校正回答；✓ 已有前置數據　△ 部分）', '要系統化')
for sid, txt, exp in [(22, 'RAM 預算 ✓', 'RAM 預算'), (24, '子集大小 △', '子集大小'), (26, '緩衝區大小 ✓', '緩衝區大小'),
                      (28, '汰換策略 △', '汰換策略')]:
    set_text(shape(s10, sid), txt, exp)
set_text(shape(s10, 31), '產出：準確率 vs. 記憶體的取捨曲線（第 15 頁已有 PC 模擬的初版）→ 先投研討會', '產出')
s10.notes_slide.notes_text_frame.text = (
    '創新點主要在這裡。Jiang 在 PC 上可以無限存資料、重新訓練樹；在 MCU 上要在 RAM 上限內更新。'
    '第 3 步已經用前置實驗驗證：375 筆 int16 buffer 加 t-SNE 和 K-Means，附加樹限制 32 葉，估計 219 KB。'
    '設計參數裡，RAM 預算和 buffer 大小已經有數據；子集大小只測了樹的數量、汰換策略只測了樹的大小上限，所以標成部分；'
    '樹池挑選和 Flash 寫入次數還沒做。')

# ------------------------------------------------------------------ slide 13: 552 B (bytes), as measured
s13 = S[12]
title13 = [sh for sh in s13.shapes if sh.has_text_frame and sh.text_frame.text.startswith('前置結果③')][0]
full13 = title13.text_frame.text
assert '552 KB' in full13
set_text(title13, full13.replace('552 KB', '552 B'))      # PowerPoint split '552 KB' across runs: rebuild as one
val13 = [sh for sh in s13.shapes if sh.has_text_frame and sh.text_frame.text == '552 KB'][0]
set_text(val13, '552 B', '552 KB')

# ------------------------------------------------------------------ slide 15: no overclaim
s15 = S[14]
t15 = [sh for sh in s15.shapes if sh.has_text_frame and sh.text_frame.text.startswith('前置結果⑤')][0]
set_text(t15, '前置結果⑤：保留 t-SNE，RAM 估算可壓到 256 KB 以下', '前置結果⑤')
set_text([sh for sh in s15.shapes if sh.has_text_frame and sh.text_frame.text == '0 損失'][0], '無可量測損失', '0 損失')

# ------------------------------------------------------------------ slide 16: fallback if t-SNE is too slow
co16 = shape(S[15], 37)
p1 = co16.text_frame.paragraphs[1]
assert p1.runs[0].text.startswith('→ 下一步')
p1.runs[0].text = '→ 下一步：C 版 t-SNE 上板實測；太慢的備案：減少迭代次數、降低 perplexity、換更省的嵌入方法'
for r in p1.runs[1:]:
    r._r.getparent().remove(r._r)


# ------------------------------------------------------------------ helpers for the new slides
def text(slide, x, y, w, h, paras, size=14, color=T.TEXT_1, bold=False, anchor=MSO_ANCHOR.TOP, name=None, space=0):
    tb_ = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb_.name = name or tb_.name
    tf = tb_.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, para in enumerate(paras if isinstance(paras, list) else [paras]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space)
        for t, o in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            r.font.size = Pt(o.get('size', size))
            r.font.bold = o.get('bold', bold)
            r.font.color.theme_color = o.get('color', color)
    return tb_


def card(slide, x, y, w, h, fill, name):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = 0.05217
    s.fill.solid()
    s.fill.fore_color.theme_color = fill
    s.line.color.theme_color = fill
    s.line.width = Pt(1)
    s.shadow.inherit = False
    s.name = name
    return s


src_slide = S[15]                                  # 前置結果⑥: title shape, page number, footer cover
title_src = [sh for sh in src_slide.shapes if sh.is_placeholder and sh.placeholder_format.type == 1
             and sh.text_frame.text.startswith('前置結果⑥')][0]
num_src = [sh for sh in src_slide.shapes if sh.is_placeholder and sh.placeholder_format.type == 13][0]
cover_src = [sh for sh in src_slide.shapes if sh.name.startswith('Rectangle')][0]


def new_slide(title, notes, cover=True):
    s = prs.slides.add_slide(src_slide.slide_layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    s.shapes._spTree.append(copy.deepcopy(title_src._element))
    tr = s.shapes[-1].text_frame.paragraphs[0].runs
    tr[0].text = title
    for r in tr[1:]:
        r.text = ''
    s.shapes._spTree.append(copy.deepcopy(num_src._element))
    ns = s.notes_slide
    if ns.notes_placeholder is None:
        ns.shapes._spTree.append(copy.deepcopy(src_slide.notes_slide.notes_placeholder._element))
    ns.notes_text_frame.text = notes
    return s


def bullets(items, color):
    return [[('• ', {'color': color, 'bold': True}), (t, {'color': color})] for t in items]


# ------------------------------------------------------------------ new slide: summary of the preliminary results
s17 = new_slide('前置結果總結：可行性已有證據，關鍵問題還沒人回答',
                '總結前置研究。左邊是已經證明的：重現論文、模型壓縮、推論只要 552 B、拿掉 t-SNE 會失去一半以上的增益、'
                f'但保留 t-SNE 並縮小 buffer 可以把 RAM 估計壓到 {c375["ram"]:.0f} KB，還保住{KEEP}的增益。'
                '右邊是還沒有人回答、也是這個碩論要做的：t-SNE 和重新訓練樹在 Cortex-M7 上的時間、MCU 上的跨日受試者實驗、'
                '樹池挑選和汰換策略、以及和同一塊板子上的 CNN 比較。可行性有證據，但關鍵問題還沒人做過，所以值得做。')
card(s17, 0.6, 1.45, 5.95, 4.55, T.BACKGROUND_2, 'Card done')
text(s17, 0.9, 1.65, 5.4, 0.5, '已經證明（PC 模擬＋編譯實測）', size=20, bold=True, color=T.TEXT_2, name='Done title')
text(s17, 0.9, 2.3, 5.4, 3.6, bullets([
    f"重現：自我校正 84.63%（論文 84.6%），讀程式碼找出 4 處和論文不一致",
    '壓縮：100 棵、深度 10、int16 → Flash 88.1 KB，自我校正只差 0.47 個百分點',
    '推論：RAM 552 B（實測），C 與 Python 預測 100% 一致',
    '偽標籤：拿掉 t-SNE 只剩不到一半的增益（重現論文 ablation）',
    f"記憶體：保留 t-SNE＋375 筆 int16 buffer＋32 葉 → 估算 {c375['ram']:.0f} KB，保住{KEEP}增益"],
    T.TEXT_1), size=15, name='Done list', space=6)
card(s17, 6.75, 1.45, 5.95, 4.55, T.TEXT_2, 'Card open')
text(s17, 7.05, 1.65, 5.4, 0.5, '還要回答（本研究的貢獻）', size=20, bold=True, color=T.ACCENT_2, name='Open title')
text(s17, 7.05, 2.3, 5.4, 3.6, bullets([
    't-SNE＋重新訓練樹在 Cortex-M7 上的時間 → RQ3',
    'MCU 上的跨日、跨姿勢受試者實驗 → RQ2',
    '樹池挑選、汰換策略、Flash 寫入次數 → 方法',
    '和同一塊板子上的 int8 1D-CNN 比延遲、功耗、續航 → RQ3',
    '系統檢索新穎性（目前最接近：Zanghieri 2023 [19]）'],
    T.BACKGROUND_1), size=15, name='Open list', space=6)
text(s17, 0.6, 6.2, 12.1, 0.4,
     'PC 模擬為 20 人 × 11 block × 3 seed（Windows／Docker，各頁註明）；RAM 為估算；MCU 上目前只有 Flash 與推論 RAM 是實測。',
     size=11, color=T.ACCENT_5, name='Footnote')
s17.shapes._spTree.append(copy.deepcopy(cover_src._element))

# ------------------------------------------------------------------ new slide: references 3/3
refs_src = S[20]
s22 = new_slide('參考文獻（3/3）', '本次快速檢索補充的文獻；[19] 是目前找到最接近的研究，[17] 支持重要性。')
REFS = [
    '[17]  X. Wang, D. Ao, L. Li, “Robust myoelectric pattern recognition methods for reducing users’ calibration burden: '
    'challenges and future,” Front. Bioeng. Biotechnol., vol. 12, 1329209, 2024.',
    '[18]  X. Jiang, C. Ma, K. Nazarpour, “Posture-invariant myoelectric control with self-calibrating random forests,” '
    'Front. Neurorobot., vol. 18, 1462023, 2024.',
    '[19]  M. Zanghieri, M. Orlandi, E. Donati, E. Gruppioni, L. Benini, S. Benatti, “Online unsupervised arm posture '
    'adaptation for sEMG-based gesture recognition on a parallel ultra-low-power microcontroller,” IEEE BioCAS, 2023.＊',
    '[20]  N. Touko, M. O. A. Ellis, C. Capone, A. Burrello, E. Donati, L. Manneschi, “Lightweight test-time adaptation '
    'for EMG-based gesture recognition,” arXiv:2601.04181, 2026.＊',
    '[21]  N. Wang, S. Wang, G. Li, Z. Fan, “EMG-UP: Unsupervised personalization in cross-user EMG gesture recognition,” '
    'arXiv:2509.21589, 2025.＊']
body_src = [sh for sh in refs_src.shapes if sh.has_text_frame and sh.text_frame.text.startswith('[9]')][0]
body = copy.deepcopy(body_src._element)
s22.shapes._spTree.append(body)
bsh = s22.shapes[-1]
paras = bsh.text_frame.paragraphs
for extra in paras[len(REFS):]:
    extra._p.getparent().remove(extra._p)
for p, t in zip(bsh.text_frame.paragraphs, REFS):
    p.runs[0].text = t
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)
note_src = [sh for sh in refs_src.shapes if sh.has_text_frame and sh.text_frame.text.startswith('＊')][0]
s22.shapes._spTree.append(copy.deepcopy(note_src._element))
set_text(s22.shapes[-1], '＊ 2026/10 快速檢索補充，只讀過摘要與公開資訊，尚未精讀全文', '＊')
cover_ref = [sh for sh in refs_src.shapes if sh.name.startswith('Rectangle')]
if cover_ref:
    s22.shapes._spTree.append(copy.deepcopy(cover_ref[0]._element))

# ------------------------------------------------------------------ footer covers that would hide the footnotes
for sl in (S[4], S[7], S[9]):                 # slides 5, 8, 10: cover only the footer line, not the footnote
    cov = [sh for sh in sl.shapes if sh.name.startswith('Rectangle')][0]
    cov.top, cov.height = Inches(6.95), Inches(0.35)
# references are now 3 slides
for sl, old, new in [(S[19], '參考文獻（1/2）', '參考文獻（1/3）'), (S[20], '參考文獻（2/2）', '參考文獻（2/3）')]:
    t = [sh for sh in sl.shapes if sh.has_text_frame and sh.text_frame.text == old][0]
    set_text(t, new, old)

# ------------------------------------------------------------------ order: summary after slide 16, refs at the end
ids = prs.slides._sldIdLst
els = list(ids)
summ, ref3 = els[-2], els[-1]
ids.remove(summ)
ids.insert(16, summ)                  # becomes slide 17
for pos, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(pos)
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides), '| gain kept', f'{keep:.1f}%')
