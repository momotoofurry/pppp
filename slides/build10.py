"""v10 = the user-edited v9 (2026-10-19 23:00, md5 b2e2960f..., 27 slides) made shorter and less template-like.

Structure: a 20-slide main line (the 10 preliminary-result slides become 6, behind a "前置結果" divider) and an
appendix behind a "附錄" divider that keeps the slides taken out of the main line (research lines, feasibility,
four directions, results ③ ④ ⑥ ⑧, the summary). Nothing is deleted.
Design, applied to every slide: the dark full-width "→ next step" callout bars are removed (charts grow into the
space), stat callouts lose their boxes (number + caption only), the remaining dark cards become light cards with
a thin accent outline, titles lose the "前置結果⑤：" / "架構：" prefixes and sit at the same place, the RQ slide gets
a title. Merged content: 552 B moves onto the compression slide, the t-SNE ablation onto the memory slide, the C
end-to-end accuracy onto the Cortex-M7 RAM slide. Page references are recomputed after the reorder.
usage: python build10.py user_v9.pptx out.pptx nums6.json
"""
import copy
import json
import re
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_THEME_COLOR as T
from pptx.util import Inches, Pt

src, dst, nums_path = sys.argv[1:4]
N = json.load(open(nums_path, encoding='utf8'))
prs = Presentation(src)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
C = {r['variant']: r for r in N['c_impl']}
FW, REF = C['C firmware logic (selfcal.c, end to end), 500 it'], C['sklearn (reference), 500 it']


def neg(v, fmt='+.2f'):
    return format(v, fmt).replace('-', '−')


def title_shape(s):
    for sh in s.shapes:
        if sh.name == 'Text 0' and sh.has_text_frame and abs(sh.top - Inches(0.35)) < Inches(0.3):
            return sh
    return None


def find(prefix):
    for s in prs.slides:
        t = title_shape(s)
        if t is not None and t.text_frame.text.startswith(prefix):
            return s
    raise SystemExit(f'slide not found: {prefix}')


def named(s, name):
    return [sh for sh in s.shapes if sh.name == name][0]


def set_para(p, text_, expect=None):
    full = ''.join(r.text for r in p.runs)
    if expect:
        assert full.startswith(expect), (full[:40], expect)
    p.runs[0].text = text_
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)


def set_title(s, text_, expect=None):
    set_para(title_shape(s).text_frame.paragraphs[0], text_, expect)


def remove(sh):
    sh._element.getparent().remove(sh._element)


# ------------------------------------------------------------------ the slides, by their v9 titles (before anything moves)
S = dict(
    title=prs.slides[0], obstacles=find('肌電控制要走出實驗室'), lines=find('讀過的論文'), gap=find('缺口'),
    feas=find('可行性'), dirs=find('四個可研究的方向'), rq=[s for s in prs.slides if any(
        sh.has_text_frame and sh.text_frame.text == 'RQ1' for sh in s.shapes)][0],
    scope=find('研究範圍'), novelty=find('創新點'), arch=find('架構'), method=find('方法核心'),
    r1=find('前置結果①'), r2=find('前置結果②'), r3=find('前置結果③'), r4=find('前置結果④'), r5=find('前置結果⑤'),
    r6=find('前置結果⑥'), r7=find('前置結果⑦'), r8=find('前置結果⑧'), r9=find('前置結果⑨'), r10=find('前置結果⑩'),
    summary=find('前置結果總結'), flow=find('研究流程'), equip=find('設備需求'),
    ref1=find('參考文獻（1/3）'), ref2=find('參考文獻（2/3）'), ref3=find('參考文獻（3/3）'))
assert len(set(map(id, S.values()))) == len(S) == len(prs.slides), 'every v9 slide must be accounted for'

# ------------------------------------------------------------------ content: merged numbers and edited text
set_title(S['r2'], '壓縮到 88 KB，推論只要 552 B', '前置結果②')
set_para(named(S['r2'], 'Stat depth value').text_frame.paragraphs[0], '552 B', '−36%')
set_para(named(S['r2'], 'Stat depth label').text_frame.paragraphs[0],
         '推論 RAM（推薦設定，編譯後靜態分析：靜態變數＋stack）', '深度 10')
for sh in S['r3'].shapes:   # appendix copy: same wording ("measured" was an overstatement)
    if sh.has_text_frame:
        for p in sh.text_frame.paragraphs:
            for r in p.runs:
                r.text = r.text.replace('推論 RAM（實測；', '推論 RAM（編譯後靜態分析；')

set_para(named(S['r5'], 'Stat int16 value').text_frame.paragraphs[0],
         f"+{N['kmeans']['gain']:.2f}／+{N['nocluster']['gain']:.2f}", '無可量測損失')
set_para(named(S['r5'], 'Stat int16 label').text_frame.paragraphs[0],
         f"拿掉 t-SNE（只用 K-Means／不分群）的增益；保留 t-SNE 是 +{N['base']['gain']:.2f}，所以不能省", 'buffer 存成 int16')

set_title(S['r9'], 'Cortex-M7 編譯後 RAM 245 KB，在預算內', '前置結果⑨')
set_para(named(S['r9'], 'Stat est value').text_frame.paragraphs[0], f"{FW['acc']:.2f}%", '224 vs 219')
set_para(named(S['r9'], 'Stat est label').text_frame.paragraphs[0],
         f"整條自我校正改用 C（靜態記憶體）的端到端準確率；sklearn {REF['acc']:.2f}%，p = {FW['p']:.2f}", '自我校正 RAM')

titles = [('gap', '沒有研究同時做到這四點', '缺口'),
          ('scope', '核心是嵌入式自我校正，Kinova 做閉迴路驗證', '研究範圍'),
          ('novelty', '和最接近的研究差在哪', '創新點'),
          ('arch', 'STM32 做決策，PC 只轉送指令', '架構'),
          ('method', 'Flash 存預訓練樹池，RAM 放使用者子集', '方法核心'),
          ('summary', '前置結果總結', '前置結果總結'),
          ('feas', '每一點都有論文數據支持', '可行性')]
for key, t, exp in titles:
    set_title(S[key], t, exp)
for key in ['r1', 'r3', 'r4', 'r5', 'r6', 'r7', 'r8', 'r10']:
    tp = title_shape(S[key]).text_frame.paragraphs[0]
    set_para(tp, re.sub(r'^前置結果[①-⑩]：', '', ''.join(r.text for r in tp.runs)), '前置結果')

# RQ slide: a title, cards moved up
empty = title_shape(S['rq'])
assert not empty.text_frame.text
new_t = copy.deepcopy(title_shape(S['gap'])._element)
new_t.xpath('./p:nvSpPr/p:cNvPr')[0].set('id', str(empty.shape_id))
empty._element.addprevious(new_t)
remove(empty)
set_title(S['rq'], '研究問題')
for sh in S['rq'].shapes:
    if sh.top >= Inches(2.9) and sh.top < Inches(6.3):
        sh.top -= Inches(1.35)

# scope: the user's double bullet, no arrows
out = named(S['scope'], 'Out list').text_frame.paragraphs
texts = ['• int8 1D-CNN 比較：選做，不影響主要貢獻',
         '• Kortex 搬上 MCU：不做，要 LwIP＋protobuf，會吃掉自我校正的記憶體預算',
         '• 連續速度控制：不做，準確率約 83%，只適合離散、低速指令']
assert len(out) == 3 and out[0].text.startswith('• • int8'), [p.text for p in out]
for p, t in zip(out, texts):
    set_para(p, t)

# flow caption: the one-year plan slide was removed by the user
cap = named(S['flow'], 'Caption v9').text_frame.paragraphs[0]
set_para(cap, ''.join(r.text for r in cap.runs).replace('；一年時程見下一頁', ''), '更新：IRB')

# ------------------------------------------------------------------ design, every slide
DARK = (T.TEXT_2,)


def theme_fill(sh):
    try:
        if sh.fill.type == 1 and sh.fill.fore_color.type == 2:
            return sh.fill.fore_color.theme_color
    except Exception:
        pass
    return None


def recolor(tf):
    for p in tf.paragraphs:
        for r in p.runs:
            c = r.font.color
            if c.type == 2 and c.theme_color in (T.BACKGROUND_1, T.LIGHT_1):
                c.theme_color = T.TEXT_1
            elif c.type == 2 and c.theme_color == T.ACCENT_2:
                c.theme_color = T.ACCENT_1
            elif c.type == 1 and c.rgb == RGBColor(0xFF, 0xFF, 0xFF):
                c.theme_color = T.TEXT_1


def inside(sh, box):
    cx, cy = sh.left + sh.width // 2, sh.top + sh.height // 2
    return box.left <= cx <= box.left + box.width and box.top <= cy <= box.top + box.height


for s in prs.slides:
    if s is S['title']:
        continue
    shapes = list(s.shapes)
    # 1. full-width callout bars
    had_callout = False
    for sh in shapes:
        if sh.name in ('Callout card', 'Callout text'):
            remove(sh)
            had_callout = True
    if had_callout:
        for sh in s.shapes:
            if sh.has_chart and abs(sh.top + sh.height - Inches(5.55)) < Inches(0.1):
                sh.height = Inches(6.2) - sh.top
    # 2. stat callouts: no boxes; a right-hand column is spread over the freed height
    cards = [sh for sh in s.shapes if re.match(r'^Stat .+ card$', sh.name)]
    col = []
    for cd in cards:
        key = cd.name[:-len(' card')]
        parts = [sh for sh in s.shapes if sh.name in (key + ' value', key + ' label')]
        for sh in parts:
            recolor(sh.text_frame)
        if cd.left >= Inches(8) and had_callout:
            col.append((cd.top, parts))
        remove(cd)
    for k, (_, parts) in enumerate(sorted(col, key=lambda x: x[0])):
        v = [sh for sh in parts if sh.name.endswith('value')][0]
        dy = Inches(1.55 + 1.6 * k) - v.top
        for sh in parts:
            sh.top += dy
    # 3. other dark cards -> light card, thin accent outline
    for sh in list(s.shapes):
        if sh.shape_type == 1 and theme_fill(sh) in DARK and sh.width < Inches(12):
            sh.fill.fore_color.theme_color = T.BACKGROUND_2
            sh.line.color.theme_color = T.ACCENT_1
            sh.line.width = Pt(1.5)
            if sh.has_text_frame:
                recolor(sh.text_frame)
            for o in s.shapes:
                if o is not sh and o.has_text_frame and inside(o, sh):
                    recolor(o.text_frame)
    # 4. titles at one place
    t = title_shape(s)
    if t is not None:
        t.left, t.top, t.width = Inches(0.6), Inches(0.35), Inches(12.1)


# ------------------------------------------------------------------ dividers (copies of the title slide)
def divider(text_):
    src_s = S['title']
    d = prs.slides.add_slide(src_s.slide_layout)
    for ph in list(d.placeholders):
        remove(ph)
    for sh in src_s.shapes:
        d.shapes._spTree.append(copy.deepcopy(sh._element))
    first = [sh for sh in d.shapes if sh.has_text_frame and sh.text_frame.text][0]
    set_para(first.text_frame.paragraphs[0], text_)
    return d


S['div_results'] = divider('前置結果')
S['div_appendix'] = divider('附錄')

# ------------------------------------------------------------------ order
MAIN = ['title', 'obstacles', 'gap', 'rq', 'scope', 'novelty', 'arch', 'method',
        'div_results', 'r1', 'r2', 'r5', 'r7', 'r9', 'r10',
        'flow', 'equip', 'ref1', 'ref2', 'ref3']
APPX = ['div_appendix', 'lines', 'feas', 'dirs', 'r3', 'r4', 'r6', 'r8', 'summary']
ORDER = MAIN + APPX
assert sorted(ORDER) == sorted(S), set(S) ^ set(ORDER)
ids = prs.slides._sldIdLst
by_part = {prs.part.related_part(e.rId): e for e in ids}
els = [by_part[S[k].part] for k in ORDER]
for e in list(ids):
    ids.remove(e)
for e in els:
    ids.append(e)
pos = {k: i for i, k in enumerate(ORDER, start=1)}
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)

# ------------------------------------------------------------------ page references, recomputed
res = f"第 {pos['r1']}–{pos['r10']} 頁"
REFS = [  # slide, shape name (None = notes), old pattern, new text
    ('gap', 'Text 1', r'第 \d+–\d+ 頁', res),
    ('gap', None, r'第 \d+ 到 \d+ 頁', f"第 {pos['r1']} 到 {pos['r10']} 頁"),
    ('feas', 'Text 25', r'第 \d+–\d+ 頁', res),
    ('novelty', 'Table 0', r'第 \d+ 頁', f"第 {pos['r5']} 頁"),
    ('method', 'Text 29', r'第 \d+ 頁', f"第 {pos['r5']} 頁"),
    ('r6', 'Stat mcu label', r'第 \d+–\d+ 頁', '第 ' + '、'.join(str(x) for x in sorted([pos['r8'], pos['r9']])) + ' 頁'),
    ('summary', 'Footnote', r'（第 \d+ 頁之前的 RAM 為估算）', f"（RAM 除第 {pos['r9']} 頁外都是估算）"),
]
done = []
for key, name, pat, new in REFS:
    s = S[key]
    if name is None:
        frames = [s.notes_slide.notes_text_frame]
    else:
        sh = named(s, name)
        frames = [c.text_frame for r in sh.table.rows for c in r.cells] if sh.has_table else [sh.text_frame]
    n = 0
    for tf in frames:
        for p in tf.paragraphs:
            for r in p.runs:
                r.text, k = re.subn(pat, new, r.text)
                n += k
    assert n == 1, (key, name, n)
    done.append(new)
left = []
for sl in prs.slides:
    for sh in sl.shapes:
        if sh.has_text_frame and re.search(r'第 \d+[–、 到]*\d* 頁', sh.text_frame.text):
            left.append(sh.text_frame.text[:30])
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides), '| main', len(MAIN), '| appendix', len(APPX), '| refs', done)
