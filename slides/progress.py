"""Progress-report deck (December 2026): how the research converged, stage by stage. Uses the drawing helpers and the
data loader of slides/proposal.py; every number is read from results/ (the report section is in each slide's notes).
Usage (in the container): python slides/progress.py <out.pptx>
"""
import os
import sys

import pandas as pd
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


class Deck(P.Deck):
    def slide(self, title=None, dark=False, notes=''):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        self.n += 1
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(NAVY if dark else WHITE)
        if title:
            text(s, 0.6, 0.42, 12.1, 0.8, title, size=28, bold=True, color=WHITE if dark else INK, anchor=MSO_ANCHOR.MIDDLE)
        if not dark:
            text(s, 0.6, 7.02, 8, 0.3, FOOT, size=10, color=MUTE)
            text(s, 11.9, 7.02, 0.83, 0.3, str(self.n), size=10, color=MUTE, align=PP_ALIGN.RIGHT)
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s


HEAD = ['讀了／問了什麼', '做了什麼', '發現', '所以改變']


def stage(d, title, cols, notes, h=2.2):
    """the four-step logic of every stage: read -> did -> found -> changed (cards at the top)"""
    s = d.slide(title, notes=notes)
    for i, lines in enumerate(cols):
        x = 0.6 + i * 3.08
        fill = TEAL_L if i == 3 else LIGHT
        box(s, x, 1.38, 2.85, h, fill=fill)
        text(s, x + 0.15, 1.45, 2.6, 0.4, HEAD[i], size=14, bold=True, color=TEAL if i < 3 else INK)
        text(s, x + 0.15, 1.85, 2.6, h - 0.5, [(ln, {'bullet': True}) for ln in lines], size=12, space=3)
        if i < 3:
            arrow(s, x + 2.88, 1.38 + h / 2 - 0.15, 0.17, 0.3)
    return s


def data():
    N = P.load()
    pc = csv('paper_comparison.csv').set_index('metric (%)')
    N['repro'] = pc
    rs = csv('ram_scenarios.csv').set_index('Unnamed: 0')
    N['ram_paper'] = float(rs.iloc[0]['KB'])
    N['ram_noTSNE'] = float(rs.iloc[2]['KB'])
    sp = csv('sweep_pareto.csv')
    r = sp[(sp.max_depth.astype(str) == '10') & (sp.n_trees == 100) & (sp.precision == 'int16')].iloc[0]   # 'none' makes it text
    N['comp'] = dict(kb=float(r.compact_KB), d=float(r.acc_minus_full))
    sh = csv('shift_sweep_raw_summary.csv').set_index('shift')
    uh = csv('shift_sweep_raw_summary_uhc.csv').set_index('shift')
    N['shift1'] = dict(fixed=float(sh.loc[1, 'tsne_fixed']), tsne=float(sh.loc[1, 'tsne']), align=float(sh.loc[1, 'align']),
                       uhc=float(uh.loc[1, 'uhc']), none=float(sh.loc[0, 'tsne']))
    ex = csv('external_check_summary.csv')
    e = ex[(ex.span == '0-2s') & (ex.comp == 'A1')].iloc[0]
    N['ext'] = dict(F=float(e.F), A=float(e.A), d=float(e['diff']), lo=float(e.ci_lo), hi=float(e.ci_hi))
    la = csv('lda_anchor_summary.csv')
    la = la[(la.stream == 'base')].set_index(['shift', 'cond']).acc
    N['la'] = la
    v = csv('task_sim6_vidovic.csv')
    v = v[(v['shift'] == 0.5) & (v.block >= 1)]                    # v.shift is DataFrame.shift
    vm = v.groupby(['tau', 'lam', 'subject']).acc.mean().groupby(['tau', 'lam']).mean()
    N['vid'] = dict(fixed=float(vm.loc[(0.0, 0.0)]), LDAMA=float(vm.loc[(0.7, 0.0)]), LDACMA=float(vm.loc[(0.8, 0.8)]))
    return N


def build(out):
    N = data()
    d = Deck()
    k, t2, t4 = N['kyr'], N['t2'], N['t4']

    # ---- 1 cover
    s = d.slide(dark=True, notes='進度報告：研究從原題目一步步收斂到現在方向的過程，每一步都附上證據與報告章節。')
    text(s, 0.9, 1.5, 11.5, 0.5, '碩士論文進度報告', size=18, color='8FD3D0')
    text(s, 0.9, 2.1, 11.6, 2.0, ['從「免標籤自我校正」到「每次配戴的短校正＋任務標籤」',
                                    ('一步步收斂的過程：讀了什麼、做了什麼、發現什麼、所以怎麼改', {'size': 22, 'bold': False, 'color': 'CFE3E6'})],
         size=32, bold=True, color=WHITE, space=10)
    text(s, 0.9, 4.75, 11, 1.2, ['機器人研究所｜生物力學與醫學應用實驗室', '報告人：【待填】　指導教授：【待填】',
                                  (f'{WHEN}　方向尚待指導老師確認', {'color': '8FD3D0'})], size=16, color='CFE3E6', space=4)

    # ---- 2 roadmap
    s = d.slide('一頁看懂：研究怎麼一步步收斂', notes='每一列是一個階段；後面每一頁照「讀了什麼 → 做了什麼 → 發現 → 所以改變」展開。')
    rows = [['階段', '問的問題', '答案 → 決定'],
            ['① 重現原方法', '原論文的結果重現得出來嗎？', f'可以（{N["repro"].loc["self-cal, all blocks (mean)", "ours (seed-avg)"]:.2f}% 對論文 84.6%）'],
            ['② 放進 MCU', '原方法放得進微控制器嗎？', '原樣放不下；刪減後可以 → 做出 pilot 韌體'],
            ['③ 獨立資料檢驗', '免標籤自我校正在別人的資料上有效嗎？', '沒有確認增益 → 轉向「少量有標籤資料」'],
            ['④ 改用收縮 LDA', '有了標籤，用什麼模型？', '收縮 LDA 最準、最便宜 → 換主線'],
            ['⑤ 任務標籤', '標籤能由機器人任務提供嗎？', '模擬有效；照原文和 CIIL、Vidovic 比較'],
            ['⑥ 真實資料', '在真實的重新配戴資料上成立嗎？', '部分成立、部分被推翻 → 修正主張'],
            ['⑦ 部署強化', '邊學邊控制可行嗎？為何不用神經網路？', 'FreeRTOS 下不拖慢；LDA 勝過 MLP'],
            ['→ 下一步', '任務標籤在同一次配戴中有用嗎？', '自我測試（12 月）決定 GO／NO-GO']]
    table(s, 0.6, 1.4, 12.1, rows, [2.4, 4.6, 5.1], size=14, row_h=0.58,
          fills={**{(i, 0): TEAL_L for i in range(1, 8)}, (8, 0): 'FBE3DD', (8, 1): 'FBE3DD', (8, 2): 'FBE3DD'})

    # ---- 3 starting point
    s = d.slide('起點：原本的題目', notes='原方法：Jiang 等（2024，Front Neurorobot）；Jiang 等（2025，J Neural Eng）。PROTOCOL 與 pilot 韌體依這個方法設計。')
    box(s, 0.6, 1.45, 6.0, 3.9, fill=LIGHT)
    text(s, 0.85, 1.65, 5.6, 3.6, [('原方法（Jiang 等，2024；2025）', {'size': 18, 'bold': True}),
                                   ('預訓練好的隨機森林（66 人資料）', {'bullet': True}),
                                   ('每次使用前做一次短的 one-shot 校正', {'bullet': True}),
                                   ('之後「免標籤」自我校正：t-SNE＋K-Means 產生偽標籤，自動重訓新的樹', {'bullet': True}),
                                   ('論文：重新配戴、換手臂姿勢後仍維持高準確率', {'bullet': True})], size=15, space=8)
    box(s, 6.9, 1.45, 5.8, 3.9, fill=TEAL_L)
    text(s, 7.15, 1.65, 5.4, 3.6, [('原題目要做的', {'size': 18, 'bold': True}),
                                   ('把這套方法放進微控制器（STM32H7）', {'bullet': True}),
                                   ('用肌電控制 Kinova 機械臂抓放', {'bullet': True}),
                                   ('先導實驗：比較「固定模型」和「完整系統」', {'bullet': True}),
                                   ('第一個問題：原方法的結果可信嗎？', {'bullet': True, 'bold': True, 'color': TEAL})], size=15, space=8)
    box(s, 0.6, 5.65, 12.1, 1.05, fill=WHITE, line=TEAL)
    text(s, 0.9, 5.72, 11.5, 0.9, [([('接下來每一頁都照同一個順序：', {'bold': True}),
                                    '讀了／問了什麼 → 做了什麼 → 發現 → 所以改變'], {}),
                                   ('每次轉向都有證據；每個實驗都先寫判準再跑，沒通過的照實報告', {'color': GREY})],
         size=15, space=4, anchor=MSO_ANCHOR.MIDDLE)

    # ---- 4 stage 1: reproduce
    rp = N['repro']
    s = stage(d, '① 重現原方法', [
        ['Jiang 等（2024、2025）', '上游公開的程式碼與資料'],
        ['照程式碼在 Docker 重跑', '20 人 × 11 block × 3 seed', '逐項和論文 Table 1 比'],
        [f'自我校正 {rp.loc["self-cal, all blocks (mean)", "ours (seed-avg)"]:.2f}%（論文 84.6%）', '所有對得上的指標差 < 1 點'],
        ['原方法的數字可信', '→ 開始壓縮、移植到 MCU']],
        notes='report 第 1 節；results/paper_comparison.csv、baseline.csv。')
    sel = ['self-cal, all blocks (mean)', 'LDA @P5 (mean)', 'RF @P5 (mean)', 'one-shot gain over RF @P5', 'self-cal gain over one-shot @P5']
    names = ['自我校正（全部 block）', 'LDA @P5', 'RF @P5', 'one-shot 比 RF 多 @P5', '自我校正比 one-shot 多 @P5']
    rows = [['指標（%）', '論文', '本研究重跑', '差']] + [[n, f'{rp.loc[m, "paper"]:.2f}', f'{rp.loc[m, "ours (seed-avg)"]:.2f}',
                                                     f'{rp.loc[m, "diff (ours-paper)"]:+.2f}'] for n, m in zip(names, sel)]
    table(s, 0.6, 3.85, 12.1, rows, [5.5, 2.2, 2.2, 2.2], size=13, row_h=0.47)

    # ---- 5 stage 2: MCU
    sh, cp = N['shift1'], N['comp']
    s = stage(d, '② 把原方法放進微控制器', [
        ['STM32H7 只有 512 KB AXI RAM', '論文 ablation：拿掉 t-SNE 會變差'],
        ['壓縮掃描：樹數、深度、int16', '整套用 C、靜態記憶體重寫', '上板量時間、即時串流'],
        [f'照原樣約 {N["ram_paper"]:.0f} KB RAM，放不下', f'100 棵、深度 10、int16：模型 {cp["kb"]:.1f} KB，準確率 {cp["d"]:+.2f} 點',
         f'電極轉一格：固定模型掉到 {sh["fixed"]:.0f}%，免標籤只拉回 {sh["tsne"] - sh["fixed"]:.0f} 點'],
        ['韌體 v2：拿掉 t-SNE', '加「開機對齊」處理電極轉動', '凍結成 pilot 版本']],
        notes='report 第 2–4、6–8、12、18–23 節；results/ram_scenarios.csv、sweep_pareto.csv、shift_sweep_raw_summary*.csv。'
              'UHC（Campbell 等，2024 的高信心偽標籤）在電極轉動後反而變差。')
    stats = [(f'{N["ram_paper"]:.0f} → {N["ram_noTSNE"]:.0f} KB', '自我校正需要的 RAM（原樣 → 不做 t-SNE）'),
             (f'{sh["fixed"]:.0f}% → {sh["tsne"]:.0f}%', '電極轉一格：固定模型 → 免標籤自我校正'),
             (f'{sh["uhc"]:.0f}%', '高信心偽標籤（UHC，Campbell 等，2024）反而更差'),
             (f'{sh["align"]:.0f}%', '加開機對齊（模擬）')]
    for i, (big, lab) in enumerate(stats):
        x = 0.6 + i * 3.08
        box(s, x, 3.95, 2.85, 2.0, fill=LIGHT)
        text(s, x + 0.2, 4.1, 2.5, 0.8, big, size=22 if len(big) > 8 else 26, bold=True, color=TEAL if i != 2 else CORAL)
        text(s, x + 0.2, 4.9, 2.5, 0.95, lab, size=12, color=GREY)
    text(s, 0.6, 6.2, 12.1, 0.5, '這時的研究問題仍是：「免標籤」能不能在 MCU 上補救重新配戴後的準確率下降', size=14, color=INK)

    # ---- 6 stage 3: external validation
    ex = N['ext']
    s = stage(d, '③ 預先登錄的獨立資料檢驗：免標籤沒有確認增益', [
        ['Kyranou 等（2025）', '8 人、兩天、Delsys Trigno', '（和本實驗室同一套設備）'],
        ['分析計畫在看資料前 commit', '同一份韌體 C 碼、參數不改', '只跑一次'],
        [f'跨日：固定 {ex["F"]:.1f}% → 完整系統 {ex["A"]:.1f}%', f'差 {ex["d"]:+.2f}（CI {ex["lo"]:+.1f}, {ex["hi"]:+.1f}）', '主要損失：開機對齊誤轉'],
        ['「免標籤」這條主線站不住', '→ 回頭看：增益到底從哪來？']],
        notes='report 第 24 節；EXTERNAL_PLAN.md（commit 8d16592）；results/external_check_summary.csv。8 人只能偵測 dz ≥ 1.16，所以是「沒有確認」，不是「無效」。')
    cd = CategoryChartData()
    cd.categories = ['固定模型', '完整系統（免標籤自我校正＋開機對齊）']
    cd.add_series('跨日準確率 %', [round(ex['F'], 1), round(ex['A'], 1)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.85), Inches(6.5), Inches(2.9), cd)
    chart_style(gf.chart, vmax=100, vmin=0, label_size=13, axis_size=12)
    P.color_points(gf.chart.plots[0].series[0], [MUTE, CORAL])
    box(s, 7.4, 3.95, 5.3, 2.7, fill=LIGHT)
    text(s, 7.65, 4.1, 4.9, 2.5, [('這一步的意義', {'size': 16, 'bold': True}),
                                  ('分析在看資料前寫定：結果是什麼就報什麼', {'bullet': True}),
                                  ('開發資料上的增益（約 +5 點）在獨立資料上沒有出現', {'bullet': True}),
                                  ('原方法的優勢可能來自開發資料本身', {'bullet': True})], size=14, space=6)

    # ---- 7 turning point 1: labels
    s = stage(d, '轉折一：真正有效的是「少量有標籤的資料」', [
        ['重看自己的實驗', '每次配戴開頭那段「有提示的手勢」其實帶標籤'],
        ['把開機序列當訓練訊號', '比較：免標籤 vs 用這 60 個有標籤視窗'],
        ['有標籤的做法比固定模型高 15–22 點', '免標籤只有 +2 點左右'],
        ['研究問題改成：每次配戴用少量標籤校正', '提出「葉節點計數」新方法']],
        notes='report 35.1–35.4、35.16(0)；results/leaf_external.csv、lda_main.csv。Kyranou 取較嚴格的 block 1（同手勢連續錄的偏樂觀已更正）。')
    cd = CategoryChartData()
    cats = ['固定模型', '免標籤自我校正', '葉節點計數（新方法）', '重做 one-shot', '收縮 LDA 兩輪提示']
    vals = [k['F'], k['A'], k['LAonly_a8_za'], k['R'], k['cum_T2']]
    cd.categories = cats
    cd.add_series('Kyranou 跨日 %', [round(x, 1) for x in vals])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.85), Inches(12.1), Inches(2.85), cd)
    chart_style(gf.chart, vmax=100, vmin=0, label_size=12, axis_size=12)
    P.color_points(gf.chart.plots[0].series[0], [MUTE, CORAL, '7FB7B9', '7FB7B9', TEAL])
    text(s, 0.6, 6.68, 12.1, 0.3, 'Kyranou 跨日資料第二個 session（較嚴格的看法），8 人，準確率 %', size=11, color=GREY)

    # ---- 8 stage 4: LDA
    la = N['la']
    s = stage(d, '④ 改用收縮 LDA：比自己提出的方法更準、更便宜', [
        ['短時重校正的文獻（例：Vidovic 等，2016）多是調整 LDA', '上游論文的 LDA 基準很差'],
        ['用同樣的開機標籤，比較 LDA 與森林的做法', 'LDA 加收縮估計（80 維、60 個視窗）'],
        [f'上游 LDA 沒做收縮：{la.loc[(0.0, "LDAfix")]:.1f}% → 加收縮 {la.loc[(0.0, "LDAfixS")]:.1f}%',
         f'標籤累積的收縮 LDA {la.loc[(0.0, "LDAcum")]:.1f}%，所有方法中最好'],
        ['主線換成收縮 LDA', '葉節點計數退為對照組（負面結果）', '寫 C 版、上板']],
        notes='report 35.9–35.11；results/lda_anchor_summary.csv（開發資料 20 人，無偏移／½ 格偏移）。')
    cd = CategoryChartData()
    cats = ['one-shot RF（固定）', '免標籤自我校正', '葉節點計數', '上游 LDA', 'LDA＋收縮', 'LDA 標籤累積']
    conds = ['F', 'A', 'LAonly_a8_za', 'LDAfix', 'LDAfixS', 'LDAcum']
    cd.categories = cats
    cd.add_series('無偏移', [round(la.loc[(0.0, c)], 1) for c in conds])
    cd.add_series('電極偏移半格', [round(la.loc[(0.5, c)], 1) for c in conds])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.8), Inches(12.1), Inches(3.0), cd)
    chart_style(gf.chart, legend=True, vmax=100, vmin=30, label_size=10, axis_size=11)
    color_series(gf.chart, [TEAL, CORAL])

    # ---- 9 LDA on the MCU
    fw, bd = N['fw'], N['board']
    s = d.slide('④-2 收縮 LDA 放上 MCU：和 PC 逐一相同', notes='report 35.10、35.13–35.15；ldacal.c、rt_lda.c；results/arm_ldacal_size.csv、lda_bench_board_480mhz_cache.txt、board_replay_lda_all_summary.csv。')
    stats = [(f'{N["ldacal"]["ram"] / 1024:.1f} KB', 'LDA 模組 RAM'),
             (f'{N["bench"]["add_total_ms"] + N["bench"]["fit_ms"]:.1f} ms', '每次配戴更新（60 個視窗＋求解）'),
             (f'{N["bench"]["predict_us"]:.1f} µs', '每次分類'),
             (f'{bd["same"]:,}／{bd["windows"]:,}', '11 分鐘即時串流：視窗和 PC 相同'),
             (f'{bd["p95"]:.1f} ms', '延遲 P95'),
             (f'{bd["lost"]}', '遺失封包')]
    for i, (big, lab) in enumerate(stats):
        x, y = 0.6 + (i % 3) * 4.1, 1.5 + (i // 3) * 2.05
        box(s, x, y, 3.85, 1.8, fill=LIGHT)
        text(s, x + 0.25, y + 0.2, 3.4, 0.85, big, size=32, bold=True, color=TEAL)
        text(s, x + 0.25, y + 1.1, 3.4, 0.6, lab, size=14, color=GREY)
    box(s, 0.6, 5.7, 12.1, 1.0, fill=TEAL_L)
    text(s, 0.9, 5.8, 11.5, 0.8, '下一個問題：每次配戴都要使用者主動做提示動作，負擔還是在。標籤能不能由「使用」本身提供？',
         size=16, bold=True, anchor=MSO_ANCHOR.MIDDLE)

    # ---- 10 stage 5: task labels
    a = t2.loc[(0.5, 0.25, 'cue1_soft_act')]
    s = stage(d, '⑤ 標籤從哪來：讓機器人任務提供', [
        ['Campbell 等（2024）CIIL：用任務情境更新 LDA', 'Xavier Fidêncio 等（2025）：用回饋訊號學習'],
        ['閉迴路抓放模擬：系統只知道機器人狀態與任務流程', '掃描回饋比例、延遲、錯誤率'],
        ['一輪提示＋任務標籤 ≈ 兩輪提示 ≈ 上限', '最怕錯的標籤；不做提示時越學越歪'],
        ['方法：每次配戴一輪 8 秒提示＋任務軟標籤', '加出力判斷擋休息誤觸發']],
        notes='report 35.15–35.19；results/task_sim2_summary.csv（20 人 × 2 seed，使用者 25% 臨時改變主意）。')
    cats = ['固定模型', '一輪提示', '一輪＋硬標籤', '一輪＋軟標籤＋出力判斷', '兩輪提示', '正確答案（上限）']
    conds = ['fixed', 'cue1', 'cue1_gate', 'cue1_soft_act', 'cue2', 'oracle']
    cd = CategoryChartData()
    cd.categories = cats
    cd.add_series('無偏移', [round(t2.loc[(0.0, 0.25, c)].probe_after, 1) for c in conds])
    cd.add_series('電極偏移半格', [round(t2.loc[(0.5, 0.25, c)].probe_after, 1) for c in conds])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.8), Inches(12.1), Inches(3.0), cd)
    chart_style(gf.chart, legend=True, vmax=100, vmin=40, label_size=10, axis_size=11)
    color_series(gf.chart, [TEAL, CORAL])

    # ---- 11 CIIL comparison and wrong labels
    s = stage(d, '⑤-2 和最接近的前人方法（CIIL）比：標籤出錯時', [
        ['精讀 Campbell 等（2024）', '先前的「硬標籤」其實就是 P+N-CIIL'],
        ['任務標籤隨機出錯 0–30%', '比較 CIIL 各策略與軟標籤', '判準事先寫定'],
        ['硬標籤約一成錯就失去好處', '軟標籤到 30% 仍比只做提示好', 'P-CIIL 一樣耐錯：「勝過所有 CIIL」不成立'],
        ['主張改成：軟標籤＋一輪提示，並照實報告未通過的判準']],
        notes='report 35.20–35.21；results/task_sim4_summary.csv（電極偏移半格、使用者 10% 改主意、一輪提示）。判準 R1 未通過。')
    es = [0.0, 0.1, 0.2, 0.3]
    cd = CategoryChartData()
    cd.categories = [f'{int(e * 100)}%' for e in es]
    cue = t4.loc[(0.5, 0.0, 'cue1')].probe_after
    series = [('只做一輪提示', None, MUTE), ('P+N-CIIL（＝硬標籤）', 'cue1_pn', CORAL), ('P-CIIL', 'cue1_pos', GREY),
              ('軟標籤（本研究）', 'cue1_soft', TEAL)]
    for name, c, _ in series:
        cd.add_series(name, [round(cue if c is None else t4.loc[(0.5, e, c)].probe_after, 1) for e in es])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.6), Inches(3.75), Inches(12.1), Inches(3.05), cd)
    ch = gf.chart
    chart_style(ch, legend=True, vmax=94, vmin=78, label_size=10, axis_size=12)
    ch.plots[0].has_data_labels = False
    for srs, (_, _, col) in zip(ch.plots[0].series, series):
        srs.format.line.color.rgb = rgb(col)
        srs.format.line.width = P.Pt(3 if col in (TEAL, CORAL) else 2)
        srs.smooth = False
        srs.marker.format.fill.solid()
        srs.marker.format.fill.fore_color.rgb = rgb(col)
    ch.value_axis.visible = True
    ch.value_axis.has_major_gridlines = True
    ch.value_axis.major_gridlines.format.line.color.rgb = rgb('E3E8EA')

    # ---- 12 published baselines from the full texts
    vd = N['vid']
    s = stage(d, '⑤-3 照原文實作文獻方法：短時重校正與拒絕', [
        ['Vidovic 等（2016）：收縮適應 LDA', 'Scheme 等（2013）：信心度拒絕與出力門檻', '（使用者提供全文）'],
        ['依原文公式與參數實作', '同一個模擬、同一批受試者比較'],
        [f'模擬中：本研究 {t4.loc[(0.5, 0.0, "cue1_soft")].probe_after:.1f}% 對 Vidovic {vd["LDACMA"]:.1f}%',
         '出力判斷 Scheme 已做過同類想法'],
        ['出力判斷改為引用先例', '只主張門檻的設法', '→ 要在真實資料上確認']],
        notes='report 35.30；results/task_sim6_vidovic.csv、task_sim4_summary.csv（½ 格偏移，block 1–10）。')
    cd = CategoryChartData()
    cats = ['固定第 1 天 LDA', 'Vidovic LDAMA', 'Vidovic LDACMA', '本研究：一輪提示', '本研究：一輪提示＋軟標籤']
    vals = [vd['fixed'], vd['LDAMA'], vd['LDACMA'], t4.loc[(0.5, 0.0, 'cue1')].probe_after, t4.loc[(0.5, 0.0, 'cue1_soft')].probe_after]
    cd.categories = cats
    cd.add_series('模擬，電極偏移半格 %', [round(x, 1) for x in vals])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.8), Inches(12.1), Inches(2.9), cd)
    chart_style(gf.chart, vmax=100, vmin=40, label_size=12, axis_size=12)
    P.color_points(gf.chart.plots[0].series[0], [MUTE, GREY, GREY, '7FB7B9', TEAL])
    text(s, 0.6, 6.68, 12.1, 0.3, '模擬的配戴情況（手臂位置＋電極偏移），不是真的重新配戴', size=11, color=GREY)

    # ---- 13 stage 6: real data DB6
    sm, nx = N['db6']['same'], N['db6']['next']
    s = stage(d, '⑥ 真實的重新配戴資料（NinaPro DB6）：部分成立、部分被推翻', [
        ['前面都是模擬的偏移', '找公開的真實跨日資料：NinaPro DB6（10 人、5 天）'],
        ['同樣的流程與事先寫定的判準', '再改用「下一個 session」評分，去掉時間相鄰'],
        [f'一輪提示＋累積：+{sm["cue1"] - sm["fixed"]:.0f} 點（成立）', '只做提示時和 Vidovic 打平',
         f'任務標籤同次 +{sm["cue1_soft"] - sm["cue1"]:.0f}，換下一次只剩 +{nx["cue1_soft"] - nx["cue1"]:.1f}'],
        ['不再主張「比 Vidovic 高 16 點」', '任務標籤的價值要靠真人實驗確認']],
        notes='report 35.31–35.32；results/db6_sim*.csv、db6_adj*.csv。DB6 同一抓握 12 次連續錄，所以同次評分會偏樂觀。判準 R8–R10 通過、R11 未通過。')
    cd = CategoryChartData()
    cd.categories = ['同一個 session 評分', '下一個 session 評分']
    series = [('固定第 1 天模型', 'fixed', MUTE), ('Vidovic LDACMA', 'LDACMA', GREY), ('一輪提示（累積）', 'cue1', '7FB7B9'),
              ('一輪提示＋軟標籤', 'cue1_soft', TEAL)]
    for name, m, _ in series:
        cd.add_series(name, [round(sm[m], 1), round(nx[m], 1)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.75), Inches(12.1), Inches(3.0), cd)
    chart_style(gf.chart, legend=True, vmax=80, vmin=0, label_size=11, axis_size=12)
    color_series(gf.chart, [c for _, _, c in series])

    # ---- 14 turning point 2: claims
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
    fills = {}
    for i, r in enumerate(rows[1:], start=1):
        fills[(i, 1)] = TEAL_L if r[1] == '站得住' else ('FBE3DD' if r[1].startswith('不') else 'FFF2CC')
    table(s, 0.6, 1.4, 12.1, rows, [5.0, 2.4, 4.7], size=14, row_h=0.56, fills=fills)
    text(s, 0.6, 6.55, 12.1, 0.4, '做法：每個實驗都先寫判準再跑；沒通過的照實寫進論文', size=14, bold=True, color=TEAL)

    # ---- 15 stage 7a: FreeRTOS
    rt = N['rtos']
    s = stage(d, '⑦ 部署強化：改用 FreeRTOS，學習再忙也不拖慢控制', [
        ['口試、業界會問：邊學邊控制會不會變慢？', 'RTOS 是嵌入式的標準做法'],
        ['即時處理、學習分成高低優先 task', '低優先 task 人工滿載的壓力測試'],
        ['輸出和裸機版完全相同', f'學習佔 {rt["learn_stress"]:.0f}% CPU 時延遲不變', f'平常 idle {rt["idle"]:.1f}%'],
        ['部署章節有了即時性的證據', '耗電量測待做']],
        notes='report 35.36–35.37；results/board_replay_lda_rtos2_*.csv、board_replay_lda_rtos_stress_*.csv、board_replay_lda_task_*.csv。')
    cd = CategoryChartData()
    cd.categories = ['P50', 'P95', 'P99']
    for name, kk in (('裸機', 'bare'), ('FreeRTOS', 'rtos'), (f'FreeRTOS＋學習滿載（idle {rt["idle_stress"]:.0f}%）', 'stress')):
        cd.add_series(name, [round(x, 2) for x in rt['lat'][kk]])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.75), Inches(12.1), Inches(2.95), cd)
    chart_style(gf.chart, legend=True, vmax=9, vmin=0, fmt='0.00', label_size=11, axis_size=12)
    color_series(gf.chart, [MUTE, '7FB7B9', TEAL])
    text(s, 0.6, 6.68, 12.1, 0.3, '分類延遲 ms（PC 送出 → 收到結果），板上 11.5 分鐘即時重放', size=11, color=GREY)

    # ---- 16 stage 7b: NN
    nn, mb = N['nn'], N['mlpb']
    s = stage(d, '⑦-2 為什麼用 LDA，不用神經網路', [
        ['口試必問：為什麼不用神經網路？', '業界常見：MCU 上的小型網路'],
        ['小型 MLP，同樣的校正預算比準確率', 'C 版放上板子實測'],
        ['能在 MCU 上更新的 MLP 都沒贏 LDA',
         f'板上：更新 {mb["lda_upd"]:.1f} ms 對 {mb["mlp_upd"]:,.0f} ms'],
        ['選 LDA 有準確率和實測兩種證據', '未比：原始訊號 CNN']],
        notes='report 35.38–35.39；results/nn_compare.csv、mlp_bench_board_480mhz_cache.txt。判準 R13 通過。')
    cd = CategoryChartData()
    cd.categories = ['同一個 session', '下一個 session']
    series = [('LDA 一輪提示＋累加（本研究）', 'lda_cue1', TEAL), ('MLP 微調', 'mlp_ft', '7FB7B9'), ('MLP 累積微調', 'mlp_ft_cum', GREY),
              ('MLP 重新訓練（MCU 做不到）', 'mlp_retrain', MUTE)]
    for name, m, _ in series:
        cd.add_series(name, [round(nn['same'][m], 1), round(nn['next'][m], 1)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.75), Inches(6.9), Inches(3.0), cd)
    chart_style(gf.chart, legend=True, vmax=62, vmin=30, label_size=10, axis_size=11)
    color_series(gf.chart, [c for _, _, c in series])
    rows = [['板上實測', 'LDA', 'MLP'],
            ['分類一個視窗', f'{mb["lda_pred"]:.1f} µs', f'{mb["mlp_pred"]:.1f} µs'],
            ['一次提示輪更新', f'{mb["lda_upd"]:.1f} ms', f'{mb["mlp_upd"]:,.0f} ms'],
            ['靜態 RAM', f'{mb["lda_ram"] / 1024:.1f} KB', f'{mb["mlp_ram"] / 1024:.1f} KB']]
    table(s, 7.8, 3.9, 4.9, rows, [2.0, 1.4, 1.5], size=13, row_h=0.6, fills={(i, 1): TEAL_L for i in range(1, 4)})

    # ---- 17 converged direction
    s = d.slide('收斂後的方向', notes='三個研究問題的狀態。若自我測試為 NO-GO，主軸改為「每次配戴的短提示＋跨次累積，可在 MCU 上執行」，任務標籤寫成負面結果。')
    text(s, 0.6, 1.35, 12.1, 0.7, '每次重新戴上後，用最少的使用者負擔把模型校正回來：一輪 8 秒提示＋跨次累積，加上機器人任務提供的標籤，整套在 MCU 上即時執行',
         size=16, bold=True, color=TEAL)
    rqs = [('RQ1', '免標籤自我校正有沒有用？', '已回答：沒有確認增益（獨立資料、預先登錄）', TEAL_L),
           ('RQ2', '標籤能不能大部分由機器人任務提供？', '主要問題，尚未回答：模擬支持、真實資料不明 → 自我測試', 'FBE3DD'),
           ('RQ3', '整套能不能在 MCU 上即時執行？', '已回答：可以（逐一驗證、FreeRTOS、和 MLP 比較）；耗電待量', TEAL_L)]
    for i, (q, a1, a2, fill) in enumerate(rqs):
        y = 2.35 + i * 1.35
        box(s, 0.6, y, 12.1, 1.15, fill=fill)
        circle_num(s, 0.85, y + 0.3, i + 1, fill=TEAL if fill == TEAL_L else CORAL, d=0.55)
        text(s, 1.65, y + 0.12, 10.8, 0.45, f'{q}：{a1}', size=16, bold=True)
        text(s, 1.65, y + 0.58, 10.8, 0.45, a2, size=14, color=GREY)
    text(s, 0.6, 6.45, 12.1, 0.4, '不論 RQ2 結果如何，RQ1＋RQ3 已足以構成論文；RQ2 決定任務標籤能不能成為主要貢獻', size=14, color=INK)

    # ---- 18 next: self-test
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
    text(s, 0.6, 2.65, 12.1, 0.4, 'T1 之後改用操作機器人的姿勢（往前伸、抬高、往外），每 10 次換一次；手勢隨機穿插，避開 DB6 的時間相鄰問題', size=13, color=GREY)
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

    # ---- 19 timeline
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

    # ---- 20 decisions
    s = d.slide('需要老師決定或討論的事', dark=True, notes='建議：方向改為「每次配戴的短校正＋任務標籤」；EMBC 用公開資料投獨立檢驗；IRB 早點準備。')
    dec = ['論文主軸改為「每次配戴的短校正＋任務提供的標籤」？',
           '自我測試需不需要 IRB 或實驗室同意？多人先導實驗的 IRB 何時送？',
           'EMBC 2027 用公開資料投「獨立檢驗」這篇，可以嗎？作者順序？',
           '病患個案的族群與時程']
    for i, t in enumerate(dec):
        y = 1.6 + i * 1.2
        circle_num(s, 0.9, y + 0.1, i + 1, fill=CORAL, d=0.6)
        text(s, 1.8, y, 10.6, 0.8, t, size=20, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)

    # ---- 21 references
    s = d.slide('參考文獻', notes='標＊者還沒打開原文逐字確認。')
    refs = ['Jiang, Ma, Nazarpour (2024). Posture-invariant myoelectric control with self-calibrating random forests. Frontiers in Neurorobotics.',
            'Jiang et al. (2025). Plug-and-play myoelectric control via a self-calibrating random forest common model. Journal of Neural Engineering.',
            'Kyranou, Szymaniak, Nazarpour (2025). 8-participant two-day Trigno dataset. Scientific Data.',
            'Campbell, Eddy, Bateman, Côté-Allard, Scheme (2024). Context-informed incremental learning improves both the performance and resilience of myoelectric control. J NeuroEng Rehabil 21:70.',
            'Xavier Fidêncio, Grün, Klaes, Iossifidis (2025). Hybrid brain-computer interface using error-related potential and reinforcement learning. Front Hum Neurosci 19:1569411.',
            'Vidovic et al. (2016). Improving the robustness of myoelectric pattern recognition for upper limb prostheses by covariate shift adaptation. IEEE TNSRE 24(9).',
            'Scheme, Hudgins, Englehart (2013). Confidence-based rejection for improved pattern recognition myoelectric control. IEEE TBME 60(6).',
            '＊Palermo et al. (2017). Repeatability of grasp recognition for robotic hand prosthesis control based on sEMG data. ICORR 2017.（NinaPro DB6）',
            'Gagné et al. (2025). Context informed incremental learning improves myoelectric control performance in virtual reality object manipulation tasks. EMBC 2025.']
    text(s, 0.6, 1.4, 12.1, 5.0, refs, size=12, color=INK, space=5)
    text(s, 0.6, 6.55, 12.1, 0.35, '＊ 尚未打開原文逐字核對', size=11, color=GREY)

    d.prs.save(out)
    print(f'{d.n} slides -> {out}')
    print('check numbers:', {k_: round(v_, 2) for k_, v_ in N['vid'].items()}, 'ext', N['ext'], 'comp', N['comp'])


if __name__ == '__main__':
    build(sys.argv[1])
