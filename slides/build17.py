"""v17 = v16 (build16.py output, written 2026-10-27) + the comparison with Zanghieri 2023 [8].

- 「工作紀錄（2/2）」: one more row (10/27, baseline [8] PCA alignment, results/pca_baseline_summary.csv); the row is a
  copy of the last row's XML, so the formatting is the same; row heights re-split to the same table height.
- 「和最接近的研究差在哪」: the [8] remark in contribution ② gets the measured comparison; speaker notes too.
usage: python build17.py v16.pptx out.pptx
"""
import copy
import os
import sys

import pandas as pd
from pptx import Presentation
from pptx.util import Inches

src, dst = sys.argv[1:3]
R = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
prs = Presentation(src)
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


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


def run_replace(s, name, old, new):
    hits = [r for p in named(s, name).text_frame.paragraphs for r in p.runs if old in r.text]
    assert len(hits) == 1, (name, old, len(hits))
    hits[0].text = hits[0].text.replace(old, new)


def notes_replace(s, old, new):
    nf = s.notes_slide.notes_text_frame
    assert old in nf.text, old
    nf.text = nf.text.replace(old, new)


def pfmt(p):
    return 'p < 0.001' if p < 0.001 else f'p = {p:.3f}' if p < 0.01 else f'p = {p:.2f}'


def sgn(v, fmt='+.1f'):
    return format(v, fmt).replace('-', '−')


PB = pd.read_csv(os.path.join(R, 'pca_baseline_summary.csv')).set_index('shift')
p0, ph, p1 = PB.loc[0], PB.loc[0.5], PB.loc[1]
lo, hi = PB.v2_vs_pca_cum_diff.min(), PB.v2_vs_pca_cum_diff.max()          # vs [8] re-estimated per block
worst_p = PB.v2_vs_pca_cum_p.max()

# ------------------------------------------------------------------ work log (2/2): one more row
lg = find('工作紀錄（2/2）')
tbl = named(lg, 'Table log').table
height = sum(r.height for r in list(tbl.rows)[1:])
tr = copy.deepcopy(tbl._tbl.tr_lst[-1])
tbl._tbl.append(tr)
row = list(tbl.rows)[-1]
texts = ('10/27', '比較組：Zanghieri 2023 [8] 免標籤 PCA 對齊（逐 block 重估，分類器不更新）',
         f"[8] 沒偏移 {sgn(p0.pca_cum_vs_fixed_diff)}（{pfmt(p0.pca_cum_vs_fixed_p)}）、偏 ½ 格 {sgn(ph.pca_cum_vs_fixed_diff)}（{pfmt(ph.pca_cum_vs_fixed_p)}）；"
         f"v2 每種偏移都比 [8] 高 {lo:.1f}–{hi:.1f} 點（p ≤ {worst_p:.3f}）")
for c, t in zip(row.cells, texts):
    paras = c.text_frame.paragraphs
    paras[0].runs[0].text = t
    for r in paras[0].runs[1:]:
        r._r.getparent().remove(r._r)
    for p in paras[1:]:
        p._p.getparent().remove(p._p)
n = len(tbl.rows) - 1
for r in list(tbl.rows)[1:]:
    r.height = int(height / n)
title_shape(lg)                                                          # title unchanged

# ------------------------------------------------------------------ 和最接近的研究
c3 = find('和最接近的研究')
run_replace(c3, 'Text 1', '（[8] 只做特徵層對齊）',
            f"（[8] 只做特徵層對齊；同一份資料上 v2 每種偏移都比它高 {lo:.0f}–{hi:.0f} 點）")
notes_replace(c3, '但只做特徵層的主成分對齊、不更新分類器；',
              '但只做特徵層的主成分對齊、不更新分類器；我把它的方法套在同一份資料上比過，'
              f"沒偏移時它反而掉 {-p0.pca_cum_vs_fixed_diff:.1f} 點，韌體 v2 在每種偏移下都比它高 {lo:.0f} 到 {hi:.0f} 點；")

# ------------------------------------------------------------------ checks
for p_, sl in enumerate(prs.slides, start=1):
    for f in sl.shapes._spTree.iter(A_NS + 'fld'):
        if f.get('type') == 'slidenum':
            f.find(A_NS + 't').text = str(p_)
assert len(prs.slides) == 21
prs.save(dst)
print('saved', dst, 'slides:', len(prs.slides))
print(' | '.join(texts))
