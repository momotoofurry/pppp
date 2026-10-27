"""v16 = v15 (build15.py output, not edited by the user: written 2026-10-27 12:21) + a dated work log.

- two new slides before the references, 「工作紀錄（1/2）」 and 「（2/2）」: per day what was done and its result. They copy the
  style of 「參考文獻（1/2）」 (title, footnote) with a table instead of the text box.
- numbers from 2026-10-24 on are read from results/*.csv; the earlier ones are the report.md summary numbers and are
  asserted to appear in report.md (their csv files predate the current schemas).
usage: python build16.py v15.pptx out.pptx
"""
import copy
import os
import sys

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

src, dst = sys.argv[1:3]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, 'results')
REPORT = open(os.path.join(ROOT, 'report.md'), encoding='utf-8').read()
prs = Presentation(src)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
HEX = dict(dk1='1F2A30', dk2='0B3C49', lt2='E1EEF1', a1='1F7A8C', a5='5B6770', a6='C9D6DA', white='FFFFFF')


def csv(name):
    return pd.read_csv(os.path.join(R, name))


def rep(*texts):
    """numbers quoted from report.md: each must appear there"""
    for t in texts:
        assert t in REPORT, t
    return texts[0] if len(texts) == 1 else texts


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


def set_para(p, text_):
    p.runs[0].text = text_
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)


def pfmt(p):
    return 'p < 0.001' if p < 0.001 else f'p = {p:.3f}' if p < 0.01 else f'p = {p:.2f}'


def sgn(v, fmt='+.2f'):
    return format(v, fmt).replace('-', '−')


def clone_after(model, after):
    """new slide with model's layout and shapes, placed right after slide `after`"""
    new = prs.slides.add_slide(model.slide_layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    for sh in model.shapes:
        new.shapes._spTree.append(copy.deepcopy(sh._element))
    ids = prs.slides._sldIdLst
    el = ids[-1]
    ids.remove(el)
    ids.insert(list(prs.slides).index(after) + 1, el)
    return new


def cell_text(cell, text_, size, bold=False, color='dk1'):
    tf = cell.text_frame
    tf.word_wrap = True
    lines = text_.split('\n')
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold = Pt(size), bold
        r.font.color.rgb = RGBColor.from_string(HEX[color])
    cell.margin_left = cell.margin_right = Inches(0.08)
    cell.margin_top = cell.margin_bottom = Inches(0.04)


def log_slide(after, title_, rows, foot):
    s = clone_after(ref, after)
    set_para(title_shape(s).text_frame.paragraphs[0], title_)
    box = named(s, 'Text 1')
    left, top, width, height = box.left, box.top, box.width, box.height
    box._element.getparent().remove(box._element)
    gf = s.shapes.add_table(len(rows) + 1, 3, left, top, width, Inches(0.4) * (len(rows) + 1))
    gf.name = 'Table log'
    tbl = gf.table
    tblPr = tbl._tbl.tblPr                                                # no built-in table style banding
    for a in ('bandRow', 'firstRow'):
        tblPr.set(a, '0')
    style = tblPr.find(qn('a:tableStyleId'))
    if style is not None:
        tblPr.remove(style)
    for j, w in enumerate((0.95, 4.9, 6.25)):
        tbl.columns[j].width = Inches(w)
    tbl.rows[0].height = Inches(0.45)
    for i in range(1, len(rows) + 1):                                     # fill down to the footnote (6.5 in)
        tbl.rows[i].height = int((Inches(6.4) - top - Inches(0.45)) / len(rows))
    for j, h in enumerate(('日期', '做了什麼', '結果（PC 模擬或 linker 實測）')):
        c = tbl.cell(0, j)
        c.fill.solid()
        c.fill.fore_color.rgb = RGBColor.from_string(HEX['dk2'])
        cell_text(c, h, 14, True, 'white')
    for i, row in enumerate(rows, start=1):
        for j, t in enumerate(row):
            c = tbl.cell(i, j)
            c.fill.solid()
            c.fill.fore_color.rgb = RGBColor.from_string(HEX['white'] if i % 2 else HEX['lt2'])
            cell_text(c, t, 13, j == 0, 'dk1')
    set_para(named(s, 'Text 2').text_frame.paragraphs[0], foot)
    nf = s.notes_slide.notes_text_frame                                  # None when the notes master has no body
    if nf is not None:
        nf.text = f"{title_}：每一天做了什麼、結果是什麼。數字都是 PC 模擬或 linker 實測，還沒有上板；細節在 report.md 對應的章節。"
    return s


# ------------------------------------------------------------------ numbers
RH = csv('ram_history.csv')
CS = csv('channel_sweep_summary.csv').set_index('set')
SR = csv('shift_sweep_raw_summary.csv').set_index('shift')
ZB = csv('zscore_sweep_summary_bal.csv').set_index(['dataset', 'shift', 'zs'])
E = csv('embed_sweep_summary.csv').set_index(['dataset', 'shift', 'embed'])
ACS = csv('adapt_c_check_summary.csv').set_index(['shift', 'update'])
AC = csv('adapt_c_check.csv')
AU = csv('aug_sweep_summary.csv').set_index(['shift', 'aug'])
PO = csv('pool_sweep_summary.csv').set_index(['shift', 'variant'])
DV = csv('decision_v2_summary.csv').set_index(['model', 'shift', 'constrained'])
FI = csv('filt_sweep_summary.csv').set_index(['shift', 'filt'])

c_ps = AC[AC.impl == 'c'].groupby(['shift', 'update', 'subject']).acc_adapt.mean().groupby(level=[0, 1]).mean() * 100
v2, v2h = c_ps.loc[(0, 1)], c_ps.loc[(0.5, 1)]
ram = dict(zip(RH.step, RH.ram_KB))
all8, d48 = CS.loc['all8'], CS.loc['drop4-8']
s1, s05, s0 = SR.loc[1], SR.loc[0.5], SR.loc[0]
zr, zb, zbh = (ZB.loc[('arm_position', 0, 'ema0.3rest')], ZB.loc[('arm_position', 0, 'bal0.3rest')],
               ZB.loc[('arm_position', 0.5, 'bal0.3rest')])
e0, t0 = E.loc[('arm_position', 0, 'none')], E.loc[('arm_position', 0, 'tsne')]
au = AU.loc[(0.5, 'app')]
po = PO.loc[(0, 'raw100')]
dd, du = DV.loc[('selfcal', 0, False)], DV.loc[('selfcal', 0, True)]
f_best = {sh: FI.loc[sh].drop('none').adapt_vs_none.idxmax() for sh in (0, 0.5)}

rows1 = [
    ('10/17', 'PC 基準重現；RF 大小分析與壓縮；C 匯出、Cortex-M7 編譯',
     f"自我校正 {rep('84.63')}%（論文 84.6%）；100 棵、深度 10、int16：Flash {rep('88.1 KB')}，推論 RAM {rep('552 B')}"),
    ('10/18', '自我校正減記憶體：int16 buffer、buffer 大小、新樹 ≤ 32 葉、t-SNE 迭代',
     f"375 筆＋32 葉：{rep('83.44%')}、增益 {rep('+3.76')}（RAM 估算 {rep('219 KB')}）；t-SNE 500 次迭代只差 −0.17（不顯著）"),
    ('10/19', '自我校正全部改寫成 C（t-SNE、K-Means、建樹、特徵擷取）；跨兩天 demo',
     f"C 端到端 {rep('83.22%')}（sklearn {rep('83.27%')}，p = 0.90）；demo 第 2 天 {rep('75%')} → {rep('93%')}（1 人）"),
    ('10/20', '簡報 v12（給老師的短版）', '—'),
    ('10/23', 'one-shot 校正搬上 MCU；決策模組；路線 B 序列協定與即時迴圈；硬體層',
     f"one-shot {rep('79.40%')}（sklearn {rep('79.68%')}，p = 0.52）；路線 B RAM {rep('248.7 KB')}，含硬體層 {ram['board layer added']:.1f} KB"),
    ('10/24', '通道數實驗（2-fold 重訓預訓練模型）；t-SNE 兩處省記憶體',
     f"拿掉 4、8 通道 {d48.acc_selfcal:.2f}% vs 8 通道 {all8.acc_selfcal:.2f}%（{pfmt(d48.acc_selfcal_p_vs_all8)}）；"
     f"RAM {ram['board layer added']:.1f} → {ram['octree 2.5 n cells']:.1f} → {ram['16-bit P, shared workspace']:.1f} KB"),
]
rows2 = [
    ('10/25', '電極轉動模擬；束帶情境＋開機對齊；從訊號判斷通道順序',
     f"轉 1 格：固定模型 {s1.tsne_fixed:.1f}%，開機對齊後回到 {s1['align']:.2f}%；偏 ½ 格 {s05['align']:.2f}%；"
     f"通道環狀順序 {rep('1-2-3-4-5-6-7-8')}（20／20 人）"),
    ('10/26', 'z-score 線上更新；類別平衡版本',
     f"休息佔一半：直接更新 {sgn(zr.adapt_vs_none)}，類別平衡 {zb.adapt:.2f}%（{pfmt(zb.adapt_p)}）；"
     f"偏 ½ 格 {sgn(zbh.adapt_vs_none)}（{pfmt(zbh.adapt_p)}）"),
    ('10/27', '偽標籤不做 t-SNE；韌體 v2：開機對齊＋z-score 更新',
     f"不嵌入 {e0.adapt:.2f}% vs t-SNE {t0.adapt:.2f}%（{pfmt(e0.vs_tsne_p)}）；v2 C 版 {v2:.2f}%、偏 ½ 格 {v2h:.2f}%；"
     f"RAM {ram['v2: no t-SNE, adapt.c']:.1f} KB"),
    ('10/27', '提升準確率①②：校正資料轉動增強；從更大的樹池挑樹',
     f"增強：偏 ½ 格 {sgn(au.adapt_vs_none)}（{pfmt(au.adapt_p)}），沒偏移固定模型 {sgn(AU.loc[(0, 'app')].fixed_vs_none)}"
     f"（{pfmt(AU.loc[(0, 'app')].fixed_p)}）→ 不採用；挑樹最多 {sgn(po.adapt_vs_first)}（{pfmt(po.adapt_p)}）→ 不採用"),
    ('10/27', '提升準確率③：決策模組（τ、streak k、多數決）',
     f"預設 τ 0.6、k 3：有效 {dd.default_effective * 100:.1f}%、{dd.default_wrong_per_min:.2f} 錯誤／分；"
     f"最高 {dd.effective * 100:.1f}% 但 {dd.wrong_per_min:.1f} 錯誤／分；同錯誤率下兩種規則一樣"),
    ('10/27', '提升準確率④：偽標籤篩選，K-Means 和森林投票一致才拿來訓練',
     f"偽標籤正確率 {FI.loc[(0, 'none')].pseudo_acc_all:.1f}% → {FI.loc[(0, f_best[0])].pseudo_acc_kept:.1f}%；準確率 "
     f"沒偏移 {sgn(FI.loc[(0, f_best[0])].adapt_vs_none)}（{pfmt(FI.loc[(0, f_best[0])].adapt_p)}）、"
     f"偏 ½ 格 {sgn(FI.loc[(0.5, f_best[0.5])].adapt_vs_none)}（{pfmt(FI.loc[(0.5, f_best[0.5])].adapt_p)}）→ 不採用"),
]

# ------------------------------------------------------------------ slides
ref = find('參考文獻（1/2）')
before = list(prs.slides)[list(prs.slides).index(ref) - 1]
foot = '20 人 × 11 block × 3 seed（arm_position）；p 是 20 人配對 Wilcoxon。細節：report.md、Notion「碩論實驗紀錄」'
l1 = log_slide(before, '工作紀錄（1/2）：10/17–10/24', rows1, foot)
l2 = log_slide(l1, '工作紀錄（2/2）：10/25–10/27', rows2, foot)

# ------------------------------------------------------------------ checks
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
assert len(prs.slides) == 21
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
for r in rows1 + rows2:
    print(' | '.join(r))
