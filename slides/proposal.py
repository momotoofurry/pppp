"""Proposal deck for the new direction (2026-11-13): 碩論計畫書_MOMO.pptx. Every number is read from results/.

The deck is a single file edited in place from now on (the user's choice, 2026-11-13); this script rebuilds it from
scratch. Before overwriting, check whether the user has edited the existing file (mtime / md5): if so, build on
their version instead.
Usage (container, Downloads mounted at /d):  python slides/proposal.py /d/碩論計畫書_MOMO.pptx
"""
import os
import re
import sys
from copy import deepcopy

import numpy as np
import pandas as pd
from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, 'results')
FONT = 'Microsoft JhengHei'
NAVY, TEAL, TEAL_L, CORAL, INK, GREY, LIGHT, WHITE, MUTE = (
    '0B2E3A', '0F7C80', 'DCEFEF', 'E8573F', '1F2A30', '5B6770', 'F1F5F6', 'FFFFFF', 'A9B4BA')
W, H = 13.333, 7.5
DATE = '2026-11-14'


# ------------------------------------------------------------------ data (all from results/)
def csv(name):
    return pd.read_csv(os.path.join(R, name))


def kyr_block1(df, conds, extra=None):
    d = df[(df.comp == 'A1') & (df.block == 1) & df.cond.isin(conds)]
    if extra is not None:
        d = d[extra(d)]
    return (d.groupby(['cond', 'subject']).acc.mean() * 100).groupby(level='cond').mean()


def load():
    N = {}
    ex = csv('external_check_summary.csv')
    r = ex[(ex.span == '0-2s') & (ex.comp == 'A1')].iloc[0]
    N['pre'] = dict(F=r.F, A=r.A, diff=r['diff'], lo=r.ci_lo, hi=r.ci_hi, n=int(r.n))
    k = kyr_block1(csv('leaf_external.csv'), ['F', 'A', 'LAonly_a8_za', 'R'])
    k2 = kyr_block1(csv('lda_main.csv'), ['cum_T2'], lambda d: d.data == 'ext')
    N['kyr'] = {**k.to_dict(), **k2.to_dict()}
    la = csv('lda_anchor_summary.csv')
    la = la[la.stream == 'base'].set_index(['shift', 'cond']).acc
    N['lda'] = {s: dict(RF=la[(s, 'F')], LDAfix=la[(s, 'LDAfix')], LDAfixS=la[(s, 'LDAfixS')]) for s in (0.0, 0.5)}
    lm = csv('lda_main_summary.csv')
    lm = lm[lm.stream == 'base'].set_index(['shift', 'cond']).acc
    N['cumT2'] = {s: lm[(s, 'cum_T2')] for s in (0.0, 0.5)}
    a = csv('arm_ldacal_size.csv').iloc[0]
    N['ldacal'] = dict(text=int(a.text), ram=int(a.bss + a.data))
    txt = open(os.path.join(R, 'lda_bench_board_480mhz_cache.txt'), encoding='utf-8').read()
    first = txt.split('60 more rows')[0]
    us = {m.group(1): float(m.group(2)) for m in re.finditer(r'(ld_\w+)\s+n=\s*\d+\s+mean\s+\d+ cyc\s+([\d.]+) us', first)}
    tot = {m.group(1): float(m.group(2)) for m in re.finditer(r'(ld_\w+)\s+n=.*total\s+([\d.]+) us', first)}
    N['bench'] = dict(add_total_ms=tot['ld_add'] / 1000, fit_ms=us['ld_fit'] / 1000, predict_us=us['ld_predict'])
    fw = open(os.path.join(R, 'arm_rt_lda_firmware_size.txt'), encoding='utf-8').read()
    sec = {m.group(1): int(m.group(2)) for m in re.finditer(r'^\.(\S+)\s+(\d+)\s+\d+', fw, re.M)}
    N['fw'] = dict(flash=sum(sec[s] for s in ('isr_vector', 'text', 'rodata', 'ARM', 'init_array', 'fini_array', 'data')),
                   ram=sec['data'] + sec['bss'], buf=120 * 80 * 4)
    b = csv('board_replay_lda_all_summary.csv').set_index('Unnamed: 0').value
    N['board'] = dict(windows=int(float(b['scored_windows'])), same=int(float(b['same_class_as_pc'])),
                      cmds=int(float(b['commands_board'])), cmds_eq=str(b['commands_equal']) == 'True',
                      p95=float(b['latency_p95']), lmax=float(b['latency_max']), lost=int(float(b['lost_packets'])))
    rk = csv('lda_reject_rank.csv')
    g = rk[(rk.rule == 'margin') & (rk.keep == 0.9)].groupby(['data', 'comp'])[['acc', 'acc_all']].mean()
    N['reject_gain'] = (g.acc - g.acc_all).min(), (g.acc - g.acc_all).max()
    op = csv('lda_reject_open.csv').groupby('rule').unknown_trigger.mean()
    N['open'] = dict(none=csv('lda_reject_open.csv').unknown_trigger_noreject.mean(), margin=op['margin'], both=op['both'])
    t2 = csv('task_sim2_summary.csv').set_index(['shift', 'p_dev', 'cond'])
    N['t2'] = t2
    t3 = csv('task_sim3_summary.csv').set_index(['struct', 'shift', 'cond'])
    N['t3'] = t3
    N['t4'] = csv('task_sim4_summary.csv').set_index(['shift', 'e', 'cond'])
    N['t5'] = csv('task_sim5_summary.csv').set_index(['shift', 'k', 'kind', 'e', 'cond'])
    sb = open(os.path.join(R, 'lda_soft_bench_board_480mhz_cache.txt'), encoding='utf-8').read().split('soft labels')[1]
    N['soft_cmd_ms'] = float(re.search(r'per command\s+n=\s*\d+\s+mean\s+\d+ cyc\s+([\d.]+) us', sb).group(1)) / 1000
    bt = csv('board_replay_lda_task_summary.csv').set_index('Unnamed: 0').value
    N['btask'] = dict(windows=int(float(bt['scored_windows'])), same=int(float(bt['same_class_as_pc'])),
                      cmds=int(float(bt['commands_board'])), cmds_eq=str(bt['commands_equal']) == 'True',
                      upd=int(float(bt['task_updates_board'])), p95=float(bt['latency_p95']),
                      lost=int(float(bt['lost_packets'])), us_max=float(bt['task_us_max']))
    rt = csv('rt_task_check.csv').sum()
    N['rt_task'] = dict(windows=int(rt.windows), agree=int(rt.agree), upd=int(rt.upd_c), same=int(rt.q_arg_same))
    g = csv('rt_gate_check.csv').sum()
    N['rt_gate'] = dict(windows=int(g.windows), agree=int(g.agree), gated_agree=int(g.gated_agree))
    fwg = open(os.path.join(R, 'arm_rt_lda_gate_firmware_size.txt'), encoding='utf-8').read().splitlines()[-1].split()
    N['fw_gate'] = dict(flash=int(fwg[0]) + int(fwg[1]), ram=int(fwg[1]) + int(fwg[2]))
    ros = open(os.path.join(R, 'logs', 'test_task_labels_ros.log'), encoding='utf-8').read()
    m = re.search(r'(\d+) labels .*?: (\d+) applied', ros)
    N['ros'] = dict(labels=int(m.group(1)), applied=int(m.group(2)),
                    actions=len(re.findall(r"'end'", ros.split('robot actions')[1])))
    sim = csv('db6_sim.csv')
    sim = sim[sim.e == 0].groupby(['method', 'subject']).acc.mean().groupby('method').mean()
    adj = csv('db6_adj.csv')
    adj = adj[adj.e == 0].groupby(['method', 'subject']).acc_next.mean().groupby('method').mean()
    N['db6'] = dict(same={m: sim[m] for m in ('fixed', 'LDACMA', 'cue1', 'cue1_soft')},
                    next={m: adj[m] for m in ('fixed', 'LDACMA', 'cue1', 'cue1_soft')})
    bg = csv('board_replay_lda_gate_summary.csv').set_index('Unnamed: 0').value
    def lat(tag):
        x = csv(f'board_replay_lda{tag}_windows.csv').latency_ms.dropna()
        return [float(x.quantile(q)) for q in (0.5, 0.95, 0.99)]
    rt = {k: csv(f'board_replay_lda{t}_summary.csv').set_index('Unnamed: 0').value for k, t in (('rtos', '_rtos2'), ('stress', '_rtos_stress'))}
    N['rtos'] = dict(lat={k: lat(t) for k, t in (('bare', '_task'), ('rtos', '_rtos2'), ('stress', '_rtos_stress'))},
                     same=int(float(rt['stress']['same_class_as_pc'])), windows=int(float(rt['stress']['scored_windows'])),
                     idle=float(rt['rtos']['rtos_cpu_idle_median_pct']), idle_stress=float(rt['stress']['rtos_cpu_idle_median_pct']),
                     learn_stress=float(rt['stress']['rtos_cpu_learn_median_pct']),
                     rx_stack=int(float(rt['rtos']['rtos_rx_stack_max'])), learn_stack=int(float(rt['rtos']['rtos_learn_stack_max'])))
    nn = csv('nn_compare.csv')
    N['nn'] = {k: nn.groupby(['method', 'subject'])[k].mean().groupby('method').mean() for k in ('same', 'next')}
    mb = open(os.path.join(R, 'mlp_bench_board_480mhz_cache.txt'), encoding='utf-8').read()
    us = {m.group(1).strip(): float(m.group(2)) for m in re.finditer(r'^  (\S.*?)\s+n=\s*\d+\s+mean\s+([\d.]+) us', mb, re.M)}
    N['mlpb'] = dict(lda_pred=us['ld_predict'], mlp_pred=us['mlp_predict'], lda_upd=us['lda cue update'] / 1000,
                     mlp_upd=us['mlp fine-tune'] / 1000, lda_ram=int(re.search(r'ldacal static (\d+) B', mb).group(1)),
                     mlp_ram=int(re.search(r'mlp static (\d+) B', mb).group(1)))
    N['bgate'] = dict(windows=int(float(bg['scored_windows'])), same=int(float(bg['same_class_as_pc'])),
                      gsame=int(float(bg['gated_same_as_pc'])), acc=float(bg['acc_board']))
    return N


# ------------------------------------------------------------------ drawing helpers
def rgb(h):
    return RGBColor.from_string(h)


def set_ea(rpr):
    """East Asian and complex-script typefaces next to a:latin, in schema order (latin, ea, cs)"""
    prev = rpr.find(qn('a:latin'))
    for tag in ('a:ea', 'a:cs'):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
            if prev is not None:
                prev.addnext(el)
        el.set('typeface', FONT)
        prev = el


def style(run, size, bold=False, color=INK, italic=False):
    f = run.font
    f.size, f.bold, f.italic, f.name = Pt(size), bold, italic, FONT
    f.color.rgb = rgb(color)
    set_ea(run._r.get_or_add_rPr())


def text(slide, x, y, w, h, paras, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         name=None, space=6, bullet=False):
    """paras: str or list of str / (str, dict) ; dict keys size, bold, color, bullet, italic"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = anchor
    if isinstance(paras, str):
        paras = [paras]
    for i, p in enumerate(paras):
        t, o = (p, {}) if isinstance(p, str) else p
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = o.get('align', align)
        para.space_after = Pt(o.get('space', space))
        if o.get('bullet', bullet):
            ppr = para._p.get_or_add_pPr()
            ppr.set('marL', str(Inches(0.28)))
            ppr.set('indent', str(-Inches(0.22)))
            bu = etree.SubElement(ppr, qn('a:buChar'))
            bu.set('char', '•')
        runs = t if isinstance(t, list) else [(t, {})]
        for rt in runs:
            s, ro = (rt, {}) if isinstance(rt, str) else rt
            r = para.add_run()
            r.text = s
            style(r, ro.get('size', o.get('size', size)), ro.get('bold', o.get('bold', bold)),
                  ro.get('color', o.get('color', color)), ro.get('italic', o.get('italic', False)))
    return tb


def box(slide, x, y, w, h, fill=LIGHT, shape=MSO_SHAPE.ROUNDED_RECTANGLE, line=None, name=None, radius=0.08):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        s.name = name
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(1.25)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.text_frame.text = ''
    return s


def label_in(shape, paras, size=14, color=INK, bold=False, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.1)
    if isinstance(paras, str):
        paras = [paras]
    for i, p in enumerate(paras):
        t, o = (p, {}) if isinstance(p, str) else p
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = o.get('align', align)
        r = para.add_run()
        r.text = t
        style(r, o.get('size', size), o.get('bold', bold), o.get('color', color))


def circle_num(slide, x, y, n, fill=TEAL, d=0.5):
    c = box(slide, x, y, d, d, fill=fill, shape=MSO_SHAPE.OVAL)
    label_in(c, str(n), size=16, color=WHITE, bold=True)
    return c


def arrow(slide, x, y, w, h, fill=MUTE, kind=MSO_SHAPE.RIGHT_ARROW):
    return box(slide, x, y, w, h, fill=fill, shape=kind)


class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(W), Inches(H)
        self.n = 0

    def slide(self, title=None, dark=False, notes=''):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        self.n += 1
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(NAVY if dark else WHITE)
        if title:
            text(s, 0.6, 0.42, 12.1, 0.8, title, size=30, bold=True, color=WHITE if dark else INK,
                 anchor=MSO_ANCHOR.MIDDLE, name='Title')
        if not dark:
            text(s, 0.6, 7.02, 8, 0.3, f'碩士論文計畫書（草案）｜{DATE}｜方向待指導老師確認', size=10, color=MUTE, name='Footer')
            text(s, 11.9, 7.02, 0.83, 0.3, str(self.n), size=10, color=MUTE, align=PP_ALIGN.RIGHT, name='Page')
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s


def chart_style(chart, legend=False, vmax=100, vmin=None, fmt='0.0', label_size=12, axis_size=12):
    chart.font.size = Pt(axis_size)
    chart.font.name = FONT
    tx = chart._chartSpace.find(qn('c:txPr'))
    if tx is not None:
        for d in tx.iter(qn('a:defRPr')):
            set_ea(d)
    chart.has_title = False
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(axis_size)
    plot = chart.plots[0]
    plot.gap_width = 55
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format, dl.number_format_is_linked = fmt, False
    dl.font.size = Pt(label_size)
    dl.font.color.rgb = rgb(INK)
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    va = chart.value_axis
    va.maximum_scale = vmax
    if vmin is not None:
        va.minimum_scale = vmin
    va.has_major_gridlines = False
    va.visible = False
    ca = chart.category_axis
    ca.tick_labels.font.size = Pt(axis_size)
    ca.tick_labels.font.color.rgb = rgb(INK)
    ca.format.line.color.rgb = rgb(MUTE)


def color_series(chart, colors):
    for s, c in zip(chart.plots[0].series, colors):
        s.format.fill.solid()
        s.format.fill.fore_color.rgb = rgb(c)


def color_points(series, colors):
    for i, c in enumerate(colors):
        p = series.points[i]
        p.format.fill.solid()
        p.format.fill.fore_color.rgb = rgb(c)


def table(slide, x, y, w, rows, widths, size=12, header_fill=TEAL, row_h=0.42, fills=None):
    t = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(row_h * len(rows))).table
    for j, cw in enumerate(widths):
        t.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        t.rows[i].height = Inches(row_h)
        for j, val in enumerate(row):
            c = t.cell(i, j)
            c.margin_left = c.margin_right = Inches(0.08)
            c.margin_top = c.margin_bottom = Inches(0.04)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.fill.solid()
            if i == 0:
                c.fill.fore_color.rgb = rgb(header_fill)
            else:
                c.fill.fore_color.rgb = rgb((fills or {}).get((i, j), WHITE if i % 2 else LIGHT))
            tf = c.text_frame
            tf.word_wrap = True
            tf.paragraphs[0].text = ''
            r = tf.paragraphs[0].add_run()
            r.text = str(val)
            style(r, size, bold=(i == 0 or j == 0 and False), color=WHITE if i == 0 else INK)
    return t


# ------------------------------------------------------------------ slides
def build(out):
    N = load()
    d = Deck()
    k, pre, lda = N['kyr'], N['pre'], N['lda']
    t2, t3 = N['t2'], N['t3']

    # 1 cover
    s = d.slide(dark=True, notes='題目與狀態。方向是 2026-11-10～11-13 依實驗結果調整出來的，尚未與指導老師確認；凍結版韌體與 PROTOCOL 未改。')
    text(s, 0.9, 1.5, 11.5, 0.5, '碩士論文計畫書（草案）', size=18, color='8FD3D0')
    text(s, 0.9, 2.1, 11.6, 2.0, ['可在微控制器上執行的肌電介面每次配戴校正',
                                    ('從免標籤適應到機器人任務提供的標籤', {'size': 26, 'bold': False, 'color': 'CFE3E6'})],
         size=36, bold=True, color=WHITE, space=10)
    text(s, 0.9, 4.75, 11, 1.2, ['機器人研究所｜生物力學與醫學應用實驗室', '報告人：【待填】　指導教授：【待填】',
                                  (f'{DATE}　方向尚待指導老師確認', {'color': '8FD3D0'})], size=16, color='CFE3E6', space=4)

    # 2 one page
    s = d.slide('一頁看懂：關鍵在標籤，不在模型', notes=(
        f'三個數字的出處：(1) Kyranou 等（2025）跨日重戴資料第二個 session（較嚴格的看法），固定 one-shot 隨機森林 {k["F"]:.1f}%、'
        f'免標籤自我校正 {k["A"]:.1f}%、收縮 LDA 兩輪提示累積 {k["cum_T2"]:.1f}%（report 35.16；leaf_external.csv、lda_main.csv）。'
        f'(2) STM32H753 實測（report 35.10）。(3) 閉迴路模擬（report 35.17–35.19），不是實機結果。'))
    text(s, 0.6, 1.35, 12.1, 0.6, '每天重新戴上肌電介面後準確率會掉。原方法用免標籤自我校正補救，但在獨立的重戴資料上沒有確認效果；'
         '真正有效的是少量有標籤資料。本研究問：標籤能不能大部分由機器人任務提供？', size=15, color=GREY)
    cards = [(f'{k["F"]:.0f}% → {k["cum_T2"]:.0f}%', '跨日重戴後，每次配戴 16 秒有標籤校正', f'免標籤自我校正只有 {k["A"]:.0f}%（Kyranou 等，2025）'),
             (f'{N["ldacal"]["ram"] / 1024:.1f} KB', 'STM32H753 上的 LDA 校正模組',
              f'每次更新 {N["bench"]["add_total_ms"] + N["bench"]["fit_ms"]:.1f} ms、推論 {N["bench"]["predict_us"]:.1f} µs'),
             ('8 秒 ≈ 16 秒', '一輪提示＋任務標籤', '效果約等於兩輪提示，使用者主動給的標籤少一半（模擬）')]
    for i, (big, lab, sub) in enumerate(cards):
        x = 0.6 + i * 4.1
        box(s, x, 2.35, 3.8, 3.9, fill=LIGHT)
        text(s, x + 0.25, 2.65, 3.3, 1.2, big, size=40, bold=True, color=TEAL if i < 2 else CORAL)
        text(s, x + 0.25, 3.95, 3.3, 0.9, lab, size=17, bold=True)
        text(s, x + 0.25, 4.95, 3.3, 1.1, sub, size=14, color=GREY)
    text(s, 0.6, 6.45, 12.1, 0.4, '前兩項有外部資料與板上實測；第三項只有模擬，公開資料（NinaPro DB6）上換下一個 session 評分時不明顯，要在實機上確認。', size=13, color=GREY)

    # 3 background
    s = d.slide('研究背景', notes='校正負擔：Wang 等（2024）綜述（使用者文獻清單已有）。原方法：Jiang 等（2024）Front Neurorobot、Jiang 等（2025）J Neural Eng。'
                '應用情境與設備：Kinova Gen3＋Robotiq 2F-85＋RealSense、Delsys Trigno 8 通道。')
    items = [('每天重新配戴', '電極位置、皮膚與姿勢改變，昨天的模型今天就不準'),
             ('校正是負擔', '每次重新錄每個手勢，使用者容易放棄（Wang 等，2024）'),
             ('原方法', '預訓練隨機森林＋一次校正＋免標籤自我校正（Jiang 等，2024；2025）'),
             ('應用情境', '上肢功能受限者用離散手勢指揮輔助機械臂抓放；使用者決定做什麼，機械臂負責怎麼做')]
    for i, (h, b) in enumerate(items):
        y = 1.45 + i * 1.32
        circle_num(s, 0.6, y + 0.12, i + 1)
        text(s, 1.3, y, 5.3, 0.45, h, size=19, bold=True)
        text(s, 1.3, y + 0.48, 5.3, 0.75, b, size=14, color=GREY)
    box(s, 7.2, 1.5, 5.5, 5.15, fill=TEAL_L)
    text(s, 7.5, 1.75, 4.9, 4.7, [('設備', {'size': 19, 'bold': True}),
                                   ('Delsys Trigno 8 通道 sEMG（2 kHz），束帶繞前臂一圈', {'bullet': True}),
                                   ('STM32H753（NUCLEO-H753ZI，Cortex-M7 480 MHz）', {'bullet': True}),
                                   ('Kinova Gen3 7 軸＋Robotiq 2F-85＋腕部 RealSense', {'bullet': True}),
                                   ('ROS 2（ros2_kortex），PC 只轉送原始樣本', {'bullet': True}),
                                   ('6 個手勢 → 5 個指令', {'size': 19, 'bold': True}),
                                   ('Power＝到 A、Pointer＝到 B、Tripod＝夾、Open＝放、Lateral＝回原位、Rest＝不動', {'bullet': True})],
         size=15, space=8)

    # 4 motivation 1
    s = d.slide('動機①：免標籤自我校正在獨立資料上沒有確認效果', notes=(
        f'預先登錄的外部驗證（report 24；external_check_summary.csv，0–2 s、A1 跨日）：固定 {pre["F"]:.2f}% → 完整系統 {pre["A"]:.2f}%，'
        f'差 {pre["diff"]:+.2f} 點（95% CI {pre["lo"]:+.2f}, {pre["hi"]:+.2f}），{pre["n"]} 人。'
        f'較嚴格的看法（第二個 session，report 35.16）：{k["F"]:.1f}% → {k["A"]:.1f}%。開發資料上同一比較是 +4.9 點，但設定是在同一批人上挑的。'))
    box(s, 0.6, 1.5, 5.6, 4.9, fill=LIGHT)
    text(s, 0.9, 1.75, 5.0, 0.5, '預先登錄的外部驗證', size=17, bold=True, color=GREY)
    text(s, 0.9, 2.3, 5.0, 1.2, f'{pre["diff"]:+.2f} 點', size=54, bold=True, color=CORAL)
    text(s, 0.9, 3.55, 5.0, 0.5, f'95% CI {pre["lo"]:+.2f} 到 {pre["hi"]:+.2f}', size=18, bold=True)
    text(s, 0.9, 4.2, 5.0, 2.0, [f'Kyranou 等（2025）{pre["n"]} 人兩天、真的重新配戴', '分析計畫在看資料前就 commit',
                                  '開發資料上看起來有效（+4.9 點），獨立資料上沒有確認'], size=14, color=GREY, bullet=True)
    cd = CategoryChartData()
    cd.categories = ['固定模型', '免標籤自我校正']
    cd.add_series('第二個 session', (round(k['F'], 1), round(k['A'], 1)))
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(6.7), Inches(1.6), Inches(6.0), Inches(4.6), cd)
    chart_style(gf.chart, vmax=100, vmin=0, label_size=16, axis_size=14)
    color_points(gf.chart.plots[0].series[0], [MUTE, GREY])
    text(s, 6.7, 6.25, 6.0, 0.5, '跨日重戴、較嚴格的看法（不含開機序列所在的 session），準確率 %', size=12, color=GREY)

    # 5 motivation 2
    s = d.slide('動機②：標籤比模型重要', notes=(
        'Kyranou 跨日資料第二個 session（report 35.16 的更正版本）。葉節點計數＝自己提出的第一個方法（樹不重訓，開機標籤累加到葉節點），'
        '重做 one-shot＝每次配戴重做原方法的校正，LDA＝收縮估計、兩輪提示、標籤累積。資料已用過，只當一致性檢查。'))
    cats = ['固定模型（隨機森林）', '免標籤自我校正', '葉節點計數（開機標籤）', '重做 one-shot 校正', '收縮 LDA（兩輪提示）']
    vals = [k['F'], k['A'], k['LAonly_a8_za'], k['R'], k['cum_T2']]
    cd = CategoryChartData()
    cd.categories = cats
    cd.add_series('準確率', [round(v, 1) for v in vals])
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.45), Inches(7.6), Inches(5.0), cd)
    chart_style(gf.chart, vmax=105, vmin=0, label_size=15, axis_size=14)
    gf.chart.category_axis.reverse_order = True
    color_points(gf.chart.plots[0].series[0], [MUTE, MUTE, TEAL, TEAL, CORAL])
    text(s, 0.6, 6.5, 7.6, 0.4, '跨日重戴（Kyranou 等，2025）第二個 session，準確率 %；灰＝沒有標籤，綠＝有標籤', size=12, color=GREY)
    box(s, 8.6, 1.6, 4.1, 4.85, fill=TEAL_L)
    text(s, 8.9, 1.85, 3.6, 4.4, [('看到的事', {'size': 19, 'bold': True}),
                                   (f'沒有標籤：{k["F"]:.0f}% → {k["A"]:.0f}%', {'bullet': True}),
                                   (f'有標籤：{min(k["LAonly_a8_za"], k["R"]):.0f}–{k["cum_T2"]:.0f}%', {'bullet': True}),
                                   ('有了標籤之後，用什麼模型差距不大', {'bullet': True}),
                                   ('所以要問的是', {'size': 19, 'bold': True}),
                                   ('標籤能不能不由使用者給？', {'size': 17, 'bold': True, 'color': CORAL})], size=15, space=8)

    # 6 motivation 3
    s = d.slide('動機③：原方法論文的 LDA 基準偏弱', notes=(
        '原論文的 LDA 基準：sklearn 預設，只用 60 個校正視窗、80 維特徵，共變異數奇異。加 Ledoit-Wolf 收縮後與 one-shot 隨機森林在無偏移時相同（report 35.9；lda_anchor_summary.csv，開發資料 20 人）。'
        '是否已有文獻指出這點，還要查。'))
    cd = CategoryChartData()
    cd.categories = ['無偏移', '電極偏移半格']
    cd.add_series('one-shot 隨機森林', [round(lda[s_]['RF'], 1) for s_ in (0.0, 0.5)])
    cd.add_series('LDA（原論文的做法）', [round(lda[s_]['LDAfix'], 1) for s_ in (0.0, 0.5)])
    cd.add_series('LDA（加收縮估計）', [round(lda[s_]['LDAfixS'], 1) for s_ in (0.0, 0.5)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.45), Inches(7.8), Inches(5.0), cd)
    chart_style(gf.chart, legend=True, vmax=100, vmin=0, label_size=14, axis_size=14)
    color_series(gf.chart, [MUTE, CORAL, TEAL])
    text(s, 0.6, 6.5, 7.8, 0.4, '開發資料 20 人，只用第 1 天校正、不更新，準確率 %', size=12, color=GREY)
    box(s, 8.8, 1.6, 3.9, 4.85, fill=LIGHT)
    text(s, 9.1, 1.85, 3.4, 4.4, [('原因', {'size': 19, 'bold': True}),
                                   ('60 個校正視窗、80 維特徵：共變異數不可逆', {'bullet': True}),
                                   ('加收縮後，固定 LDA 與隨機森林在無偏移時一樣', {'bullet': True}),
                                   ('有偏移時隨機森林仍好約 9 點', {'bullet': True}),
                                   ('意義', {'size': 19, 'bold': True}),
                                   ('隨機森林的優勢被高估；有了每次配戴的標籤，LDA 更省也更準', {'bullet': True})], size=15, space=8)

    # 7 RQ
    s = d.slide('研究問題', notes='RQ1–RQ3 已有前置結果，RQ4 待做。')
    rqs = [('RQ1 校正策略', '重新配戴後，免標籤適應、短時有標籤校正、任務提供的標籤各能恢復多少準確率？代價是多少？', '已有結果'),
           ('RQ2 任務標籤', '機器人任務能提供多可靠的標籤？標籤錯誤、任務結構、使用者偏離流程的影響？', '模擬完成（含和 CIIL 比較、錯標籤掃描）'),
           ('RQ3 可部署性', '整套方法能否在微控制器上即時執行、與 PC 參考逐一相同？記憶體、時間、能量？', '板上實測完整學習迴路（能量未量）'),
           ('RQ4 驗證', '真人（健常人為主、視情況加病患）與真實機械臂上是否成立？', '待做')]
    for i, (h, b, st) in enumerate(rqs):
        x, y = 0.6 + (i % 2) * 6.15, 1.5 + (i // 2) * 2.65
        box(s, x, y, 5.95, 2.4, fill=LIGHT)
        text(s, x + 0.3, y + 0.25, 5.3, 0.5, h, size=20, bold=True, color=TEAL)
        text(s, x + 0.3, y + 0.85, 5.3, 1.0, b, size=15)
        text(s, x + 0.3, y + 1.85, 5.3, 0.4, st, size=13, bold=True, color=CORAL if st == '待做' else GREY)

    # 8 architecture
    s = d.slide('系統架構', notes='PC 在資料路徑上只因 Trigno 基地台只有 USB 輸出，不做肌電運算。機器人回傳任務結果只有幾個位元組。'
                '資料傳輸：PC→板子每 10 ms 一個 329 B 的封包（約 33 KB/s，921600 baud 的 36%）。')
    blocks = [(0.6, 'Trigno\n8 通道 sEMG\n2 kHz', LIGHT, INK), (3.0, 'PC\n只轉送\n原始樣本', LIGHT, INK),
              (5.4, 'STM32H753\n全部肌電運算\n與模型更新', TEAL, WHITE), (8.6, 'ROS 2\n任務狀態機', LIGHT, INK),
              (11.0, 'Kinova Gen3\n＋夾爪', LIGHT, INK)]
    for x, t, f, c in blocks:
        b = box(s, x, 1.7, 2.0 if x != 5.4 else 2.7, 1.45, fill=f)
        label_in(b, [(ln, {'size': 15 if j else 17, 'bold': j == 0}) for j, ln in enumerate(t.split('\n'))], color=c)
    for x in (2.65, 5.05, 8.15, 10.65):
        arrow(s, x, 2.25, 0.32, 0.35)
    b = box(s, 5.4, 3.65, 6.2, 0.75, fill=TEAL_L, radius=0.3)
    label_in(b, '← 任務結果回傳（幾個位元組）：這次指令對不對、原本要什麼', size=14)
    steps = ['濾波、200 ms 視窗', '80 個特徵', '本次配戴 z-score', '收縮 LDA', '出力判斷', '拒絕', '連續 3 視窗成立', '軟標籤更新']
    for i, st in enumerate(steps):
        x = 0.6 + i * 1.53
        b = box(s, x, 5.0, 1.38, 0.95, fill=WHITE, line=TEAL)
        label_in(b, st, size=13)
    text(s, 0.6, 4.55, 12, 0.4, 'STM32 上每 100 ms 的流程', size=15, bold=True, color=TEAL)
    text(s, 0.6, 6.15, 12.1, 0.6, '指令只在當下做得出事時才有效（例如沒夾著東西時「放」無效）；機器人動作中收到的指令忽略。', size=13, color=GREY)

    # 9 method flow
    s = d.slide('方法：每次配戴的流程', notes='一輪提示序列＝依提示依序做 6 個手勢（約 8 秒）。z-score 用這段的統計量；LDA 的累加量跨次累積，不存樣本。'
                '只做提示的話要兩輪（約 16 秒）才有同樣效果（report 35.11、35.17）。')
    flow = [('戴上', '束帶依記號戴好'), ('一輪提示（8 秒）', '依提示做 6 個手勢\n→ 本次 z-score\n→ 加進 LDA 累加量'),
            ('使用中', '指揮機械臂抓放\n出力判斷擋掉休息時的誤觸發'), ('任務提供標籤', '機器人狀態推出可能的下一步\n→ 軟標籤 → 更新 LDA')]
    for i, (h, b) in enumerate(flow):
        x = 0.6 + i * 3.15
        circle_num(s, x, 1.55, i + 1, fill=CORAL if i == 3 else TEAL, d=0.6)
        box(s, x, 2.35, 2.85, 2.6, fill=TEAL_L if i == 3 else LIGHT)
        text(s, x + 0.2, 2.55, 2.45, 0.5, h, size=18, bold=True)
        text(s, x + 0.2, 3.15, 2.45, 1.7, b.split('\n'), size=14, color=GREY, space=4)
        if i < 3:
            arrow(s, x + 2.88, 3.45, 0.24, 0.35)
    box(s, 0.6, 5.3, 12.1, 1.35, fill=LIGHT)
    text(s, 0.9, 5.45, 11.5, 1.1, [('收縮 LDA，以累加量表示', {'size': 17, 'bold': True}),
                                    '每類的和與筆數＋一個 80×80 外積和；OAS 收縮（只需共變異數與筆數）＋Cholesky。可一直累積、不存樣本，30 KB 內可放進 MCU。'],
         size=14, space=4)

    # 10 method components
    s = d.slide('方法：任務引導的軟標籤與出力判斷', notes='參數 ε 0.15、p0 0.05、β 0.3 在跑模擬前固定，沒有調（report 35.18）。'
                '出力判斷：8 通道原始 MAV 加總，門檻＝第 1 天校正 Rest 中位數與最小手勢中位數的幾何平均。')
    box(s, 0.6, 1.5, 6.0, 3.65, fill=LIGHT)
    text(s, 0.9, 1.7, 5.4, 0.5, '軟標籤', size=21, bold=True, color=TEAL)
    text(s, 0.9, 2.3, 5.4, 0.9, 'q(g) ∝ 先驗(g｜機器人狀態) × exp(β × g 的平均判別值)', size=16, bold=True)
    text(s, 0.9, 3.25, 5.4, 3.2, ['先驗把大部分機率給系統眼中可能的下一步，保留一點給其他有效指令',
                                   '使用者臨時改主意時，肌電的證據會把機率拉回來',
                                   '外積和不需要標籤，只有類別的和與筆數按 q 加權：MCU 上成本不變'], size=14, bullet=True, space=8)
    box(s, 6.9, 1.5, 5.8, 3.65, fill=LIGHT)
    text(s, 7.2, 1.7, 5.2, 0.5, '出力判斷', size=21, bold=True, color=TEAL)
    text(s, 7.2, 2.3, 5.2, 0.9, '8 個通道的訊號強度加總 < 門檻 → 當作休息', size=16, bold=True)
    text(s, 7.2, 3.25, 5.2, 3.2, ['加總對束帶轉動不變：電極偏移時仍可靠',
                                   '休息時不送指令、也不產生標籤',
                                   '同類想法：Scheme 等（2013）的出力門檻；本研究的門檻誤觸發較少（35.30）'], size=14, bullet=True, space=8)
    ga0, ga5 = t2.loc[(0.0, 0.0, 'soft_act')].act_gate_acc, t2.loc[(0.5, 0.0, 'soft_act')].act_gate_acc
    ev = [(f'{ga0:.1f}%', '出力判斷單獨區分「休息／在出力」（無偏移）'), (f'{ga5:.1f}%', '同上，電極偏移半格'),
          ('不變', 'MCU 上的 RAM 與運算量（軟標籤只是加權）')]
    for i, (big, lab) in enumerate(ev):
        x = 0.6 + i * 4.1
        box(s, x, 5.35, 3.85, 1.35, fill=TEAL_L)
        text(s, x + 0.25, 5.45, 3.4, 0.6, big, size=26, bold=True, color=TEAL)
        text(s, x + 0.25, 6.05, 3.4, 0.6, lab, size=13, color=GREY)

    # 11 divider
    s = d.slide(dark=True, notes='以下是目前的結果：MCU 為板上實測；校正策略為開發資料與 Kyranou；任務標籤為模擬。')
    text(s, 0.9, 2.6, 11.5, 1.0, '目前的結果', size=40, bold=True, color=WHITE)
    text(s, 0.9, 3.7, 11.5, 1.6, ['MCU 可部署性：板上實測', '任務標籤：閉迴路模擬、和 CIIL 比較、標籤出錯時', '完整學習迴路：MCU＋ROS 2 模擬手臂', '負面結果與更正'],
         size=18, color='CFE3E6', space=6)

    # 12 MCU
    fw, bd = N['fw'], N['board']
    s = d.slide('結果①：整套方法放得進微控制器', notes=(
        'NUCLEO-H753ZI，480 MHz＋I/D-cache。ldacal.c：arm_ldacal_size.csv；時間：lda_bench_board_480mhz_cache.txt（第一輪 60 筆）；'
        '整個韌體：arm_rt_lda_firmware_size.txt；11 分鐘即時串流：board_replay_lda_all_summary.csv（report 35.10、35.14、35.15）。能量尚未量測。'))
    stats = [(f'{N["ldacal"]["ram"] / 1024:.1f} KB', 'LDA 模組 RAM'), (f'{N["bench"]["add_total_ms"] + N["bench"]["fit_ms"]:.1f} ms', '每次配戴更新（60 筆＋求解）'),
             (f'{N["bench"]["predict_us"]:.1f} µs', '每次推論'), (f'{fw["flash"] / 1024:.0f} KB', '整個韌體 Flash'),
             (f'{fw["ram"] / 1024:.0f} KB', f'整個韌體 RAM（含 {fw["buf"] / 1024:.0f} KB 暫存）'), (f'{bd["p95"]:.1f} ms', '延遲 P95（PC 送出 → 收到結果）')]
    for i, (big, lab) in enumerate(stats):
        x, y = 0.6 + (i % 3) * 4.1, 1.5 + (i // 3) * 2.05
        box(s, x, y, 3.85, 1.8, fill=LIGHT)
        text(s, x + 0.25, y + 0.2, 3.4, 0.85, big, size=34, bold=True, color=TEAL)
        text(s, x + 0.25, y + 1.1, 3.4, 0.6, lab, size=14, color=GREY)
    box(s, 0.6, 5.7, 12.1, 1.05, fill=TEAL_L)
    text(s, 0.9, 5.82, 11.5, 0.85, [(f'即時串流 11 分鐘：{bd["same"]:,}／{bd["windows"]:,} 個視窗、{bd["cmds"]} 個指令和 PC 逐一相同；'
                                     f'掉封包 {bd["lost"]}；最大延遲 {bd["lmax"]:.1f} ms', {'bold': True}),
                                    ('能量尚未量測；PC 只轉送原始樣本（Trigno 基地台只有 USB 輸出）', {'color': GREY})], size=15, space=4)

    # 13 closed loop
    s = d.slide('結果②：閉迴路抓放模擬，標籤由系統自己推', notes=(
        '模擬：使用者照任務流程做抓放（A→夾→B→放→回原位），25% 的時候臨時改變主意；系統只知道機器人狀態與任務流程，沒有正確答案（report 35.17、35.18；task_sim2_summary.csv）。'
        '準確率＝配戴結束後在互動沒看過的 trial 上測的視窗準確率。限制：使用者照固定流程、沒有手勢轉換的過渡段。'))
    cats = ['固定模型', '一輪提示', '一輪＋硬標籤', '一輪＋軟標籤\n＋出力判斷', '兩輪提示', '正確答案（上限）']
    conds = ['fixed', 'cue1', 'cue1_gate', 'cue1_soft_act', 'cue2', 'oracle']
    cd = CategoryChartData()
    cd.categories = cats
    cd.add_series('無偏移', [round(t2.loc[(0.0, 0.25, c)].probe_after, 1) for c in conds])
    cd.add_series('電極偏移半格', [round(t2.loc[(0.5, 0.25, c)].probe_after, 1) for c in conds])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.45), Inches(8.6), Inches(5.0), cd)
    chart_style(gf.chart, legend=True, vmax=100, vmin=40, label_size=12, axis_size=12)
    color_series(gf.chart, [TEAL, CORAL])
    text(s, 0.6, 6.5, 8.6, 0.4, '20 人 × 2 seed，使用者 25% 臨時改變主意，準確率 %', size=12, color=GREY)
    a, b2 = t2.loc[(0.5, 0.25, 'cue1_soft_act')], t2.loc[(0.5, 0.25, 'cue1_gate')]
    box(s, 9.5, 1.6, 3.2, 4.85, fill=LIGHT)
    text(s, 9.75, 1.85, 2.75, 4.4, [('看到的事', {'size': 19, 'bold': True}),
                                     ('一輪提示＋軟標籤＋出力判斷 ≈ 兩輪提示 ≈ 上限', {'bullet': True}),
                                     (f'標籤錯誤率（半格）：硬標籤 {b2.label_err_pct:.1f}% → 軟標籤 {a.label_err_pct:.1f}%', {'bullet': True}),
                                     ('使用者主動給的標籤少一半', {'bullet': True})], size=15, space=10)

    # 14 activity gate + no cue
    h0, h1 = t2.loc[(0.5, 0.0, 'hard')], t2.loc[(0.5, 0.0, 'hard_act')]
    s0, s1 = t2.loc[(0.5, 0.0, 'soft')], t2.loc[(0.5, 0.0, 'cue1')]
    s = d.slide('結果③：出力判斷有效；完全不做提示則不行', notes=(
        '電極偏移半格、使用者照流程（report 35.18）。不做提示序列時，任務標籤的錯誤幾乎都來自休息時的誤觸發；出力判斷把它們擋掉。'
        '軟標籤不做提示時失敗：模型本身不準時，肌電的證據會強化錯誤（類似自我訓練）。'))
    for i, (big, lab, sub, col) in enumerate([
            (f'{h0.label_err_pct:.0f}% → {h1.label_err_pct:.1f}%', '任務標籤的錯誤率', '不做提示、半格偏移；加上出力判斷', TEAL),
            (f'{h0.probe_after:.0f}% → {h1.probe_after:.0f}%', '準確率', '同上', TEAL),
            (f'{s0.probe_after:.0f}%', '不做提示＋軟標籤', f'比固定模型（{t2.loc[(0.5, 0.0, "fixed")].probe_after:.0f}%）還差', CORAL)]):
        x = 0.6 + i * 4.1
        box(s, x, 1.55, 3.85, 3.0, fill=LIGHT)
        text(s, x + 0.25, 1.8, 3.4, 1.0, big, size=36, bold=True, color=col)
        text(s, x + 0.25, 2.9, 3.4, 0.5, lab, size=17, bold=True)
        text(s, x + 0.25, 3.5, 3.4, 0.9, sub, size=14, color=GREY)
    box(s, 0.6, 4.9, 12.1, 1.25, fill=TEAL_L)
    text(s, 0.9, 5.05, 11.5, 1.5, [('結論：一輪提示是必要的起點', {'size': 18, 'bold': True}),
                                    (f'只做一輪提示 {s1.probe_after:.0f}%；模型先夠準，任務標籤才幫得上忙，否則錯誤會自我強化', {'color': INK})],
         size=15, space=6)

    # 15 task structure
    labels = {'fixed': '系統知道\n完整流程', 'known_goal': '被告知\n目的地', 'unknown_goal': '不知道\n目的地', 'free': '沒有\n任務模型'}
    s = d.slide('結果④：任務結構變弱時，軟標籤仍然有效', notes=(
        '新的任務世界：三個地點、目的地每次隨機（report 35.19；task_sim3_summary.csv）。電極偏移半格、使用者 10% 改變目的地。'
        '軟標籤在四種結構都比只做提示好（+1.9 到 +3.0 點，95% CI 不含 0）；硬標籤在沒有任務模型時比只做提示差 5.4 點。事後修正的標籤規則沒有用。'))
    structs = list(labels)
    cd = CategoryChartData()
    cd.categories = [labels[x] for x in structs]
    cd.add_series('一輪提示', [round(t3.loc[(x, 0.5, 'cue1')].probe_after, 1) for x in structs])
    cd.add_series('一輪＋硬標籤', [round(t3.loc[(x, 0.5, 'cue1_hard')].probe_after, 1) for x in structs])
    cd.add_series('一輪＋軟標籤', [round(t3.loc[(x, 0.5, 'cue1_soft')].probe_after, 1) for x in structs])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.45), Inches(8.6), Inches(5.0), cd)
    chart_style(gf.chart, legend=True, vmax=100, vmin=60, label_size=12, axis_size=13)
    color_series(gf.chart, [MUTE, GREY, TEAL])
    text(s, 0.6, 6.5, 8.6, 0.4, '電極偏移半格，準確率 %；由左到右，系統對任務的了解越來越少', size=12, color=GREY)
    e = [t3.loc[(x, 0.5, 'cue1_soft')].label_err_pct for x in structs]
    eh = [t3.loc[(x, 0.5, 'cue1_hard')].label_err_pct for x in structs]
    box(s, 9.5, 1.6, 3.2, 4.85, fill=LIGHT)
    text(s, 9.75, 1.85, 2.75, 4.4, [('看到的事', {'size': 19, 'bold': True}),
                                     ('軟標籤四種情況都比只做提示好', {'bullet': True}),
                                     (f'標籤錯誤率：軟 {min(e):.1f}–{max(e):.1f}%，硬 {min(eh):.1f}–{max(eh):.1f}%', {'bullet': True}),
                                     ('回答「方法是不是只在設計好的任務裡有效」', {'bullet': True})], size=15, space=10)

    # 16 CIIL comparison and wrong task labels
    t4 = N['t4']
    s = d.slide('結果⑤：和最接近的前人方法（CIIL）比，任務標籤出錯時', notes=(
        'Campbell 等（2024）的情境式增量學習（CIIL）對應到本研究的閉迴路抓放模擬（report 35.20；task_sim4_summary.csv）。'
        '先前的硬標籤就是 P+N-CIIL。任務標籤以機率 e 換成隨機的另一個手勢（獨立亂數）。電極偏移半格、使用者 10% 改變主意、一輪提示。'
        '事先寫定的判準 R1（軟標籤比最好的 CIIL 變體多 2 點以上）不通過：P-CIIL 對隨機錯標籤一樣耐。'
        'CIIL 原本的更新式（每 10 秒以 α 0.1 混入）在這種稀疏標籤下比只做提示還差，見備註；漏撤銷（錯的動作被當成對的）影響很小（report 35.21）。'))
    es = [0.0, 0.1, 0.2, 0.3]
    cd = CategoryChartData()
    cd.categories = [f'{int(e * 100)}%' for e in es]
    cue = t4.loc[(0.5, 0.0, 'cue1')].probe_after
    series = [('只做一輪提示', None, MUTE), ('P+N-CIIL（＝硬標籤）', 'cue1_pn', CORAL), ('P-CIIL', 'cue1_pos', GREY),
              ('gate 規則', 'cue1_gate', '7FB7B9'), ('軟標籤（本研究）', 'cue1_soft', TEAL)]
    for name, c, _ in series:
        cd.add_series(name, [round(cue if c is None else t4.loc[(0.5, e, c)].probe_after, 1) for e in es])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.6), Inches(1.45), Inches(8.2), Inches(5.0), cd)
    ch = gf.chart
    chart_style(ch, legend=True, vmax=94, vmin=78, label_size=11, axis_size=13)
    ch.plots[0].has_data_labels = False
    for srs, (_, _, col) in zip(ch.plots[0].series, series):
        srs.format.line.color.rgb = rgb(col)
        srs.format.line.width = Pt(3.5 if col in (TEAL, CORAL) else 2.25)
        srs.smooth = False
        srs.marker.format.fill.solid()
        srs.marker.format.fill.fore_color.rgb = rgb(col)
        srs.marker.format.line.color.rgb = rgb(col)
    ch.value_axis.visible = True
    ch.value_axis.tick_labels.font.size = Pt(12)
    ch.value_axis.has_major_gridlines = True
    ch.value_axis.major_gridlines.format.line.color.rgb = rgb('E3E8EA')
    text(s, 0.6, 6.5, 8.2, 0.4, '橫軸：任務標籤隨機出錯的比例；縱軸：重戴後準確率 %（電極偏移半格，一輪提示）', size=12, color=GREY)
    soft3, pn3 = t4.loc[(0.5, 0.3, 'cue1_soft')].probe_after, t4.loc[(0.5, 0.3, 'cue1_pn')].probe_after
    box(s, 9.1, 1.6, 3.6, 4.85, fill=LIGHT)
    text(s, 9.35, 1.8, 3.15, 4.5, [('看到的事', {'size': 19, 'bold': True}),
                                    ('先前的硬標籤就是 P+N-CIIL：約一成錯標籤就失去好處', {'bullet': True}),
                                    (f'軟標籤到 30% 錯標籤仍 {soft3:.1f}%（P+N {pn3:.1f}%）', {'bullet': True}),
                                    ('但 P-CIIL 一樣耐隨機錯標籤：「比所有 CIIL 都好」不成立', {'bullet': True, 'color': CORAL}),
                                    ('不做提示時，所有 CIIL 變體在偏移下都失敗', {'bullet': True})], size=14, space=8)

    # 17 MCU learning loop end to end
    bt, rtt, rtg, fg, ros = N['btask'], N['rt_task'], N['rt_gate'], N['fw_gate'], N['ros']
    s = d.slide('結果⑥：完整學習迴路在 MCU 上跑起來', notes=(
        f'軟標籤 C 版（report 35.22–35.23）：每學一個任務標籤 {N["soft_cmd_ms"]:.2f} ms（板子實測）。'
        f'即時迴圈 RTL_TASK_LABEL：機器人只回傳 2 個位元組＋視窗編號（35.24、35.26）。板上 11.5 分鐘重放（35.25）。'
        f'出力判斷 C 版 RTL_SET_GATE（35.28）。RViz 模擬 Gen3：ros2_kortex mock hardware（35.27）。'
        '實驗室 C# 橋接已支援 LDA 韌體與任務標籤轉送（35.29）。出力判斷上板重放（35.33）。能量量測韌體已在板上試跑，電流待量（35.34）。還沒有：真的 Kinova、真人。'))
    steps = ['手勢', 'MCU 指令', 'ROS 2 手臂動作', '機器人回傳|預期手勢', 'MCU 軟標籤|更新模型']
    for i, st in enumerate(steps):
        x = 0.6 + i * 2.5
        b = box(s, x, 1.5, 2.15, 0.95, fill=TEAL if i in (1, 4) else LIGHT)
        label_in(b, st.split('|'), size=14, color=WHITE if i in (1, 4) else INK, bold=i in (1, 4))
        if i < 4:
            arrow(s, x + 2.19, 1.8, 0.27, 0.35)
    stats = [(f'{N["soft_cmd_ms"]:.1f} ms', '每學一個任務標籤（板上）'),
             (f'{bt["same"]:,}／{bt["windows"]:,}', f'板上 11.5 分鐘重放：視窗和 PC 相同；{bt["upd"]} 次任務更新'),
             (f'{N["bgate"]["gsame"]:,}／{N["bgate"]["windows"]:,}', '出力判斷上板重放：類別與擋下的視窗都和 PC 相同'),
             (f'{ros["applied"]}／{ros["labels"]}', f'RViz 模擬手臂：標籤送回並套用；{ros["actions"]} 個動作正常結束'),
             (f'{fg["flash"] / 1024:.1f} KB', '整個韌體 Flash（四個元件都在）'),
             (f'{fg["ram"] / 1024:.0f} KB', '整個韌體 RAM（512 KB 的 20%）')]
    for i, (big, lab) in enumerate(stats):
        x, y = 0.6 + (i % 3) * 4.1, 2.8 + (i // 3) * 1.85
        box(s, x, y, 3.85, 1.65, fill=LIGHT)
        text(s, x + 0.25, y + 0.15, 3.4, 0.75, big, size=30, bold=True, color=TEAL)
        text(s, x + 0.25, y + 0.9, 3.4, 0.7, lab, size=13, color=GREY)
    text(s, 0.6, 6.55, 12.1, 0.4, '一輪提示、收縮 LDA、出力判斷、任務軟標籤都有 C 版並在板上和參考逐一相同；能量量測韌體已就緒；還沒有真的 Kinova 與真人。',
         size=13, color=GREY)

    # 18 public real data (NinaPro DB6)
    sm, nx = N['db6']['same'], N['db6']['next']
    s = d.slide('結果⑦：真實跨 session 資料（NinaPro DB6）', notes=(
        'NinaPro DB6（Palermo 等，2017）：10 人、5 天 × 2 個 session、7 種抓握＋休息共 8 類、Delsys Trigno 第一圈 8 通道，'
        '特徵用本研究的 features.c。第 1 天模型與 z-score 固定；之後 9 個 session 各做一輪提示（每類第 1 次），任務流用第 2–6 次（腳本化：預期抓握＝提示的抓握），'
        '第 7–12 次評分（report 35.31）。DB6 同一抓握 12 次連續錄，任務流緊接在評分資料之前；所以 35.32 改用下一個 session 評分。'
        '判準：R8、R9、R10 通過；R11（下一個 session 上任務標籤 ≥ +1 點）未通過：+2.2（−0.7, +5.1），連正確標籤也只有 +2.1。'))
    cd = CategoryChartData()
    cd.categories = ['同一個 session 評分', '下一個 session 評分']
    series = [('固定第 1 天模型', 'fixed', MUTE), ('Vidovic LDACMA', 'LDACMA', GREY),
              ('一輪提示（累積）', 'cue1', '7FB7B9'), ('一輪提示＋軟標籤', 'cue1_soft', TEAL)]
    for name, m, _ in series:
        cd.add_series(name, [round(sm[m], 1), round(nx[m], 1)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.45), Inches(8.2), Inches(5.0), cd)
    chart_style(gf.chart, legend=True, vmax=80, vmin=0, label_size=12, axis_size=13)
    color_series(gf.chart, [c for _, _, c in series])
    text(s, 0.6, 6.5, 8.2, 0.4, '8 類準確率 %，10 人；「下一個」＝在下一次配戴、做提示前評分（去掉時間相鄰）', size=12, color=GREY)
    box(s, 9.1, 1.6, 3.6, 4.85, fill=LIGHT)
    text(s, 9.35, 1.8, 3.15, 4.5, [('看到的事', {'size': 19, 'bold': True}),
                                    (f'真實換次後固定模型只剩 {sm["fixed"]:.0f}%；一輪提示＋累積拉回 {sm["cue1"] - sm["fixed"]:.0f} 點', {'bullet': True}),
                                    ('只做一輪提示時和 Vidovic 打平', {'bullet': True}),
                                    (f'任務標籤同次 +{sm["cue1_soft"] - sm["cue1"]:.0f} 點，換下一次只剩 +{nx["cue1_soft"] - nx["cue1"]:.1f}（不顯著）', {'bullet': True, 'color': CORAL}),
                                    ('DB6 分不出「時間相鄰」和「只適應本次配戴」：要靠先導實驗', {'bullet': True})], size=14, space=8)

    # 19 FreeRTOS
    rt = N['rtos']
    s = d.slide('結果⑧：即時架構改用 FreeRTOS：學習再忙也不拖慢控制', notes=(
        'report 35.36–35.37。FreeRTOS V10.6.2（STM32CubeH7 附），全部靜態配置；rt_lda.c 等核心與 CubeMX 檔案都沒改。'
        '同一段 11.5 分鐘錄音（受試者 0，含任務標籤）在板上重放三次：裸機、RTOS、RTOS＋低優先 task 人工滿載（idle 0%）。'
        '延遲在 PC 端量（送出完成視窗的封包到收到 PRED，含 USB），偶發 10–25 ms 的最大值每次都有、裸機也有。'))
    layers = [('USART3 中斷（最高）', '收樣本 → 環形緩衝', LIGHT, INK), ('rx task（高優先）', '特徵、分類、指令', TEAL, WHITE),
              ('learn task（低優先）', 'LDA 求解、任務標籤更新', TEAL_L, INK), ('idle', 'WFI 睡眠', LIGHT, INK)]
    for i, (h_, b_, fill, col) in enumerate(layers):
        bx = box(s, 0.6, 1.5 + i * 0.98, 4.2, 0.82, fill=fill)
        label_in(bx, [(h_, {'bold': True}), b_], size=13, color=col)
    text(s, 0.6, 5.5, 4.2, 1.0, [f'實測 stack：rx {rt["rx_stack"]} B、learn {rt["learn_stack"]} B（各配 2 KB）',
                                  f'平常 CPU idle {rt["idle"]:.1f}%'], size=13, color=GREY, space=4)
    cd = CategoryChartData()
    cd.categories = ['P50', 'P95', 'P99']
    for name, k in (('裸機', 'bare'), ('FreeRTOS', 'rtos'), (f'FreeRTOS＋學習滿載（idle {rt["idle_stress"]:.0f}%）', 'stress')):
        cd.add_series(name, [round(v, 2) for v in rt['lat'][k]])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(5.1), Inches(1.45), Inches(7.6), Inches(4.3), cd)
    chart_style(gf.chart, legend=True, vmax=9, vmin=0, fmt='0.00', label_size=11, axis_size=13)
    color_series(gf.chart, [MUTE, '7FB7B9', TEAL])
    text(s, 5.1, 5.75, 7.6, 0.4, '分類延遲（ms，PC 送出 → 收到結果）', size=12, color=GREY)
    box(s, 5.1, 6.1, 7.6, 0.7, fill=TEAL_L)
    text(s, 5.3, 6.15, 7.3, 0.6, f'三種版本都 {rt["same"]:,}／{rt["windows"]:,} 視窗和 PC 相同；學習 task 佔 {rt["learn_stress"]:.0f}% CPU 時延遲不變',
         size=14, bold=True, anchor=MSO_ANCHOR.MIDDLE)

    # 20 why LDA, not a neural network
    nn, mb = N['nn'], N['mlpb']
    s = d.slide('結果⑨：為什麼用 LDA，不用神經網路', notes=(
        'report 35.38–35.39。DB6 10 人 8 類，每次配戴只有一輪提示（每類 10 個視窗）。MLP 80-64-32-8，設定事先寫定、未調參，3 個 seed。'
        '判準 R13（可在 MCU 更新的網路最好的一個沒有贏 LDA ≥ 2 點）通過。板上實測：DB6 受試者 1，同一份資料，C 版與 float64 參考預測完全相同。'
        '未比：原始訊號 CNN、int8 CMSIS-NN、跨使用者大模型。'))
    cd = CategoryChartData()
    cd.categories = ['同一個 session', '下一個 session']
    series = [('LDA 一輪提示＋累加（本研究）', 'lda_cue1', TEAL), ('MLP 微調', 'mlp_ft', '7FB7B9'), ('MLP 累積微調', 'mlp_ft_cum', GREY),
              ('MLP＋LDA 輸出層', 'mlp_head_lda', CORAL), ('MLP 重新訓練（MCU 做不到）', 'mlp_retrain', MUTE)]
    for name, m, _ in series:
        cd.add_series(name, [round(nn['same'][m], 1), round(nn['next'][m], 1)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.45), Inches(6.9), Inches(4.6), cd)
    chart_style(gf.chart, legend=True, vmax=62, vmin=30, label_size=10, axis_size=12)
    color_series(gf.chart, [c for _, _, c in series])
    text(s, 0.6, 6.05, 6.9, 0.4, 'NinaPro DB6 8 類準確率 %，10 人', size=12, color=GREY)
    rows = [['板上實測（480 MHz）', 'LDA', 'MLP'],
            ['分類一個視窗', f'{mb["lda_pred"]:.1f} µs', f'{mb["mlp_pred"]:.1f} µs'],
            ['一次提示輪更新', f'{mb["lda_upd"]:.1f} ms', f'{mb["mlp_upd"]:,.0f} ms'],
            ['靜態 RAM', f'{mb["lda_ram"] / 1024:.1f} KB', f'{mb["mlp_ram"] / 1024:.1f} KB'],
            ['更新方式', '閉式解', '反向傳播 30 epoch']]
    table(s, 7.8, 1.5, 4.9, rows, [2.1, 1.3, 1.5], size=13, row_h=0.62, fills={(i, 1): TEAL_L for i in range(1, 5)})
    box(s, 7.8, 4.85, 4.9, 1.6, fill=LIGHT)
    text(s, 8.0, 4.95, 4.55, 1.45, [('能在 MCU 上更新的 MLP 都沒贏 LDA；相同資料從頭重訓也只打平', {'bold': True}),
                                    (f'LDA 更新快約 {mb["mlp_upd"] / mb["lda_upd"]:.0f} 倍、分類快約 {mb["mlp_pred"] / mb["lda_pred"]:.0f} 倍', {'color': TEAL, 'bold': True}),
                                    ('未比：原始訊號 CNN、int8 CMSIS-NN', {'color': GREY, 'size': 12})], size=14, space=5)

    # 18 negative results
    s = d.slide('負面結果與更正（會寫進論文）', notes='出處：report 35.4、35.8、35.9–35.10、35.16–35.21、35.31–35.32。另：「開機序列第一輪比第二輪差」只在開發資料看得到，已撤回。')
    neg = [('自己提出的葉節點計數', '輸給收縮 LDA，退為對照組'),
           ('沒有用的規則', '只學認錯的視窗、逐手勢門檻、開機序列當裁判、類別中心取中位數、事後修正標籤'),
           ('軟標籤不做提示', '有偏移時比固定模型還差：錯誤自我強化'),
           ('不成立的主張', '「軟標籤比所有 CIIL 變體都耐錯標籤」：隨機錯標籤時 P-CIIL 一樣耐'),
           ('CIIL 原本的更新式', '每 10 秒以 α 0.1 混入，在稀疏標籤下比只做提示還差；累加和才適合'),
           ('出力判斷的門檻', '原門檻擋掉 6.6% 手勢視窗、完成率 86%；實驗先不開，用真實資料決定'),
           ('資料陷阱（已更正）', 'Kyranou 每個手勢連續錄 5 次；緊接著評分會偏樂觀，改看第二個 session 低 2–5 點、結論不變'),
           ('DB6 上的大幅領先', '同次評分比 Vidovic 高 16 點；改在下一個 session 評分時任務標籤只剩 +2.2，不顯著')]
    for i, (h, b) in enumerate(neg):
        y = 1.38 + i * 0.68
        box(s, 0.6, y, 12.1, 0.6, fill=LIGHT)
        text(s, 0.85, y + 0.04, 3.6, 0.52, h, size=15, bold=True, color=CORAL if i in (3, 7) else INK, anchor=MSO_ANCHOR.MIDDLE)
        text(s, 4.5, y + 0.04, 8.0, 0.52, b, size=13, color=GREY, anchor=MSO_ANCHOR.MIDDLE)

    # 17 contributions
    s = d.slide('創新與貢獻', notes='兩輪文獻檢索（2026-11-13，文獻搜尋_2026-11-13.md）：任務情境更新 LDA（Campbell 等，2024）、VR 軟標籤（Gagné 等，2025）、'
                'GAP9 上的情境式學習展示（Orlandi & Rossi，2026）、短校正收縮適應（Vidovic 等，2016）都已有人做。沒找到：實體機械臂、離散稀疏的任務結果、系統性的情境錯誤率掃描。')
    rows = [['貢獻', '狀態', '強度'],
            ['獨立檢驗：免標籤自我校正在重戴資料上沒有確認增益（預先登錄）', '完成', '中（8 人）'],
            ['指出原方法論文的 LDA 基準缺少收縮估計', '完成', '中'],
            ['任務引導的軟標籤＋出力判斷＋一輪提示，用在離散機械臂指令', '模擬＋公開資料', '中（換次後效果不明，待實機）'],
            ['系統性掃描任務標籤錯誤率，並和 CIIL 各策略比較', '模擬完成', '中高（檢索中沒找到別人做過）'],
            ['量化任務結構強弱的影響', '模擬完成', '中'],
            ['完整學習迴路在 MCU 上逐一驗證（裸機與 FreeRTOS）；和 MLP 的板上比較', '完成', '工程貢獻']]
    fills = {(i, 1): TEAL_L for i in (1, 2, 6)}
    fills.update({(i, 1): 'FBE3DD' for i in (3, 4, 5)})
    table(s, 0.6, 1.5, 12.1, rows, [7.6, 1.6, 2.9], size=14, row_h=0.62, fills=fills)
    text(s, 0.6, 6.05, 12.1, 0.8, '不主張「首創」：任務情境更新 LDA 已有人做（Campbell 等，2024）。本研究補的是實體機械臂、一個指令一個稀疏的結果、標籤會錯時怎麼辦，以及在 MCU 上的實作。',
         size=14, color=GREY)

    # 18 related work
    s = d.slide('與相關研究的差別', notes='逐篇查證過（文獻搜尋_2026-11-13.md）。Orlandi & Rossi（2026）是 RISC-V Summit 的展示摘要，未經同儕審查。'
                'Campbell 等（2025）讀的是博士論文第 4 章。Vidovic 等（2016）全文已讀，照原文式 6–7 與參數實作（report 35.30–35.31）。')
    rows = [['', '標籤從哪來', '情境多密', '情境出錯', '環境／平台'],
            ['Campbell 等（2024）CIIL', '任務情境（游標方向）', '每 100 ms', '假設完美', '虛擬游標／PC'],
            ['Campbell 等（2025）', '同上，從零開始', '每 50 ms', '假設完美', '虛擬游標／PC'],
            ['Gagné 等（2025）', '接觸物件＋候選握法平均', '每 50 ms', '假設完美', 'VR／PC'],
            ['Orlandi & Rossi（2026）', '游標靠近目標', '未說明', '—', '虛擬游標／GAP9'],
            ['Vidovic 等（2016）', '短時提示校正（< 1 分鐘）；和一輪提示打平（DB6）', '—', '—', '義肢／PC'],
            ['本研究', '機械臂任務狀態機＋軟標籤', '一個指令一個', '掃 0–30%', '機械臂／Cortex-M7']]
    table(s, 0.6, 1.5, 12.1, rows, [3.0, 3.4, 1.7, 1.6, 2.4], size=14, row_h=0.68,
          fills={(6, j): TEAL_L for j in range(5)})

    # self-test (next step)
    s = d.slide('下一步：自我測試——任務標籤在同一次配戴中有沒有用', notes=(
        'report 35.35；lab_kit/SELFTEST.md、src/selftest_analysis.py（判準在錄之前已 commit）。DB6 回答不了這個問題（同一手勢連續錄，35.32）。'
        '用自己的筆電：Trigno SDK（TCU）已安裝；板子已燒 LDA 韌體。自我測試的資料只用來決定方向；要發表需 IRB 核准的先導實驗。'))
    steps = [('提示輪', '8 秒、中立姿勢'), ('P0', '提示手勢 6×2'), ('T1', '任務指令 40 次'), ('P1', '提示手勢 6×2'),
             ('T2', '任務指令 40 次'), ('P2', '提示手勢 6×2')]
    for i, (h_, b_) in enumerate(steps):
        x = 0.6 + i * 2.07
        bx = box(s, x, 1.5, 1.8, 1.05, fill=TEAL if h_ in ('T1', 'T2') else LIGHT)
        label_in(bx, [(h_, {'bold': True}), b_], size=13, color=WHITE if h_ in ('T1', 'T2') else INK)
        if i < 5:
            arrow(s, x + 1.83, 1.85, 0.2, 0.32)
    text(s, 0.6, 2.65, 12.1, 0.4, 'T1 之後的段落改用操作機器人的姿勢（往前伸、抬高、往外），每 10 次換一次；手勢隨機穿插', size=13, color=GREY)
    box(s, 0.6, 3.25, 5.9, 2.75, fill=LIGHT)
    text(s, 0.85, 3.4, 5.5, 2.5, [('比較（同一份錄音離線重放）', {'size': 17, 'bold': True}),
                                  ('只做提示輪 vs 加任務軟標籤', {'bullet': True}),
                                  ('也比硬標籤、P-CIIL，以及只用 T1 的標籤（5–10 分鐘前的標籤還有沒有用）', {'bullet': True}),
                                  ('第 2 天起：自己真實的跨日重戴效果', {'bullet': True})], size=14, space=6)
    box(s, 6.8, 3.25, 5.9, 2.75, fill=TEAL_L)
    text(s, 7.05, 3.4, 5.5, 2.5, [('判準 R12（錄之前已寫定）', {'size': 17, 'bold': True}),
                                  ([('GO', {'bold': True, 'color': TEAL}), '：P1、P2 平均多 ≥ 2 點且多數天為正 → 任務標籤留在主軸'], {'bullet': True}),
                                  ([('NO-GO', {'bold': True, 'color': CORAL}), '：≤ 0 → 寫成負面結果，主軸改為短提示＋MCU 部署'], {'bullet': True}),
                                  ('其他或天花板 → 交給多人先導實驗', {'bullet': True})], size=14, space=6)
    text(s, 0.6, 6.25, 12.1, 0.5, '自己 1 人、2–4 天、每天約 20 分鐘；不需要 Kinova；只用來決定方向，要發表需 IRB 核准的多人實驗', size=13, color=GREY)

    # 19 plan
    s = d.slide('實驗規劃與時程（草案）', notes='時程是草案，待與指導老師討論；病患個案視醫院合作與 IRB 時程，不綁畢業條件。')
    plan = [('自我測試；12 月中進度報告', 0, 2),
            ('EMBC 2027 投稿（公開資料：獨立檢驗）', 1, 3),
            ('IRB；能量量測；真 Kinova 整條接起來', 1, 3),
            ('先導實驗（健常人、跨日）', 3, 5),
            ('正式實驗／病患個案（視 IRB）', 5, 7),
            ('分析與撰寫', 6, 8)]
    months = ['11月', '12月', '1月', '2月', '3月', '4月', '5月', '6月']
    x0, cw = 5.6, 0.89
    for j, m in enumerate(months):
        text(s, x0 + j * cw, 1.45, cw, 0.35, m, size=12, color=GREY, align=PP_ALIGN.CENTER)
    for i, (t, a0, a1) in enumerate(plan):
        y = 1.95 + i * 0.66
        text(s, 0.6, y, 4.9, 0.6, t, size=15, anchor=MSO_ANCHOR.MIDDLE)
        box(s, x0, y + 0.08, cw * len(months), 0.45, fill=LIGHT, radius=0.5)
        box(s, x0 + a0 * cw, y + 0.08, (a1 - a0) * cw, 0.45, fill=CORAL if i == 0 else TEAL, radius=0.5)
    box(s, 0.6, 6.0, 12.1, 0.8, fill=TEAL_L)
    text(s, 0.85, 6.05, 11.6, 0.7, [([('主要指標：', {'bold': True}),
                                       '重戴後準確率與任務成功率、active error（Campbell 等，2024）、誤觸發／休息分鐘、完成時間、使用者主動給標籤的秒數、NASA-TLX；MCU 的 RAM、時間、能量'], {})],
         size=14, anchor=MSO_ANCHOR.MIDDLE)

    # 20 risks
    s = d.slide('風險與退路', notes='最關鍵的未知數是機器人成功判斷本身的錯誤率：隨機錯誤下硬標籤約 10% 就失效，軟標籤到 30% 仍比只做提示好；漏撤銷的影響很小（report 35.20–35.21）。')
    rows = [['風險', '影響', '退路'],
            ['機器人成功判斷常錯（隨機錯誤 > 30%）', '任務標籤的效果縮小', '論文以檢驗與短時校正為主，任務標籤寫成可靠度分析'],
            ['使用者行為比模擬亂', '軟標籤的先驗失準', '加大先驗的不確定度；加入使用者取消重做的證據'],
            ['沒教過的動作造成誤觸發', '安全性', '機器人端狀態過濾、啟動手勢；非控制動作段實測'],
            ['病患收案時程不確定', '驗證規模縮小', '畢業條件只綁健常人實驗'],
            ['被問「為什麼不用神經網路／免校正大模型」（Eddy 等，2026）', '主線被質疑', 'DB6 上可在 MCU 更新的小型 MLP 都沒贏 LDA（35.38）；板上實測 LDA 更新 9 ms、MLP 1.05 s（35.39）'],
            ['方向未獲同意', '—', '檢驗與短時校正本身可銜接原題目']]
    table(s, 0.6, 1.5, 12.1, rows, [3.6, 2.6, 5.9], size=15, row_h=0.74)

    # 21 decisions
    s = d.slide('需要老師決定的事', dark=True, notes='建議：先導實驗多錄兩輪提示序列即可，不必改實驗設計；所有方法都能用錄下的原始肌電離線重放比較。')
    dec = ['主軸從「免標籤自我校正」改為「每次配戴校正與任務提供的標籤」？',
           'PROTOCOL 與 IRB 要不要改？（建議：先導多錄兩輪提示序列，不改設計）',
           '病患個案的族群與時程',
           '硬體主張的範圍（建議：可部署性，不主張穿戴式裝置）']
    for i, t in enumerate(dec):
        y = 1.6 + i * 1.2
        circle_num(s, 0.9, y + 0.1, i + 1, fill=CORAL, d=0.6)
        text(s, 1.8, y, 10.6, 0.8, t, size=20, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)

    # 22 references
    s = d.slide('參考文獻', notes='Campbell 2024、2025、Gagné 2025、Orlandi & Rossi 2026、Vidovic 2016、Eddy 2026、Zanghieri 2024 已在 2026-11-13 逐篇查證（文獻搜尋_2026-11-13.md）。標＊者還沒打開原文確認。')
    refs = ['Jiang, Ma, Nazarpour (2024). Posture-invariant myoelectric control with self-calibrating random forests. Frontiers in Neurorobotics.',
            'Jiang et al. (2025). Plug-and-play myoelectric control via a self-calibrating random forest common model. Journal of Neural Engineering.',
            'Kyranou, Szymaniak, Nazarpour (2025). 8-participant two-day Trigno dataset. Scientific Data.',
            'Wang et al. (2024). Review of calibration burden in myoelectric control. Frontiers in Bioengineering and Biotechnology.',
            'Campbell, Eddy, Bateman, Côté-Allard, Scheme (2024). Context-informed incremental learning improves both the performance and resilience of myoelectric control. JNER 21:70.',
            'Campbell et al. (2025). Screen guided training does not capture goal-oriented behaviors... IEEE TNSRE 33:332–342.',
            'Gagné et al. (2025). Context informed incremental learning improves myoelectric control performance in VR object manipulation tasks. EMBC 2025.',
            'Orlandi, Rossi (2026). On-device context-informed incremental learning for myoelectric control on a RISC-V wearable platform. RISC-V Summit Europe demo.',
            'Vidovic et al. (2016). Improving the robustness of myoelectric pattern recognition for upper limb prostheses by covariate shift adaptation. IEEE TNSRE 24(9).',
            'Eddy, Campbell, Scheme, Bateman (2026). Open, accurate, and calibration-free muscle-computer interfaces. CHI 2026.',
            'Scheme, Hudgins, Englehart (2013). Confidence-based rejection for improved pattern recognition myoelectric control. IEEE TBME 60(6).',
            'Zanghieri et al. (2024). sEMG-driven hand dynamics estimation with incremental online learning on a parallel ultra-low-power microcontroller. IEEE TBioCAS 18(4).',
            '＊Gilja et al. (2012). A high-performance neural prosthesis enabled by control algorithm design. Nature Neuroscience.',
            '＊Chen, Wiesel, Eldar, Hero (2010). Shrinkage algorithms for MMSE covariance estimation. IEEE Transactions on Signal Processing.']
    text(s, 0.6, 1.4, 12.1, 5.5, refs, size=12, color=INK, space=4)

    d.prs.save(out)
    print(f'{d.n} slides -> {out}')


if __name__ == '__main__':
    build(sys.argv[1])
