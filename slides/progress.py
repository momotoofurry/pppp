"""Progress-report deck (December 2026): how the research converged, stage by stage. For every paper the deck relies
on: one slide with the paper's method, one with the paper's own results, then my work compared with it. One idea per
slide. Uses the drawing helpers and the data loader of slides/proposal.py; every number of mine is read from results/
(the report section is in each slide's notes); the papers' numbers are quoted from their full texts (abstract /
results), as recorded in 文獻搜尋_2026-11-13.md and report 35.30.
Usage (in the container): python slides/progress.py <out.pptx>
"""
import os
import sys

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proposal as P  # noqa: E402
from proposal import (CORAL, GREY, INK, LIGHT, MUTE, NAVY, TEAL, TEAL_L, WHITE, arrow, box, chart_style,  # noqa: E402
                      circle_num, color_series, csv, label_in, rgb, table, text)

WHEN = '2026 年 12 月'
FOOT = f'碩士論文進度報告｜{WHEN}｜方向待指導老師確認'
PINK, YELLOW = 'FBE3DD', 'FFF2CC'


class Deck(P.Deck):
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
            text(s, x, 0.42, 12.7 - x, 0.8, title, size=27, bold=True, color=WHITE if dark else INK, anchor=MSO_ANCHOR.MIDDLE)
        if not dark:
            text(s, 0.6, 7.02, 8, 0.3, FOOT, size=10, color=MUTE)
            text(s, 11.9, 7.02, 0.83, 0.3, str(self.n), size=10, color=MUTE, align=PP_ALIGN.RIGHT)
        if notes:
            s.notes_slide.notes_text_frame.text = notes
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


def paper_method(d, title, cite, setting, steps, notes):
    """the paper's method: setting on the left, its pipeline as a vertical flow on the right"""
    s = d.slide(title, notes=notes, tag='論文')
    text(s, 0.6, 1.3, 12.1, 0.4, cite, size=13, color=GREY)
    box(s, 0.6, 1.85, 5.9, 4.85, fill=LIGHT)
    text(s, 0.85, 2.0, 5.5, 4.6, [('實驗設定', {'size': 17, 'bold': True})] + [(ln, {'bullet': True}) for ln in setting],
         size=15, space=8)
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
    """the paper's own results (a table) and what the authors themselves list as limits"""
    s = d.slide(title, notes=notes, tag='論文')
    text(s, 0.6, 1.3, 12.1, 0.4, cite, size=13, color=GREY)
    table(s, 0.6, 1.85, 7.6, rows, widths, size=14, row_h=row_h, header_fill=CORAL)
    box(s, 8.5, 1.85, 4.2, 4.85, fill=LIGHT)
    text(s, 8.75, 2.0, 3.8, 4.6, [(head, {'size': 15, 'bold': True})] +
         [(ln, {'bullet': True}) for ln in limits], size=14, space=7)
    return s


def bars(s, cats, series, colors, x=0.6, y=1.9, w=12.1, h=4.0, vmin=0, vmax=100, legend=True, fmt='0.0', points=None):
    cd = CategoryChartData()
    cd.categories = cats
    for name, vals in series:
        cd.add_series(name, [round(v, 2) for v in vals])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), cd)
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
    N['fwrtos'] = [int(v) for v in next(ln for ln in sz if ln.strip().endswith('build/rtos/blink.elf')).split()[:3]]
    return N


def build(out):
    N = data()
    d = Deck()
    k, t2, t4, rp = N['kyr'], N['t2'], N['t4'], N['repro']

    # ================================================================ opening
    s = d.slide(dark=True, notes='進度報告：研究從原題目一步步收斂到現在方向的過程。每篇依據的論文都先講它的方法與結果，再講我的做法與比較。')
    text(s, 0.9, 1.5, 11.5, 0.5, '碩士論文進度報告', size=18, color='8FD3D0')
    text(s, 0.9, 2.1, 11.6, 2.0, ['從「免標籤自我校正」到「每次配戴的短校正＋任務標籤」',
                                    ('讀了哪些論文、做了什麼、發現什麼、所以怎麼改：一步步收斂', {'size': 22, 'bold': False, 'color': 'CFE3E6'})],
         size=32, bold=True, color=WHITE, space=10)
    text(s, 0.9, 4.75, 11, 1.2, ['機器人研究所｜生物力學與醫學應用實驗室', '報告人：【待填】　指導教授：【待填】',
                                  (f'{WHEN}　方向尚待指導老師確認', {'color': '8FD3D0'})], size=16, color='CFE3E6', space=4)

    s = d.slide('一頁看懂：研究怎麼一步步收斂', notes='每一列是一個階段；後面每個階段先講依據的論文（紅色「論文」標籤），再講我的做法（綠色標籤）。')
    rows = [['階段', '依據的論文', '問的問題', '答案 → 決定'],
            ['① 重現', 'Jiang 等（2024）', '原論文結果重現得出來嗎？', '可以 → 開始移植 MCU'],
            ['② 放進 MCU', '—', '原方法放得進微控制器嗎？', '刪減後可以 → pilot 韌體'],
            ['③ 獨立檢驗', 'Kyranou 等（2025）資料', '免標籤在別人的資料上有效嗎？', '沒有確認增益 → 轉向「少量標籤」'],
            ['④ 收縮 LDA', 'Vidovic 等（2016）', '有標籤後用什麼模型？', '收縮 LDA 最準最便宜 → 換主線'],
            ['⑤ 任務標籤', 'Campbell 等（2024）', '標籤能由機器人任務提供嗎？', '模擬有效'],
            ['⑥ 和文獻比', 'Vidovic、Scheme', '比文獻方法好嗎？', '模擬中較好；出力判斷有先例'],
            ['⑦ 真實資料', 'NinaPro DB6', '真實重新配戴上成立嗎？', '部分成立、部分被推翻'],
            ['⑧ 部署強化', '—', '邊學邊控制可行？為何不用神經網路？', 'FreeRTOS 不拖慢；LDA 勝 MLP'],
            ['→ 下一步', '—', '任務標籤在同一次配戴中有用嗎？', '自我測試決定 GO／NO-GO']]
    table(s, 0.6, 1.35, 12.1, rows, [1.9, 2.7, 3.9, 3.6], size=13, row_h=0.53,
          fills={**{(i, 0): TEAL_L for i in range(1, 9)}, **{(9, j): PINK for j in range(4)}})

    s = d.slide('起點：原本的題目', notes='原方法：Jiang 等（2024，Front Neurorobot）；Jiang 等（2025，J Neural Eng）。PROTOCOL 與 pilot 韌體依這個方法設計。')
    box(s, 0.6, 1.45, 12.1, 2.3, fill=LIGHT)
    text(s, 0.9, 1.6, 11.5, 2.1, [('原題目要做的', {'size': 18, 'bold': True}),
                                  ('把 Jiang 等（2024；2025）的「免標籤自我校正隨機森林」放進微控制器（STM32H7）', {'bullet': True}),
                                  ('用肌電控制 Kinova 機械臂抓放；先導實驗比較「固定模型」和「完整系統」', {'bullet': True})], size=16, space=8)
    box(s, 0.6, 4.05, 12.1, 2.6, fill=WHITE, line=TEAL)
    text(s, 0.9, 4.2, 11.5, 2.4, [('這份報告的讀法', {'size': 18, 'bold': True}),
                                  ([('論文', {'bold': True, 'color': CORAL}), ' 標籤：那篇論文用的方法、它自己報告的結果'], {'bullet': True}),
                                  ([('我的做法', {'bold': True, 'color': TEAL}), ' 標籤：我做了什麼、和論文比較、所以怎麼改'], {'bullet': True}),
                                  ('每個實驗都先寫判準再跑；沒通過的照實報告', {'bullet': True})], size=16, space=8)

    # ================================================================ ① Jiang 2024
    paper_method(d, 'Jiang 等（2024）：免標籤自我校正隨機森林', 'Jiang, Ma, Nazarpour. Posture-invariant myoelectric control with self-calibrating random forests. Frontiers in Neurorobotics, 2024',
                 ['資料：arm_position，20 人', '5 個手臂位置（P2、P4、P5、P6、P8）、11 個 block', '6 類手勢（含放鬆）、8 通道', '比較：LDA、RF、one-shot、自我校正'],
                 [('預訓練隨機森林', '用其他人的資料先訓練好'), ('one-shot 校正', '使用者做一次短校正：剪枝＋加新樹'),
                  ('使用中收集視窗', '不需要使用者給標籤'), ('t-SNE＋K-Means 偽標籤', '把視窗分群、對到類別'),
                  ('自動重訓新的樹', '免標籤地跟上變化')],
                 notes='方法照上游程式碼與論文文字整理（report 1.2）。')
    paper_results(d, 'Jiang 等（2024）報告的結果', '論文 Table 1 與正文（arm_position，20 人）',
                  [['指標（%）', '論文數字']] + [[n, f'{rp.loc[m, "paper"]:.1f}'] for n, m in
                                               (('自我校正（全部 block）', 'self-cal, all blocks (mean)'), ('LDA @P5', 'LDA @P5 (mean)'),
                                                ('RF @P5', 'RF @P5 (mean)'), ('one-shot 比 RF 多 @P5', 'one-shot gain over RF @P5'),
                                                ('自我校正比 one-shot 多 @P5', 'self-cal gain over one-shot @P5'))],
                  [5.4, 2.2],
                  ['只在同一份資料（arm_position）上驗證', 'LDA 只當對照，沒有做收縮估計', '放進穿戴裝置時的記憶體與運算沒有討論'],
                  notes='數字取自論文（results/paper_comparison.csv 的 paper 欄）。限制欄是我讀完後的整理，不是作者原話。')
    s = story(d, '我的重現：和論文逐項比較', '原論文的結果，用它公開的程式碼重跑得出來嗎？', notes='report 第 1 節；results/paper_comparison.csv（20 人 × 11 block × 3 seed）。')
    sel = [('自我校正（全部 block）', 'self-cal, all blocks (mean)'), ('LDA @P5', 'LDA @P5 (mean)'), ('RF @P5', 'RF @P5 (mean)'),
           ('one-shot 比 RF 多 @P5', 'one-shot gain over RF @P5'), ('自我校正比 one-shot 多 @P5', 'self-cal gain over one-shot @P5')]
    table(s, 0.6, 1.95, 12.1, [['指標（%）', '論文', '我重跑', '差']] +
          [[n, f'{rp.loc[m, "paper"]:.2f}', f'{rp.loc[m, "ours (seed-avg)"]:.2f}', f'{rp.loc[m, "diff (ours-paper)"]:+.2f}'] for n, m in sel],
          [5.5, 2.2, 2.2, 2.2], size=15, row_h=0.6)
    conclude(s, '重現成功：所有對得上的指標差距都 < 1 點 → 原方法可信，開始放進 MCU')

    # ================================================================ ② MCU
    cp = N['comp']
    s = story(d, '② 放進微控制器：照原樣放不下，要刪減', 'STM32H7 只有 512 KB 的 AXI RAM；原方法照原樣放得進去嗎？', notes='report 第 2–4、6、7、12 節；results/ram_scenarios.csv、sweep_pareto.csv。')
    bars(s, ['照論文原樣（float32 buffer、400 棵樹、t-SNE）', '不做 t-SNE（int16 buffer、100 棵樹）'],
         [('自我校正需要的 RAM（KB）', [N['ram_paper'], N['ram_noTSNE']])], None, y=1.9, h=3.0, vmax=1400, legend=False,
         fmt='0', points=[CORAL, TEAL])
    text(s, 0.6, 4.95, 12.1, 0.9, [f'模型壓縮：100 棵、深度 10、int16 只要 {cp["kb"]:.1f} KB（完整模型 {N["comp_full_kb"]:.0f} KB），準確率只差 {cp["d"]:+.2f} 點',
                                   '整套用 C、靜態記憶體重寫，在 NUCLEO-H753ZI 上即時執行'], size=15, space=4)
    conclude(s, '韌體 v2：拿掉 t-SNE、模型壓縮，凍結成 pilot 版本')

    sh = N['shift']
    s = story(d, '② 電極轉動時：免標籤救不回來', '電極環轉了一格（約 45°），免標籤的自我校正能補救嗎？', notes='report 8.1；results/shift_sweep_raw_summary*.csv（模擬：轉原始 EMG 再算特徵）。UHC＝Campbell 等（2024）的高信心偽標籤基準。')
    bars(s, ['沒有轉動', '轉一格：固定模型', '轉一格：免標籤自我校正', '轉一格：高信心偽標籤（UHC）', '轉一格：加開機對齊'],
         [('準確率 %', [sh['none'], sh['fixed'], sh['tsne'], sh['uhc'], sh['align']])], None, y=1.9, h=3.9, legend=False,
         points=[MUTE, GREY, CORAL, CORAL, TEAL])
    conclude(s, '加上「開機對齊」（估計轉了幾格再對回來）；模擬中可以救回')

    # ================================================================ ③ external
    ex = N['ext']
    s = story(d, '③ 預先登錄的獨立資料檢驗：免標籤沒有確認增益', '在別人錄的跨日資料（Kyranou 等，2025；8 人、Delsys Trigno）上，完整系統比固定模型好嗎？',
              notes='report 第 24 節；分析計畫在看資料前 commit（EXTERNAL_PLAN.md，8d16592），只跑一次；results/external_check_summary.csv。8 人可偵測 dz ≥ 1.16。')
    bars(s, ['固定模型', '完整系統（免標籤自我校正＋開機對齊）'], [('跨日準確率 %', [ex['F'], ex['A']])], None, x=0.6, y=1.9, w=7.0, h=3.9,
         legend=False, points=[MUTE, CORAL])
    box(s, 7.9, 2.0, 4.8, 3.7, fill=LIGHT)
    text(s, 8.15, 2.15, 4.4, 3.5, [('結果', {'size': 17, 'bold': True}),
                                   (f'差 {ex["d"]:+.2f} 點（95% CI {ex["lo"]:+.1f}, {ex["hi"]:+.1f}）', {'bullet': True}),
                                   ('主要損失：開機對齊在沒轉動時誤轉', {'bullet': True}),
                                   ('開發資料上約 +5 點的增益沒有出現', {'bullet': True})], size=15, space=8)
    conclude(s, '「免標籤」這條主線站不住 → 回頭看：增益到底從哪來？')

    s = story(d, '轉折一：真正有效的是「少量有標籤的資料」', '每次配戴開頭那段「有提示的手勢」其實帶標籤：拿它來校正，和免標籤比如何？',
              notes='report 35.1–35.4、35.16(0)；results/leaf_external.csv、lda_main.csv。Kyranou 取較嚴格的第二個 session（同手勢連續錄的偏樂觀已更正）。')
    bars(s, ['固定模型', '免標籤自我校正', '葉節點計數（我的新方法）', '重做 one-shot', '收縮 LDA 兩輪提示'],
         [('Kyranou 跨日 %', [k['F'], k['A'], k['LAonly_a8_za'], k['R'], k['cum_T2']])], None, y=1.9, h=3.9, legend=False,
         points=[MUTE, CORAL, '7FB7B9', '7FB7B9', TEAL])
    conclude(s, '研究問題改成：每次配戴用「少量標籤」校正；有標籤的做法高 15–22 點，免標籤只有約 +2')

    # ================================================================ ④ Vidovic 2016 + LDA
    paper_method(d, 'Vidovic 等（2016）：用小校正集收縮 LDA', 'Vidovic et al. Improving the robustness of myoelectric pattern recognition for upper limb prostheses by covariate shift adaptation. IEEE TNSRE, 2016',
                 ['離線：7 位健常人＋4 位截肢者，跨 5 天', '線上：8 位健常人＋1 位截肢者，3 天', '8 個電極；每天重新穿戴', '校正資料：不到 1 分鐘'],
                 [('第 1 天訓練 LDA', '類別平均 μ、共變異 Σ'), ('每天錄小校正集', '每個動作一次（< 1 分鐘）'),
                  ('把參數往校正集收縮', 'μ = (1 − τ)μ訓練 + τμ校正；Σ 同理（λ）'), ('用調整後的 LDA 分類', '原文最佳 τ 0.8、λ 0.8（LDACMA）')],
                 notes='依原文式 6–7、II-C、III-B 節（report 35.30）。')
    paper_results(d, 'Vidovic 等（2016）報告的結果', '原文摘要',
                  [['條件', '原文結果'], ['離線，有適應（5 天）', '準確率維持 92% 以上'], ['離線，沒有適應', '降到 75%'],
                   ['線上，有適應 vs 沒有', '表現提升 25%'], ['只調平均（LDAMA）', '比同時調共變異差']],
                  [4.0, 3.6],
                  ['每天仍要使用者主動做校正動作', '每次都從第 1 天的模型出發，不累積', '在 PC 上，不是穿戴裝置'],
                  notes='數字取自原文摘要；LDAMA 較差見原文 III-B 節。限制欄是我的整理。', row_h=0.62)
    la = N['la']
    s = story(d, '我的做法：收縮 LDA＋標籤跨次累積', '用同樣的開機標籤，LDA 能不能比我自己提出的森林方法更好？', notes='report 35.9–35.11；results/lda_anchor_summary.csv（開發資料 20 人，無偏移）。')
    bars(s, ['one-shot RF（固定）', '免標籤自我校正', '葉節點計數（我的方法）', '上游的 LDA', 'LDA＋收縮', 'LDA＋收縮＋標籤累積'],
         [('準確率 %（無偏移）', [la.loc[(0.0, c)] for c in ('F', 'A', 'LAonly_a8_za', 'LDAfix', 'LDAfixS', 'LDAcum')])], None,
         y=1.9, h=3.9, legend=False, vmin=50, points=[MUTE, CORAL, '7FB7B9', GREY, '7FB7B9', TEAL])
    conclude(s, '上游 LDA 輸給森林是因為沒做收縮；收縮＋累積的 LDA 最好 → 主線換成 LDA，葉節點計數退為對照組')

    bd = N['board']
    s = story(d, '我的做法：收縮 LDA 放上 MCU', 'LDA 的校正在 MCU 上做得到嗎？和 PC 結果一樣嗎？', notes='report 35.10、35.13–35.15；results/arm_ldacal_size.csv、lda_bench_board_480mhz_cache.txt、board_replay_lda_all_summary.csv。')
    stats = [(f'{N["ldacal"]["ram"] / 1024:.1f} KB', 'LDA 模組 RAM'), (f'{N["bench"]["add_total_ms"] + N["bench"]["fit_ms"]:.1f} ms', '每次配戴的更新'),
             (f'{bd["same"]:,}／{bd["windows"]:,}', '即時串流：視窗和 PC 相同')]
    for i, (big, lab) in enumerate(stats):
        x = 0.6 + i * 4.1
        box(s, x, 2.0, 3.85, 2.2, fill=LIGHT)
        text(s, x + 0.25, 2.25, 3.4, 0.9, big, size=34, bold=True, color=TEAL)
        text(s, x + 0.25, 3.3, 3.4, 0.7, lab, size=15, color=GREY)
    text(s, 0.6, 4.6, 12.1, 0.6, '但每次配戴都要使用者主動做提示動作，負擔還是在。', size=16)
    conclude(s, '下一個問題：標籤能不能由「使用」本身提供？')

    # ================================================================ ⑤ Campbell 2024 CIIL + task labels
    paper_method(d, 'Campbell 等（2024）：情境式增量學習（CIIL）', 'Campbell, Eddy, Bateman, Côté-Allard, Scheme. Context-informed incremental learning improves both the performance and resilience of myoelectric control. J NeuroEng Rehabil, 2024',
                 ['任務：虛擬游標 2 自由度 Fitts 測試', 'Myo 臂環 8 通道；LDA；5 類', '32 人（情境 2 的 21 人：臂環轉 45°）', '對照：UHC（高信心偽標籤）'],
                 [('使用者控制游標', '朝目標移動'), ('用任務情境推標籤', '朝目標＝正情境；遠離目標＝負情境'),
                  ('正情境：沿用預測當標籤', 'P-CIIL'), ('負情境：改成正確方向', 'N-CIIL；兩者合用＝P+N-CIIL'), ('增量更新 LDA', '邊用邊學')],
                 notes='依全文 Methods 整理（文獻搜尋_2026-11-13.md 1.0 節）。')
    paper_results(d, 'Campbell 等（2024）報告的結果（電極轉動後）', '全文 Results 圖 4–5、Discussion（情境 2，21 人）',
                  [['指標', 'P+N-CIIL', '其他'], ['throughput（bit/s）', '0.61', '轉動前 0.50'], ['path efficiency', '66.0%', 'P-CIIL 40.1%、UHC 11.7%'],
                   ['active error', '21.0%', '沒有適應 61.5%'], ['恢復到能做線上測試', '21／21', 'UHC 5、P-CIIL 14']],
                  [2.6, 1.8, 3.2],
                  ['虛擬環境提供「完美情境」：要找出情境正確率的下限', '要到更真實的實體環境驗證', '要擴展到 2 自由度以上'],
                  notes='數字與限制取自全文（作者 Discussion → Future work）。', row_h=0.62, head='作者自己說的未來工作')
    s = story(d, '我的做法：讓機器人任務提供標籤', '補 CIIL 留下的問題：實體機械臂、一個指令一個稀疏的結果、情境會錯；能不能少做提示？',
              notes='report 35.15–35.19；results/task_sim2_summary.csv（20 人 × 2 seed，使用者 25% 臨時改主意，電極偏移半格）。'
                    '另一個靈感：Xavier Fidêncio 等（2025）用錯誤相關電位與強化學習讓 BCI 從互動中適應。')
    bars(s, ['固定模型', '一輪提示', '一輪＋硬標籤', '一輪＋軟標籤＋出力判斷', '兩輪提示', '正確答案（上限）'],
         [('電極偏移半格 %', [t2.loc[(0.5, 0.25, c)].probe_after for c in ('fixed', 'cue1', 'cue1_gate', 'cue1_soft_act', 'cue2', 'oracle')])],
         None, y=1.9, h=3.9, legend=False, vmin=40, points=[MUTE, '7FB7B9', GREY, TEAL, '7FB7B9', MUTE])
    conclude(s, '一輪提示＋任務軟標籤 ≈ 兩輪提示 ≈ 上限：使用者主動給的標籤少一半（模擬）')

    s = story(d, '我的做法 vs CIIL：任務標籤出錯時', 'CIIL 假設情境完美；機器人的成功判斷會錯。標籤錯 0–30% 時，誰比較耐？',
              notes='report 35.20；results/task_sim4_summary.csv（½ 格偏移、使用者 10% 改主意、一輪提示）。判準 R1（軟標籤比最好的 CIIL 多 2 點）未通過。')
    es = [0.0, 0.1, 0.2, 0.3]
    cd = CategoryChartData()
    cd.categories = [f'標籤錯 {int(e * 100)}%' for e in es]
    cue = t4.loc[(0.5, 0.0, 'cue1')].probe_after
    series = [('只做一輪提示', None, MUTE), ('P+N-CIIL（＝硬標籤）', 'cue1_pn', CORAL), ('P-CIIL', 'cue1_pos', GREY), ('軟標籤（我的）', 'cue1_soft', TEAL)]
    for name, c, _ in series:
        cd.add_series(name, [round(cue if c is None else t4.loc[(0.5, e, c)].probe_after, 1) for e in es])
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

    # ================================================================ ⑥ Vidovic / Scheme direct comparison
    vd = N['vid']
    s = story(d, '我的做法 vs Vidovic（2016）：照原文公式實作', '用 Vidovic 原文的公式和參數，在同一個模擬、同一批人上比較', notes='report 35.30；results/task_sim6_vidovic.csv、task_sim4_summary.csv（½ 格偏移，block 1–10，20 人）。判準 R6 通過。')
    bars(s, ['固定第 1 天 LDA', 'Vidovic LDAMA', 'Vidovic LDACMA', '我的：一輪提示', '我的：一輪提示＋軟標籤'],
         [('模擬 %', [vd['fixed'], vd['LDAMA'], vd['LDACMA'], t4.loc[(0.5, 0.0, 'cue1')].probe_after, t4.loc[(0.5, 0.0, 'cue1_soft')].probe_after])],
         None, y=1.9, h=3.9, legend=False, vmin=40, points=[MUTE, GREY, GREY, '7FB7B9', TEAL])
    conclude(s, '模擬中我的方法較好，但部分來自「標籤跨次累積」，而且是模擬的偏移 → 要在真實資料上確認')

    fr = N['front']
    paper_method(d, 'Scheme 等（2013）：信心度拒絕與出力門檻', 'Scheme, Hudgins, Englehart. Confidence-based rejection for improved pattern recognition myoelectric control. IEEE TBME, 2013',
                 ['即時 Fitts 目標擷取任務', '健常人與截肢者', '對照：一般 LDA', '原文結果：throughput、path efficiency、完成率都顯著較高（p < 0.001）'],
                 [('LDA 分類', '每個視窗的判別值'), ('信心度＝判別值的 softmax', '低於門檻（例 0.97）就輸出「不動」'),
                  ('出力門檻（式 15）', '出力低於 μ不動＋3σ不動 的段落當「不動」')],
                 notes='依原文摘要、式 11–15、III-A 節（report 35.30）。')
    s = story(d, '我的出力判斷 vs Scheme 的做法', '不做提示、電極偏移時，休息中被誤觸發成動作的比例（越低越安全）',
              notes='report 35.30；results/task_sim6_frontend.csv（½ 格偏移、硬標籤、不做提示的壓力測試）。判準 R7：保留本研究的門檻。')
    bars(s, ['不加', 'Scheme：信心度拒絕 0.97', 'Scheme：出力門檻 μ＋3σ', '我的出力判斷'],
         [('休息誤觸發 %', [fr['none'], fr['rej'], fr['act_s'], fr['act']])], None, y=1.9, h=3.9, legend=False, vmax=25,
         fmt='0.00', points=[MUTE, CORAL, GREY, TEAL])
    conclude(s, '我的門檻誤觸發最少；但「出力門檻」Scheme 已做過 → 引用先例，只主張門檻的設法')

    # ================================================================ ⑦ real data
    sm, nx = N['db6']['same'], N['db6']['next']
    s = story(d, '⑦ 真實的重新配戴資料（NinaPro DB6）', '前面都是模擬的偏移。在公開的真實跨日資料（10 人、5 天、8 類）上還成立嗎？',
              notes='report 35.31–35.32；results/db6_sim*.csv、db6_adj*.csv。DB6 同一抓握 12 次連續錄，同次評分偏樂觀，所以加做「下一個 session」評分。判準 R8–R10 通過、R11 未通過。')
    bars(s, ['同一個 session 評分', '下一個 session 評分（去掉時間相鄰）'],
         [(n_, [sm[m], nx[m]]) for n_, m in (('固定第 1 天模型', 'fixed'), ('Vidovic LDACMA', 'LDACMA'), ('一輪提示（累積）', 'cue1'), ('一輪提示＋軟標籤', 'cue1_soft'))],
         [MUTE, GREY, '7FB7B9', TEAL], y=1.9, h=3.9, vmax=80)
    conclude(s, f'一輪提示＋累積成立（+{sm["cue1"] - sm["fixed"]:.0f} 點）；任務標籤換次後只剩 +{nx["cue1_soft"] - nx["cue1"]:.1f}；只做提示時和 Vidovic 打平')

    s = d.slide('轉折二：誠實整理——哪些站得住、哪些不成立', notes='每一項的出處見 report 35.x；判準都在跑之前寫進程式檔頭。')
    rows = [['主張', '狀態', '證據'],
            ['免標籤自我校正有增益', '不成立（未確認）', '預先登錄的獨立資料（Kyranou 8 人）'],
            ['每次配戴一輪提示＋跨次累積有效', '站得住', 'Kyranou、DB6 真實跨日'],
            ['收縮 LDA 比原方法的森林好且便宜', '站得住', '開發資料、Kyranou、DB6；板上實測'],
            ['整套能在 MCU 上即時執行', '站得住', '板上和 PC 逐一相同'],
            ['任務標籤能提升準確率', '未證實', '模擬有效；DB6 換次後不明顯'],
            ['軟標籤勝過所有 CIIL 策略', '不成立', '模擬中 P-CIIL 一樣耐錯'],
            ['比 Vidovic 高 16 點', '不成立', '只在同次評分；換次後消失'],
            ['出力判斷是新方法', '不是新的', 'Scheme 等（2013）已有同類做法']]
    fills = {(i, 1): TEAL_L if r[1] == '站得住' else (PINK if r[1].startswith('不') else YELLOW) for i, r in enumerate(rows[1:], start=1)}
    table(s, 0.6, 1.4, 12.1, rows, [5.0, 2.4, 4.7], size=14, row_h=0.56, fills=fills)
    text(s, 0.6, 6.55, 12.1, 0.4, '做法：每個實驗都先寫判準再跑；沒通過的照實寫進論文', size=14, bold=True, color=TEAL)

    # ================================================================ ⑧ deployment
    rt = N['rtos']
    s = story(d, '⑧ 改用 FreeRTOS：學習再忙也不拖慢控制', '邊用邊學時，模型更新會不會拖慢分類？（口試與業界都會問）',
              notes='report 35.36–35.37；results/board_replay_lda_rtos2_*.csv、_rtos_stress_*.csv、_task_*.csv。延遲在 PC 端量，含 USB。')
    bars(s, ['P50', 'P95', 'P99'], [(n_, rt['lat'][kk]) for n_, kk in (('裸機', 'bare'), ('FreeRTOS', 'rtos'),
                                                                       (f'FreeRTOS＋學習把 CPU 佔滿（idle {rt["idle_stress"]:.0f}%）', 'stress'))],
         [MUTE, '7FB7B9', TEAL], y=1.9, h=3.9, vmax=9, fmt='0.00')
    conclude(s, f'即時處理放高優先、學習放低優先：學習佔 {rt["learn_stress"]:.0f}% CPU 時分類延遲（ms）不變')

    nn, mb = N['nn'], N['mlpb']
    s = story(d, '⑧ 為什麼用 LDA，不用神經網路：準確率', '同樣只有一輪提示的校正預算，小型神經網路（MLP）會不會更準？',
              notes='report 35.38；results/nn_compare.csv（DB6 10 人 8 類；MLP 80-64-32-8，設定事先寫定、未調參，3 個 seed）。判準 R13 通過。')
    bars(s, ['同一個 session', '下一個 session'],
         [(n_, [nn['same'][m], nn['next'][m]]) for n_, m in (('LDA 一輪提示＋累加（我的）', 'lda_cue1'), ('MLP 微調', 'mlp_ft'),
                                                             ('MLP 累積微調', 'mlp_ft_cum'), ('MLP 重新訓練（MCU 做不到）', 'mlp_retrain'))],
         [TEAL, '7FB7B9', GREY, MUTE], y=1.9, h=3.9, vmin=30, vmax=62)
    conclude(s, '能在 MCU 上更新的 MLP 都沒贏 LDA；給相同資料從頭重訓也只打平')

    s = story(d, '⑧ 為什麼用 LDA，不用神經網路：板上實測', '同一顆 MCU、同一份資料，兩者的成本差多少？',
              notes='report 35.39；results/mlp_bench_board_480mhz_cache.txt。C 版 MLP 和 float64 參考預測完全相同。未比：原始訊號 CNN、int8 CMSIS-NN。')
    rows = [['NUCLEO-H753ZI，480 MHz', 'LDA', 'MLP', 'MLP／LDA'],
            ['分類一個視窗', f'{mb["lda_pred"]:.1f} µs', f'{mb["mlp_pred"]:.1f} µs', f'{mb["mlp_pred"] / mb["lda_pred"]:.0f} 倍'],
            ['一次提示輪的更新', f'{mb["lda_upd"]:.1f} ms', f'{mb["mlp_upd"]:,.0f} ms', f'{mb["mlp_upd"] / mb["lda_upd"]:.0f} 倍'],
            ['靜態 RAM', f'{mb["lda_ram"] / 1024:.1f} KB', f'{mb["mlp_ram"] / 1024:.1f} KB', f'{mb["mlp_ram"] / mb["lda_ram"]:.1f} 倍'],
            ['更新方式', '閉式解', '反向傳播 30 epoch', '—']]
    table(s, 0.6, 2.0, 12.1, rows, [4.3, 2.4, 3.0, 2.4], size=16, row_h=0.72, fills={(i, 1): TEAL_L for i in range(1, 5)})
    conclude(s, '選 LDA 有準確率和板上實測兩種證據；尚未比較原始訊號的 CNN')

    # ================================================================ converged + next
    s = d.slide('收斂後的方向', notes='若自我測試為 NO-GO，主軸改為「每次配戴的短提示＋跨次累積，可在 MCU 上執行」，任務標籤寫成負面結果。')
    text(s, 0.6, 1.35, 12.1, 0.7, '每次重新戴上後，用最少的使用者負擔把模型校正回來：一輪 8 秒提示＋跨次累積，加上機器人任務提供的標籤，整套在 MCU 上即時執行',
         size=16, bold=True, color=TEAL)
    rqs = [('RQ1', '免標籤自我校正有沒有用？', '已回答：沒有確認增益（獨立資料、預先登錄）', TEAL_L),
           ('RQ2', '標籤能不能大部分由機器人任務提供？', '主要問題，尚未回答：模擬支持、真實資料不明 → 自我測試', PINK),
           ('RQ3', '整套能不能在 MCU 上即時執行？', '已回答：可以（逐一驗證、FreeRTOS、和 MLP 比較）；耗電待量', TEAL_L)]
    for i, (q, a1, a2, fill) in enumerate(rqs):
        y = 2.35 + i * 1.35
        box(s, 0.6, y, 12.1, 1.15, fill=fill)
        circle_num(s, 0.85, y + 0.3, i + 1, fill=TEAL if fill == TEAL_L else CORAL, d=0.55)
        text(s, 1.65, y + 0.12, 10.8, 0.45, f'{q}：{a1}', size=16, bold=True)
        text(s, 1.65, y + 0.58, 10.8, 0.45, a2, size=14, color=GREY)
    text(s, 0.6, 6.45, 12.1, 0.4, '不論 RQ2 結果如何，RQ1＋RQ3 已足以構成論文；RQ2 決定任務標籤能不能成為主要貢獻', size=14)

    # ================================================================ implementation details
    s = d.slide(dark=True, notes='系統實作細節：最後收斂的系統怎麼做出來。來源：src/c/*.h 檔頭註解、report 6、7、35.10–35.29、35.36。')
    text(s, 0.9, 2.3, 11.5, 0.9, '系統實作細節', size=40, bold=True, color=WHITE)
    text(s, 0.9, 3.4, 11.5, 0.9, '訊號 → 特徵 → 模型 → 決策 → 機器人 → 標籤，以及怎麼驗證每一步', size=20, color='CFE3E6')

    s = story(d, '系統架構：PC 只轉送，MCU 做全部運算', '一個指令從肌電到機械臂、再把任務標籤送回 MCU 的路徑', notes='report 7.3、35.13、35.24–35.27；src/c/protocol.h、rt_lda.h、src/pc/TrignoBridge.cs、kinova_bridge.py。')
    chain = [('Delsys Trigno', '8 通道、2 kHz'), ('PC 橋接', 'TrignoBridge（C#）'), ('STM32H753', '480 MHz、Cortex-M7'),
             ('PC／ROS 2', 'kinova_bridge'), ('Kinova Gen3', '＋Robotiq 夾爪')]
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
    s = story(d, '特徵擷取：串流計算，和原論文的程式一致', '每 100 ms 從 8 個通道算出一個 80 維的特徵向量', notes='src/c/features.h；report 6.4；results/features_c_check.csv（C 和上游 Python 特徵逐一比對）。')
    steps = [('帶通濾波', '10–500 Hz、4 階 Butterworth'), ('切視窗', '長 200 ms、每 100 ms 一個'),
             ('每通道 10 個特徵', '時域 6 個＋頻域 4 個'), ('80 維向量', '10 特徵 × 8 通道')]
    for i, (h_, b_) in enumerate(steps):
        x = 0.6 + i * 3.08
        bx = box(s, x, 1.95, 2.8, 1.25, fill=TEAL if i == 3 else TEAL_L)
        label_in(bx, [(h_, {'bold': True}), (b_, {'size': 12})], size=15, color=WHITE if i == 3 else INK)
        if i < 3:
            arrow(s, x + 2.83, 2.42, 0.22, 0.3)
    table(s, 0.6, 3.5, 12.1, [['類別', '特徵', '說明'],
                              ['時域', 'RMS、WL、SSC、ZC、MAV、偏度', 'SSC、ZC 門檻為 0；偏度為有偏估計'],
                              ['頻域', 'VCF、MDF、MNF、PKF', 'Welch PSD：Hamming 400 點、補零到 512 點 FFT']],
          [1.6, 4.6, 5.9], size=14, row_h=0.6)
    text(s, 0.6, 5.4, 12.1, 0.5, f'C 版和上游 Python 逐一比對：相對誤差中位數約 {fc:.0e}（float32 的捨入誤差）', size=14, color=GREY)
    conclude(s, '特徵和原論文完全相同，差異只來自之後的模型與校正方式')

    s = story(d, '正規化與定點數：每次配戴重算 z-score', '不同次配戴的訊號大小不同；MCU 上要省記憶體又要和 PC 結果一模一樣', notes='src/c/rt_lda.h、features.h（fe_normalize_q16）、ldacal.h；report 35.11、35.13。')
    blocks = [('每次配戴的提示輪', ['6 個手勢 × 約 2 秒', '每個手勢取 10 個視窗', '存在暫存區（最多 120 個視窗，37.5 KB）']),
              ('z-score', ['用這次提示視窗算 μ、σ', 'x′ = (x − μ) / σ', '換次配戴就重算']),
              ('Q5.10 定點數', ['int16：值 = round(x′ × 1024)', '範圍 ±32，超過就飽和', '四捨六入五成雙；PC 與 MCU 結果相同'])]
    for i, (h_, lines) in enumerate(blocks):
        x = 0.6 + i * 4.1
        box(s, x, 1.95, 3.85, 2.75, fill=TEAL_L if i == 2 else LIGHT)
        text(s, x + 0.25, 2.1, 3.4, 2.5, [(h_, {'bold': True, 'size': 17})] + [(ln, {'bullet': True}) for ln in lines], size=14, space=6)
        if i < 2:
            arrow(s, x + 3.88, 3.15, 0.2, 0.32)
    text(s, 0.6, 4.95, 12.1, 0.5, '注意：PC 上的離線分析（DB6、自我測試）用的是第 1 天的 z-score；板上是每次配戴重算', size=13, color=GREY)
    conclude(s, 'int16 讓模型輸入只佔一半記憶體，而且 PC 參考和板上逐位元可比')

    lc = N['ldachk']
    s = story(d, '收縮 LDA：只存累加和，不存資料', '每次配戴只有 60 個視窗、80 維：共變異數不收縮就是奇異的；資料又要跨次累積', notes='src/c/ldacal.h（OAS：Chen 等，2010；同 sklearn.covariance.oas）；report 35.10；results/ldacal_c_check.csv、arm_ldacal_size.csv。')
    box(s, 0.6, 1.95, 7.3, 3.9, fill=LIGHT)
    text(s, 0.85, 2.05, 6.9, 3.7, [('狀態（固定大小）', {'bold': True, 'size': 16}),
                                   ('每類的數量 n_c、總和 s_c = Σx', {'bullet': True}),
                                   ('G = Σ x xᵀ（對稱，只存下三角 3,240 個 float）', {'bullet': True}),
                                   ('求解', {'bold': True, 'size': 16}),
                                   ('m_c = s_c / n_c；S = (G − Σ n_c m_c m_cᵀ) / N', {'bullet': True}),
                                   ('OAS 收縮：C = (1 − ρ)S + ρ·tr(S)/p·I', {'bullet': True}),
                                   ('Cholesky 分解；w_c = C⁻¹m_c，b_c = −½ m_cᵀw_c', {'bullet': True}),
                                   ('分類：argmax_c (x·w_c + b_c)；遺忘：每學一次 G、s、n × 0.97', {'bullet': True})], size=14, space=4)
    stats = [(f'{N["ldacal"]["ram"] / 1024:.1f} KB', 'LDA 模組 RAM'), (f'{N["bench"]["fit_ms"]:.1f} ms', '一次求解（板上）'),
             (f'{lc[1]:,}／{lc[0]:,}', '視窗預測和 Python 參考相同')]
    for i, (big, lab) in enumerate(stats):
        y = 1.95 + i * 1.32
        box(s, 8.2, y, 4.5, 1.18, fill=TEAL_L)
        text(s, 8.4, y + 0.08, 4.1, 0.6, big, size=24, bold=True, color=TEAL)
        text(s, 8.4, y + 0.68, 4.1, 0.45, lab, size=13, color=GREY)
    conclude(s, '收縮讓少量資料也能解；累加和讓標籤跨次累積但記憶體固定；整個更新是閉式解')

    s = story(d, '任務軟標籤：把「預期的手勢」變成機率標籤', '機器人端只說「這一步預期哪個手勢、哪些手勢也合理」；MCU 怎麼更新模型？', notes='src/c/rt_lda.h（RTL_EPS 0.15、RTL_P0 0.05、RTL_P_INVALID 0.01、RTL_BETA 0.3、RTL_DECAY 0.97、RTL_CMD_MAX 16）、ldacal.h（ld_soft_q、ld_add_soft）；report 35.18、35.22–35.24。')
    table(s, 0.6, 1.95, 5.6, [['先驗（依機器人狀態）', '機率'], ['預期的手勢', '1 − ε = 0.85'], ['其他當下合理的手勢', '共分 ε = 0.15'],
                              ['放鬆', '0.05'], ['當下不合理的手勢', '0.01']], [3.6, 2.0], size=14, row_h=0.6)
    box(s, 6.5, 1.95, 6.2, 3.9, fill=LIGHT)
    text(s, 6.75, 2.05, 5.8, 3.7, [('更新步驟', {'bold': True, 'size': 16}),
                                   ('取出造成這個指令的視窗（最多 16 個）', {'bullet': True}),
                                   ('q ∝ 先驗 × exp(β·(s̄ − max s̄))，β = 0.3', {'bullet': True}),
                                   ('遺忘：累加和 × 0.97', {'bullet': True}),
                                   ('G += Σ x xᵀ；s_c += q_c Σ x；n_c += q_c × 視窗數', {'bullet': True}),
                                   ('重新求解（同一個閉式解）', {'bullet': True}),
                                   (f'板上一次 {N["soft_cmd_ms"]:.2f} ms', {'bullet': True, 'bold': True, 'color': TEAL})], size=14, space=5)
    conclude(s, '標籤錯了也只是機率偏一點；晚到、對應到舊指令的標籤用視窗編號擋掉')

    s = story(d, '出力判斷與指令決策', '休息時不能亂動：什麼時候才送出一個機器人指令？', notes='src/c/rt_lda.h（RTL_SET_GATE）、decision.h；report 35.18、35.21、35.28；預設 k = 3，出力判斷錄資料時先不開。')
    box(s, 0.6, 1.95, 5.9, 3.9, fill=LIGHT)
    text(s, 0.85, 2.05, 5.5, 3.7, [('出力判斷', {'bold': True, 'size': 16}),
                                   ('出力 = 8 個通道原始 MAV 的總和', {'bullet': True}),
                                   ('門檻 = √（放鬆的中位數 × 最小手勢的中位數）', {'bullet': True}),
                                   ('用提示輪的視窗算；低於門檻 → 一律當放鬆', {'bullet': True}),
                                   ('對照：Scheme 等（2013）用 μ不動＋3σ不動', {'bullet': True, 'color': GREY})], size=14, space=6)
    box(s, 6.8, 1.95, 5.9, 3.9, fill=TEAL_L)
    text(s, 7.05, 2.05, 5.5, 3.7, [('指令決策', {'bold': True, 'size': 16}),
                                   ('連續 3 個視窗分類相同 → 確立這個手勢', {'bullet': True}),
                                   ('和上一個不同才送指令；一直握著只送一次', {'bullet': True}),
                                   ('握拳＝位置 A、側捏＝回原位、三指捏＝夾', {'bullet': True}),
                                   ('食指指出＝位置 B、張開＝放、放鬆＝不動', {'bullet': True})], size=14, space=6)
    conclude(s, '一個指令要連續 3 個視窗（每 100 ms 一個）一致才送出；休息誤觸發主要靠出力判斷擋')

    s = story(d, '通訊協定：PC、MCU、機器人之間', '同一套封包格式，PC 工具、板子和 PC 參考版都用它', notes='src/c/protocol.h、rt_lda.h；src/pc/protocol.py。')
    table(s, 0.6, 1.95, 12.1, [['欄位', '同步碼', '類型', '序號', '長度', '內容', '檢查碼'],
                               ['大小', '0xA5 0x5A', '1 B', '2 B', '2 B', '0–512 B', 'CRC-16/CCITT']], [1.6, 1.8, 1.4, 1.4, 1.4, 2.0, 2.5], size=14, row_h=0.6)
    table(s, 0.6, 3.35, 12.1, [['方向', '封包', '內容'],
                               ['PC → MCU', 'SAMPLES', '20 個樣本 × 8 通道 int16（10 ms）；32.9 KB/s，佔 921600 baud 的 36%'],
                               ['PC → MCU', 'CONTROL', '提示開始／結束、FIT、任務標籤、出力判斷設定、清除累積'],
                               ['MCU → PC', 'COMMAND／PRED／STATUS', '機器人指令、每個視窗的分類（記錄與延遲）、事件與診斷']],
          [1.8, 3.0, 7.3], size=13, row_h=0.55)
    conclude(s, '封包有序號與 CRC：掉封包可以偵測；板上重放時用同一串位元組在 PC 重跑比對')

    fs = N['fwrtos']
    s = story(d, '韌體架構與記憶體', '最後的韌體：FreeRTOS、全部靜態配置，用了 STM32H753 多少記憶體？', notes='src/c/app_rt_rtos.c、FreeRTOSConfig.h；results/arm_rt_lda_rtos2_firmware_size.txt（1 KB = 1024 B）。')
    layers = [('USART3 中斷（最高）', '收樣本 → 環形緩衝', LIGHT, INK), ('rx task（高優先）', '特徵、分類、指令', TEAL, WHITE),
              ('learn task（低優先）', 'LDA 求解、任務標籤', TEAL_L, INK), ('idle', 'WFI 睡眠', LIGHT, INK)]
    for i, (h_, b_, fill, col) in enumerate(layers):
        bx = box(s, 0.6, 1.95 + i * 0.97, 4.6, 0.82, fill=fill)
        label_in(bx, [(h_, {'bold': True}), (b_, {'size': 12})], size=14, color=col)
    table(s, 5.6, 1.95, 7.1, [['項目', '大小'], ['提示輪暫存區（120 視窗 × 80 × float）', '37.5 KB'],
                              ['LDA 模組（累加和、Cholesky 工作區）', f'{N["ldacal"]["ram"] / 1024:.1f} KB'],
                              ['兩個 task 的 stack', '各 2 KB（實測用約 0.5 KB）'],
                              ['整個韌體 RAM（data＋bss）', f'{(fs[1] + fs[2]) / 1024:.1f} KB／512 KB'],
                              ['整個韌體程式（text）', f'{fs[0] / 1024:.1f} KB／2 MB']], [4.6, 2.5], size=13, row_h=0.6)
    conclude(s, 'RAM 用不到四分之一：還有空間放更多暫存或第二個模型')

    rtt, rtg, btk, rt = N['rt_task'], N['rt_gate'], N['btask'], N['rtos']
    s = story(d, '驗證方法：每一步都和參考逐一比對', '怎麼確定 C 版、板子上的結果是對的？', notes='report 6.4、35.10、35.22–35.25、35.28、35.33、35.36–35.39；對應的 results/*_check.csv 與 board_replay_*_summary.csv。')
    rows = [['驗證什麼', '怎麼比', '結果'],
            ['特徵（C vs 上游 Python）', '全部錄音逐一比對', f'相對誤差中位數約 {fc:.0e}'],
            ['LDA 求解（C vs Python）', '開發資料每個視窗', f'{lc[1]:,}／{lc[0]:,} 相同'],
            ['即時迴圈＋任務標籤（PC 上的 C）', '每個視窗、每次更新', f'{rtt["agree"]:,}／{rtt["windows"]:,} 相同'],
            ['出力判斷 C 版', '三種設定', f'{rtg["agree"]:,}／{rtg["windows"]:,} 相同'],
            ['板上即時重放（裸機）', '同一串位元組在 PC 重跑', f'{btk["same"]:,}／{btk["windows"]:,}；{btk["upd"]} 次更新'],
            ['板上 FreeRTOS（含 CPU 滿載）', '和裸機版、PC 比', f'{rt["same"]:,}／{rt["windows"]:,}；任務標籤值逐筆相同'],
            ['MLP C 版（對照組）', '和 float64 參考比', '預測 hash 相同']]
    table(s, 0.6, 1.95, 12.1, rows, [4.4, 3.6, 4.1], size=13, row_h=0.5)
    conclude(s, '每個 C 模組都有 Python 參考；分析判準都在跑之前寫定')

    s = d.slide('下一步：自我測試——任務標籤在同一次配戴中有沒有用', notes=(
        'report 35.35；lab_kit/SELFTEST.md、src/selftest_analysis.py（判準在錄之前已 commit）。用自己的筆電：Trigno SDK（TCU）已安裝；板子已燒 LDA 韌體。'
        '自我測試的資料只用來決定方向；要發表需 IRB 核准的先導實驗。'))
    steps = [('提示輪', '8 秒、中立姿勢'), ('P0', '提示手勢 6×2'), ('T1', '任務指令 40 次'), ('P1', '提示手勢 6×2'),
             ('T2', '任務指令 40 次'), ('P2', '提示手勢 6×2')]
    for i, (h_, b_) in enumerate(steps):
        x = 0.6 + i * 2.07
        bx = box(s, x, 1.5, 1.8, 1.05, fill=TEAL if h_ in ('T1', 'T2') else LIGHT)
        label_in(bx, [(h_, {'bold': True}), b_], size=13, color=WHITE if h_ in ('T1', 'T2') else INK)
        if i < 5:
            arrow(s, x + 1.83, 1.85, 0.2, 0.32)
    text(s, 0.6, 2.65, 12.1, 0.4, 'T1 之後改用操作機器人的姿勢，每 10 次換一次；手勢隨機穿插，避開 DB6 的時間相鄰問題', size=13, color=GREY)
    box(s, 0.6, 3.25, 5.9, 2.75, fill=LIGHT)
    text(s, 0.85, 3.4, 5.5, 2.5, [('比較（同一份錄音離線重放）', {'size': 17, 'bold': True}),
                                  ('只做提示輪 vs 加任務軟標籤', {'bullet': True}),
                                  ('也比硬標籤、P-CIIL，以及只用 T1 的標籤', {'bullet': True}),
                                  ('第 2 天起：自己真實的跨日重戴效果', {'bullet': True})], size=14, space=6)
    box(s, 6.8, 3.25, 5.9, 2.75, fill=TEAL_L)
    text(s, 7.05, 3.4, 5.5, 2.5, [('判準 R12（錄之前已寫定）', {'size': 17, 'bold': True}),
                                  ([('GO', {'bold': True, 'color': TEAL}), '：P1、P2 平均多 ≥ 2 點且多數天為正 → 任務標籤留在主軸'], {'bullet': True}),
                                  ([('NO-GO', {'bold': True, 'color': CORAL}), '：≤ 0 → 負面結果，主軸改為短提示＋MCU 部署'], {'bullet': True}),
                                  ('其他或天花板 → 交給多人先導實驗', {'bullet': True})], size=14, space=6)
    text(s, 0.6, 6.25, 12.1, 0.5, '自己 1 人、2–4 天、每天約 20 分鐘；不需要 Kinova；結果【待填：錄完後更新這一頁】', size=13, color=GREY)

    s = d.slide('接下來的時程（草案）', notes='時程待與指導老師討論；EMBC 2027 截止日以官網為準（第三方列表為 2027-01-24）。')
    plan = [('自我測試；12 月中進度報告', 0, 2), ('EMBC 2027 投稿（公開資料：獨立檢驗）', 1, 3), ('IRB；能量量測；真 Kinova 整條接起來', 1, 3),
            ('先導實驗（健常人、跨日）', 3, 5), ('正式實驗／病患個案（視 IRB）', 5, 7), ('分析與撰寫', 6, 8)]
    months = ['11月', '12月', '1月', '2月', '3月', '4月', '5月', '6月']
    x0, cw = 5.6, 0.89
    for j, m in enumerate(months):
        text(s, x0 + j * cw, 1.45, cw, 0.35, m, size=12, color=GREY, align=PP_ALIGN.CENTER)
    for i, (t, a0, a1) in enumerate(plan):
        y = 1.95 + i * 0.7
        text(s, 0.6, y, 4.9, 0.6, t, size=15, anchor=MSO_ANCHOR.MIDDLE)
        box(s, x0, y + 0.08, cw * len(months), 0.45, fill=LIGHT, radius=0.5)
        box(s, x0 + a0 * cw, y + 0.08, (a1 - a0) * cw, 0.45, fill=CORAL if i == 0 else TEAL, radius=0.5)

    s = d.slide('需要老師決定或討論的事', dark=True, notes='建議：方向改為「每次配戴的短校正＋任務標籤」；EMBC 用公開資料投獨立檢驗；IRB 早點準備。')
    for i, t in enumerate(['論文主軸改為「每次配戴的短校正＋任務提供的標籤」？', '自我測試需不需要 IRB 或實驗室同意？多人先導實驗的 IRB 何時送？',
                           'EMBC 2027 用公開資料投「獨立檢驗」這篇，可以嗎？作者順序？', '病患個案的族群與時程']):
        y = 1.6 + i * 1.2
        circle_num(s, 0.9, y + 0.1, i + 1, fill=CORAL, d=0.6)
        text(s, 1.8, y, 10.6, 0.8, t, size=20, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)

    s = d.slide('參考文獻', notes='標＊者還沒打開原文逐字確認。')
    refs = ['Jiang, Ma, Nazarpour (2024). Posture-invariant myoelectric control with self-calibrating random forests. Frontiers in Neurorobotics.',
            'Jiang et al. (2025). Plug-and-play myoelectric control via a self-calibrating random forest common model. Journal of Neural Engineering.',
            'Kyranou, Szymaniak, Nazarpour (2025). 8-participant two-day Trigno dataset. Scientific Data.',
            'Campbell, Eddy, Bateman, Côté-Allard, Scheme (2024). Context-informed incremental learning improves both the performance and resilience of myoelectric control. J NeuroEng Rehabil 21:70.',
            'Xavier Fidêncio, Grün, Klaes, Iossifidis (2025). Hybrid brain-computer interface using error-related potential and reinforcement learning. Front Hum Neurosci 19:1569411.',
            'Vidovic et al. (2016). Improving the robustness of myoelectric pattern recognition for upper limb prostheses by covariate shift adaptation. IEEE TNSRE 24(9).',
            'Scheme, Hudgins, Englehart (2013). Confidence-based rejection for improved pattern recognition myoelectric control. IEEE TBME 60(6).',
            '＊Palermo et al. (2017). Repeatability of grasp recognition for robotic hand prosthesis control based on sEMG data. ICORR 2017.（NinaPro DB6）']
    text(s, 0.6, 1.4, 12.1, 5.0, refs, size=12, color=INK, space=5)
    text(s, 0.6, 6.55, 12.1, 0.35, '＊ 尚未打開原文逐字核對', size=11, color=GREY)

    d.prs.save(out)
    print(f'{d.n} slides -> {out}')
    print('check:', {kk: round(vv, 2) for kk, vv in N['vid'].items()}, {kk: round(vv, 2) for kk, vv in N['front'].items()})


if __name__ == '__main__':
    build(sys.argv[1])
