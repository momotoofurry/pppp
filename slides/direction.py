"""Direction deck (2026-11-18): every claim of the proposed thesis direction with its evidence and data.
Output: 研究方向與證據_2026-11-18.pptx (a new deck; the progress-report deck is not touched).
Numbers of our own work are read from results/ (no hand-typed values); literature numbers are written with their
citation and were read from abstracts / search snippets only (marked on the slides).
Usage (container, Downloads mounted at /d):  python slides/direction.py /d/研究方向與證據_2026-11-18.pptx
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proposal as P  # noqa: E402
from pptx.chart.data import CategoryChartData  # noqa: E402
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

R = P.R
NAVY, TEAL, TEAL_L, CORAL, INK, GREY, LIGHT, WHITE, MUTE = (P.NAVY, P.TEAL, P.TEAL_L, P.CORAL, P.INK, P.GREY, P.LIGHT,
                                                           P.WHITE, P.MUTE)
CORAL_L, AMBER, AMBER_L = 'FBE3DE', 'B7791F', 'FBF0DC'
DATE = '2026-11-18'
text, box, label_in, table = P.text, P.box, P.label_in, P.table


def rd(*p):
    return open(os.path.join(R, *p), encoding='utf-8').read()


# ------------------------------------------------------------------ data
def load():
    N = {}
    # GrabMyo cross-day (35.51): blocks "<cfg> <set> (n 43): ..."
    gm = {}
    txt = rd('grabmyo', 'combined.txt')
    for m in re.finditer(r'^(ring8|4ch)\s+(G\d) \(n (\d+)\): mean day1 / day8 / day29\n(.*?)(?=\n\n|\Z)', txt, re.M | re.S):
        cfg, s, n, body = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        d = {'n': n}
        for c, a, b, e in re.findall(r'^\s+(\w+)\s+([\d.]+) /\s+([\d.]+) /\s+([\d.]+)$', body, re.M):
            d[c] = (float(a), float(b), float(e))
        for c, v, k in re.findall(r'^\s+(\w+)\s+- cue \(days 8\+29\): ([+-][\d.]+) \(SD [\d.]+\), better in (\d+)/', body, re.M):
            d['d_' + c] = (float(v), int(k))
        gm[(cfg, s)] = d
    N['gm'] = gm
    # labels of use (35.55)
    lab = {}
    txt = rd('grabmyo', 'grabmyo_labels_1-43.txt')
    for blk in re.split(r'^===== ', txt, flags=re.M)[1:]:
        s = blk.split()[0]
        for part in re.split(r'later, difference vs ', blk)[1:]:
            ref = part.split(':')[0]
            for c, v, lo, hi, k in re.findall(r'^\s+(\w+)\s+([+-][\d.]+)\s+\(95 % CI ([+-][\d.]+) to ([+-][\d.]+)\), better in (\d+)/', part, re.M):
                lab[(s, ref, c)] = (float(v), float(lo), float(hi), int(k))
        for x, y, v, k in re.findall(r'^\s+(\w+) - (\w+): ([+-][\d.]+), better in (\d+)/', blk, re.M):
            lab[(s, 'pair', x)] = (float(v), int(k))
    N['lab'] = lab
    sw = {}
    txt = rd('grabmyo', 'grabmyo_labels_sweep_1-43.txt')
    for blk in re.split(r'^===== ', txt, flags=re.M)[1:]:
        s = blk.split(':')[0]
        rows = {}
        for r, cells in re.findall(r'^\s+(\d+) %\s+\|(.*)$', blk, re.M):
            rows[int(r)] = [(float(a), int(b)) for a, b in re.findall(r'([+-][\d.]+) \(\s*(\d+)\)', cells)]
        sw[s] = rows
        sw[s + '_accmcue'] = float(re.search(r'acc - cue: ([+-][\d.]+)', blk).group(1))
    N['sw'] = sw
    # latency (35.54)
    txt = rd('latency', 'latency_sweep.txt')
    q = lambda lab_: float(re.search(lab_ + r'\s+median\s+(\d+) ms', txt).group(1))  # noqa: E731
    N['lat'] = dict(total=q(r'cue -> command \(TaskScreen\):'), react=q(r'cue -> EMG onset \(reaction\):'),
                    system=q(r'EMG onset -> command \(system\):'))
    ks = {}
    for blk in re.split(r'^===== ', txt, flags=re.M):
        if not blk.startswith(('S7', 'S5')):
            continue
        s = blk[:2]
        sec = blk.split('effect of k alone')[1]
        for k, fo, st, sp, wr, fm in re.findall(r'k (\d): first_ok\s+([\d.]+)\s+start\s+(\d+) ms\s+stop\s+(\d+) ms\s+wrong/tr ([\d.]+)\s+false/min\s+([\d.]+)', sec):
            ks[(s, int(k))] = (float(fo), int(st), int(sp), float(wr), float(fm))
    N['ks'] = ks
    # Ozdemir (35.52) and DB2 (35.46/35.47)
    txt = rd('ozdemir2022', 'ozdemir_sim.txt')
    N['oz'] = {(k, s): float(v) for k, s, v in re.findall(r'^(pass\d) (S\d): cue\s+([\d.]+)', txt, re.M)}
    N['oz_n'] = {(k, s): (int(a), int(b)) for k, s, a, b in re.findall(r'^(pass\d) (S\d):.*>= 85 % \(cue\): (\d+)/(\d+)', txt, re.M)}
    db = {}
    for p_ in (1, 2):
        t = rd('db2_wrist', f'db2_wrist_sim_short_passes{p_}.txt')
        for s, v in re.findall(r'^(S\d): 4ch_median\s+([\d.]+)', t, re.M):
            db[(p_, s)] = float(v)
    N['db2'] = db
    # board measurements (35.10 / 35.23): reuse the proposal loader's parsing
    txt = rd('lda_bench_board_480mhz_cache.txt').split('60 more rows')[0]
    us = {m.group(1): float(m.group(2)) for m in re.finditer(r'(ld_\w+)\s+n=\s*\d+\s+mean\s+\d+ cyc\s+([\d.]+) us', txt)}
    N['bench'] = dict(fit_ms=us['ld_fit'] / 1000, predict_us=us['ld_predict'], add_us=us['ld_add'])
    a = P.csv('arm_ldacal_size.csv').iloc[0]
    N['ldacal_ram'] = int(a.bss + a.data)
    return N


# ------------------------------------------------------------------ deck
class Deck(P.Deck):
    def slide(self, title=None, dark=False, notes=''):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        self.n += 1
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = P.rgb(NAVY if dark else WHITE)
        if title:
            text(s, 0.6, 0.38, 12.1, 0.8, title, size=28, bold=True, color=WHITE if dark else INK,
                 anchor=MSO_ANCHOR.MIDDLE, name='Title')
        if not dark:
            text(s, 0.6, 7.02, 9, 0.3, f'研究方向與證據｜{DATE}｜方向待指導老師確認', size=10, color=MUTE, name='Footer')
            text(s, 11.9, 7.02, 0.83, 0.3, str(self.n), size=10, color=MUTE, align=PP_ALIGN.RIGHT, name='Page')
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s


KIND = {'pub': ('公開資料模擬', TEAL_L, TEAL), 'board': ('板子實測', TEAL_L, TEAL), 'self': ('自己的錄製', TEAL_L, TEAL),
        'lit': ('文獻（只讀摘要）', AMBER_L, AMBER), 'none': ('尚無證據', CORAL_L, CORAL)}


def tag(s, x, y, kind, extra=''):
    lab, fill, col = KIND[kind]
    t = lab + ('｜' + extra if extra else '')
    w = 0.4 + sum(0.19 if ord(ch) > 0x2E80 else 0.105 for ch in t)
    b = box(s, x, y, w, 0.36, fill=fill, radius=0.5)
    label_in(b, t, size=12, color=col, bold=True)
    return x + w + 0.15


def tags(s, items, y=1.18):
    x = 0.6
    for k, e in items:
        x = tag(s, x, y, k, e)


def source(s, t):
    text(s, 0.6, 6.55, 12.1, 0.42, t, size=11, color=GREY, name='Source')


def bar_chart(s, x, y, w, h, cats, series, colors, vmin=None, vmax=None, fmt='+0.0;-0.0;0', legend=False, horiz=False,
              label_size=13, axis_size=13):
    cd = CategoryChartData()
    cd.categories = cats
    for name, vals in series:
        cd.add_series(name, [round(v, 2) for v in vals])
    kind = XL_CHART_TYPE.BAR_CLUSTERED if horiz else XL_CHART_TYPE.COLUMN_CLUSTERED
    gf = s.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart
    P.chart_style(ch, legend=legend, vmax=vmax, vmin=vmin, fmt=fmt, label_size=label_size, axis_size=axis_size)
    if horiz:
        ch.category_axis.reverse_order = True
    ch.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
    for sr in ch.plots[0].series:
        sr.invert_if_negative = False
    if len(series) == 1:
        P.color_points(ch.plots[0].series[0], colors)
    else:
        P.color_series(ch, colors)
    from pptx.oxml.ns import qn
    from lxml import etree
    for sr in ch.plots[0].series:
        for dpt in sr._element.findall(qn('c:dPt')):
            if dpt.find(qn('c:invertIfNegative')) is None:
                el = etree.SubElement(dpt, qn('c:invertIfNegative'))
                el.set('val', '0')
                dpt.find(qn('c:idx')).addnext(el)
    return ch


def build(out):
    N = load()
    gm, lab, sw, lat, ks = N['gm'], N['lab'], N['sw'], N['lat'], N['ks']
    d = Deck()
    g9, g7, g5 = gm[('4ch', 'G9')], gm[('4ch', 'G7')], gm[('4ch', 'G5')]

    # 1 cover
    s = d.slide(dark=True, notes='這份簡報只放有證據的論點；每頁左上的標籤說明證據來自哪裡。')
    text(s, 0.9, 1.5, 11.5, 0.5, '研究方向與證據', size=18, color='8FD3D0')
    text(s, 0.9, 2.1, 11.6, 2.2, ['在微控制器上的跨天肌電校正',
                                    ('用任務情境的軟標籤安全地利用使用資料，應用於輔助機械臂', {'size': 24, 'bold': False, 'color': 'CFE3E6'})],
         size=36, bold=True, color=WHITE, space=10)
    text(s, 0.9, 4.75, 11.5, 1.2, ['每個論點附上證據等級、數據與出處',
                                    (f'{DATE}　方向尚待指導老師確認', {'color': '8FD3D0'})], size=16, color='CFE3E6', space=4)

    # 2 one page: claims and evidence level
    s = d.slide('一頁看懂：九個論點和它們的證據', notes='證據等級：公開資料模擬（多人）＞板子實測＞文獻（只讀摘要，要讀全文確認）＞尚無證據。')
    l1, l9 = lab[('G9', 'self', 'soft1')], lab[('G9', 'pair', 'soft30')]
    rows = [['#', '論點', '關鍵數據', '證據'],
            ['1', '不更新的模型跨天會變差', f'第 8、29 天少 {-g9["d_fixed"][0]:.1f} 點（{43 - g9["d_fixed"][1]}/43 人變差）', '公開資料 43 人'],
            ['2', '跨天累加比每天只做短校正好', f'+{g9["d_acc"][0]:.1f} 點（{g9["d_acc"][1]}/43 人變好）', '公開資料 43 人'],
            ['3', '整個更新可以在 MCU 上做', f'重算 {N["bench"]["fit_ms"]:.1f} ms、模組 RAM {N["ldacal_ram"] / 1024:.1f} KB', '板子實測'],
            ['4', '任務情境標籤比自我訓練好', f'+{l1[0]:.1f} 點（{l1[3]}/43 人）', '公開資料 43 人'],
            ['5', '情境會猜錯時，硬標籤有害、軟標籤安全', f'30 % 猜錯：軟比硬 +{l9[0]:.1f} 點（{l9[1]}/43 人）', '公開資料 43 人'],
            ['6', '軟標籤的強度應等於情境的錯誤率', '最佳 ε 落在對角線（3 個手勢集合都是）', '公開資料 43 人'],
            ['7', '4 顆感測器分不好手指動作 → 只用手腕', f'DB2 4 顆：9 類 {N["db2"][(1, "S9")]:.0f} %、5 類 {N["db2"][(1, "S5")]:.0f} %', '公開資料＋文獻'],
            ['8', '目標使用者是上肢受限者，需要輔助', 'JACO 使用者研究、需求調查', '文獻（摘要）'],
            ['9', '延遲約一半是使用者的反應', f'反應 {lat["react"]:.0f} ms、系統 {lat["system"]:.0f} ms', '自己的錄製＋公開資料']]
    fills = {(i, 3): (TEAL_L if '公開' in rows[i][3] or '板子' in rows[i][3] or '自己' in rows[i][3] else AMBER_L) for i in range(1, 10)}
    table(s, 0.6, 1.3, 12.1, rows, [0.45, 4.6, 4.75, 2.3], size=13, row_h=0.5, fills=fills)
    source(s, '數據出處：report 35.51、35.54、35.55（GrabMyo 跨天、延遲、標籤比較），35.10 / 35.23（板子實測），35.46（DB2）。文獻見最後一頁。')

    # 3 how the direction was chosen
    s = d.slide('怎麼選方向：風險、價值、技術含量', notes='風險＝論文成立是否依賴還沒驗證或不可控的事；價值＝解決的問題是否被文獻承認、別人還沒做；技術＝MCU、即時、定點。')
    rows = [['候選方向', '風險', '研究價值', '技術含量', '判斷依據'],
            ['9 個手勢直接控制', '高', '中', '中', f'DB2 4 顆 9 類只有 {N["db2"][(1, "S9")]:.0f} %，要靠 11/23 的錄製'],
            ['找患者當受試者', '高', '高', '中', '需要 IRB、醫院合作，碩士期間時間不夠'],
            ['加攝影機做物體辨識', '中', '中', '高', '運算離開 MCU；NUCLEO 沒有攝影機介面'],
            ['int8 CNN 取代 LDA', '低', '低', '中', '已有很多人做；適合當比較基準'],
            ['跨天累加＋情境軟標籤（推薦）', '低', '高', '高', '主要論點都在 43 人公開資料上驗證；全部在 MCU']]
    fills = {(5, j): TEAL_L for j in range(5)}
    for i in range(1, 5):
        for j in (1,):
            if rows[i][j] == '高':
                fills[(i, j)] = CORAL_L
    table(s, 0.6, 1.4, 12.1, rows, [3.2, 0.9, 1.2, 1.2, 5.6], size=14, row_h=0.62, fills=fills)
    text(s, 0.6, 5.35, 12.1, 1.0, ['風險低的關鍵：論文的主要論點不依賴自我測試或手臂實驗的結果；自我測試和手臂是展示和補充。',
                                    '患者、9 手勢、攝影機都列為未來工作。'], size=15, color=GREY, bullet=True)

    # 4 claim 1
    s = d.slide('論點 1：不更新的模型，跨天會變差 11 點以上',
                notes=f'GrabMyo 4 顆（ring 1 每隔一顆，兩組平均），7 類。fixed＝第 1 天模型不更新；cue＝每天只用當天提示輪。report 35.51。')
    tags(s, [('pub', 'GrabMyo 43 人、第 1／8／29 天'), ('lit', 'Vidovic 2016')])
    cats = ['第 1 天', '第 8 天', '第 29 天']
    ch = bar_chart(s, 0.6, 1.75, 7.6, 4.6, cats, [('不更新（第 1 天的模型）', g7['fixed']), ('每天短校正', g7['cue']),
                                                   ('跨天累加', g7['acc'])], [MUTE, GREY, TEAL], vmin=0, vmax=100,
                   fmt='0.0', legend=True, label_size=12)
    box(s, 8.6, 1.75, 4.1, 4.6, fill=LIGHT)
    text(s, 8.85, 1.95, 3.6, 4.3, [('看到的事', {'size': 18, 'bold': True}),
                                    (f'不更新：第 8、29 天比每天短校正少 {-g7["d_fixed"][0]:.1f} 點（9 類：{-g9["d_fixed"][0]:.1f}）', {'bullet': True}),
                                    (f'43 人中只有 {g9["d_fixed"][1]}–{g7["d_fixed"][1]} 人沒有變差', {'bullet': True}),
                                    ('文獻一致：Vidovic 等（2016）5 天後不調整 75 %、調整後 > 92 %', {'bullet': True})],
         size=15, space=8)
    source(s, '準確率 %（平衡準確率），4 顆感測器、7 類。出處：report 35.51（results/grabmyo/combined.txt）；Vidovic 等，2016，IEEE TNSRE 24(9)（摘要）。')

    # 5 claim 2
    s = d.slide('論點 2：跨天累加比每天只做短校正好', notes='acc＝每天用自己提示輪的 z-score，把提示輪視窗加進前幾天的累加和，不遺忘。report 35.51。')
    tags(s, [('pub', 'GrabMyo 43 人'), ('board', '韌體已實作')])
    rows = [['感測器', '手勢集合', '每天短校正', '跨天累加', '差', '變好的人']]
    for cfg, lab_ in (('4ch', '4 顆'), ('ring8', '8 顆一圈')):
        for st in ('G9', 'G7', 'G5'):
            g = gm[(cfg, st)]
            cue, acc = (g['cue'][1] + g['cue'][2]) / 2, (g['acc'][1] + g['acc'][2]) / 2
            rows.append([lab_, {'G9': '9 類', 'G7': '7 類', 'G5': '5 類'}[st], f'{cue:.1f} %', f'{acc:.1f} %',
                         f'{g["d_acc"][0]:+.1f}', f'{g["d_acc"][1]}/{g["n"]}'])
    fills = {(i, 4): TEAL_L for i in range(1, 7)}
    table(s, 0.6, 1.75, 8.0, rows, [1.3, 1.1, 2.3, 1.3, 0.8, 1.2], size=14, row_h=0.55, fills=fills)
    box(s, 9.0, 1.75, 3.7, 3.85, fill=TEAL_L)
    text(s, 9.25, 1.95, 3.2, 3.6, [('為什麼有效', {'size': 18, 'bold': True}),
                                    ('每天的提示輪只有幾秒，資料少', {'bullet': True}),
                                    ('累加讓之前每一天的資料都留下，每天用自己的 z-score 對齊', {'bullet': True}),
                                    ('只存累加和，不存原始資料，記憶體固定', {'bullet': True})], size=15, space=8)
    source(s, '第 8、29 天平均，平衡準確率。出處：report 35.51（results/grabmyo/combined.txt）。')

    # 6 claim 3 (board)
    s = d.slide('論點 3：整個更新可以在 MCU 上做', notes='STM32H753，480 MHz、快取開。ld_fit＝合併共變異數 → OAS → Cholesky → 權重。report 35.10、35.23。')
    tags(s, [('board', 'STM32H753 480 MHz')])
    b = N['bench']
    cards = [(f'{b["fit_ms"]:.1f} ms', '重算整個模型（ld_fit）', 'OAS 收縮 + Cholesky 求解，80 維特徵'),
             (f'{b["predict_us"]:.1f} µs', '預測一個視窗', '每 100 ms 一次，負擔 < 0.1 %'),
             (f'{N["ldacal_ram"] / 1024:.1f} KB', '校正模組的 RAM', '只存累加和，天數再多也不變')]
    for i, (big, lab_, sub) in enumerate(cards):
        x = 0.6 + i * 4.1
        box(s, x, 1.8, 3.8, 3.3, fill=LIGHT)
        text(s, x + 0.25, 2.05, 3.3, 1.1, big, size=40, bold=True, color=TEAL)
        text(s, x + 0.25, 3.2, 3.3, 0.6, lab_, size=17, bold=True)
        text(s, x + 0.25, 3.9, 3.3, 1.0, sub, size=14, color=GREY)
    text(s, 0.6, 5.35, 12.1, 1.0, ['和深度學習的裝置端訓練不同：閉式解、不用反向傳播，結果每次一樣、可以逐位元和 PC 對照。',
                                    '相關研究（Benini 團隊，TBCAS 2024）在專用的低功耗多核心 MCU 上做增量訓練；我們用一般的 Cortex-M7。'],
         size=15, color=GREY, bullet=True)
    source(s, '出處：results/lda_bench_board_480mhz_cache.txt、arm_ldacal_size.csv（report 35.10、35.23）。')

    # 7 claim 4
    s = d.slide('論點 4：任務情境給的標籤，比自我訓練好', notes='self＝模型自己判定的指令當硬標籤（常見的非監督基準）。ciil＝CIIL 式重新標記（依摘要的簡化版）。soft＝板子的軟標籤。report 35.55。')
    tags(s, [('pub', 'GrabMyo 43 人、第 8／29 天'), ('lit', 'CIIL：Campbell 2024')])
    conds = [('self', '自我訓練'), ('ciil1', 'CIIL 式硬標籤'), ('soft1', '軟標籤'), ('soft2', '軟標籤（目標在斜方向）')]
    vals = [lab[('G9', 'acc', c)][0] for c, _ in conds]
    bar_chart(s, 0.6, 1.75, 7.4, 4.6, [n for _, n in conds], [('和只累加相比', vals)], [CORAL, TEAL, TEAL, TEAL],
              vmin=-3, vmax=3.5, label_size=15, horiz=True)
    box(s, 8.4, 1.75, 4.3, 4.6, fill=LIGHT)
    lines = [('和自我訓練相比（9 類）', {'size': 18, 'bold': True})]
    for c, n in conds[1:]:
        v = lab[('G9', 'self', c)]
        lines.append((f'{n}：{v[0]:+.1f} 點（95 % CI {v[1]:+.1f} 到 {v[2]:+.1f}），{v[3]}/43 人變好', {'bullet': True}))
    lines.append((f'自我訓練本身比只累加還差 {lab[("G9", "acc", "self")][0]:+.1f} 點：模型會強化自己的錯誤', {'bullet': True}))
    text(s, 8.65, 1.95, 3.85, 4.3, lines, size=14, space=8)
    source(s, '9 類，和「只累加、不加標籤」的差（點）。出處：report 35.55（results/grabmyo/grabmyo_labels_1-43.txt）；Campbell 等，2024，JNER（摘要）。')

    # 8 claim 5
    s = d.slide('論點 5：情境會猜錯時，硬標籤有害，軟標籤安全', notes='shared autonomy 的意圖推論一定會猜錯一部分。這頁是把猜錯的比例從 0 拉到 50 %。report 35.55。')
    tags(s, [('pub', 'GrabMyo 43 人、9 類')])
    rows9 = sw['G9']
    rates = sorted(rows9)
    cd = CategoryChartData()
    cd.categories = [f'{r} %' for r in rates]
    names = ['硬標籤（CIIL 式）', '軟標籤 ε 0.05', '軟標籤 ε 0.15', '軟標籤 ε 0.30', '軟標籤 ε 0.50']
    for j, nm in enumerate(names):
        cd.add_series(nm, [rows9[r][j][0] for r in rates])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.6), Inches(1.75), Inches(7.6), Inches(4.6), cd)
    ch = gf.chart
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.legend.font.size = Pt(12)
    ch.font.size = Pt(12)
    ch.font.name = P.FONT
    ch.value_axis.minimum_scale, ch.value_axis.maximum_scale = -15, 4
    ch.value_axis.has_major_gridlines = True
    ch.value_axis.major_gridlines.format.line.color.rgb = P.rgb('E3E8EA')
    ch.value_axis.tick_labels.font.size = Pt(12)
    ch.category_axis.tick_labels.font.size = Pt(12)
    ch.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
    for sr, c in zip(ch.plots[0].series, [CORAL, 'A8D5D6', '5FB3B5', TEAL, NAVY]):
        sr.format.line.color.rgb = P.rgb(c)
        sr.format.line.width = Pt(2.5)
        sr.marker.style = XL_MARKER_STYLE.CIRCLE
        sr.marker.format.fill.solid()
        sr.marker.format.fill.fore_color.rgb = P.rgb(c)
        sr.smooth = False
    text(s, 0.6, 6.3, 7.6, 0.3, '橫軸：情境猜錯的比例；縱軸：和只累加相比（點）', size=12, color=GREY)
    p30 = lab[('G9', 'pair', 'soft30')]
    box(s, 8.6, 1.75, 4.1, 4.6, fill=LIGHT)
    text(s, 8.85, 1.95, 3.6, 4.3, [('看到的事', {'size': 18, 'bold': True}),
                                    (f'只猜錯 10 %，硬標籤就變成負的（{rows9[10][0][0]:+.1f}）', {'bullet': True}),
                                    (f'猜錯 30 %：硬標籤 {rows9[30][0][0]:+.1f}，軟標籤約 0', {'bullet': True}),
                                    (f'軟比硬多 {p30[0]:+.1f} 點，{p30[1]}/43 人變好', {'bullet': True}),
                                    ('軟標籤的價值不是提高上限，而是猜錯時不會拖垮模型', {'bullet': True, 'bold': True})],
         size=15, space=8)
    source(s, '出處：report 35.55（results/grabmyo/grabmyo_labels_sweep_1-43.txt、grabmyo_labels_1-43.txt）。猜錯的情境是隨機的（見「還沒有證據的地方」）。')

    # 9 claim 6
    s = d.slide('論點 6：軟標籤的強度，應該等於情境的錯誤率', notes='ε＝先驗分給其他指令的機率。最佳 ε ≈ 猜錯率，和貝氏推論一致。所以 ε = 1 − P(目標)。report 35.55。')
    tags(s, [('pub', 'GrabMyo 43 人、3 個手勢集合')])
    hdr = ['猜錯率', '硬標籤', 'ε 0.05', 'ε 0.15', 'ε 0.30', 'ε 0.50']
    rows = [hdr]
    fills = {}
    for i, r in enumerate(rates, start=1):
        cells = rows9[r]
        best = max(range(len(cells)), key=lambda j: cells[j][0])
        rows.append([f'{r} %'] + [f'{v:+.2f}（{k}）' for v, k in cells])
        fills[(i, best + 1)] = TEAL_L
    table(s, 0.6, 1.75, 7.6, rows, [1.1, 1.3, 1.3, 1.3, 1.3, 1.3], size=13, row_h=0.6, fills=fills)
    text(s, 0.6, 4.95, 7.6, 0.4, '9 類，和只累加相比（點）；括號＝變好的人數 / 43；綠＝該列最好', size=12, color=GREY)
    for st, y in (('G7', 5.35), ('G5', 5.75)):
        best = [max(range(5), key=lambda j: sw[st][r][j][0]) for r in rates]
        text(s, 0.6, y, 7.6, 0.4, f'{ {"G7": "7 類", "G5": "5 類"}[st]}：每列最好的是 ' + '、'.join(hdr[b + 1] for b in best),
             size=13, color=INK)
    box(s, 8.6, 1.75, 4.1, 4.6, fill=TEAL_L)
    text(s, 8.85, 1.95, 3.6, 4.3, [('設計規則', {'size': 18, 'bold': True}),
                                    ('ε = 1 − P(目標)', {'size': 26, 'bold': True, 'color': TEAL}),
                                    ('P(目標) 來自 shared autonomy 的意圖推論', {'bullet': True}),
                                    ('有把握 → 接近硬標籤，拿到 CIIL 的好處', {'bullet': True}),
                                    ('沒把握 → 自動變軟，不會拖垮模型', {'bullet': True}),
                                    ('同一個機率也決定輔助強度 α', {'bullet': True})], size=15, space=8)
    source(s, '出處：report 35.55（results/grabmyo/grabmyo_labels_sweep_1-43.txt）。')

    # 10 comparison with prior work
    s = d.slide('和現有方法比：我們補的是哪一塊', notes='依各論文摘要整理；要讀全文確認。')
    tags(s, [('lit', 'CIIL 等 4 篇'), ('pub', '我們的數據')])
    Y, Nn, Pp = '有', '沒有', '部分'
    rows = [['', '跨天驗證', '在一般 MCU 上', '情境猜錯時穩定', '使用中標籤'],
            ['CIIL（Campbell 等，2024）', Pp + '（後續研究指出缺跨 session）', Nn, Nn + '（硬性重新標記）', Y],
            ['Vidovic 等（2016）', Y + '（5 天）', Nn, '—', Nn + '（每天短校正）'],
            ['Benini 團隊（TBCAS 2024）', '—', Pp + '（專用多核心 MCU）', '—', Nn],
            ['自我訓練（Yoneda 等，2023／2025）', Y + '（30 天）', Nn, '—', '用自己的預測'],
            ['本研究', Y + '（29 天，43 人）', Y + '（Cortex-M7）', Y + '（論點 5、6）', Y + '（軟標籤）']]
    fills = {(5, j): TEAL_L for j in range(5)}
    table(s, 0.6, 1.75, 12.1, rows, [3.2, 2.6, 2.1, 2.2, 2.0], size=13, row_h=0.68, fills=fills)
    source(s, '出處（皆為摘要）：Campbell 等 2024 JNER、2025 VR 研究；Vidovic 等 2016 TNSRE；Benini 團隊 2024 TBCAS；Yoneda 等 2023、2025。')

    # 11 claim 7
    oz = N['oz']
    s = d.slide('論點 7：4 顆感測器分不好手指動作 → 控制只用手腕', notes='DB2：一輪提示、4 顆（FDS、EDC＋兩顆環狀，28 種組合的中位數）。Ozdemir：4 顆貼手腕的肌肉，沒有單指手勢。Li 2010：截肢者。')
    tags(s, [('pub', 'DB2 10 人、Ozdemir 40 人'), ('lit', 'Li 2010')])
    db = N['db2']
    bar_chart(s, 0.6, 1.75, 7.4, 4.6, ['9 類（含單指）', '7 類（去掉單指）', '5 類（只有手腕）'],
              [('一輪提示', [db[(1, 'S9')], db[(1, 'S7')], db[(1, 'S5')]]), ('兩輪提示', [db[(2, 'S9')], db[(2, 'S7')], db[(2, 'S5')]])],
              ['A8D5D6', TEAL], vmin=0, vmax=100, fmt='0.0', legend=True)
    n2 = N['oz_n'][('pass2', 'S5')]
    box(s, 8.4, 1.75, 4.3, 4.6, fill=LIGHT)
    text(s, 8.65, 1.95, 3.85, 4.3, [('其他證據', {'size': 18, 'bold': True}),
                                     (f'Ozdemir（4 顆貼手腕肌肉，兩輪提示）：7 類 {oz[("pass2", "S7")]:.1f} %、5 類 {oz[("pass2", "S5")]:.1f} %（{n2[0]}/{n2[1]} 人 ≥ 85 %）', {'bullet': True}),
                                     ('Li 等（2010）：6 個動作 93.1 %，10 個動作（多種抓握）84.4 %；殘肢肌肉夠做手腕、不夠分抓握', {'bullet': True}),
                                     ('反方：Young 等（2012）4–6 通道對手腕和整手動作足夠 → 難的是手指，不是類別數', {'bullet': True})],
         size=14, space=8)
    source(s, 'DB2 準確率 %（4 顆，28 種組合中位數）。出處：report 35.46–35.47、35.52（results/db2_wrist/、ozdemir2022/）；Li 等 2010 TNSRE、Young 等 2012 TBME（摘要）。')

    # 12 claim 8
    s = d.slide('論點 8：目標使用者是上肢受限者，需要輔助而不是更多手勢', notes='全部是摘要或二手引用，引用前要讀全文確認數字。')
    tags(s, [('lit', '需讀全文確認')])
    cards = [('31 人', 'Maheu 等（2011，ICORR）', 'JACO 使用者評估；經濟模型推估照顧時間可能減少 41 %'),
             ('9／11 人', 'Chung 等（2023，RESNA）', '長期使用者多用搖桿控制；研究主題是模式切換的負擔'),
             ('681 人', 'Anderson（2004）', '四肢癱瘓者把恢復手與手臂功能列為第一優先（二手引用）'),
             ('8＋9 人', 'Fonseca 等（2019，Sensors）', '四肢癱瘓者用殘存肌肉的 EMG／IMU 控制機器手，訓練很少就能操作')]
    for i, (big, who, sub) in enumerate(cards):
        x = 0.6 + (i % 2) * 6.15
        y = 1.75 + (i // 2) * 2.35
        box(s, x, y, 5.95, 2.15, fill=LIGHT)
        text(s, x + 0.25, y + 0.15, 2.2, 0.8, big, size=30, bold=True, color=AMBER)
        text(s, x + 2.45, y + 0.25, 3.35, 0.6, who, size=15, bold=True)
        text(s, x + 0.25, y + 1.0, 5.5, 1.05, sub, size=14, color=GREY)
    source(s, '推論（不是直接證據）：使用者是上肢受限者、模式切換是負擔 → 手腕方向給使用者，前後與夾取交給系統。「C6–C7 保留手腕、失去手指」【此處需補文獻】。')

    # 13 claim 9
    s = d.slide('論點 9：延遲約一半是使用者的反應，系統部分有設計空間', notes='第 1 天 6 手勢流程測試的拆解；Ozdemir 40 人離線掃描。report 35.54。')
    tags(s, [('self', '第 1 天流程測試'), ('pub', 'Ozdemir 40 人')])
    bar_chart(s, 0.6, 1.75, 5.6, 4.4, ['全部', '使用者反應', '系統'],
              [('中位數 ms', [lat['total'], lat['react'], lat['system']])], [GREY, AMBER, TEAL], vmin=0, vmax=1400, fmt='0')
    rows = [['k', '第一個指令正確', '開始', '停止', '休息時誤送／分']]
    for k in (2, 3, 4):
        fo, st, sp, wr, fm = ks[('S7', k)]
        rows.append([f'{k}{"（現在）" if k == 3 else ""}', f'{fo:.1f} %', f'{st} ms', f'{sp} ms', f'{fm:.1f}'])
    table(s, 6.6, 1.85, 6.1, rows, [1.2, 1.5, 1.0, 1.0, 1.4], size=13, row_h=0.5, fills={(2, j): TEAL_L for j in range(5)})
    text(s, 6.6, 4.0, 6.1, 2.2, ['k 從 3 降到 2：快約 150 ms，但第一個指令正確率大幅下降 → 不划算',
                                  '停止比開始慢 → 實驗 2 用振幅門檻停止（尚未驗證）',
                                  '100 ms 視窗配小的 margin 門檻：同樣速度更準（report 35.54）'], size=14, color=INK, bullet=True)
    source(s, '左：全部＝使用者反應（提示→開始用力）＋系統（開始用力→指令），第 1 天 6 手勢的中位數。右：Ozdemir 7 類，200 ms 視窗、100 ms 步長。出處：report 35.54。')

    # 14 open gaps
    s = d.slide('還沒有證據的地方，以及怎麼補', notes='這頁的每一項都還沒有數據支持，不能當成結論。')
    tags(s, [('none', '以下都還沒有數據')])
    rows = [['尚未證明', '為什麼重要', '怎麼補'],
            ['意圖推論的錯誤和分類器的錯誤一起發生', '模擬的猜錯是隨機的，真實情況可能更糟', '模擬：意圖由解碼的指令推得（可以先做）'],
            ['自己的資料上也成立', '目前都是公開資料', '11/23 起的 9 手勢自我測試（判準 1–3 已事先登記）'],
            ['橈偏／尺偏的跨天結果', 'GrabMyo 用旋後／旋前代替', '自我測試第 2 天；或找有這兩個動作的跨天資料'],
            ['和 CIIL 原方法比較', '目前是依摘要的簡化版', '讀全文，照原方法實作'],
            ['shared autonomy 真的讓任務變快', '還沒有手臂實驗', 'RViz 模擬 → 實機 Kinova（條件 A／B／C）'],
            ['患者身上也有效', '健康的人做 S5 ≠ 患者', '未來工作（需要 IRB）']]
    table(s, 0.6, 1.75, 12.1, rows, [3.9, 3.6, 4.6], size=13, row_h=0.62)

    # 15 next steps
    s = d.slide('接下來的順序', notes='每一步都是補上一頁的一個缺口。')
    steps = [('11/19–11/22', '模擬：意圖由解碼指令推得（錯誤相關）', '補論點 5、6 最大的缺口'),
             ('11/23 起', '自我測試 9 手勢，第 1、2 天', '判準 1–3；自己的資料上驗證論點 2、4'),
             ('之後', '帶結果和指導教授討論方向', '確定 shared autonomy、只用手腕'),
             ('實驗 2', 'RViz → Kinova，條件 A／B／C', '驗證輔助與 ε = 1 − P(目標)')]
    for i, (when, what, why) in enumerate(steps):
        y = 1.6 + i * 1.25
        P.circle_num(s, 0.6, y + 0.1, i + 1)
        text(s, 1.3, y, 2.2, 0.5, when, size=16, bold=True, color=TEAL)
        text(s, 3.5, y, 9.2, 0.5, what, size=18, bold=True)
        text(s, 3.5, y + 0.5, 9.2, 0.5, why, size=14, color=GREY)

    # 16 references
    s = d.slide('參考文獻（只讀過摘要，引用前要讀全文）')
    refs = ['Anderson (2004) J Neurotrauma — 脊髓損傷者的功能恢復優先順序（二手引用）',
            'Benini 團隊 (2024) IEEE TBCAS — 低功耗 MCU 上的 sEMG 增量學習',
            'Campbell 等 (2024) J NeuroEng Rehabil — Context-informed incremental learning (CIIL)',
            'Chung 等 (2023) RESNA — 輔助機械臂長期使用者訪談',
            'Fonseca 等 (2019) Sensors 19(20):4532 — 四肢癱瘓者用殘存肌肉控制',
            'Li G, Schultz AE, Kuiken TA (2010) IEEE TNSRE 18(2):185–192',
            'Maheu 等 (2011) IEEE ICORR — JACO 機械臂評估',
            'Ozdemir 等 (2022) Data in Brief 41:107921 — 4 顆貼肌肉的資料集',
            'Vidovic MM 等 (2016) IEEE TNSRE 24(9):961–970 — 共變量偏移調整',
            'Yoneda 等 (2023) IEEE SMC；(2025) IEEE TNSRE — EMG 自我訓練（作者依檔名，待確認）',
            'Young AJ, Hargrove LJ, Kuiken TA (2012) IEEE TBME 59(3)',
            '資料集：NinaPro DB2；GrabMyo（PhysioNet 1.1.0）']
    text(s, 0.6, 1.35, 12.1, 5.5, refs, size=14, space=5, bullet=True)

    d.prs.save(out)
    return d.n


if __name__ == '__main__':
    out = sys.argv[1]
    tmp = out + '.tmp.pptx'
    n = build(tmp)
    os.replace(tmp, out)
    print('slides', n, '->', out)
