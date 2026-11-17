"""Progress-report deck (December 2026), told as a conference talk: background -> problem -> the original method and
its independent check (RQ1) -> methods (with the equations) -> simulation results -> real data -> implementation on
the MCU (with the computations) -> conclusions and next step. For every paper used: its method, its own results,
then my work compared with it. One idea per slide. Equations are native PowerPoint equations (OMML, slides/omml.py).
Every number of mine is read from results/ (the report section is in each slide's notes); the papers' numbers are
quoted from their full texts (文獻搜尋_2026-11-13.md, report 35.30).
Usage (in the container): python slides/progress.py <out.pptx>
"""
import math
import os
import re
import sys

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import omml as M  # noqa: E402
import proposal as P  # noqa: E402
from omml import bar, cases, cat, frac, par, rad, sub, subsup, sum_, sup, t, w  # noqa: E402
from proposal import (CORAL, GREY, INK, LIGHT, MUTE, NAVY, TEAL, TEAL_L, WHITE, arrow, box, chart_style,  # noqa: E402
                      circle_num, color_series, csv, label_in, rgb, table, text)

WHEN = '2026 年 12 月'
FOOT = f'碩士論文進度報告｜{WHEN}｜方向待指導老師確認'
PINK, YELLOW = 'FBE3DD', 'FFF2CC'
SECTIONS = ['1 背景與問題', '2 RQ1：原方法能不能用', '3 方法', '4 模擬結果', '5 真實資料', '6 系統實作', '7 結論與下一步']


class Deck(P.Deck):
    section = ''

    def slide(self, title=None, dark=False, notes='', tag=None):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        self.n += 1
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(NAVY if dark else WHITE)
        x = 0.6
        if tag:                                       # small label in front of the title: 論文 / 我的做法
            b = box(s, 0.6, 0.6, 1.25, 0.46, fill=CORAL if tag == '論文' else TEAL, radius=0.3)
            label_in(b, tag, size=13, color=WHITE, bold=True)
            x = 2.0
        if title:
            text(s, x, 0.42, 12.7 - x, 0.8, title, size=26, bold=True, color=WHITE if dark else INK, anchor=MSO_ANCHOR.MIDDLE)
        if not dark:
            if self.section:                          # where we are in the talk
                text(s, 8.7, 0.08, 4.0, 0.3, self.section, size=11, color=TEAL, align=PP_ALIGN.RIGHT)
            text(s, 0.6, 7.02, 8, 0.3, FOOT, size=10, color=MUTE)
            text(s, 11.9, 7.02, 0.83, 0.3, str(self.n), size=10, color=MUTE, align=PP_ALIGN.RIGHT)
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s

    def divider(self, i, sub_):
        self.section = SECTIONS[i]
        s = self.slide(dark=True, notes=f'段落 {SECTIONS[i]}')
        text(s, 0.9, 2.2, 11.5, 0.9, SECTIONS[i], size=40, bold=True, color=WHITE)
        text(s, 0.9, 3.3, 11.5, 1.2, sub_, size=20, color='CFE3E6')
        return s


def story(d, title, question, notes, tag='我的做法'):
    """one idea per slide: the question at the top, one visual in the middle, the conclusion at the bottom"""
    s = d.slide(title, notes=notes, tag=tag)
    text(s, 0.6, 1.3, 12.1, 0.45, question, size=16, color=GREY)
    return s


def conclude(s, line, y=6.05):
    box(s, 0.6, y, 12.1, 0.75, fill=TEAL_L)
    text(s, 0.9, y + 0.05, 11.6, 0.65, [([('→ 所以：', {'bold': True, 'color': TEAL}), line], {})], size=16,
         anchor=MSO_ANCHOR.MIDDLE)


def eqs(s, x, y, wdt, h, items, size=20, fill=LIGHT):
    """a panel of native equations; items: E(omml) / T(text)"""
    if fill:
        box(s, x, y, wdt, h, fill=fill)
    M.eq_box(s, x + 0.2, y + 0.1, wdt - 0.4, h - 0.2, items, size=size)


def E(omml, fb='equation'):
    return ('eq', omml, fb)


def T(s_, bold=False):
    return ('txt', s_, bold)


def paper_method(d, title, cite, setting, steps, notes, limits=None):
    """the paper's method: setting on the left (optionally the limits I saw below it), its pipeline as a vertical flow
    on the right"""
    s = d.slide(title, notes=notes, tag='論文')
    text(s, 0.6, 1.3, 12.1, 0.4, cite, size=13, color=GREY)
    box(s, 0.6, 1.85, 5.9, 4.85, fill=LIGHT)
    paras = [('實驗設定', {'size': 17, 'bold': True})] + [(ln, {'bullet': True}) for ln in setting]
    if limits:                                    # the user's own layout (2026-11-15): limits under the setting
        paras += [('', {})] + [('我讀完後看到的限制', {'bold': True})] + [(ln, {'bullet': True, 'size': 16}) for ln in limits]
    text(s, 0.85, 2.0, 5.5, 4.02 if limits else 4.6, paras, size=15, space=8)
    n = len(steps)
    hh = min(0.95, (4.85 - 0.2 * (n - 1)) / n)
    for i, (h_, b_) in enumerate(steps):
        y = 1.85 + i * (hh + 0.2)
        bx = box(s, 7.0, y, 5.7, hh, fill=TEAL if i == n - 1 else TEAL_L)
        label_in(bx, [(h_, {'bold': True}), (b_, {'size': 13})], size=15, color=WHITE if i == n - 1 else INK)
        if i < n - 1:
            arrow(s, 9.7, y + hh + 0.02, 0.3, 0.16, kind=P.MSO_SHAPE.DOWN_ARROW)
    return s


def paper_results(d, title, cite, rows, widths, limits, notes, row_h=0.55, head='我讀完後看到的限制'):
    """the paper's own results (a table) and its limits"""
    s = d.slide(title, notes=notes, tag='論文')
    text(s, 0.6, 1.3, 12.1, 0.4, cite, size=13, color=GREY)
    table(s, 0.6, 1.85, 7.6, rows, widths, size=14, row_h=row_h, header_fill=CORAL)
    box(s, 8.5, 1.85, 4.2, 4.85, fill=LIGHT)
    text(s, 8.75, 2.0, 3.8, 4.6, [(head, {'size': 15, 'bold': True})] + [(ln, {'bullet': True}) for ln in limits], size=14, space=7)
    return s


def bars(s, cats, series, colors, x=0.6, y=1.9, w_=12.1, h=4.0, vmin=0, vmax=100, legend=True, fmt='0.0', points=None):
    cd = CategoryChartData()
    cd.categories = cats
    for name, vals in series:
        cd.add_series(name, [round(v, 2) for v in vals])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x), Inches(y), Inches(w_), Inches(h), cd)
    chart_style(gf.chart, legend=legend, vmax=vmax, vmin=vmin, fmt=fmt, label_size=12, axis_size=12)
    if points:
        P.color_points(gf.chart.plots[0].series[0], points)
    else:
        color_series(gf.chart, colors)
    return gf


def data():
    N = P.load()
    N['repro'] = csv('paper_comparison.csv').set_index('metric (%)')
    rs = csv('ram_scenarios.csv').set_index('Unnamed: 0')
    N['ram_paper'], N['ram_noTSNE'] = float(rs.iloc[0]['KB']), float(rs.iloc[2]['KB'])
    sp = csv('sweep_pareto.csv')
    r = sp[(sp.max_depth.astype(str) == '10') & (sp.n_trees == 100) & (sp.precision == 'int16')].iloc[0]   # 'none' makes it text
    N['comp'] = dict(kb=float(r.compact_KB), d=float(r.acc_minus_full))
    full = sp[(sp.max_depth.astype(str) == 'none') & (sp.n_trees == 400) & (sp.precision == 'float32')].iloc[0]
    N['comp_full_kb'] = float(full.compact_KB)
    sh = csv('shift_sweep_raw_summary.csv').set_index('shift')
    uh = csv('shift_sweep_raw_summary_uhc.csv').set_index('shift')
    N['shift'] = dict(none=float(sh.loc[0, 'tsne_fixed']), fixed=float(sh.loc[1, 'tsne_fixed']), tsne=float(sh.loc[1, 'tsne']),
                      uhc=float(uh.loc[1, 'uhc']), align=float(sh.loc[1, 'align']))
    ex = csv('external_check_summary.csv')
    e = ex[(ex.span == '0-2s') & (ex.comp == 'A1')].iloc[0]
    N['ext'] = dict(F=float(e.F), A=float(e.A), d=float(e['diff']), lo=float(e.ci_lo), hi=float(e.ci_hi))
    la = csv('lda_anchor_summary.csv')
    N['la'] = la[la.stream == 'base'].set_index(['shift', 'cond']).acc
    v = csv('task_sim6_vidovic.csv')
    v = v[(v['shift'] == 0.5) & (v.block >= 1)]                    # v.shift is DataFrame.shift
    vm = v.groupby(['tau', 'lam', 'subject']).acc.mean().groupby(['tau', 'lam']).mean()
    N['vid'] = dict(fixed=float(vm.loc[(0.0, 0.0)]), LDAMA=float(vm.loc[(0.7, 0.0)]), LDACMA=float(vm.loc[(0.8, 0.8)]))
    f = csv('task_sim6_frontend.csv')
    f = f[f.block >= 1].copy()                                     # as task_sim6.py: blocks 1-10, per subject, then mean
    f['fr'] = f.false_rest / f.actions.clip(lower=1) * 100
    f = f[(f['shift'] == 0.5) & (f.base == 'pn')]
    N['front'] = f.groupby(['front', 'subject']).fr.mean().groupby('front').mean()
    fc = csv('features_c_check.csv')
    N['featchk'] = float(fc.rel_med.median())
    lc = csv('ldacal_c_check.csv')
    N['ldachk'] = (int(lc.windows.sum()), int(lc.agree.sum()))
    sz = open(os.path.join(P.R, 'arm_rt_lda_rtos2_firmware_size.txt'), encoding='utf-8').read().splitlines()
    N['fwrtos'] = [int(v_) for v_ in next(ln for ln in sz if ln.strip().endswith('build/rtos/blink.elf')).split()[:3]]
    db = csv('db6_sim.csv')
    db = db[db.e == 0].groupby(['method', 'subject']).acc.mean().groupby('method').mean()
    N['db6within'] = float(db['within'])
    en = open(os.path.join(P.R, 'energy_dryrun_board.txt'), encoding='utf-8').read()
    N['win_us'] = float(re.search(r'window\s+n=\s*\d+\s+mean\s+([\d.]+) us', en).group(1))
    N['t7'] = csv('task_sim7_summary.csv').set_index(['shift', 'e', 'cond']).probe_after
    return N


def build(out):
    N = data()
    d = Deck()
    k, t2, t4, rp = N['kyr'], N['t2'], N['t4'], N['repro']
    sm, nx = N['db6']['same'], N['db6']['next']

    # ================================================================ title + outline
    s = d.slide(dark=True, notes='研討會式報告：背景與問題 → 原方法檢驗 → 方法 → 結果 → 真實資料 → 系統實作 → 結論。')
    text(s, 0.9, 1.5, 11.5, 0.5, '碩士論文進度報告', size=18, color='8FD3D0')
    text(s, 0.9, 2.1, 11.6, 2.0, ['在微控制器上、用最少的使用者負擔做每次配戴的肌電校正',
                                    ('從「免標籤自我校正」收斂到「一輪提示＋機器人任務提供的標籤」', {'size': 22, 'bold': False, 'color': 'CFE3E6'})],
         size=28, bold=True, color=WHITE, space=10)
    text(s, 0.9, 4.75, 11, 1.2, ['機器人研究所｜生物力學與醫學應用實驗室', '報告人：【待填】　指導教授：【待填】',
                                  (f'{WHEN}　方向尚待指導老師確認', {'color': '8FD3D0'})], size=16, color='CFE3E6', space=4)

    s = d.slide('報告大綱', notes='每一段都接著上一段留下的問題。')
    outline = [('背景與問題', '重新戴上肌電介面後準確率下降；現有做法與缺口'),
               ('RQ1：原方法能不能用', '重現 → 放進 MCU → 預先登錄的獨立檢驗 → 轉折'),
               ('方法', '收縮 LDA、任務軟標籤、出力判斷（含公式）'),
               ('模擬結果', '和 CIIL、Vidovic、Scheme 照原文比較'),
               ('真實資料', 'NinaPro DB6：哪些成立、哪些被推翻'),
               ('系統實作', 'MCU 上的計算、記憶體、即時性、和神經網路比較'),
               ('結論與下一步', '三個研究問題的答案；自我測試')]
    for i, (h_, b_) in enumerate(outline):
        y = 1.45 + i * 0.75
        circle_num(s, 0.7, y + 0.06, i + 1, fill=TEAL, d=0.5)
        text(s, 1.45, y, 3.8, 0.6, h_, size=18, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        text(s, 5.3, y, 7.4, 0.6, b_, size=15, color=GREY, anchor=MSO_ANCHOR.MIDDLE)

    # ================================================================ 1 background
    d.divider(0, '每天重新戴上肌電介面，準確率就掉；校正又是使用者的負擔')
    s = story(d, '問題：重新戴上之後，昨天的模型今天就不準', '公開資料 NinaPro DB6（10 人、5 天、8 類手勢）：同樣的人、同樣的手勢，換一次配戴差多少？',
              notes='report 35.31；results/db6_sim.csv。「當次完整重新校正」＝只用該次的第 1–6 次重複訓練（上限參考，使用者要做很多提示動作）。', tag=None)
    bars(s, ['用當次資料完整重新校正（負擔大）', '用第 1 天的模型（不校正）'], [('8 類準確率 %', [N['db6within'], sm['fixed']])], None,
         y=1.9, h=3.9, legend=False, points=[TEAL, CORAL])
    conclude(s, f'換一次配戴，準確率從 {N["db6within"]:.0f}% 掉到 {sm["fixed"]:.0f}%：每次配戴都需要校正，但校正越短越好')

    s = d.slide('現有做法與缺口', notes='三類做法各有一篇本研究直接依據的論文；後面每一篇都會先介紹它的方法與結果，再和本研究比較。')
    rows = [['做法', '代表論文', '使用者要做什麼', '缺口'],
            ['免標籤自我校正', 'Jiang 等（2024、2025）', '一次短校正，之後不用', '在獨立資料上是否有效？能放進 MCU 嗎？'],
            ['短時重校正', 'Vidovic 等（2016）', '每次配戴做一輪提示動作', '每次都要主動做；不跨次累積'],
            ['情境式增量學習', 'Campbell 等（2024）', '正常使用，任務情境當標籤', '只在虛擬游標；假設情境完美'],
            ['信心度拒絕／出力門檻', 'Scheme 等（2013）', '—', '擋誤觸發的前端，可與上面合用']]
    table(s, 0.6, 1.45, 12.1, rows, [2.6, 2.8, 3.2, 3.5], size=14, row_h=0.75)
    text(s, 0.6, 5.45, 12.1, 0.5, '我的出發點：把第一列（原題目）放進 MCU；結果發現必須轉向第二、三列', size=15, color=GREY)

    s = d.slide('研究問題與這份報告的地圖', notes='RQ1、RQ3 已有答案；RQ2 是主要問題，下一步的自我測試要回答。')
    rqs = [('RQ1', '免標籤自我校正有沒有用？', '→ 第 2 段'), ('RQ2', '標籤能不能大部分由機器人任務提供？', '→ 第 3–5 段'),
           ('RQ3', '整套能不能在 MCU 上即時執行？', '→ 第 6 段')]
    for i, (q, a1, a2) in enumerate(rqs):
        y = 1.5 + i * 1.3
        box(s, 0.6, y, 12.1, 1.1, fill=TEAL_L if i != 1 else PINK)
        circle_num(s, 0.85, y + 0.28, i + 1, fill=TEAL if i != 1 else CORAL, d=0.55)
        text(s, 1.65, y + 0.1, 8.5, 0.9, f'{q}：{a1}', size=19, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        text(s, 10.2, y + 0.1, 2.4, 0.9, a2, size=16, color=GREY, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 0.6, 5.55, 12.1, 0.9, '研究的方向不是一開始就定好的：每一段的結果決定了下一段要做什麼。', size=16, color=GREY)

    # ================================================================ 2 RQ1
    d.divider(1, '原題目：把 Jiang 等的免標籤自我校正隨機森林放進微控制器')
    paper_method(d, 'Jiang 等（2024）：免標籤自我校正隨機森林', 'Jiang, Ma, Nazarpour. Posture-invariant myoelectric control with self-calibrating random forests. Frontiers in Neurorobotics, 2024',
                 ['資料：arm_position，20 人', '5 個手臂位置（P2、P4、P5、P6、P8）、11 個 block', '6 類手勢（含放鬆）、8 通道', '比較：LDA、RF、one-shot、自我校正'],
                 [('預訓練隨機森林', '用其他人的資料先訓練好'), ('one-shot 校正', '使用者做一次短校正：剪枝＋加新樹'),
                  ('使用中收集視窗', '不需要使用者給標籤'), ('t-SNE＋K-Means 偽標籤', '把視窗分群、對到類別'),
                  ('自動重訓新的樹', '免標籤地跟上變化')],
                 notes='方法照上游程式碼與論文文字整理（report 1.2）。限制是我讀完後的整理，不是作者原話。',
                 limits=['只在同一份資料（arm_position）上驗證', 'LDA 只當對照，沒有做收縮估計', '放進穿戴裝置時的記憶體與運算沒有討論'])
    sel = [('自我校正（全部 block）', 'self-cal, all blocks (mean)'), ('LDA @P5', 'LDA @P5 (mean)'), ('RF @P5', 'RF @P5 (mean)'),
           ('one-shot 比 RF 多 @P5', 'one-shot gain over RF @P5'), ('自我校正比 one-shot 多 @P5', 'self-cal gain over one-shot @P5')]
    # 2026-11-15: the user deleted the separate "Jiang reported results" slide and the conclusion bar here
    s = story(d, '我的重現：和論文逐項比較', '原論文的結果，用它公開的程式碼重跑得出來嗎？', notes='report 第 1 節；results/paper_comparison.csv（20 人 × 11 block × 3 seed）。')
    table(s, 0.6, 1.95, 12.1, [['指標（%）', '論文', '我重跑', '差']] +
          [[n, f'{rp.loc[m_, "paper"]:.2f}', f'{rp.loc[m_, "ours (seed-avg)"]:.2f}', f'{rp.loc[m_, "diff (ours-paper)"]:+.2f}'] for n, m_ in sel],
          [5.5, 2.2, 2.2, 2.2], size=15, row_h=0.6)

    cp = N['comp']
    s = story(d, '放進微控制器：照原樣放不下，要刪減', 'STM32H7 只有 512 KB 的 AXI RAM；原方法照原樣放得進去嗎？', notes='report 第 2–4、6、7、12 節；results/ram_scenarios.csv、sweep_pareto.csv。')
    bars(s, ['照論文原樣（float32 buffer、400 棵樹、t-SNE）', '不做 t-SNE（int16 buffer、100 棵樹）'],
         [('自我校正需要的 RAM（KB）', [N['ram_paper'], N['ram_noTSNE']])], None, y=1.9, h=3.0, vmax=1400, legend=False, fmt='0', points=[CORAL, TEAL])
    text(s, 0.6, 4.95, 12.1, 0.9, [f'模型壓縮：100 棵、深度 10、int16 只要 {cp["kb"]:.1f} KB（完整模型 {N["comp_full_kb"]:.0f} KB），準確率只差 {cp["d"]:+.2f} 點',
                                   '整套用 C、靜態記憶體重寫，在 NUCLEO-H753ZI 上即時執行'], size=15, space=4)
    conclude(s, '韌體 v2：拿掉 t-SNE、模型壓縮，凍結成 pilot 版本')

    sh = N['shift']
    s = story(d, '電極轉動時：免標籤救不回來', '電極環轉了一格（約 45°），免標籤的自我校正能補救嗎？', notes='report 8.1；results/shift_sweep_raw_summary*.csv（模擬：轉原始 EMG 再算特徵）。UHC＝Campbell 等（2024）的高信心偽標籤基準。')
    bars(s, ['沒有轉動', '轉一格：固定模型', '轉一格：免標籤自我校正', '轉一格：高信心偽標籤（UHC）', '轉一格：加開機對齊'],
         [('準確率 %', [sh['none'], sh['fixed'], sh['tsne'], sh['uhc'], sh['align']])], None, y=1.9, h=3.9, legend=False,
         points=[MUTE, GREY, CORAL, CORAL, TEAL])
    conclude(s, '加上「開機對齊」（估計轉了幾格再對回來）；模擬中可以救回 → 要在真實資料上確認')

    ex = N['ext']
    s = story(d, '預先登錄的獨立資料檢驗：免標籤沒有確認增益', '在別人錄的跨日資料（Kyranou 等，2025；8 人、Delsys Trigno）上，完整系統比固定模型好嗎？',
              notes='report 第 24 節；分析計畫在看資料前 commit（EXTERNAL_PLAN.md），只跑一次；results/external_check_summary.csv。8 人可偵測 dz ≥ 1.16。')
    bars(s, ['固定模型', '完整系統（免標籤自我校正＋開機對齊）'], [('跨日準確率 %', [ex['F'], ex['A']])], None, w_=7.0, y=1.9, h=3.9,
         legend=False, points=[MUTE, CORAL])
    box(s, 7.9, 2.0, 4.8, 3.7, fill=LIGHT)
    text(s, 8.15, 2.15, 4.4, 3.5, [('結果', {'size': 17, 'bold': True}),
                                   (f'差 {ex["d"]:+.2f} 點（95% CI {ex["lo"]:+.1f}, {ex["hi"]:+.1f}）', {'bullet': True}),
                                   ('主要損失：開機對齊在沒轉動時誤轉', {'bullet': True}),
                                   ('開發資料上約 +5 點的增益沒有出現', {'bullet': True})], size=15, space=8)
    conclude(s, 'RQ1 的答案：免標籤自我校正在獨立資料上沒有確認增益 → 增益到底從哪來？')

    s = story(d, '轉折一：真正有效的是「少量有標籤的資料」', '每次配戴開頭那段「有提示的手勢」其實帶標籤：拿它來校正，和免標籤比如何？',
              notes='report 35.1–35.4、35.16(0)；results/leaf_external.csv、lda_main.csv。Kyranou 取較嚴格的第二個 session。')
    bars(s, ['固定模型', '免標籤自我校正', '葉節點計數（我的新方法）', '重做 one-shot', '收縮 LDA 兩輪提示'],
         [('Kyranou 跨日 %', [k['F'], k['A'], k['LAonly_a8_za'], k['R'], k['cum_T2']])], None, y=1.9, h=3.9, legend=False,
         points=[MUTE, CORAL, '7FB7B9', '7FB7B9', TEAL])
    conclude(s, '研究問題改成：每次配戴用「少量標籤」校正 → 用什麼模型？標籤從哪來？')

    # ================================================================ 3 methods
    d.divider(2, '有了少量標籤：用收縮 LDA 校正；讓機器人任務提供更多標籤；出力判斷擋誤觸發')
    paper_method(d, 'Vidovic 等（2016）：用小校正集收縮 LDA', 'Vidovic et al. Improving the robustness of myoelectric pattern recognition for upper limb prostheses by covariate shift adaptation. IEEE TNSRE, 2016',
                 ['離線：7 位健常人＋4 位截肢者，跨 5 天', '線上：8 位健常人＋1 位截肢者，3 天', '8 個電極；每天重新穿戴', '校正資料：不到 1 分鐘'],
                 [('第 1 天訓練 LDA', '類別平均、共變異'), ('每天錄小校正集', '每個動作一次（< 1 分鐘）'),
                  ('把參數往校正集收縮', '公式見下一頁'), ('用調整後的 LDA 分類', '原文最佳 τ = 0.8、λ = 0.8')],
                 notes='依原文式 6–7、II-C、III-B 節（report 35.30）。')
    s = d.slide('Vidovic 等（2016）：收縮公式與報告的結果', notes='公式依原文式 6–7；結果取自原文摘要與 III-B 節。', tag='論文')
    mu, Sg = t('μ'), t('Σ')
    eqs(s, 0.6, 1.4, 6.4, 3.7, [
        T('第 1 天的 LDA 參數，往這次配戴的小校正集收縮：', True),
        E(cat(sub(bar(mu), t('c')), t('='), par(cat(t('1'), t('−'), t('τ'))), subsup(mu, t('c'), w('訓練')), t('+'), t('τ'), subsup(mu, t('c'), w('校正')))),
        E(cat(bar(Sg), t('='), par(cat(t('1'), t('−'), t('λ'))), sup(Sg, w('訓練')), t('+'), t('λ'), sup(Sg, w('校正')))),
        T('判別函數（等先驗）：'),
        E(cat(sub(t('g'), t('c')), par(t('x')), t('='), subsup(bar(mu), t('c'), t('T')), sup(bar(Sg), t('−1')), t('x'), t('−'), frac(t('1'), t('2')),
              subsup(bar(mu), t('c'), t('T')), sup(bar(Sg), t('−1')), sub(bar(mu), t('c')))),
    ], size=19)
    table(s, 7.3, 1.4, 5.4, [['原文結果', ''], ['離線，有適應（5 天）', '維持 92% 以上'], ['離線，沒有適應', '降到 75%'],
                             ['線上，有適應 vs 沒有', '提升 25%'], ['只調平均（τ, λ = 0）', '較差']], [3.1, 2.3], size=14, row_h=0.62, header_fill=CORAL)
    text(s, 0.6, 5.35, 12.1, 0.9, ['τ、λ 越大越相信這次的校正集；τ = λ = 1 就是只用校正集重訓',
                                   '我讀完後看到的限制：每天仍要主動校正；每次都從第 1 天出發，不跨次累積；在 PC 上'], size=14, color=GREY, space=4)

    s = d.slide('我的方法①：收縮 LDA，只存累加和', notes='src/c/ldacal.h（OAS：Chen 等，2010；同 sklearn.covariance.oas）；report 35.9–35.10。', tag='我的做法')
    n_, s_, G, c = t('n'), t('s'), t('G'), t('c')
    xi = sub(t('x'), t('i'))
    eqs(s, 0.6, 1.35, 6.3, 5.4, [
        T('1. 狀態只有累加和（不存原始資料）', True),
        E(cat(sub(n_, c), t(','), w('  '), sub(s_, c), t('='), sum_(cat(t('i'), t('∈'), c), '', xi), t(','), w('  '), G, t('='), sum_(t('i'), '', cat(xi, subsup(t('x'), t('i'), t('T')))))),
        T('2. 類別平均與合併共變異', True),
        E(cat(sub(t('m'), c), t('='), frac(sub(s_, c), sub(n_, c)), t(','), w('  '), t('S'), t('='), frac(cat(G, t('−'), sum_(c, '', cat(sub(n_, c), sub(t('m'), c), subsup(t('m'), c, t('T'))))), t('N')))),
        T('3. OAS 收縮（p = 80 維）', True),
        E(cat(t('μ'), t('='), frac(cat(w('tr'), par(t('S'))), t('p')), t(','), w('  '), t('a'), t('='), frac(t('1'), sup(t('p'), t('2'))), sum_(cat(t('i'), t(','), t('j')), '', subsup(t('S'), cat(t('i'), t('j')), t('2'))))),
        E(cat(t('ρ'), t('='), w('min'), par(cat(t('1'), t(','), frac(cat(t('a'), t('+'), sup(t('μ'), t('2'))), cat(par(cat(t('N'), t('+'), t('1'))), par(cat(t('a'), t('−'), frac(sup(t('μ'), t('2')), t('p')))))))))),
        E(cat(t('C'), t('='), par(cat(t('1'), t('−'), t('ρ'))), t('S'), t('+'), t('ρ'), t('μ'), t('I'))),
    ], size=17)
    eqs(s, 7.1, 1.35, 5.6, 5.4, [
        T('4. 求解（Cholesky：C = L Lᵀ）', True),
        E(cat(sub(t('w'), c), t('='), sup(t('C'), t('−1')), sub(t('m'), c), t(','), w('  '), sub(t('b'), c), t('='), t('−'), frac(t('1'), t('2')), subsup(t('m'), c, t('T')), sub(t('w'), c))),
        T('5. 分類', True),
        E(cat(M.hat(t('c')), t('='), M.lim_low('argmax', t('c'), par(cat(t('x'), t('·'), sub(t('w'), c), t('+'), sub(t('b'), c)))))),
        T('6. 跨次累積＋遺忘（每學一次）', True),
        E(cat(G, t('←'), t('γ'), G, t('+'), sum_(t('i'), '', cat(xi, subsup(t('x'), t('i'), t('T')))), t(','), w('  '), t('γ'), t('='), t('0.97'))),
        T('為什麼一定要收縮：一輪提示 = 6 手勢 × 10 視窗 = 60', True),
        E(cat(w('rank'), par(t('S')), t('≤'), t('N'), t('−'), t('K'), t('='), t('60'), t('−'), t('6'), t('='), t('54'))),
        E(cat(t('54'), t('<'), t('p'), t('='), t('80'))),
        T('→ S 是奇異矩陣，不能直接求反矩陣；加 ρμI 之後一定可逆'),
    ], size=17, fill=TEAL_L)

    la = N['la']
    s = story(d, '收縮 LDA 的效果：比我自己提出的森林方法更好', '用同樣的開機標籤，各種方法的準確率（開發資料 20 人，無偏移）', notes='report 35.9–35.11；results/lda_anchor_summary.csv。')
    bars(s, ['one-shot RF（固定）', '免標籤自我校正', '葉節點計數（我的方法）', '上游的 LDA（沒收縮）', 'LDA＋收縮', 'LDA＋收縮＋標籤累積'],
         [('準確率 %', [la.loc[(0.0, c_)] for c_ in ('F', 'A', 'LAonly_a8_za', 'LDAfix', 'LDAfixS', 'LDAcum')])], None,
         y=1.9, h=3.9, legend=False, vmin=50, points=[MUTE, CORAL, '7FB7B9', GREY, '7FB7B9', TEAL])
    conclude(s, '上游 LDA 輸給森林是因為沒做收縮；收縮＋累積最好 → 主線換成 LDA，葉節點計數退為對照組')

    paper_method(d, 'Campbell 等（2024）：情境式增量學習（CIIL）', 'Campbell, Eddy, Bateman, Côté-Allard, Scheme. Context-informed incremental learning improves both the performance and resilience of myoelectric control. J NeuroEng Rehabil, 2024',
                 ['任務：虛擬游標 2 自由度 Fitts 測試', 'Myo 臂環 8 通道；LDA；5 類', '32 人（情境 2 的 21 人：臂環轉 45°）', '對照：UHC（高信心偽標籤）'],
                 [('使用者控制游標', '朝目標移動'), ('用任務情境推標籤', '朝目標＝正情境；遠離目標＝負情境'),
                  ('正情境：沿用預測當標籤', 'P-CIIL'), ('負情境：改成正確方向', 'N-CIIL；兩者合用＝P+N-CIIL'), ('增量更新 LDA', '邊用邊學')],
                 notes='依全文 Methods 整理（文獻搜尋_2026-11-13.md 1.0 節）。')
    paper_results(d, 'Campbell 等（2024）報告的結果（電極轉動後）', '全文 Results 圖 4–5、Discussion（情境 2，21 人）',
                  [['指標', 'P+N-CIIL', '其他'], ['throughput（bit/s）', '0.61', '轉動前 0.50'], ['path efficiency', '66.0%', 'P-CIIL 40.1%、UHC 11.7%'],
                   ['active error', '21.0%', '沒有適應 61.5%'], ['恢復到能做線上測試', '21／21', 'UHC 5、P-CIIL 14']],
                  [2.6, 1.8, 3.2], ['虛擬環境提供「完美情境」：要找出情境正確率的下限', '要到更真實的實體環境驗證', '要擴展到 2 自由度以上'],
                  notes='數字與限制取自全文（作者 Discussion → Future work）。', row_h=0.62, head='作者自己說的未來工作')

    s = d.slide('我的方法②：任務軟標籤', notes='src/c/rt_lda.h（RTL_EPS 0.15、RTL_P0 0.05、RTL_P_INVALID 0.01、RTL_BETA 0.3、RTL_DECAY 0.97）、ldacal.h（ld_soft_q、ld_add_soft）；report 35.18、35.22–35.24。右邊的數字是示意計算。', tag='我的做法')
    pi = t('π')
    expo = lambda j: sup(t('e'), cat(t('β'), par(cat(sub(bar(t('s')), j), t('−'), w('max'), w(' '), bar(t('s'))))))  # noqa: E731
    eqs(s, 0.6, 1.35, 6.6, 5.4, [
        T('1. 機器人依任務狀態給先驗（預期手勢 e）', True),
        E(cat(sub(pi, t('c')), t('='), cases(cat(t('1'), t('−'), t('ε'), t('='), t('0.85'), w('    c = e')),
                                              cat(frac(t('ε'), t('|V|')), w('    c ∈ V（其他當下合理的）')),
                                              cat(t('0.05'), w('    c = 放鬆')), cat(t('0.01'), w('    其他'))))),
        T('2. 和分類器的判斷結合（造成這個指令的視窗平均分數 s̄）', True),
        E(cat(sub(t('q'), t('c')), t('='), frac(cat(sub(pi, t('c')), expo(t('c'))), sum_(t('k'), '', cat(sub(pi, t('k')), expo(t('k'))))),
              t(','), w('  '), t('β'), t('='), t('0.3'))),
        T('3. 用機率加權更新累加和（n 個視窗）', True),
        E(cat(sub(t('n'), t('c')), t('←'), t('γ'), sub(t('n'), t('c')), t('+'), sub(t('q'), t('c')), t('n'), t(','), w('  '),
              sub(t('s'), t('c')), t('←'), t('γ'), sub(t('s'), t('c')), t('+'), sub(t('q'), t('c')), sum_(t('i'), '', sub(t('x'), t('i'))))),
    ], size=17)
    names = ['e（預期）', 'v（另一個合理）', 'u（另一個合理）', '放鬆']
    prior = dict(zip(names, (0.85, 0.075, 0.075, 0.05)))
    gap = dict(zip(names, (-2.0, 0.0, -4.0, -6.0)))
    raw = {kk: prior[kk] * math.exp(0.3 * gap[kk]) for kk in names}
    tot = sum(raw.values())
    rows = [['示意計算', '先驗 π', 's̄ − max', 'π·e^(βΔ)', 'q']] + [[kk, f'{prior[kk]:.3f}', f'{gap[kk]:+.0f}', f'{raw[kk]:.4f}', f'{raw[kk] / tot:.3f}'] for kk in names]
    table(s, 7.4, 1.35, 5.3, rows, [1.75, 0.8, 0.85, 1.0, 0.9], size=12, row_h=0.55, header_fill=TEAL)
    text(s, 7.4, 4.25, 5.3, 2.4, ['分類器覺得是 v（分數最高），任務預期 e', f'結果 q_e = {raw[names[0]] / tot:.2f}、q_v = {raw[names[1]] / tot:.2f}：大部分給 e，但保留一點給 v',
                                  '若任務的預期是錯的，錯的那一類不會拿到全部權重', f'板上學一個任務標籤 {N["soft_cmd_ms"]:.2f} ms'],
         size=13, color=GREY, space=5)

    s = d.slide('我的方法③：出力判斷與指令決策', notes='src/c/rt_lda.h（RTL_SET_GATE）、decision.h；report 35.18、35.21、35.28、35.30。Scheme 的門檻見原文式 15。', tag='我的做法')
    a = t('a')
    eqs(s, 0.6, 1.35, 6.3, 5.4, [
        T('1. 每個視窗的出力（8 個通道原始 MAV 的總和）', True),
        E(cat(a, t('='), sum_(t('ch=1'), t('8'), sub(w('MAV'), t('ch'))), t(','), w('  '), sub(w('MAV'), t('ch')), t('='), frac(t('1'), t('400')), sum_(t('i'), '', par(sub(t('x'), t('i')), '|', '|')))),
        T('2. 門檻：放鬆與最弱手勢中位數的幾何平均', True),
        E(cat(t('θ'), t('='), rad(cat(w('med'), par(cat(a, t('|'), w('放鬆'))), t('·'), M.lim_low('min', t('g'), cat(w('med'), par(cat(a, t('|'), t('g'))))))))),
        E(cat(a, t('<'), t('k'), t('θ'), t('⇒'), w('一律當放鬆'))),
        T('對照 Scheme 等（2013）：', True),
        E(cat(sub(t('θ'), w('Scheme')), t('='), sub(t('μ'), w('不動')), t('+'), t('3'), sub(t('σ'), w('不動')))),
        T('示意：放鬆中位數 10、最弱手勢 40 → θ = √(10 × 40) = 20'),
    ], size=17)
    eqs(s, 7.1, 1.35, 5.6, 5.4, [
        T('3. 指令決策（每 100 ms 一個視窗）', True),
        E(cat(sub(M.hat(t('c')), t('t')), t('='), sub(M.hat(t('c')), t('t−1')), t('='), sub(M.hat(t('c')), t('t−2')), t('⇒'), w('確立手勢'))),
        T('和上一個確立的不同才送指令；一直握著只送一次'),
        T('4. 手勢 → 機械臂指令（9 類）', True),
        T('手腕上翹／下彎 → 上／下'),
        T('往拇指側／小指側偏 → 左／右'),
        T('食指指出／比讚 → 前／後'),
        T('張開／握拳 → 夾爪開／夾；放鬆 → 停'),
    ], size=17, fill=TEAL_L)

    s = d.slide('評估方法：每個比較都事先寫好判準', notes='report 35.20–35.32、35.38；每個實驗的判準寫在程式檔頭並在執行前 commit。', tag='我的做法')
    di, db, sd_ = sub(t('d'), t('i')), bar(t('d')), sub(t('s'), t('d'))
    tq = sub(t('t'), t('0.975, n−1'))
    eqs(s, 0.6, 1.35, 6.3, 5.4, [
        T('逐人配對差（n 人）', True),
        E(cat(di, t('='), subsup(t('A'), t('i'), w('方法1')), t('−'), subsup(t('A'), t('i'), w('方法2')), t(','), w('  '), db, t('='), frac(t('1'), t('n')), sum_(t('i=1'), t('n'), di))),
        T('95% 信賴區間（t 分布）', True),
        E(cat(db, t('±'), tq, frac(sd_, rad(t('n'))))),
        T('判準範例（R9）：差 ≥ +1 點，且 CI 下界 > 0 才算通過', True),
        E(cat(db, t('≥'), t('1'), w('  且  '), db, t('−'), tq, frac(sd_, rad(t('n'))), t('>'), t('0'))),
    ], size=17)
    box(s, 7.1, 1.35, 5.6, 5.4, fill=TEAL_L)
    text(s, 7.35, 1.5, 5.2, 5.1, [('資料與設定', {'bold': True, 'size': 16}),
                                  ('開發資料：arm_position 20 人（手臂位置＋模擬電極偏移）', {'bullet': True}),
                                  ('獨立資料：Kyranou 8 人跨日（預先登錄）', {'bullet': True}),
                                  ('真實重新配戴：NinaPro DB6 10 人 5 天', {'bullet': True}),
                                  ('閉迴路模擬：抓放任務，使用者會改主意、標籤會錯', {'bullet': True}),
                                  ('原則', {'bold': True, 'size': 16}),
                                  ('判準寫在程式檔頭，執行前 commit', {'bullet': True}),
                                  ('沒通過的照實報告（R1、R11 未通過）', {'bullet': True})], size=14, space=6)

    # ================================================================ 4 simulation results
    d.divider(3, '在模擬的閉迴路抓放任務中：任務標籤能取代多少提示？標籤出錯時誰比較耐？')
    s = story(d, '結果①：一輪提示＋任務標籤 ≈ 兩輪提示', '閉迴路抓放模擬（20 人，使用者 25% 臨時改主意，電極偏移半格）', notes='report 35.15–35.19；results/task_sim2_summary.csv。')
    bars(s, ['固定模型', '一輪提示', '一輪＋硬標籤', '一輪＋軟標籤＋出力判斷', '兩輪提示', '正確答案（上限）'],
         [('準確率 %', [t2.loc[(0.5, 0.25, c_)].probe_after for c_ in ('fixed', 'cue1', 'cue1_gate', 'cue1_soft_act', 'cue2', 'oracle')])],
         None, y=1.9, h=3.9, legend=False, vmin=40, points=[MUTE, '7FB7B9', GREY, TEAL, '7FB7B9', MUTE])
    conclude(s, '使用者主動給的提示少一半，準確率和兩輪提示、正確答案上限一樣（模擬）')

    s = story(d, '結果②：任務標籤出錯時，和 CIIL 比', 'CIIL 假設情境完美；機器人的成功判斷會錯。標籤錯 0–30% 時，誰比較耐？',
              notes='report 35.20；results/task_sim4_summary.csv（½ 格偏移、使用者 10% 改主意、一輪提示）。判準 R1（軟標籤比最好的 CIIL 多 2 點）未通過。')
    es = [0.0, 0.1, 0.2, 0.3]
    cd = CategoryChartData()
    cd.categories = [f'標籤錯 {int(e_ * 100)}%' for e_ in es]
    cue = t4.loc[(0.5, 0.0, 'cue1')].probe_after
    series = [('只做一輪提示', None, MUTE), ('P+N-CIIL（＝硬標籤）', 'cue1_pn', CORAL), ('P-CIIL', 'cue1_pos', GREY), ('軟標籤（我的）', 'cue1_soft', TEAL)]
    for name, c_, _ in series:
        cd.add_series(name, [round(cue if c_ is None else t4.loc[(0.5, e_, c_)].probe_after, 1) for e_ in es])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.6), Inches(1.9), Inches(12.1), Inches(3.95), cd)
    ch = gf.chart
    chart_style(ch, legend=True, vmax=94, vmin=78, label_size=11, axis_size=12)
    ch.plots[0].has_data_labels = False
    for srs, (_, _, col) in zip(ch.plots[0].series, series):
        srs.format.line.color.rgb = rgb(col)
        srs.format.line.width = P.Pt(3.5 if col in (TEAL, CORAL) else 2.25)
        srs.smooth = False
        srs.marker.format.fill.solid()
        srs.marker.format.fill.fore_color.rgb = rgb(col)
    ch.value_axis.visible = True
    ch.value_axis.has_major_gridlines = True
    ch.value_axis.major_gridlines.format.line.color.rgb = rgb('E3E8EA')
    conclude(s, '硬標籤一錯就掉；軟標籤到 30% 仍穩。但 P-CIIL 一樣穩 →「勝過所有 CIIL」不成立，照實報告')

    t7 = N['t7']
    s = story(d, '結果②（續）：軟標籤要不要乘上分類器分數？', 'Campbell 的博士論文（2026，第 4 章）已用「平分」的軟標籤；我的差別是乘上分類器分數。這一步有用嗎？',
              notes='report 35.41；results/task_sim7_summary.csv（½ 格偏移、一輪提示、20 人 × 2 seed）。判準 R14（e = 0.3 時比平分多 ≥ 1 點且 CI > 0；e = 0 時 ≥ −0.5）在執行前 commit，通過：'
                    '+2.09（+1.55, +2.63），19 人較好；e = 0 時 +0.29。平分版沒有 label spreading（需要成長的記憶庫，作者自己指出不適合嵌入式）。')
    cd = CategoryChartData()
    cd.categories = [f'標籤錯 {int(e_ * 100)}%' for e_ in es]
    series7 = [('只做一輪提示', None, MUTE), ('只有先驗（不乘分數）', 'cue1_prior', CORAL), ('平分（Campbell 第 4 章）', 'cue1_avg', GREY),
               ('先驗 × 分數（我的）', 'cue1_soft', TEAL)]
    for name, c_, _ in series7:
        cd.add_series(name, [round(t7.loc[(0.5, 0.0, 'cue1')] if c_ is None else t7.loc[(0.5, e_, c_)], 1) for e_ in es])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.6), Inches(1.9), Inches(7.4), Inches(3.95), cd)
    ch = gf.chart
    chart_style(ch, legend=True, vmax=94, vmin=78, label_size=11, axis_size=12)
    ch.plots[0].has_data_labels = False
    for srs, (_, _, col) in zip(ch.plots[0].series, series7):
        srs.format.line.color.rgb = rgb(col)
        srs.format.line.width = P.Pt(3.5 if col in (TEAL, CORAL) else 2.25)
        srs.smooth = False
        srs.marker.format.fill.solid()
        srs.marker.format.fill.fore_color.rgb = rgb(col)
    ch.value_axis.visible = True
    ch.value_axis.has_major_gridlines = True
    ch.value_axis.major_gridlines.format.line.color.rgb = rgb('E3E8EA')
    elig = sub(t('E'), w('合理'))
    eqs(s, 8.2, 1.9, 4.5, 3.95, [
        T('我的：先驗 × 分數', True),
        E(cat(sub(t('q'), t('c')), t('∝'), sub(t('π'), t('c')), sup(t('e'), cat(t('β'), par(cat(sub(bar(t('s')), t('c')), t('−'), w('max'), w(' '), bar(t('s')))))))),
        T('平分（情境為負時）', True),
        E(cat(sub(t('q'), t('c')), t('='), frac(t('1'), par(elig, '|', '|')), t(','), w('  '), t('c'), t('∈'), elig)),
        T('只有先驗（β = 0）', True),
        E(cat(sub(t('q'), t('c')), t('='), sub(t('π'), t('c')))),
        T(f'標籤錯 30%：我的 − 平分 = +{t7.loc[(0.5, 0.3, "cue1_soft")] - t7.loc[(0.5, 0.3, "cue1_avg")]:.1f} 點', True),
    ], size=15, fill=TEAL_L)
    conclude(s, '耐錯主要來自「乘上分類器分數」：比平分多約 2 點、比只有先驗多約 9 點（模擬）→ 可以主張這一步')

    vd = N['vid']
    s = story(d, '結果③：和 Vidovic（2016）照原文公式比較', '用 Vidovic 原文的公式和參數（τ = λ = 0.8），在同一個模擬、同一批人上比較', notes='report 35.30；results/task_sim6_vidovic.csv、task_sim4_summary.csv（½ 格偏移，block 1–10，20 人）。判準 R6 通過。')
    bars(s, ['固定第 1 天 LDA', 'Vidovic LDAMA（只調平均）', 'Vidovic LDACMA', '我的：一輪提示', '我的：一輪提示＋軟標籤'],
         [('模擬 %', [vd['fixed'], vd['LDAMA'], vd['LDACMA'], t4.loc[(0.5, 0.0, 'cue1')].probe_after, t4.loc[(0.5, 0.0, 'cue1_soft')].probe_after])],
         None, y=1.9, h=3.9, legend=False, vmin=40, points=[MUTE, GREY, GREY, '7FB7B9', TEAL])
    conclude(s, '模擬中我的方法較好，但部分來自「標籤跨次累積」，而且是模擬的偏移 → 要在真實資料上確認')

    fr = N['front']
    s = d.slide('Scheme 等（2013）：信心度拒絕與出力門檻', notes='依原文摘要、式 11–15、III-A 節（report 35.30）。', tag='論文')
    text(s, 0.6, 1.3, 12.1, 0.4, 'Scheme, Hudgins, Englehart. Confidence-based rejection for improved pattern recognition myoelectric control. IEEE TBME, 2013', size=13, color=GREY)
    eqs(s, 0.6, 1.85, 6.6, 4.85, [
        T('信心度＝LDA 判別值的 softmax（式 11）', True),
        E(cat(t('P'), par(cat(t('c'), t('|'), t('x'))), t('='), frac(sup(t('e'), sub(t('g'), t('c'))), sum_(t('k'), '', sup(t('e'), sub(t('g'), t('k'))))))),
        E(cat(M.lim_low('max', t('c'), cat(t('P'), par(cat(t('c'), t('|'), t('x'))))), t('<'), t('0.97'), t('⇒'), w('輸出不動'))),
        T('出力門檻（式 15）', True),
        E(cat(t('a'), t('<'), sub(t('μ'), w('不動')), t('+'), t('3'), sub(t('σ'), w('不動')), t('⇒'), w('當作不動'))),
    ], size=18)
    box(s, 7.5, 1.85, 5.2, 4.85, fill=PINK)
    text(s, 7.75, 2.0, 4.8, 4.6, [('原文結果', {'bold': True, 'size': 16}),
                                  ('即時 Fitts 目標擷取任務，健常人與截肢者', {'bullet': True}),
                                  ('比一般 LDA：throughput、path efficiency、完成率都顯著較高（p < 0.001）', {'bullet': True}),
                                  ('和我的關係', {'bold': True, 'size': 16}),
                                  ('我的「出力判斷」和它的出力門檻是同類想法 → 要引用', {'bullet': True}),
                                  ('差別只在門檻怎麼設：幾何平均 vs μ＋3σ', {'bullet': True})], size=14, space=6)

    s = story(d, '結果④：出力判斷 vs Scheme 的兩種做法', '不做提示、電極偏移時，休息中被誤觸發成動作的比例（越低越安全）',
              notes='report 35.30；results/task_sim6_frontend.csv（½ 格偏移、硬標籤、不做提示的壓力測試）。判準 R7：保留本研究的門檻。')
    bars(s, ['不加', 'Scheme：信心度拒絕 0.97', 'Scheme：出力門檻 μ＋3σ', '我的出力判斷（幾何平均）'],
         [('休息誤觸發 %', [fr['none'], fr['rej'], fr['act_s'], fr['act']])], None, y=1.9, h=3.9, legend=False, vmax=25, fmt='0.00',
         points=[MUTE, CORAL, GREY, TEAL])
    conclude(s, '我的門檻誤觸發最少；但「出力門檻」Scheme 已做過 → 引用先例，只主張門檻的設法')

    # ================================================================ 5 real data
    d.divider(4, '前面都是模擬的偏移；在真實的重新配戴資料上還成立嗎？')
    s = story(d, '結果⑤：真實的重新配戴（NinaPro DB6）', '10 人、5 天、8 類；每次配戴一輪提示。另外改用「下一個 session」評分，去掉時間相鄰',
              notes='report 35.31–35.32；results/db6_sim*.csv、db6_adj*.csv。DB6 同一抓握 12 次連續錄，同次評分偏樂觀。判準 R8–R10 通過、R11 未通過。')
    bars(s, ['同一個 session 評分', '下一個 session 評分（去掉時間相鄰）'],
         [(n2, [sm[m_], nx[m_]]) for n2, m_ in (('固定第 1 天模型', 'fixed'), ('Vidovic LDACMA', 'LDACMA'), ('一輪提示（累積）', 'cue1'), ('一輪提示＋軟標籤', 'cue1_soft'))],
         [MUTE, GREY, '7FB7B9', TEAL], y=1.9, h=3.9, vmax=80)
    conclude(s, f'一輪提示＋累積成立（+{sm["cue1"] - sm["fixed"]:.0f} 點）；任務標籤換次後只剩 +{nx["cue1_soft"] - nx["cue1"]:.1f}；只做提示時和 Vidovic 打平')

    s = d.slide('轉折二：誠實整理——哪些站得住、哪些不成立', notes='每一項的出處見 report 35.x；判準都在跑之前寫進程式檔頭。')
    rows = [['主張', '狀態', '證據'],
            ['免標籤自我校正有增益', '不成立（未確認）', '預先登錄的獨立資料（Kyranou 8 人）'],
            ['每次配戴一輪提示＋跨次累積有效', '站得住', 'Kyranou、DB6 真實跨日'],
            ['收縮 LDA 比原方法的森林好且便宜', '站得住', '開發資料、Kyranou、DB6；板上實測'],
            ['整套能在 MCU 上即時執行', '站得住', '板上和 PC 逐一相同（第 6 段）'],
            ['任務標籤能提升準確率', '未證實', '模擬有效；DB6 換次後不明顯'],
            ['軟標籤勝過所有 CIIL 策略', '不成立', '模擬中 P-CIIL 一樣耐錯'],
            ['「先驗 × 分數」比平分式軟標籤耐錯', '站得住（模擬）', '錯 30% 時多 2.1 點（Campbell 2026 第 4 章）'],
            ['比 Vidovic 高 16 點', '不成立', '只在同次評分；換次後消失'],
            ['出力判斷是新方法', '不是新的', 'Scheme 等（2013）已有同類做法']]
    fills = {(i, 1): TEAL_L if r_[1].startswith('站得住') else (PINK if r_[1].startswith('不') else YELLOW) for i, r_ in enumerate(rows[1:], start=1)}
    table(s, 0.6, 1.4, 12.1, rows, [5.0, 2.4, 4.7], size=14, row_h=0.5, fills=fills)
    text(s, 0.6, 6.55, 12.1, 0.4, '→ 任務標籤從「主要貢獻」降為「要用真人實驗檢驗的假設」', size=15, bold=True, color=TEAL)

    # ================================================================ 6 implementation
    d.divider(5, 'RQ3：整套方法怎麼放進 STM32H753，以及怎麼驗證每一步')
    s = story(d, '系統架構：PC 只轉送，MCU 做全部運算', '一個指令從肌電到機械臂、再把任務標籤送回 MCU 的路徑', notes='report 7.3、35.13、35.24–35.27；src/c/protocol.h、rt_lda.h、src/pc/TrignoBridge.cs、kinova_bridge.py。')
    chain = [('Delsys Trigno', '4 顆貼主要肌肉、2 kHz'),('PC 橋接', 'TrignoBridge（C#）'), ('STM32H753', '480 MHz、Cortex-M7'), ('PC／ROS 2', 'kinova_bridge'), ('Kinova Gen3', '＋Robotiq 夾爪')]
    for i, (h_, b_) in enumerate(chain):
        x = 0.6 + i * 2.5
        bx = box(s, x, 2.0, 2.15, 1.05, fill=TEAL if i == 2 else LIGHT)
        label_in(bx, [(h_, {'bold': True}), (b_, {'size': 12})], size=15, color=WHITE if i == 2 else INK)
        if i < 4:
            arrow(s, x + 2.18, 2.37, 0.3, 0.32)
    back = box(s, 3.1, 3.35, 9.65, 0.6, fill=PINK, shape=P.MSO_SHAPE.LEFT_ARROW)
    label_in(back, '任務標籤：預期的手勢＋當下合理的手勢＋指令的視窗編號（3–7 bytes）', size=14)
    cols = [('PC 橋接', ['只轉送原始樣本，不做運算', 'int16，1 LSB = 0.25 µV', '每 10 ms 一個封包（20 個樣本）']),
            ('MCU', ['濾波、特徵、z-score', 'LDA 分類、指令決策', '提示輪校正與任務標籤學習']),
            ('機器人端', ['依指令移動手臂', '知道任務流程與目前狀態', '回傳「預期的手勢」當標籤'])]
    for i, (h_, lines) in enumerate(cols):
        x = 0.6 + i * 4.1
        box(s, x, 4.2, 3.85, 1.65, fill=LIGHT)
        text(s, x + 0.2, 4.28, 3.5, 1.55, [(h_, {'bold': True, 'size': 15})] + [(ln, {'bullet': True}) for ln in lines], size=13, space=3)
    conclude(s, '演算法全部在 MCU 上；Trigno 基地台只有 USB 輸出，所以 PC 只當轉接')

    fc = N['featchk']
    s = d.slide('特徵擷取：每 100 ms 從 8 個通道算出 80 維', notes='src/c/features.c、features.h；report 6.4；results/features_c_check.csv。帶通 10–500 Hz 4 階 Butterworth；視窗 400 點（200 ms）、每 200 點（100 ms）；PSD：Hamming 400 點補零到 512 點 FFT。', tag='我的做法')
    x_i = sub(t('x'), t('i'))
    ind = lambda body: cat(t('𝟙'), par(body, '[', ']'))  # noqa: E731
    eqs(s, 0.6, 1.35, 6.3, 5.4, [
        T('時域（每個視窗 N = 400 點，每通道 10 個特徵）', True),
        E(cat(w('RMS'), t('='), rad(cat(frac(t('1'), t('N')), sum_(t('i'), '', sup(x_i, t('2'))))), t(','), w('  '), w('MAV'), t('='), frac(t('1'), t('N')), sum_(t('i'), '', par(x_i, '|', '|')))),
        E(cat(w('WL'), t('='), sum_(t('i'), '', par(cat(sub(t('x'), t('i+1')), t('−'), x_i), '|', '|')))),
        E(cat(w('ZC'), t('='), sum_(t('i'), '', ind(cat(x_i, sub(t('x'), t('i+1')), t('<'), t('0')))))),
        E(cat(w('SSC'), t('='), sum_(t('i'), '', ind(cat(par(cat(x_i, t('−'), sub(t('x'), t('i−1')))), par(cat(x_i, t('−'), sub(t('x'), t('i+1')))), t('>'), t('0')))))),
        E(cat(w('偏度'), t('='), frac(cat(frac(t('1'), t('N')), sum_(t('i'), '', sup(par(cat(x_i, t('−'), bar(t('x')))), t('3')))), sup(t('σ'), t('3'))))),
    ], size=16)
    Pk, fk = sub(t('P'), t('k')), sub(t('f'), t('k'))
    eqs(s, 7.1, 1.35, 5.6, 5.4, [
        T('頻域（功率譜 Pₖ，fₖ = k·Δf）', True),
        E(cat(w('MNF'), t('='), frac(sum_(t('k'), '', cat(fk, Pk)), sum_(t('k'), '', Pk)))),
        E(cat(w('VCF'), t('='), frac(sum_(t('k'), '', cat(sup(fk, t('2')), Pk)), sum_(t('k'), '', Pk)), t('−'), sup(w('MNF'), t('2')))),
        E(cat(sum_(t('k ≤ MDF'), '', Pk), t('≈'), frac(t('1'), t('2')), sum_(t('k'), '', Pk), t(','), w('  '), w('PKF'), t('='), M.lim_low('argmax', t('k'), Pk))),
        E(cat(t('Δf'), t('='), frac(cat(t('2000'), w(' Hz')), t('512')), t('='), t(f'{2000 / 512:.3f}'), w(' Hz'))),
        T(f'C 版和原論文的 Python 逐一比對：相對誤差中位數約 {fc:.0e}', True),
    ], size=16, fill=TEAL_L)

    s = d.slide('正規化與定點數：每次配戴重算 z-score', notes='src/c/rt_lda.h、features.h（fe_normalize_q16）、ldacal.h；report 35.11、35.13、35.40。', tag='我的做法')
    eqs(s, 0.6, 1.35, 6.3, 5.4, [
        T('1. 用這次配戴提示輪的 n = 6 × 10 = 60 個視窗', True),
        E(cat(t('μ'), t('='), frac(t('1'), t('n')), sum_(t('i'), '', sub(t('x'), t('i'))), t(','), w('  '), t('σ'), t('='), rad(cat(frac(t('1'), t('n')), sum_(t('i'), '', sup(par(cat(sub(t('x'), t('i')), t('−'), t('μ'))), t('2'))))))),
        E(cat(sup(t('x'), t('′')), t('='), frac(cat(t('x'), t('−'), t('μ')), t('σ')))),
        T('2. Q5.10 定點數（int16）', True),
        E(cat(t('q'), t('='), w('clip'), par(cat(w('round'), par(cat(t('1024'), sup(t('x'), t('′')))), t(','), t('−32768'), t(','), t('32767'))))),
        E(cat(w('範圍'), w(' '), t('±'), frac(t('32768'), t('1024')), t('='), t('±32'), t(','), w('  解析度 '), frac(t('1'), t('1024')))),
    ], size=17)
    v0 = 1.2345
    qv = round(v0 * 1024)
    eqs(s, 7.1, 1.35, 5.6, 5.4, [
        T('計算範例', True),
        E(cat(sup(t('x'), t('′')), t('='), t(f'{v0}'), t('⇒'), t('1024'), t('×'), t(f'{v0}'), t('='), t(f'{v0 * 1024:.2f}'))),
        E(cat(t('q'), t('='), t(f'{qv}'), t(','), w('  還原 '), frac(t(f'{qv}'), t('1024')), t('='), t(f'{qv / 1024:.6f}'))),
        T('最大捨入誤差', True),
        E(cat(frac(t('1'), t('2')), t('×'), frac(t('1'), t('1024')), t('='), t(f'{1 / 2048:.5f}'))),
        T('好處：輸入只佔 float 的一半；PC 參考與板上可以逐位元比對'),
        T('注意：先前的離線分析（DB6、模擬）用第 1 天的 z-score；自我測試的分析已改成和板子一樣'),
    ], size=17, fill=TEAL_L)

    lc = N['ldachk']
    p_ = 80
    tri = p_ * (p_ + 1) // 2
    s = d.slide('MCU 上的 LDA：記憶體與運算量', notes='src/c/ldacal.c；report 35.10、35.23；results/arm_ldacal_size.csv、lda_bench_board_480mhz_cache.txt、ldacal_c_check.csv。', tag='我的做法')
    eqs(s, 0.6, 1.35, 6.3, 5.4, [
        T('累加和 G 對稱：只存下三角', True),
        E(cat(frac(cat(t('p'), par(cat(t('p'), t('+'), t('1')))), t('2')), t('='), frac(cat(t('80'), t('×'), t('81')), t('2')), t('='), t(f'{tri:,}'), w(' 個 float'))),
        E(cat(t(f'{tri:,}'), t('×'), t('4'), w(' B'), t('='), t(f'{tri * 4:,}'), w(' B'), t('='), t(f'{tri * 4 / 1024:.1f}'), w(' KB'))),
        T('Cholesky 分解的乘加次數', True),
        E(cat(t('≈'), frac(sup(t('p'), t('3')), t('3')), t('='), frac(sup(t('80'), t('3')), t('3')), t('≈'), t(f'{p_ ** 3 / 3:,.0f}'))),
        T('每個類別再解兩次三角方程（各約 p² / 2）'),
    ], size=17)
    stats = [(f'{N["ldacal"]["ram"] / 1024:.1f} KB', 'LDA 模組 RAM（累加和＋工作區）'), (f'{N["bench"]["fit_ms"]:.1f} ms', '一次求解（板上，480 MHz）'),
             (f'{N["bench"]["predict_us"]:.1f} µs', '一次分類'), (f'{lc[1]:,}／{lc[0]:,}', '視窗預測和 Python 參考相同')]
    for i, (big, lab) in enumerate(stats):
        y = 1.35 + i * 1.37
        box(s, 7.1, y, 5.6, 1.22, fill=TEAL_L)
        text(s, 7.35, y + 0.08, 5.1, 0.6, big, size=26, bold=True, color=TEAL)
        text(s, 7.35, y + 0.72, 5.1, 0.45, lab, size=13, color=GREY)

    s = d.slide('通訊協定與頻寬', notes='src/c/protocol.h；src/pc/protocol.py。', tag='我的做法')
    table(s, 0.6, 1.35, 12.1, [['同步碼', '類型', '序號', '長度', '內容', '檢查碼'],
                               ['0xA5 0x5A', '1 B', '2 B', '2 B', '0–512 B', 'CRC-16/CCITT 2 B']], [2.0, 1.6, 1.6, 1.6, 2.3, 3.0], size=14, row_h=0.55)
    eqs(s, 0.6, 2.65, 7.3, 4.1, [
        T('一個樣本封包（10 ms）', True),
        E(cat(t('20'), w(' 樣本'), t('×'), t('8'), w(' 通道'), t('×'), t('2'), w(' B'), t('+'), t('9'), w(' B（標頭＋CRC）'), t('='), t('329'), w(' B'))),
        E(cat(frac(cat(t('329'), w(' B')), cat(t('10'), w(' ms'))), t('='), t('32,900'), w(' B/s'))),
        T('序列埠 921600 baud（8N1：每位元組 10 位元）', True),
        E(cat(frac(t('921,600'), t('10')), t('='), t('92,160'), w(' B/s'), t('⇒'), frac(t('32,900'), t('92,160')), t('='), t(f'{32900 / 92160 * 100:.1f}'), t('%'))),
    ], size=17)
    box(s, 8.2, 2.65, 4.5, 4.1, fill=TEAL_L)
    text(s, 8.45, 2.8, 4.1, 3.9, [('封包種類', {'bold': True, 'size': 16}),
                                  ('PC → MCU：SAMPLES、CONTROL（提示、FIT、任務標籤、出力判斷、清除）', {'bullet': True}),
                                  ('MCU → PC：COMMAND、PRED、STATUS', {'bullet': True}),
                                  ('序號＋CRC：掉封包可偵測；板上重放時用同一串位元組在 PC 重跑比對', {'bullet': True})], size=14, space=6)

    fs = N['fwrtos']
    ram = fs[1] + fs[2]
    s = d.slide('韌體架構與記憶體配置', notes='src/c/app_rt_rtos.c、FreeRTOSConfig.h；results/arm_rt_lda_rtos2_firmware_size.txt（1 KB = 1024 B）。', tag='我的做法')
    layers = [('USART3 中斷（最高）', '收樣本 → 環形緩衝', LIGHT, INK), ('rx task（高優先）', '特徵、分類、指令', TEAL, WHITE),
              ('learn task（低優先）', 'LDA 求解、任務標籤', TEAL_L, INK), ('idle', 'WFI 睡眠', LIGHT, INK)]
    for i, (h_, b_, fill, col) in enumerate(layers):
        bx = box(s, 0.6, 1.4 + i * 0.97, 4.4, 0.82, fill=fill)
        label_in(bx, [(h_, {'bold': True}), (b_, {'size': 12})], size=14, color=col)
    eqs(s, 5.3, 1.35, 7.4, 4.0, [
        T('提示輪暫存區（9 手勢版：最多 3 輪 × 9 手勢 × 30 視窗）', True),
        E(cat(t('810'), w(' 視窗'), t('×'), t('80'), t('×'), t('4'), w(' B'), t('='), t('259,200'), w(' B'), t('='), t('253.1'), w(' KB'))),
        T('9 手勢自我測試版（裸機）：RAM 327,812 B = 320.1 KB = 62.5%', True),
        T('整個韌體（FreeRTOS 版，6 手勢、120 視窗）', True),
        E(cat(w('RAM'), t('='), t(f'{fs[1]:,}'), t('+'), t(f'{fs[2]:,}'), t('='), t(f'{ram:,}'), w(' B'), t('='), t(f'{ram / 1024:.1f}'), w(' KB'))),
        E(cat(frac(t(f'{ram / 1024:.1f}'), t('512')), t('='), t(f'{ram / 1024 / 512 * 100:.1f}'), t('%'), w('  （程式 '), t(f'{fs[0] / 1024:.1f}'), w(' KB）'))),
    ], size=17)
    text(s, 5.3, 5.5, 7.4, 0.5, '兩個 task 的 stack 各 2 KB，實測只用約 0.5 KB；全部靜態配置，沒有 heap', size=14, color=GREY)

    rt = N['rtos']
    s = story(d, '即時性：學習再忙也不拖慢控制（FreeRTOS）', '低優先的學習 task 把 CPU 佔滿時，分類延遲會變嗎？（板上 11.5 分鐘即時重放）',
              notes='report 35.36–35.37；results/board_replay_lda_rtos2_*.csv、_rtos_stress_*.csv、_task_*.csv、energy_dryrun_board.txt。延遲在 PC 端量，含 USB。')
    bars(s, ['P50', 'P95', 'P99'], [(n2, rt['lat'][kk]) for n2, kk in (('裸機', 'bare'), ('FreeRTOS', 'rtos'), (f'FreeRTOS＋學習佔滿 CPU', 'stress'))],
         [MUTE, '7FB7B9', TEAL], w_=7.6, y=1.9, h=3.9, vmax=9, fmt='0.00')
    eqs(s, 8.4, 1.95, 4.3, 3.85, [
        T('CPU 使用率（平常）', True),
        E(cat(frac(cat(t(f'{N["win_us"] / 1000:.2f}'), w(' ms')), cat(t('100'), w(' ms'))), t('='), t(f'{N["win_us"] / 1000:.1f}'), t('%'))),
        T('每 100 ms 一個視窗的特徵＋分類'),
        T(f'實測 idle {rt["idle"]:.1f}%；壓力測試 idle {rt["idle_stress"]:.0f}%', True),
    ], size=16, fill=TEAL_L)
    conclude(s, f'即時處理放高優先、學習放低優先：學習佔 {rt["learn_stress"]:.0f}% CPU 時分類延遲（ms）不變')

    nn, mb = N['nn'], N['mlpb']
    s = story(d, '為什麼用 LDA，不用神經網路：準確率', '同樣只有一輪提示的校正預算（DB6 10 人 8 類），小型神經網路（MLP）會不會更準？',
              notes='report 35.38；results/nn_compare.csv（MLP 80-64-32-8，設定事先寫定、未調參，3 個 seed）。判準 R13 通過。')
    bars(s, ['同一個 session', '下一個 session'],
         [(n2, [nn['same'][m_], nn['next'][m_]]) for n2, m_ in (('LDA 一輪提示＋累加（我的）', 'lda_cue1'), ('MLP 微調', 'mlp_ft'),
                                                               ('MLP 累積微調', 'mlp_ft_cum'), ('MLP 重新訓練（MCU 做不到）', 'mlp_retrain'))],
         [TEAL, '7FB7B9', GREY, MUTE], y=1.9, h=3.9, vmin=30, vmax=62)
    conclude(s, '能在 MCU 上更新的 MLP 都沒贏 LDA；給相同資料從頭重訓也只打平')

    s = d.slide('為什麼用 LDA，不用神經網路：成本', notes='report 35.38–35.39；results/mlp_bench_board_480mhz_cache.txt。C 版 MLP 和 float64 參考預測完全相同。未比：原始訊號 CNN、int8 CMSIS-NN。', tag='我的做法')
    eqs(s, 0.6, 1.35, 6.6, 5.4, [
        T('MLP 80 → 64 → 32 → 8 的參數', True),
        E(cat(par(cat(t('80'), t('·'), t('64'), t('+'), t('64'))), t('+'), par(cat(t('64'), t('·'), t('32'), t('+'), t('32'))), t('+'), par(cat(t('32'), t('·'), t('8'), t('+'), t('8'))), t('='), t(f'{80 * 64 + 64 + 64 * 32 + 32 + 32 * 8 + 8:,}'))),
        T('每個視窗的乘加', True),
        E(cat(t('80'), t('·'), t('64'), t('+'), t('64'), t('·'), t('32'), t('+'), t('32'), t('·'), t('8'), t('='), t(f'{80 * 64 + 64 * 32 + 32 * 8:,}'), w('  （LDA：80 · 8 = 640）'))),
        T('一次提示輪的微調（反向傳播約 3 倍前向）', True),
        E(cat(t('3'), t('×'), t('7,424'), t('×'), t('80'), w(' 視窗'), t('×'), t('30'), w(' epoch'), t('≈'), t(f'{3 * 7424 * 80 * 30 / 1e6:.1f}'), t('×'), sup(t('10'), t('6')))),
    ], size=15)
    rows = [['板上實測（480 MHz）', 'LDA', 'MLP'],
            ['分類一個視窗', f'{mb["lda_pred"]:.1f} µs', f'{mb["mlp_pred"]:.1f} µs'],
            ['一次提示輪更新', f'{mb["lda_upd"]:.1f} ms', f'{mb["mlp_upd"]:,.0f} ms'],
            ['靜態 RAM', f'{mb["lda_ram"] / 1024:.1f} KB', f'{mb["mlp_ram"] / 1024:.1f} KB'],
            ['更新方式', '閉式解', '反向傳播']]
    table(s, 7.5, 1.35, 5.2, rows, [2.2, 1.4, 1.6], size=14, row_h=0.65, fills={(i, 1): TEAL_L for i in range(1, 5)})
    text(s, 7.5, 4.85, 5.2, 1.6, [f'更新慢 {mb["mlp_upd"] / mb["lda_upd"]:.0f} 倍、分類慢 {mb["mlp_pred"] / mb["lda_pred"]:.0f} 倍、RAM 多 {mb["mlp_ram"] / mb["lda_ram"]:.1f} 倍',
                                  '選 LDA 有準確率和板上實測兩種證據'], size=14, color=GREY, space=5)

    rtt, rtg, btk = N['rt_task'], N['rt_gate'], N['btask']
    s = story(d, '驗證方法：每一步都和參考逐一比對', '怎麼確定 C 版、板子上的結果是對的？', notes='report 6.4、35.10、35.22–35.25、35.28、35.33、35.36–35.39。')
    rows = [['驗證什麼', '怎麼比', '結果'],
            ['特徵（C vs 上游 Python）', '全部錄音逐一比對', f'相對誤差中位數約 {fc:.0e}'],
            ['LDA 求解（C vs Python）', '開發資料每個視窗', f'{lc[1]:,}／{lc[0]:,} 相同'],
            ['即時迴圈＋任務標籤（PC 上的 C）', '每個視窗、每次更新', f'{rtt["agree"]:,}／{rtt["windows"]:,} 相同'],
            ['出力判斷 C 版', '三種設定', f'{rtg["agree"]:,}／{rtg["windows"]:,} 相同'],
            ['板上即時重放（裸機）', '同一串位元組在 PC 重跑', f'{btk["same"]:,}／{btk["windows"]:,}；{btk["upd"]} 次更新'],
            ['板上 FreeRTOS（含 CPU 滿載）', '和裸機版、PC 比', f'{rt["same"]:,}／{rt["windows"]:,}；任務標籤值逐筆相同'],
            ['MLP C 版（對照組）', '和 float64 參考比', '預測 hash 相同']]
    table(s, 0.6, 1.95, 12.1, rows, [4.4, 3.6, 4.1], size=13, row_h=0.5)
    conclude(s, 'RQ3 的答案：整套方法能在 MCU 上即時執行，每一步都和參考逐一相同（耗電待量）')

    # ================================================================ 7 conclusions
    d.divider(6, '三個研究問題的答案，以及接下來要回答 RQ2 的實驗')
    s = d.slide('結論：三個研究問題', notes='若自我測試為 NO-GO，主軸改為「每次配戴的短提示＋跨次累積，可在 MCU 上執行」，任務標籤寫成負面結果。')
    rqs = [('RQ1', '免標籤自我校正有沒有用？', '沒有確認增益（獨立資料、預先登錄）；真正有效的是少量有標籤資料', TEAL_L),
           ('RQ2', '標籤能不能大部分由機器人任務提供？', '模擬中可以；真實資料上換次後不明顯 → 尚未回答，用自我測試檢驗', PINK),
           ('RQ3', '整套能不能在 MCU 上即時執行？', '可以：逐一驗證、FreeRTOS 下不拖慢、比 MLP 便宜；耗電待量', TEAL_L)]
    for i, (q, a1, a2, fill) in enumerate(rqs):
        y = 1.45 + i * 1.45
        box(s, 0.6, y, 12.1, 1.25, fill=fill)
        circle_num(s, 0.85, y + 0.35, i + 1, fill=TEAL if fill == TEAL_L else CORAL, d=0.55)
        text(s, 1.65, y + 0.12, 10.8, 0.5, f'{q}：{a1}', size=17, bold=True)
        text(s, 1.65, y + 0.62, 10.8, 0.5, a2, size=15, color=GREY)
    text(s, 0.6, 5.95, 12.1, 0.8, '收斂後的方向：每次重新戴上後，用一輪短提示＋跨次累積把模型校正回來，並檢驗機器人任務能否提供更多標籤，整套在 MCU 上即時執行',
         size=15, bold=True, color=TEAL)

    s = d.slide('感測器擺法：4 顆貼在主要肌肉上', notes=(
        'report 35.43；lab_kit/SOP_自我測試.md 3B。實驗室的 4 顆 Trigno IM 配對後完全不送資料（EMG 和加速度都是 0），借不到別的，'
        '只剩 4 顆 Avanti；4 個通道各送兩次當 8 通道（slots 16:15:11:5:16:15:11:5），韌體不用改。'), tag='我的做法')
    rows = [['通道', '肌肉', '位置', '用力時摸最鼓的地方'],
            ['1', '伸指肌（EDC）', '背側，靠肘 1/3–1/2', '手指用力伸直張開'],
            ['2', '屈指淺肌（FDS）', '掌側中段，稍偏小指側', '用力握拳'],
            ['3', '拇指側（FCR／FPL 一帶）', '掌側拇指側，中段稍往手腕', '拇指壓食指側面'],
            ['4', '尺側屈腕肌（FCU）', '掌側小指側，靠肘 1/3', '手腕往小指方向彎']]
    table(s, 0.6, 1.4, 12.1, rows, [0.9, 3.3, 4.1, 3.8], size=14, row_h=0.55)
    box(s, 0.6, 4.4, 12.1, 2.2, fill=TEAL_L)
    text(s, 0.85, 4.5, 11.6, 2.0, [('為什麼是 4 顆、貼主要肌肉', {'bold': True, 'size': 16}),
                                    ('原本計畫 8 顆繞一圈；實驗室的 IM 感測器不能串流，只剩 4 顆 Avanti', {'bullet': True}),
                                    ('貼在負責手腕上下左右與握放的 4 塊肌肉上；4 個通道各送兩次，8 通道的韌體不用改', {'bullet': True}),
                                    ('每天照描好的外框貼回同一位置（跨天累積要靠位置一致）', {'bullet': True})], size=14, space=5)

    s = d.slide('公開資料：貼主要肌肉時，4 顆夠不夠？', notes=(
        'report 35.46–35.48、35.50、35.52；results/db2_wrist/*.txt、results/ozdemir2022/ozdemir_sim.txt。'
        'DB2 的 4 顆 = FDS＋EDC 專用電極＋2 個環上電極（28 種組合的中位數）；Ozdemir 2022 = 4 顆由醫師定位在 ECR、FCR、ECU、FCU。'
        '兩者都是單次配戴；Ozdemir 照提示時間表標籤。'), tag='我的做法')
    rows = [['資料（4 顆）', '擺法', '7 類 一輪', '7 類 兩輪', '5 類 一輪', '軟標籤增益'],
            ['NinaPro DB2（10 人）', '2 顆對肌肉＋2 顆在環上', '58.5', '—', '64.1', '+3.5'],
            ['Ozdemir 2022（40 人）', '4 顆都對準肌肉', '85.3', '90.7', '90.9', '+2.7']]
    table(s, 0.6, 1.4, 12.1, rows, [2.9, 2.9, 1.4, 1.4, 1.4, 2.1], size=14, row_h=0.6)
    text(s, 0.6, 3.4, 12.1, 0.4, 'balanced accuracy（%）；7 類 = 手腕上下左右＋張開＋握拳＋放鬆，5 類 = 手腕上下左右＋放鬆；軟標籤增益 = 7 類一輪提示後加軟標籤（點）', size=12, color=GREY)
    box(s, 0.6, 3.95, 12.1, 2.0, fill=TEAL_L)
    text(s, 0.85, 4.05, 11.6, 1.8, [('看得到的', {'bold': True, 'size': 16}),
                                     ('4 顆都對準肌肉時，7 類兩輪提示平均 90.7%，40 人中 32 人 ≥ 85%', {'bullet': True}),
                                     ('兩輪比一輪好（85.3 → 90.7）；軟標籤再加 1–3 點，任務期望錯 30% 時幾乎不變', {'bullet': True}),
                                     ('9 類（加食指、比讚）只有 DB2 有：4 顆一輪 50.3%，加軟標籤 54.6%', {'bullet': True})], size=14, space=4)
    conclude(s, '4 顆對準肌肉在公開資料上 7 類約 90%（兩資料集的人與流程不同，不能直接比）；自我測試看自己能不能過 85%')

    s = d.slide('下一步：自我測試（9 個方向手勢、4 顆貼主要肌肉）', notes=(
        'report 35.44–35.49；lab_kit/SOP_自我測試.md 3B、4A；src/selftest9_analysis.py（兩條判準在錄之前已 commit）。'
        '2026-11-17 的 6 手勢錄製只當流程測試。自我測試的資料只用來決定方向；要發表需 IRB。'))
    steps = [('提示輪', '9 × 4 秒 × 2 輪'), ('P0', '提示手勢 9×3'), ('T1', '機械臂指令 40 次'), ('P1', '提示手勢 9×3'), ('T2', '機械臂指令 40 次'), ('P2', '提示手勢 9×3')]
    for i, (h_, b_) in enumerate(steps):
        x = 0.6 + i * 2.07
        bx = box(s, x, 1.4, 1.8, 1.0, fill=TEAL if h_ in ('T1', 'T2') else LIGHT)
        label_in(bx, [(h_, {'bold': True}), b_], size=13, color=WHITE if h_ in ('T1', 'T2') else INK)
        if i < 5:
            arrow(s, x + 1.83, 1.74, 0.2, 0.32)
    text(s, 0.6, 2.5, 12.1, 0.4, '8 個指令 = 上下左右前後＋夾爪開／夾；任務段換操作姿勢；判準 1：7／5 類選 ≥ 85% 中最多類的一組', size=13, color=GREY)
    Ad = lambda m_, pp: subsup(t('A'), t(pp), w(m_))  # noqa: E731
    eqs(s, 0.6, 3.0, 7.6, 3.75, [
        T('判準 2（錄之前已寫定；9 類；第 d 天）', True),
        E(cat(sub(t('D'), t('d')), t('='), frac(t('1'), t('2')), sum_(t('P ∈ {P1, P2}'), '', par(cat(Ad('軟標籤', 'P'), t('−'), Ad('只做提示', 'P')))))),
        E(cat(w('GO：  '), bar(t('D')), t('≥'), t('2'), w('  且  '), t('#'), par(cat(sub(t('D'), t('d')), t('>'), t('0'))), t('≥'), par(cat(frac(t('2'), t('3')), t('n')), '⌈', '⌉'))),
        E(cat(w('NO‑GO：  '), bar(t('D')), t('≤'), t('0'))),
    ], size=17)
    box(s, 8.5, 3.0, 4.2, 3.75, fill=TEAL_L)
    text(s, 8.75, 3.15, 3.8, 3.5, [('如果結果是', {'bold': True, 'size': 15}),
                                   ([('GO', {'bold': True, 'color': TEAL}), '：任務標籤留在主軸 → 多人先導實驗'], {'bullet': True}),
                                   ([('NO-GO', {'bold': True, 'color': CORAL}), '：寫成負面結果，主軸改為短提示＋MCU'], {'bullet': True}),
                                   ('其他：交給多人先導實驗', {'bullet': True}),
                                   ('結果【待填：錄完後更新】', {'color': GREY})], size=14, space=6)

    s = d.slide('接下來的時程（草案）', notes='時程待與指導老師討論；EMBC 2027 截止日以官網為準（第三方列表為 2027-01-24）。')
    plan = [('自我測試（9 手勢、4 顆）；12 月中進度報告', 0, 2), ('EMBC 2027 投稿（公開資料：獨立檢驗）', 1, 3), ('IRB；能量量測；真 Kinova 整條接起來', 1, 3),
            ('先導實驗（健常人、跨日）', 3, 5), ('正式實驗／病患個案（視 IRB）', 5, 7), ('分析與撰寫', 6, 8)]
    months = ['11月', '12月', '1月', '2月', '3月', '4月', '5月', '6月']
    x0, cw = 5.6, 0.89
    for j, m_ in enumerate(months):
        text(s, x0 + j * cw, 1.45, cw, 0.35, m_, size=12, color=GREY, align=PP_ALIGN.CENTER)
    for i, (t_, a0, a1) in enumerate(plan):
        y = 1.95 + i * 0.7
        text(s, 0.6, y, 4.9, 0.6, t_, size=15, anchor=MSO_ANCHOR.MIDDLE)
        box(s, x0, y + 0.08, cw * len(months), 0.45, fill=LIGHT, radius=0.5)
        box(s, x0 + a0 * cw, y + 0.08, (a1 - a0) * cw, 0.45, fill=CORAL if i == 0 else TEAL, radius=0.5)

    s = d.slide('需要老師決定或討論的事', dark=True, notes='建議：方向改為「每次配戴的短校正＋任務標籤」；EMBC 用公開資料投獨立檢驗；IRB 早點準備。')
    for i, t_ in enumerate(['論文主軸改為「每次配戴的短校正＋任務提供的標籤」？', '自我測試需不需要 IRB 或實驗室同意？多人先導實驗的 IRB 何時送？',
                            'EMBC 2027 用公開資料投「獨立檢驗」這篇，可以嗎？作者順序？', '病患個案的族群與時程']):
        y = 1.6 + i * 1.2
        circle_num(s, 0.9, y + 0.1, i + 1, fill=CORAL, d=0.6)
        text(s, 1.8, y, 10.6, 0.8, t_, size=20, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)

    s = d.slide('參考文獻', notes='標＊者還沒打開原文逐字確認。')
    refs = ['Jiang, Ma, Nazarpour (2024). Posture-invariant myoelectric control with self-calibrating random forests. Frontiers in Neurorobotics.',
            'Jiang et al. (2025). Plug-and-play myoelectric control via a self-calibrating random forest common model. Journal of Neural Engineering.',
            'Kyranou, Szymaniak, Nazarpour (2025). 8-participant two-day Trigno dataset. Scientific Data.',
            'Vidovic et al. (2016). Improving the robustness of myoelectric pattern recognition for upper limb prostheses by covariate shift adaptation. IEEE TNSRE 24(9).',
            'Campbell, Eddy, Bateman, Côté-Allard, Scheme (2024). Context-informed incremental learning improves both the performance and resilience of myoelectric control. J NeuroEng Rehabil 21:70.',
            'Scheme, Hudgins, Englehart (2013). Confidence-based rejection for improved pattern recognition myoelectric control. IEEE TBME 60(6).',
            'Chen, Wiesel, Eldar, Hero (2010). Shrinkage algorithms for MMSE covariance estimation. IEEE Transactions on Signal Processing.（OAS）',
            '＊Palermo et al. (2017). Repeatability of grasp recognition for robotic hand prosthesis control based on sEMG data. ICORR 2017.（NinaPro DB6）']
    text(s, 0.6, 1.4, 12.1, 5.0, refs, size=12, color=INK, space=5)
    text(s, 0.6, 6.55, 12.1, 0.35, '＊ 尚未打開原文逐字核對', size=11, color=GREY)

    d.prs.save(out)
    print(f'{d.n} slides -> {out}')


if __name__ == '__main__':
    build(sys.argv[1])
