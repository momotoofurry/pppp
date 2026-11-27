# 讀書筆記：Di Domenico et al. 2024

**題目**：Long-Term Upper-Limb Prosthesis Myocontrol via High-Density sEMG and Incremental Learning
**來源**：arXiv 2412.16271v1（2024-12-20）
**PDF**：`D:\有用PAPER\2412.16271v1.pdf`
**資料集 / 程式**：DELTA（Zenodo 10.5281/zenodo.10801000）；github.com/DarioDiDomenico/Incr_HDsEMG
**讀書日期**：2026-11-22

> 這篇是「短校正＋跨天累積」最直接的前例，增量更新的數學（累加充分統計量）和我的 OAS LDA running sums 是同一類。

---

## 總結

**(a) 做了什麼**
- 硬體：64 顆乾電極做成 HD-sEMG 義肢內襯（§IV-A）。
- 資料：DELTA，7 位受試者（6 健康、1 先天肢體缺損），6 個 session，相鄰至少隔一週，第一次到最後一次相隔 48–262 天（§IV-B）。7 類手勢，每類每天 10 次 × 2 s。
- 方法：7 種 batch 分類器 vs. 增量 RLSC / RF-RLSC。
  - batch：只用第 1 天 2 次重複訓練，之後固定。
  - 增量：之後每天再用 2 次**有提示**的重複更新（每類 2 × 2 s × 7 類 = 28 s）（§IV-C、§V-C）。
- 結果：batch 後面幾天大幅下降，最好的 kNN 也掉超過 10%（§V-C）；增量 (RF-)RLSC 高且穩定（圖 7）；RF-RLSC 一致優於線性 RLSC（圖 7c–d）；RLSC 系列預測快 10–1000 倍（圖 6c、§VI）。
- 限制：**全部離線**，在 i7 工作站上跑（§V），沒有閉迴路、沒有在 MCU 上執行。準確率只有圖，沒有數字表。

**(b) 對我研究的影響**
- **新穎性**：「短校正＋跨天累積」和「累加量閉式更新」都已被做過。
  - 增量 RLSC（Alg. 1）累積 bₖ = Σ xᵢ eᵧᵢᵀ，用 Cholesky 更新 (XᵀX + λI)，和 OAS LDA running sums 同類。
  - 我的區隔只能放在：① 標籤來源（提示 ground truth vs. 任務 hindsight，不用每天再做提示校正）；② 實際在 STM32H753 上更新（它只在 §VI 提到嵌入式限制）；③ 實機閉迴路驗證。
- **實驗設計**：batch vs. incremental 可當離線「label off / label on」範本。可借：所有天數排列都跑（§V-C）；超參數只用第 1 天選定。
- **指標**：每天測試準確率曲線、增量 − batch 準確率差、預測時間。我要補：MCU 更新時間、RAM（KB = 1024）、閉迴路 SR / TAT。
- **它的弱點**：
  - 每天 min-max 正規化用**當天全部資料**算（§IV-C 3），包含測試的 8 次重複 → 輕微資訊洩漏。我的 z-score 只用當次提示資料，較乾淨。
  - 沒有遺忘因子，每天權重一樣。

**(c) 可寫進哪一章**
- 第 2 章：跨天適應 / 增量學習，列為**最直接前例**，要明確寫區隔。
- 第 3 章：baseline 設計（第 1 天固定 vs. 增量）、充分統計量更新的理論依據。
- 第 5 章：標籤來源（提示 vs. 任務 hindsight）、PC vs. MCU。

---

## 細節（附出處）

### 硬體（§IV-A）
- 64 顆乾電極，間距約 2 cm；1–32 在屈肌、33–64 在伸肌。
- 客製半硬式內襯（和 INAIL Budrio 合作），讓每次穿戴的電極位置可重複。
- Sessantaquattro（OT Bioelettronica），2 kHz、單極、16 bit，Wi-Fi 傳到 PC。

### 資料集（§IV-B）
- 6 位健康（5 男，右撇子，25–34 歲，28.5 ± 3.0）＋ 1 位 28 歲先天上肢缺損。
- 時間跨度 3.9 ± 2.2 個月。倫理審查：Regione Liguria（IIT REHAB HT01）。
- 7 類：HC、HO、WP、WS、WF、WE、Rest（對應 Hannes 義肢的動作）。
- 每次動作從開始做持續到穩態，共 2 s；每類 10 次。

### 學習流程（§IV-C）
1. 濾波：50 Hz notch ＋ 20–500 Hz Butterworth 帶通
2. 特徵：每通道 RMS，200 ms 窗（400 樣本）、50 ms 步長
3. 正規化：每通道 min-max，**每天各自算**
4. 模型選擇：在第 1 天訓練資料上做 10-fold CV，選「平均準確率 − 2 STD」最高的
5. 訓練 / 更新：batch 只用第 1 天；增量在第 2–6 天各用 20%（2 次重複）更新
6. 測試：每天剩下的 8 次重複

### 數學（§III、Alg. 1）
- RLSC 閉式解：W = (XᵀX + λI)⁻¹ XᵀY（式 1），預測 ŷ = argmax(Wᵀx)（式 2）
- batch 成本 O(n·m² + m³)；增量每次更新 O(m²)
- Alg. 1：bₖ ← bₖ₋₁ + xₖ eᵧₖᵀ；Rₖ = CholeskyUpdate(Rₖ₋₁, xₖ)；Wₖ = Rₖ⁻¹ (Rₖᵀ)⁻¹ bₖ
- RF-RLSC：用 random features 近似 Gaussian kernel，M = 500（考慮嵌入式記憶體，§V-B）

### 結果
- KPCA 視覺化（圖 4）：同一天內各類分得開，跨天後重疊嚴重、分布漂移明顯。
- batch 大幅下降，kNN 掉幅最小但仍超過 10%（§V-C、圖 7）。
- 增量 (RF-)RLSC 高且穩定，健康受試者和肢體缺損受試者都是（圖 7a–b）。
- RF-RLSC − RLSC 的準確率差一致為正（圖 7c–d）。

---

## 延伸：Burrello et al. 2021（從這篇參考文獻 [17] 找到）

**書目**：Burrello, Zanghieri, Sarti, Ravaglia, Benatti, Benini. Tackling Time-Variability in sEMG-based Gesture Recognition with On-Device Incremental Learning and Temporal Convolutional Networks. IEEE SAS 2021, pp. 1–6. DOI 10.1109/SAS51076.2021.9530007

**狀態**：只讀到摘要層級；全文在 polito 典藏為限制存取，**沒有下載**。下面硬體數字來自搜尋結果摘要，**還沒對過原文**。

- 方法：TCN，存過去 session 的 latent 資料，新 session 時重新訓練（latent replay）。
- 資料：UniBo-20-Session，3 位受試者、8 手勢（錄好的資料集，標籤 = 提示 ground truth）。
- 結果：比單次訓練 baseline 高 18.9%，比最強對手（RBF-SVM）高 5.60%。
- 硬體：GAP8。回報的是**推論**：12.9 ms、0.66 mJ、權重 427 kB；資料記憶體 0.5–32 MB；增量資料約 8 MB（完整 144 MB）。單位是原文的 kB/MB，尚未換算成 KiB。
- **和我的差別**：它存資料再用反向傳播重訓（MB 級）；我只存充分統計量做閉式更新（約 29.4 KB）。摘要看不出重訓有沒有真的在 GAP8 上跑。
- **處理方式**：「在 MCU 上做增量學習」本身不新（初稿第 1–2 章第 111 行已承認），把 Burrello 2021 加進同一段即可。

---

## 待辦
- [ ] 用學校帳號從 IEEE Xplore 下載 Burrello 2021，確認重訓是否在 GAP8 上跑、核對數字
- [ ] 看 Ravaglia et al.（arXiv 2110.10486，TinyML on-device continual learning with quantized latent replays）是否也要引用
- [ ] 離線實驗考慮「所有天數排列」的做法
- [ ] 想清楚要不要加遺忘因子（它沒有）
