"""v12 = the user's v11 (v10 without the appendix, 2026-10-19 23:10, 20 slides) cut down to a short pitch: what I want
to do, the closest papers, and my reproduction / preliminary results.

Order: title (with a one-line subtitle) -> NEW "我想做的事" (one sentence, done / not done by anyone / next year, the ask)
-> closest-work table -> RQs -> architecture -> method -> results divider -> 6 result slides -> scope (do / not do)
-> references. Dropped: the three obstacles, the gap table, the old flow figure, equipment. References keep only
the papers still cited (plus Jiang 2024 [18], whose arm-position data the reproduction uses) and are renumbered
1..n in their old order; every in-text [n] is renumbered with them. Numbers on the new slide are read from the
result slides themselves (which came from results/ via nums*.json), not typed.
usage: python build12.py user_v11.pptx out.pptx
"""
import copy
import re
import sys

from pptx import Presentation
from pptx.enum.dml import MSO_THEME_COLOR as T
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Inches, Pt

src, dst = sys.argv[1:3]
prs = Presentation(src)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


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


def remove(sh):
    sh._element.getparent().remove(sh._element)


S = dict(
    title=prs.slides[0], obstacles=find('肌電控制要走出實驗室'), gap=find('沒有研究同時做到'), rq=find('研究問題'),
    scope=find('核心是嵌入式自我校正'), novelty=find('和最接近的研究'), arch=find('STM32 做決策'), method=find('Flash 存預訓練樹池'),
    div=find('前置結果') if False else [s for s in prs.slides if any(
        sh.has_text_frame and sh.text_frame.text == '前置結果' for sh in s.shapes)][0],
    r1=find('PC 基準已重現'), r2=find('壓縮到 88 KB'), r5=find('保留 t-SNE'), r7=find('t-SNE 迭代減半'),
    r9=find('Cortex-M7 編譯後 RAM'), r10=find('跨兩天 demo'), flow=find('研究流程'), equip=find('設備需求'),
    ref1=find('參考文獻（1/3）'), ref2=find('參考文獻（2/3）'), ref3=find('參考文獻（3/3）'))
assert len(set(map(id, S.values()))) == len(S) == len(prs.slides), 'every v11 slide must be accounted for'


# ------------------------------------------------------------------ numbers for the new slide, read off the result slides
def val(key, name):
    return named(S[key], name).text_frame.text


ACC_REPRO = val('r1', 'Stat selfcal value')                       # 84.63%
PAPER = re.search(r'論文 ([\d.]+%)', val('r1', 'Stat selfcal label'))[1]
INFER = val('r2', 'Stat depth value')                              # 552 B
tbl = named(S['r2'], 'Table configs').table
row = [r for r in tbl.rows if '推薦' in r.cells[0].text][0]
FLASH = row.cells[1].text                                           # 88.1 KB
RAM = val('r9', 'Stat ram value')                                   # 245.0 KB
TAIL = val('r10', 'Stat tail value')                                # 92.2%
FIXED = re.search(r'固定模型 ([\d.]+%)', val('r10', 'Stat tail label'))[1]
for v in (ACC_REPRO, PAPER, INFER, FLASH, RAM, TAIL, FIXED):
    assert re.search(r'\d', v), v


# ------------------------------------------------------------------ helpers in the v10 style (light cards, no bars)
def text(slide, x, y, w, h, paras, size=15, color=T.TEXT_1, bold=False, anchor=MSO_ANCHOR.TOP, name=None, space=6):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.name = name or tb.name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, para in enumerate(paras if isinstance(paras, list) else [paras]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if i:
            p.space_before = Pt(space)
        for t, o in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            r.font.size = Pt(o.get('size', size))
            r.font.bold = o.get('bold', bold)
            r.font.color.theme_color = o.get('color', color)
    return tb


def card(slide, x, y, w, h, name, outline=False):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = 0.05217
    s.fill.solid()
    s.fill.fore_color.theme_color = T.BACKGROUND_2
    s.line.color.theme_color = T.ACCENT_1 if outline else T.BACKGROUND_2
    s.line.width = Pt(1.5 if outline else 1)
    s.shadow.inherit = False
    s.name = name
    return s


def new_slide(like, title_):
    s = prs.slides.add_slide(like.slide_layout)
    for ph in list(s.placeholders):
        remove(ph)
    s.shapes._spTree.append(copy.deepcopy(title_shape(like)._element))
    set_para(title_shape(s).text_frame.paragraphs[0], title_)
    num = [sh for sh in like.shapes if sh.is_placeholder and sh.placeholder_format.type == 13][0]
    s.shapes._spTree.append(copy.deepcopy(num._element))
    return s


# ------------------------------------------------------------------ title slide: one-line subtitle
sub = [sh for sh in S['title'].shapes if sh.has_text_frame and not sh.text_frame.text][0]
p = sub.text_frame.paragraphs[0]
r = p.add_run()
r.text = '在 STM32H7 上做記憶體預算內、免標籤的自我校正隨機森林，用 Kinova 閉迴路任務驗證'
r.font.size = Pt(20)
r.font.color.theme_color = T.BACKGROUND_1

# ------------------------------------------------------------------ NEW: what I want to do
w = new_slide(S['rq'], '我想做的事')
text(w, 0.6, 1.4, 12.1, 0.95,
     '把 Jiang 的免標籤自我校正隨機森林 [1][18] 放進 STM32H7，在 256 KB RAM 內完成，'
     '讓使用者第 2 天不用重新校正，並用 Kinova 離散指令任務驗證', size=20, bold=True, color=T.TEXT_2, name='Lead')
cols = [
    ('已經做到（PC 重現＋編譯）', [
        f'重現自我校正 {ACC_REPRO}（論文 {PAPER}）',
        f'壓縮後 Flash {FLASH}，推論 {INFER}',
        f'自我校正全用 C 寫好，M7 編譯 RAM {RAM}',
        f'跨兩天 demo：第 2 天 {TAIL}，固定模型 {FIXED}',
    ], True),
    ('還沒有人做', [
        'Jiang [1][2][18]：只在 PC 上跑，沒有記憶體限制',
        'Zanghieri [19]：GAP9 上免標籤，但只做特徵層對齊、不更新分類器',
        '[20][21]：免標籤適應，沒有上 MCU',
    ], False),
    ('接下來一年', [
        '上板量 one-shot 準確率與自我校正時間（RQ1）',
        '12–16 人 × 2 天，和 PCA 對齊 [19] 比較（RQ2）',
        'Kinova 夾放＋預設位置：成功率、誤觸發（RQ3）',
    ], False),
]
for k, (head, items, outline) in enumerate(cols):
    x = 0.6 + k * 4.1
    card(w, x, 2.6, 3.9, 3.5, f'Col {k} card', outline=outline)
    text(w, x + 0.25, 2.8, 3.4, 0.45, head, size=17, bold=True, color=T.ACCENT_1 if outline else T.TEXT_2,
         name=f'Col {k} head')
    text(w, x + 0.25, 3.35, 3.4, 2.7, ['• ' + t for t in items], size=14, name=f'Col {k} list')
text(w, 0.6, 6.35, 12.1, 0.4, [[('需要老師同意　', {'bold': True, 'color': T.TEXT_2}),
                                ('送 IRB（審查要時間，正式實驗排在第 6–9 個月）、採購 NUCLEO-H743ZI2', {})]],
     size=14, name='Ask')
w.shapes._spTree.append(copy.deepcopy([sh for sh in S['rq'].shapes if sh.name.startswith('Rectangle')][0]._element))
cover = [sh for sh in w.shapes if sh.name.startswith('Rectangle')][-1]
cover.top, cover.height = Inches(6.95), Inches(0.35)
ns = w.notes_slide
if ns.notes_placeholder is None:
    ns.shapes._spTree.append(copy.deepcopy(S['rq'].notes_slide.notes_placeholder._element))
ns.notes_text_frame.text = (
    '一句話：把 Jiang 團隊的免標籤自我校正隨機森林放進 STM32，在 256 KB 以內完成，第二天不用重新校正，最後接 Kinova 驗證。'
    '左邊是我已經做完的：在 PC 上重現論文、壓縮模型、整條自我校正改寫成 C 並在 Cortex-M7 上編譯，跨兩天的 demo 也有效。'
    '中間是最接近的研究都還沒做的。右邊是接下來一年要做的三件事，對應三個研究問題。需要老師同意的是送 IRB 和買板子。')

# divider text
set_para([sh for sh in S['div'].shapes if sh.has_text_frame and sh.text_frame.text][0].text_frame.paragraphs[0],
         '重現與前置結果', '前置結果')
S['what'] = w

# ------------------------------------------------------------------ references: only what is cited, renumbered
MAIN = ['title', 'what', 'novelty', 'rq', 'arch', 'method', 'div', 'r1', 'r2', 'r5', 'r7', 'r9', 'r10', 'scope']
REF_RE = re.compile(r'\[(\d+)\]')


def frames(s):
    out = [sh.text_frame for sh in s.shapes if sh.has_text_frame]
    out += [c.text_frame for sh in s.shapes if sh.has_table for r_ in sh.table.rows for c in r_.cells]
    if s.has_notes_slide and s.notes_slide.notes_placeholder is not None:
        out.append(s.notes_slide.notes_text_frame)
    return out


cited = {18}
for k in MAIN:
    for tf in frames(S[k]):
        cited |= {int(n) for n in REF_RE.findall(tf.text)}
entries = {}
for k in ('ref1', 'ref2', 'ref3'):
    body = [sh for sh in S[k].shapes if sh.has_text_frame and sh.text_frame.text.startswith('[')][0]
    for p_ in body.text_frame.paragraphs:
        m = re.match(r'\[(\d+)\]', p_.text)
        if m:
            entries[int(m[1])] = p_._p
assert cited <= set(entries), cited - set(entries)
NEW = {old: i for i, old in enumerate(sorted(cited), start=1)}
print('references kept (old -> new):', NEW)

for k in MAIN:
    for tf in frames(S[k]):
        for p_ in tf.paragraphs:
            whole = ''.join(r_.text for r_ in p_.runs)
            if REF_RE.search(whole):
                assert len(REF_RE.findall(whole)) == sum(len(REF_RE.findall(r_.text)) for r_ in p_.runs), whole
                for r_ in p_.runs:
                    r_.text = REF_RE.sub(lambda m: f'[{NEW[int(m[1])]}]', r_.text)

pages = [S['ref1'], S['ref3']]
order = sorted(cited)
split = [order[:6], order[6:]]
star = [sh for sh in S['ref2'].shapes if sh.has_text_frame and sh.text_frame.text.startswith('＊')][0]
for n, (pg, olds) in enumerate(zip(pages, split), start=1):
    set_para(title_shape(pg).text_frame.paragraphs[0], f'參考文獻（{n}/2）', '參考文獻')
    body = [sh for sh in pg.shapes if sh.has_text_frame and sh.text_frame.text.startswith('[')][0]
    txb = body.text_frame._txBody
    for p_ in list(body.text_frame.paragraphs):
        txb.remove(p_._p)
    for old in olds:
        el = copy.deepcopy(entries[old])
        ts = el.findall('.//' + A_NS + 't')
        ts[0].text = re.sub(r'^\[\d+\]', f'[{NEW[old]}]', ts[0].text)
        assert ts[0].text.startswith(f'[{NEW[old]}]'), ts[0].text[:10]
        txb.append(el)
    if any('＊' in ''.join(t.text or '' for t in entries[o].findall('.//' + A_NS + 't')) for o in olds):
        if not any(sh.has_text_frame and sh.text_frame.text.startswith('＊') for sh in pg.shapes):
            pg.shapes._spTree.append(copy.deepcopy(star._element))
    if pg.has_notes_slide and pg.notes_slide.notes_placeholder is not None:
        pg.notes_slide.notes_text_frame.text = ''
S['refA'], S['refB'] = pages

# ------------------------------------------------------------------ order, drop the rest
ORDER = MAIN + ['refA', 'refB']
ids = prs.slides._sldIdLst
by_part = {prs.part.related_part(e.rId): e for e in ids}
keep = [by_part[S[k].part] for k in ORDER]
for e in list(ids):
    ids.remove(e)
    if e not in keep:
        prs.part.drop_rel(e.rId)
for e in keep:
    ids.append(e)
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
pos = {k: i for i, k in enumerate(ORDER, start=1)}

# page references in the kept slides
for k, name, pat, new in [('novelty', 'Table 0', r'第 \d+ 頁', f"第 {pos['r5']} 頁"),
                          ('method', 'Text 29', r'第 \d+ 頁', f"第 {pos['r5']} 頁")]:
    sh = named(S[k], name)
    fs = [c.text_frame for r_ in sh.table.rows for c in r_.cells] if sh.has_table else [sh.text_frame]
    n = 0
    for tf in fs:
        for p_ in tf.paragraphs:
            for r_ in p_.runs:
                r_.text, c_ = re.subn(pat, new, r_.text)
                n += c_
    assert n == 1, (k, n)
left = [(i, tf.text[:40]) for i, sl in enumerate(prs.slides, 1) for tf in frames(sl) if re.search(r'第 \d+[–、 到]*\d* 頁', tf.text)]
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides), '| page refs left:', left)
