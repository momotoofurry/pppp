# 自我校正隨機森林肌電控制：PC 基準重現與 STM32H743 記憶體分析

> 論文題目：在 STM32H7 上實現有記憶體預算、不需要標籤的自我校正隨機森林（RF）肌電手勢控制
> 日期：2026-10-17　｜　目標硬體：NUCLEO-H743ZI2（Cortex-M7，2 MB Flash，AXI SRAM 512 KB + SRAM1–4 + DTCM 128 KB）
> 上游程式碼與資料：MoveR-Digital-Health-and-Care-Hub/self-calibrating-rf（commit `48ea4d1`）

報告中的數字，除了明確標示為「估算」的部分，都來自實際執行的結果。每個數字都可以用 `README.md` 裡的指令重新產生。
各階段的詳細說明在 `results/stage1_summary.md`、`stage2_summary.md`、`stage3_summary.md`。
本報告的數字都是在 Windows 11 上跑出來的；之後的實驗改在 WSL2 + Docker（`docker/`）進行，兩個平台的差異見 1.6 節。

## 摘要

| 問題 | 答案 |
|---|---|
| PC 基準重現得出來嗎？ | 可以。自我校正 RF 在 arm_position 資料（20 人、11 個 block）的平均準確率是 **84.63 ± 8.58%**，論文是 84.6 ± 8.5%；所有和論文對得上的指標差距都 < 1 個百分點。 |
| 原始模型放得進 H743 嗎？ | 推論模型可以。論文的完整設定（剪枝後的 200 棵 + 附加的 200 棵，深度不限）用 compact float32 格式，編譯後 Flash 是 **693.8 KB**；照題目設定的 naive 格式要 1519 KB，也放得進 2 MB Flash。 |
| 推薦的壓縮設定 | **100 棵、深度 10、int16 門檻值**：Flash 88.1 KB，one-shot 準確率 79.75%（完整模型是 80.12%，差 −0.37 個百分點）。Flash 夠用的話，400 棵、深度 10、int16 只差 −0.04 個百分點，要 345.5 KB。**自我校正之後**（3.1 節）：100 棵是 83.96%，完整模型 84.43%，差 −0.47 個百分點，差距沒有明顯擴大。 |
| 推論需要多少 RAM？ | 實測 **552 B**（特徵緩衝區 + 最壞情況的 stack）。 |
| 自我校正放得進 MCU 嗎？（估算） | 照論文原樣做（float32 buffer + t-SNE）約需 1208 KB，**放不下**。改用 int16 buffer、100 棵樹、不做 t-SNE，約 334 KB，放得進 AXI 512 KB。但「不做 t-SNE」在論文的 ablation 裡準確率比較低，這是論文要解決的核心問題。 |
| 能壓到 256 KB 以下嗎？（實測，3.5–3.6 節） | 可以：buffer 375 筆（int16）＋ 新樹 32 葉 ＋ t-SNE，自我校正 83.44%、增益 +3.76，RAM 估算 219 KB，和基準無顯著差異（p = 0.17）。250 筆開始明顯變差。t-SNE 在 PC 上每次 2.1 s（1500 筆 9.3 s），MCU 上的時間還沒量。 |
| t-SNE 迭代可以減少嗎？（實測，3.7 節） | 可以減半：同一設定下 500 次迭代自我校正 83.27%、增益 +3.59，和 1000 次（83.44%、+3.76）差 −0.17 個百分點，不顯著（p = 0.14）；PC 上 t-SNE 時間 1.96 → 1.01 s。400 次開始顯著變差（−0.41，p = 0.017），250 次增益只剩 +0.48。 |
| 降低 t-SNE perplexity 有用嗎？（實測，3.8 節） | 不太有用：perplexity 3／5／7 在 PC 上**不省時間**（時間由 octree 排斥力決定，和近鄰數無關），只省 t-SNE 的近鄰表 RAM（估算 100 → 54–81 KB），準確率全都比 perplexity 10 低（−0.07 到 −0.69，部分顯著）。維持 perplexity 10、500 次迭代。 |
| 上板前能先用 C 做完嗎？（實測，第 6 節） | 可以：特徵擷取、t-SNE、K-Means、建樹、整個自我校正迴圈都用 C（靜態記憶體）寫好並在 PC 上驗證，端到端 83.22%（sklearn 83.27%，p = 0.90；修正樹的亂數種子之後，7.1 節），沒有一項有顯著差異。跨兩天的 demo（1 人）上，C 韌體邏輯把第 2 天的 75% 拉回 93%（6.6 節）。MCU 時間要等板子。 |
| one-shot 校正也能在 MCU 上做嗎？（實測，第 7 節） | 可以：剪枝和 Python 逐節點相同（20/20 人），one-shot 79.40%（sklearn 79.68%，p = 0.52），自我校正後 82.98%（83.27%，p = 0.28）。整個路線 B 韌體（序列協定＋即時迴圈＋MCU 上 one-shot＋自我校正）linker 實測 RAM 約 248.7 KB（含中斷 stack 上界），Flash 115.6 KB；加上硬體層（只編譯）253.2 KB。之後 octree 改配 2.5 n（準確率逐列不變）：路線 B 242.1 KB、含硬體層 246.5 KB（7.5 節）。 |
| 怎樣才放得進 512 KB？（實測，3.3–3.4 節） | **不必拿掉 t-SNE**：buffer 存成 int16（無損失）並縮到 750 筆，自我校正 83.83%、增益 +4.15，RAM 估算 394 KB；500 筆 280 KB、增益 +3.78。新樹限制 32 葉讓附加樹保證 ≤ 10.6 KB、準確率無顯著差異。兩者合併使用還沒實測。 |
| 不做 t-SNE 會掉多少？（實測，3.2 節） | 推薦設定上，只用 K-Means 81.03%、不分群 81.64%，t-SNE 版 83.98%；自我校正增益從 +4.30 掉到 +1.35 / +1.96 個百分點（20 人配對 p < 0.001）。完整模型的結果重現了論文的 ablation（84.66 / 80.89 / 82.16 vs 論文 84.6 / 81.0 / 82.7）。 |
| 換平台結果會變嗎？ | 特徵、預測、one-shot、C/ARM 編譯在 Docker（Linux）和 Windows 上都相同。**自我校正不會逐位元相同**：Linux 84.66% vs Windows 84.43%（差 0.23 個百分點，和 seed 之間的變動同一個等級）。同一個比較只用同一個平台的數字（1.6 節）。 |

---

## 1. 重現結果（vs. 論文）

### 1.1 環境與作法
- Python 3.12.3（conda-forge 版），numpy 2.1.2 / scipy 1.14.1 / scikit-learn 1.5.2（版本和 requirements 一樣，joblib 模型才能正確載入）。
- 上游程式沒有設亂數種子，所以用 `src/run_upstream.py` 先固定 numpy 的全域種子再執行，上游程式碼不做任何修改。同一個 seed 重跑兩次，結果逐位元相同。
- arm_position 跑了 3 個 seed（0/1/2），每個 seed 約 57 分鐘；demo 也跑了 3 個 seed。

### 1.2 方法重點（讀程式碼得到）
| 項目 | 實際做法 |
|---|---|
| 濾波 | 每個 channel 用 4 階 Butterworth 帶通 10–500 Hz，`lfilter`（單向、因果） |
| 視窗 | 200 ms（400 點），步長 100 ms；每個 2 秒的 trial 只取後 1 秒 → 10 個視窗 |
| 特徵（10 種 × 8 ch = 80 維） | RMS、WL、SSC、ZC、MAV、偏度、VCF、MDF、MNF、PKF（Welch：Hamming、nperseg 400、nfft 512）；用該受試者 calibration 資料的 mean/std 做 z-score |
| One-shot 校正 | 6 個手勢各 1 個 trial（共 60 個視窗）。預訓練的 200 棵樹由下往上剪枝（calibration 準確率**嚴格提高**才剪），再附加 200 棵只用這 60 筆訓練的新樹 → 400 棵 |
| 自我校正 | 每個 block 結束後，把資料放進最多 1500 筆的 buffer（滿了就刪掉數量最多的偽標籤類別中最舊的一筆）。每類都 ≥ 10 筆時，先做類別平衡 → t-SNE 3 維 → 用 RF 預測的各類中心初始化 K-Means，得到偽標籤。用「偽標籤 + 60 筆真標籤」訓練 80 棵樹，取代 200 棵附加樹中的 80 棵 |
| 偽標籤篩選 | **沒有信心門檻**。buffer 裡的樣本全部會用到（只做類別平衡） |

程式和論文描述不一樣的地方：
- 剪枝條件：論文寫 `≤`，程式是嚴格 `>`。
- 偽標籤初始化：論文寫用「current model」，程式其實一直用最初的 one-shot 模型。
- 比較方向：預測用 `x < thr`，剪枝和 sklearn 用 `x <= thr`。
- bootstrap 比例：JNE 寫 7%，實際模型是 1%–2%。

### 1.3 arm_position 結果（20 人 × 11 block，3 個 seed 平均；`results/baseline.csv`、`baseline_by_position.csv`）

| 方法 | P2 | P4 | P5 | P6 | P8 | 全部 |
|---|---|---|---|---|---|---|
| LDA（只用 calibration） | 69.59 | 70.15 | 75.99 | 71.47 | 73.06 | 72.41 |
| RF（只用 calibration） | 75.67 | 77.84 | 77.37 | 76.25 | 78.66 | 77.18 |
| 預訓練 RF（不校正） | 68.09 | 70.35 | 71.46 | 70.36 | 73.62 | 70.84 |
| **固定模型：one-shot RF** | 78.09 | 81.04 | 81.17 | 78.63 | 81.63 | **80.21** |
| **自我校正 RF** | 82.24 | 85.59 | 84.95 | 83.88 | 86.33 | **84.63** |

20 人中有 18 人的自我校正準確率高於固定模型。

![accuracy vs block](results/baseline_blocks.png)

### 1.4 和論文比較（Front. Neurorobot. 2024，只用論文文字和 Table 1 裡的數字；`results/paper_comparison.csv`）

| 指標 | 論文 | 我們（3 個 seed 平均） | 差距 |
|---|---|---|---|
| 自我校正 RF，全部 block | 84.6 ± 8.5 | 84.63 ± 8.58 | +0.03 |
| LDA @P5 | 76.0 ± 9.3 | 75.99 ± 9.26 | −0.01 |
| RF @P5 | 77.6 ± 9.6 | 77.37 ± 10.05 | −0.23 |
| LDA 換到 P2/P4/P6/P8 的下降 | 6.4 / 5.8 / 4.5 / 2.9 | 6.40 / 5.84 / 4.52 / 2.94 | ≤ 0.04 |
| one-shot 比 RF 多的增益 P2/P4/P5/P6/P8 | 2.5 / 3.5 / 4.2 / 2.6 / 3.1 | 2.42 / 3.20 / 3.80 / 2.38 / 2.97 | −0.08 ~ −0.40 |
| 自我校正比 one-shot 多的增益 P2/P4/P5/P6/P8 | 3.3 / 4.2 / 3.7 / 5.0 / 4.1 | 4.14 / 4.55 / 3.77 / 5.25 / 4.69 | +0.07 ~ +0.84 |

**差距都很小，沒有需要特別解釋的大差異。** 可能的小差異來源：
1. RF 訓練和 t-SNE 本身有隨機性：3 個 seed 之間，自我校正的全部平均在 84.38–84.80% 之間變動。
2. 論文本身沒寫 seed 數量和重複次數。
3. 自我校正增益在 P2、P8 的論文值落在我們 seed 的範圍外（+0.8、+0.6），可能來自論文作者用的程式版本或亂數。我們無法再細分原因。

### 1.5 Demo（JNE 2025 的 1 位受試者、10 個 block、跨兩天）
3 個 seed 平均：固定 one-shot 81.89% → 自我校正 90.02%。到了第 2 天後段（block 7–9），固定模型降到 71.6–76.0%，自我校正則是 89.1–96.0%。
JNE 論文報告的是 28 人平均（固定模型 84.3% → 78.6%，自我校正最後 86.5%），不是這位受試者的數字，所以只能比較趨勢：趨勢一致。

### 1.6 實驗環境與跨平台可重現性（`results/platform_check.md`）
原本的結果在 Windows 11 上產生（conda-forge Python 3.12.3、MinGW gcc 8.1、WSL2 裡的 arm-none-eabi-gcc 10.3.1）。
之後的實驗在 WSL2 + Docker 執行（Ubuntu 22.04、Python 3.12.3、同樣的套件版本、gcc 11.4、arm-none-eabi-gcc 10.3.1），
專案放在 WSL 的 `~/model`。兩個平台的比較（實測）：

| 部分 | Docker（Linux）vs. Windows |
|---|---|
| 特徵擷取 | 10 種特徵中 7 種逐位元相同；MNF、偏度、VCF 只差最後一位（相對誤差 ≤ 7e-15） |
| 預測、壓縮掃描（subject 0，660 列）、one-shot（20 人 × 3 seed，660 列） | 完全相同 |
| C 匯出、PC 檢查、Cortex-M7 編譯 | text/data/bss/stack 和預測完全相同 |
| 自我校正（400 棵、深度不限、float64，20 人 × 3 seed） | Linux **84.66%**（84.50–84.81）vs Windows **84.43%**（84.08–84.83）；只有 157/660 個 block 相同 |

- 每個 (seed, 受試者) 的差（Linux − Windows）：平均 +0.23 個百分點，SD 0.85；20 人的 Wilcoxon 檢定 p = 0.040。
  差異小於 Windows 自己 seed 之間的差距（0.75 個百分點），只有 3 個 seed，不足以判斷是系統性的還是偶然。
- 原因：t-SNE → K-Means → 重新訓練樹 這條鏈對極小的浮點差異很敏感；連 Linux 單執行緒和多執行緒的結果都不一樣。
  **Windows 單執行緒**（和原本 joblib worker 的條件一樣）可以逐位元重現原本的結果，所以差異來自平台，不是程式錯誤。
- **規則**：同一張表、同一個比較的數字只用同一個平台的結果；新的實驗都在 Docker 裡跑，對照組也一起在 Docker 裡重跑。

---

## 2. 原始模型大小，以及能不能放進 H743

### 2.1 預訓練模型結構（`results/model_stats.csv`）
| | 38 人模型 | 66 人模型 |
|---|---|---|
| 樹數 / 特徵 / 類別 | 200 / 80 / 6 | 200 / 80 / 6 |
| 每棵樹節點數 平均（最大） | 778.6（855） | 821.4（895） |
| 深度 平均（最大） | 18.6（31） | 18.5（24） |
| 平均葉節點深度 | 10.8 | 10.7 |
| 總節點數 | 155,730 | 164,284 |

### 2.2 原始大小（只算走得到的節點，外加每棵樹 4 B 的 offset 表）
| 66 人預訓練模型 | float32 | int16 |
|---|---|---|
| naive（每個節點都存 feature u8 + thr + L/R u16 + class u8） | 1605 KB | 1284 KB |
| compact（只存內部節點，葉節點編在 child index 裡） | 722 KB | 562 KB |

實際部署的是「剪枝後的 200 棵 + 附加的 200 棵」。剪枝只讓每棵預訓練樹從 821 個節點降到約 764 個；
附加樹只用 60 筆資料訓練，每棵約 13 個節點。實測：compact float32 是 682 KB、naive float32 是 1519 KB。
**結論：放得進 2 MB Flash（naive 格式佔約 74%），但不論哪種格式都超過 512 KB 的參考線。**

---

## 3. 壓縮取捨曲線與推薦設定

掃描做法（`src/compression_sweep.py`，20 人 × 11 block × 5 個 seed，**one-shot 固定模型**）：
把預訓練樹截到深度 d → 剪枝 → 保留 N/2 棵 → 附加 N/2 棵新樹（max_depth = d）。
int16 用 Q5.10 定點（z-score 後的門檻值範圍是 −9.9 到 20.8，放得進 ±32）。

![size vs accuracy](results/sweep_size_vs_acc.png)

one-shot 準確率（%，int16；和 float32 的差距在所有設定下都 ≤ 0.023 個百分點）：

| depth \ N | 5 | 10 | 20 | 50 | 100 | 400 |
|---|---|---|---|---|---|---|
| 6 | 68.06 | 73.32 | 75.87 | 77.44 | 78.38 | 78.88 |
| 8 | 68.97 | 73.75 | 76.84 | 78.76 | 79.31 | 79.62 |
| 10 | 68.16 | 73.21 | 76.82 | 79.01 | 79.75 | 80.08 |
| 12 | 67.89 | 73.25 | 77.04 | 79.13 | 79.72 | 80.06 |
| 不限 | 67.61 | 73.39 | 76.75 | 78.83 | 79.74 | 80.11 |

大小（KB，compact int16）：深度 10 時，N = 5/10/20/50/100/400 分別是 3.0 / 7.9 / 17.1 / 42.8 / 85.4 / 338.2。
完整表格在 `results/sweep_summary.csv`，Pareto 前緣在 `results/sweep_pareto.csv`。

觀察：
1. **int16 量化完全沒有準確率損失**，大小少 22%。
2. **深度 10 就夠了**：和不限深度的差距 ≤ 0.1 個百分點，大小少 36%。
3. **準確率主要看樹的數量**：N = 100 時差 −0.37 個百分點，N = 20 時差 −3.3，N = 10 時差 −6.9。
   題目舉的「20 棵、深度 10」只要 17 KB，但要付出 3.3 個百分點的代價。
4. 變體 B（固定保留 200 棵附加樹，只減少預訓練樹）只有在深度 6 時有幾個點落在 Pareto 前緣上，在深度 10 都比一半一半的組合差。

**推薦設定：100 棵（50 棵剪枝後的預訓練樹 + 50 棵附加樹）、深度 10、int16 Q5.10。**
理由：Flash 只要 88 KB（佔 2 MB 的 4%），one-shot 準確率只差 0.37 個百分點；而且只有 50 棵附加樹會被自我校正替換，放在 RAM 的部分比較小（見第 5 節）。
備選：400 棵、深度 10、int16（345.5 KB，−0.04 個百分點），適合 Flash 很充裕、想最接近原始模型的情況。

上面的準確率都是 one-shot（固定模型）。自我校正之後的結果在 3.1 節。

### 3.1 壓縮後模型的自我校正準確率（`src/selfcal_sweep.py` → `results/selfcal_sweep*.csv`）

做法：照上游 `main_replay_arm_position.py` 的迴圈重寫（buffer_update / manifold_clustering / replace 直接呼叫上游函式，沒有改）。
設定 (N, d, 精度)：預訓練樹截到深度 d → 剪枝 → 保留 N/2 棵 → 附加 N − N/2 棵；每個 block 之後用
buffer（1500 筆）+ t-SNE（3 維、perplexity 10）+ K-Means（min_sample_class 10）產生偽標籤，
訓練 round(0.4 × 附加樹數) 棵新樹（同樣 max_depth；N = 400 時是 80 棵）替換隨機選的附加樹。
所有預測（包含 manifold_clustering 內部的預測）都用該設定的精度；新樹用 float64 訓練。
照上游行為，K-Means 初始中心用的偽標籤一律由**最初的 one-shot 模型**產生，不是當下自我校正過的模型。
亂數照上游走 numpy 全域 RNG，每個 (seed, 受試者) 呼叫 `np.random.seed`。20 人 × 11 block × 3 個 seed（0/1/2）。

**驗證**：(400, 不限, float64) 得到 **84.43%**（seed 0/1/2 = 84.38 / 84.08 / 84.83），
上游 3 個 seed 是 84.38–84.80（平均 84.63），平均值落在範圍內。one-shot 80.03%（上游 80.21%）。

| 設定 (N, 深度, 精度) | one-shot | 自我校正（seed 範圍） | 增益 | 自我校正 vs 完整模型 | one-shot vs 完整模型 |
|---|---|---|---|---|---|
| 400, 不限, float64（上游） | 80.03 | **84.43**（84.08–84.83） | +4.40 | — | — |
| 400, 不限, float32 | 80.03 | 84.46（84.25–84.67） | +4.43 | +0.03 | 0.00 |
| 400, 10, int16 | 79.84 | 84.37（84.17–84.54） | +4.53 | −0.06 | −0.19 |
| **100, 10, int16（推薦）** | 79.68 | **83.96**（83.89–84.07） | +4.28 | **−0.47** | −0.35 |
| 50, 8, int16 | 78.77 | 83.19（82.94–83.40） | +4.42 | −1.24 | −1.26 |
| 20, 10, int16 | 77.17 | 81.93（81.69–82.14） | +4.76 | −2.50 | −2.86 |

（%，20 人平均；增益的 seed 範圍在 `results/selfcal_sweep_summary.csv`。受試者間標準差 8.7–9.5。
這裡的 one-shot 是 3 個 seed、全域 RNG，和上面 5 個 seed 的掃描差 ≤ 0.1 個百分點。）

觀察：
1. **自我校正的增益在所有壓縮設定下都差不多（+4.3 到 +4.8 個百分點）**，所以 one-shot 的差距大致原樣保留：
   推薦設定從 −0.35 變成 −0.47（差 0.12，和 seed 範圍同等級），N = 20 反而從 −2.86 縮小到 −2.50。
2. **int16 和深度 10 在自我校正後仍然沒有損失**：400 棵、深度 10、int16 只差 −0.06。
3. **自我校正後的樹比 one-shot 的附加樹大很多**（實測，`results/selfcal_sweep_trees.csv`）：
   one-shot 附加樹只用 60 筆 calibration 資料訓練，平均 13 個節點；自我校正後的附加樹是用 buffer + calibration 訓練的，

   | 設定 | 自我校正後附加樹節點數：平均 / 最大 | 整個模型 compact 大小：one-shot → 自我校正後平均（最大） |
   |---|---|---|
   | 400, 不限, float32 | 149 / 443（深度最深 26） | 682.4 → 802.3 KB（942.1） |
   | 400, 10, int16 | 133 / 343 | 338.2 → 420.5 KB（494.8） |
   | 100, 10, int16 | 135 / 331 | 85.4 → 106.3 KB（122.6） |
   | 50, 8, int16 | 105 / 223 | 23.2 → 31.1 KB（36.3） |
   | 20, 10, int16 | 141 / 309 | 17.1 → 21.5 KB（24.9） |

   深度 10 的單棵樹最大 331–343 個節點（165–171 個內部節點），比原本的近似值（每棵最多 107 個內部節點，
   來自 `compression_sweep.py` 不做 t-SNE/K-Means 的近似訓練集）大約 1.6 倍。但不會每棵樹都長到最大，
   所以 5.2 節改用**實測的整個附加樹區塊**：二元樹的內部節點數 = (節點數 − 1) / 2，每次執行的區塊大小 =
   附加樹數 × (平均節點數 − 1) / 2 × 每節點 bytes，再取 20 人 × 3 個 seed 中的最大值。
   推薦設定（50 棵附加樹）：平均 22.9 KB、最大 **38.8 KB**；400 棵、深度 10、int16：平均 90.5 KB、最大 163.5 KB；
   400 棵、深度不限、float32：平均 130.4 KB、最大 267.8 KB。

### 3.2 低記憶體的偽標籤方法（實測，Docker；`src/analyze_pseudo.py` → `results/pseudo_label_summary.csv`）

`selfcal_sweep.py --pseudo` 用上游 `manifold_clustering` 原有的分支比較三種偽標籤做法（上游程式不改）：
t-SNE + K-Means（上游預設）、只用 K-Means（80 維，`embedding=None`）、不分群（`min_sample_class = ∞`，
直接用 one-shot 模型的預測、只做類別平衡）。20 人 × 11 block × 3 seed，全部在 Docker 上跑，彼此可以直接比較
（但不要和上面 Windows 的數字混著比，見 1.6 節）。RAM 是 5.2 節的估算方式，但可替換附加樹用**各方法自己實測**的樹大小。

| 模型 | 偽標籤方法 | 自我校正後（seed 範圍） | 增益 | 和 t-SNE 版比（20 人配對） | 論文 ablation | RAM（估算） |
|---|---|---|---|---|---|---|
| 400 棵、深度不限、float64 | t-SNE + K-Means | **84.66**（84.50–84.81） | +4.63 | — | 84.6 | 1206 KB |
| | 只用 K-Means | 80.89（80.77–81.06） | +0.86 | −3.77，3/20 人較好，p < 0.001 | 81.0 | 879 KB |
| | 不分群 | 82.16（82.02–82.29） | +2.13 | −2.50，4/20 人較好，p < 0.001 | 82.7 | 758 KB |
| 100 棵、深度 10、int16 | t-SNE + K-Means | **83.98**（83.90–84.03） | +4.30 | — | — | 737 KB |
| | 只用 K-Means | 81.03（80.94–81.21） | +1.35 | −2.94，2/20 人較好，p < 0.001 | — | **341 KB** |
| | 不分群 | 81.64（81.60–81.66） | +1.96 | −2.33，3/20 人較好，p < 0.001 | — | **327 KB** |

（one-shot 都是 80.03%（400 棵）和 79.68%（100 棵）；配對差異是 seed 平均後的 20 人 Wilcoxon 檢定。）

觀察：
1. **重現了論文的 ablation**：完整模型的三個數字和論文高低順序相同，差距 ≤ 0.6 個百分點，所以這裡的實作和論文作者的做法一致。
   「不分群」比「只用 K-Means」好，和論文一樣。
2. **壓縮後研究問題仍然成立**：放得進 AXI 512 KB 的兩種做法（只用 K-Means、不分群），自我校正增益從 +4.30 掉到 +1.35 / +1.96，
   少了一半以上；20 人中只有 2–3 人比 t-SNE 版好。t-SNE 本身（估算 401 KB）是放不進去的主因。
3. 只用 K-Means 的附加樹長得比較大（完整模型最大 597 個節點，t-SNE 版 449），偽標籤比較雜時樹會變複雜，RAM 也跟著變大。

### 3.3 限制自我校正新樹的大小（實測，Docker；`src/analyze_leaf_buffer.py` → `results/leaf_buffer_summary.csv`）

推薦設定（100 棵、深度 10、int16）＋ t-SNE + K-Means，只限制自我校正時新訓練的樹（one-shot 的附加樹不變），
20 人 × 11 block × 3 seed。基準是同一模型、不限制（3.2 節的 Docker 結果 83.98%）。
附加樹區塊 = 50 棵 × (平均節點數 − 1) / 2 × 7 B，取 20 人 × 3 seed 中最大的一次；`max_leaf_nodes = L` 時另有保證上限 50 × (L − 1) × 7 B。

| 新樹的限制 | 自我校正後（seed 範圍） | 增益 | 和不限制比（20 人配對） | 附加樹區塊（實測最大） | 保證上限 |
|---|---|---|---|---|---|
| 不限制 | 83.98（83.90–84.03） | +4.30 | — | 40.3 KB | 無 |
| **max_leaf_nodes 32** | **83.90**（83.78–84.05） | +4.22 | −0.08，7/20 人較好，p = 0.35 | **10.6 KB** | **10.6 KB** |
| max_leaf_nodes 64 | 84.05（83.89–84.22） | +4.37 | +0.07，9/20，p = 0.73 | 21.5 KB | 21.5 KB |
| max_leaf_nodes 128 | 84.00（83.78–84.15） | +4.32 | +0.02，11/20，p = 0.76 | 38.5 KB | 43.4 KB |
| min_samples_leaf 5 | 83.83（83.70–83.91） | +4.15 | −0.14，8/20，p = 0.12 | 24.9 KB | 無 |
| min_samples_leaf 10 | 83.75（83.66–83.87） | +4.07 | −0.22，6/20，p = 0.064 | 16.1 KB | 無 |

觀察：
1. **`max_leaf_nodes = 32` 把附加樹的 RAM 從「實測最大 40 KB、沒有上限」變成保證 ≤ 10.6 KB，準確率沒有可量測的損失**（−0.08 個百分點，在 seed 範圍內，p = 0.35）。
2. `min_samples_leaf` 也能讓樹變小，但沒有保證上限，而且準確率掉得比較多；MCU 上要配置固定大小的記憶體池，所以用 `max_leaf_nodes`。
3. 這組結果是在 t-SNE + K-Means 上量的；和低記憶體偽標籤方法（3.2 節）一起用時的準確率還沒量。

### 3.4 buffer 大小與 int16 buffer（實測，Docker；同上 `leaf_buffer_summary.csv`）

推薦設定 ＋ t-SNE + K-Means，不限制樹大小。`--buffer-int16`：buffer 和自我校正訓練用的校正資料都存成 Q5.10 int16
（量化後再讀回來做 t-SNE、K-Means 和訓練），one-shot 模型不變。RAM 用 5.2 節的算法，buffer、t-SNE、K-Means、偽標籤、
RF 訓練暫存都依 buffer 大小重算，附加樹用各組實測的最大區塊。

| buffer | 自我校正後（seed 範圍） | 增益 | 和基準比（20 人配對） | t-SNE | 自我校正 RAM 合計（估算） |
|---|---|---|---|---|---|
| 1500 筆 float32（基準，上游） | 83.98（83.90–84.03） | +4.30 | — | 401 KB | 980 KB |
| 1500 筆 int16 | 84.00（83.95–84.04） | +4.32 | +0.02，11/20 人較好，p = 0.96 | 401 KB | 735 KB |
| 1000 筆 int16 | 84.05（83.80–84.40） | +4.37 | +0.08，11/20，p = 0.48 | 268 KB | **508 KB** |
| **750 筆 int16** | **83.83**（83.62–84.18） | **+4.15** | −0.15，11/20，p = 0.87 | 201 KB | **394 KB** |
| 500 筆 int16 | 83.46（83.40–83.55） | +3.78 | −0.52，9/20，p = 0.11 | 134 KB | **280 KB** |
| （3.2 節）不分群，1500 筆 int16 | 81.64（81.60–81.66） | +1.96 | −2.33，3/20，p < 0.001 | 0 | 327 KB |

觀察：
1. **int16 buffer 沒有損失**（84.00 vs 83.98，p = 0.96），buffer 和校正資料的 RAM 直接減半。
2. **縮小 buffer 就能把 t-SNE 版放進 AXI 512 KB，而且增益幾乎都保住**：750 筆 394 KB、增益 +4.15；500 筆 280 KB、增益 +3.78。
   在差不多的 RAM 下，小 buffer 的 t-SNE 遠比拿掉 t-SNE 好（不分群 327 KB、增益只有 +1.96）。
3. 所以 5.2 節「放得進 512 KB 的只有不做 t-SNE 的做法」要修正：**t-SNE 本身不必拿掉，縮小 buffer 就夠了**。
   下一個真正的限制是 256 KB 以下（目前最小 280 KB），以及 t-SNE 在 MCU 上的運算時間（還沒量）。
4. 小 buffer ＋ `max_leaf_nodes 32` 一起用的結果在 3.5 節。

### 3.5 小 buffer ＋ 新樹限制 32 葉（實測，Docker；同上 `leaf_buffer_summary.csv`）

推薦設定 ＋ t-SNE + K-Means，buffer 存成 int16，新樹 `max_leaf_nodes = 32`（附加樹保證 ≤ 10.6 KB），20 人 × 11 block × 3 seed。

| buffer | 自我校正後（seed 範圍） | 增益 | 和基準比（20 人配對） | t-SNE | 自我校正 RAM 合計（估算） |
|---|---|---|---|---|---|
| 750 筆 | 83.78（83.68–83.88） | +4.10 | −0.20，9/20 人較好，p = 0.60 | 201 KB | 382 KB |
| 500 筆 | 83.58（83.51–83.66） | +3.90 | −0.39，7/20，p = 0.14 | 134 KB | 273 KB |
| **375 筆** | **83.44**（83.17–83.69） | **+3.76** | −0.54，7/20，p = 0.17 | 100 KB | **219 KB** |
| 250 筆 | 82.83（82.53–83.03） | +3.15 | −1.15，2/20，**p = 0.001** | 67 KB | 164 KB |

觀察：
1. **256 KB 以下也做得到**：buffer 375 筆 ＋ 32 葉，RAM 估算 219 KB，增益 +3.76（基準 +4.30），和基準沒有顯著差異。
2. 250 筆開始明顯變差（−1.15 個百分點，20 人中 18 人變差，p = 0.001），所以 buffer 的下限大約在 375 筆。
3. 和兩項限制分開跑的結果一致（750 筆：單獨 83.83、合併 83.78；500 筆：83.46 / 83.58），兩項限制之間沒有明顯的交互作用。

### 3.6 t-SNE 的運算量（PC 實測；`src/tsne_cost.py` → `results/tsne_cost.csv`）

用和自我校正相同的 buffer（int16、類別平衡後才進 t-SNE）和相同的 t-SNE 設定（3 維、perplexity 10、Barnes-Hut），
在 PC 上單執行緒量每次 t-SNE 的 CPU 時間，3 位受試者平均：

| buffer | 實際進 t-SNE 的點數 | 迭代次數 | PC CPU 時間 | 相對 1500 筆 |
|---|---|---|---|---|
| 1500 | 1060 | 999 | 9.3 s | 1.00 |
| 1000 | 776 | 999 | 6.0 s | 0.64 |
| 750 | 650 | 999 | 4.7 s | 0.50 |
| 500 | 444 | 999 | 2.8 s | 0.31 |
| 375 | 362 | 999 | 2.1 s | 0.22 |
| 250 | 188 | 999 | 0.9 s | 0.10 |

- 時間大致和點數成正比；buffer 375 筆時是 1500 筆的 22%。
- **每次都跑到迭代上限（sklearn 預設 1000 次）**，沒有提早停止，所以減少迭代次數是另一個可以省運算量的方向（準確率影響還沒量）。
- 這是 PC（x86、sklearn 的 Cython 實作）的時間，**不是 Cortex-M7 的時間**；MCU 上要用 C 實作 Barnes-Hut t-SNE 後在板子上量。
  自我校正每個 block（30 個 trial）才做一次，所以 MCU 上能接受的時間比即時推論寬鬆得多，但具體能不能接受要等實測。

### 3.7 減少 t-SNE 迭代次數（實測，Docker；`src/analyze_tsne_iter.py` → `results/tsne_iter_summary.csv`）

設定和 3.5 節的 256 KB 以下版本相同（100 棵、深度 10、int16、buffer 375 筆 int16、新樹 32 葉），只改 t-SNE 的迭代次數
（sklearn `max_iter`；`src/selfcal_sweep.py --tsne-iter`，上游程式不改，在 worker 裡把 `emg_functions.TSNE` 換成固定 `max_iter` 的版本）。
20 人 × 3 seed；比較對象是同一次執行的 1000 次（上游預設），它和 3.5 節的結果 660 個 block 完全相同。
時間是 `src/tsne_cost.py --sizes 375 --iters ...`：CPU 空閒時單執行緒、3 位受試者平均、同一個 t-SNE 輸入和 seed。

| 迭代次數 | 自我校正 | seed 範圍 | 增益 | vs 1000 次（20 人配對） | 較好／較差人數 | Wilcoxon p | PC t-SNE CPU 時間 | 相對 1000 次 |
|---|---|---|---|---|---|---|---|---|
| 250 | 80.16 | 79.72–80.84 | +0.48 | −3.28 | 0 / 20 | < 0.001 | 0.46 s | 0.23 |
| 300 | 82.15 | 81.96–82.47 | +2.47 | −1.28 | 2 / 18 | < 0.001 | 0.62 s | 0.32 |
| 350 | 82.72 | 82.57–82.93 | +3.04 | −0.72 | 5 / 15 | < 0.001 | 0.78 s | 0.40 |
| 400 | 83.03 | 82.84–83.29 | +3.35 | −0.41 | 6 / 14 | 0.017 | 0.81 s | 0.41 |
| **500** | **83.27** | 83.13–83.37 | **+3.59** | −0.17 | 8 / 12 | 0.14 | **1.01 s** | **0.51** |
| 750 | 83.41 | 83.25–83.58 | +3.73 | −0.03 | 9 / 11 | 0.50 | 1.63 s | 0.83 |
| 1000（上游） | 83.44 | 83.17–83.69 | +3.76 | — | — | — | 1.96 s | 1.00 |

觀察：
1. **500 次迭代可以把 t-SNE 時間減半**（PC 上 1.96 → 1.01 s），準確率差 −0.17 個百分點，和 1000 次沒有顯著差異。
   但「不顯著」不等於「相同」：20 人中 12 人略差，只有 3 個 seed，所以論文裡要寫成「差異小於 seed 間的變動」，不能寫成無損。
2. **400 次以下開始顯著變差**，250 次幾乎沒有增益（+0.48）。原因是 sklearn 的前 250 次是 early exaggeration 階段，
   只跑這一段時嵌入還沒收斂成可分群的形狀；之後每多 50–100 次迭代都還有明顯的改善，到 500 次才趨於平緩。
3. 時間大致和迭代次數成正比（每次迭代的運算量固定）。這次 1000 次量到 1.96 s，3.6 節是 2.1 s：同一個輸入在不同時間量的差異，
   所以只在同一次量測裡比較相對值。
4. 這仍然是 PC 的時間；迭代次數對 MCU 時間的影響要等 C 版 t-SNE 上板後量（預期也大致成正比，但沒有實測就不報數字）。

---

### 3.8 降低 t-SNE perplexity（實測，Docker；`src/analyze_tsne_px.py` → `results/tsne_px_summary.csv`）

同 3.7 節的設定，perplexity 改成 3／5／7（每個點的近鄰數 3 × perplexity + 1 = 10／16／22，上游 10 → 31），各配 500 和 1000 次迭代
（`src/selfcal_sweep.py --tsne-perplexity`；上游呼叫時自己傳了 `perplexity=10`，所以替換的 TSNE 會強制覆寫這個參數）。
perplexity 10 的兩列來自 3.7 節那次執行。比較對象：上游設定（perplexity 10、1000 次）。時間：`src/tsne_cost.py --perplexities`，CPU 空閒時單執行緒、3 人平均。
RAM 是估算（t-SNE 近鄰表依近鄰數縮放，其他項同 3.5 節）。

| perplexity | 迭代 | 近鄰數 | 自我校正 | 增益 | vs 上游（20 人配對） | 較好／較差 | p | PC t-SNE 時間 | t-SNE RAM（估算） | 總 RAM（估算） |
|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 500 | 10 | 82.75 | +3.07 | −0.69 | 4 / 16 | 0.004 | 1.15 s | 54 KB | 173 KB |
| 3 | 1000 | 10 | 83.01 | +3.33 | −0.42 | 8 / 12 | 0.19 | 2.06 s | 54 KB | 173 KB |
| 5 | 500 | 16 | 83.19 | +3.51 | −0.25 | 8 / 12 | 0.13 | 1.08 s | 67 KB | 186 KB |
| 5 | 1000 | 16 | 83.21 | +3.53 | −0.23 | 8 / 12 | 0.23 | 2.12 s | 67 KB | 186 KB |
| 7 | 500 | 22 | 83.05 | +3.37 | −0.38 | 4 / 16 | 0.012 | 1.05 s | 81 KB | 199 KB |
| 7 | 1000 | 22 | 83.36 | +3.68 | −0.07 | 9 / 11 | 0.65 | 2.01 s | 81 KB | 199 KB |
| **10** | **500** | 31 | **83.27** | **+3.59** | −0.17 | 8 / 12 | 0.14 | **0.99 s** | 100 KB | 219 KB |
| 10（上游） | 1000 | 31 | 83.44 | +3.76 | — | — | — | 1.99 s | 100 KB | 219 KB |

觀察：
1. **降低 perplexity 在 PC 上不省時間**：同樣迭代次數下，perplexity 3–10 的時間差不到 ±0.1 s（perplexity 小的甚至略慢）。
   3.6 節的工作量模型（近鄰吸引力 n × k ＋ octree n log n）認為近鄰項是大宗，**這個假設不成立**：sklearn 的時間主要在
   Barnes-Hut 排斥力（octree），和近鄰數無關。C 版 t-SNE 要優化的應該是排斥力那一段（例如 angle、octree 的實作）。
2. **只省 RAM**：近鄰表從 100 KB 降到 54–81 KB（估算），總 RAM 219 → 173–199 KB。但 219 KB 已經在 256 KB 以內，這不是目前的瓶頸。
3. **準確率都比較低**，而且不是單調的（perplexity 7、500 次比 5、500 次差），看起來是 seed 層級的雜訊加上真實的小損失；
   3／500 和 7／500 顯著變差。沒有一個設定同時比 perplexity 10、500 次更快又更準。
4. 結論：**維持 perplexity 10、500 次迭代**。如果之後 RAM 預算要降到 200 KB 以下，perplexity 5 是可以考慮的備案（−0.25，不顯著）。

## 4. 編譯後的 Flash/RAM 用量

PC 正確性檢查（MinGW gcc 8.1，3300 筆測試視窗）：3 個設定 × 2 種實作，C 和 Python 的預測**100% 一致**（`results/c_check.csv`）。
在 Docker 裡用 gcc 11.4 重跑，結果也相同（`results/logs/linux/c_check.csv`）。

交叉編譯（WSL2，arm-none-eabi-gcc 10.3.1；`-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard -Os -ffunction-sections -fdata-sections -Wl,--gc-sections --specs=nano.specs --specs=nosys.specs`；`results/arm_size.csv`）：

| 設定 | 實作 | text | data | bss† | Flash | 靜態 RAM | 最壞 stack | 推論 RAM |
|---|---|---|---|---|---|---|---|---|
| 400 棵 / 不限 / float32 | 自寫 table | 710,480 | 4 | 324 | **693.8 KB** | 328 B | 72 B | **400 B** |
| 400 棵 / 不限 / float32 | emlearn inline | 2,024,756 | 4 | 324 | 1977.3 KB | 328 B | 192 B | 520 B |
| 400 棵 / 深度 10 / int16 | 自寫 table | 353,796 | 4 | 484 | **345.5 KB** | 488 B | 64 B | **552 B** |
| 400 棵 / 深度 10 / int16 | emlearn loadable | 404,180 | 32 | 488 | 394.7 KB | 520 B | 212 B | 732 B |
| **100 棵 / 深度 10 / int16** | **自寫 table** | 90,204 | 4 | 484 | **88.1 KB** | 488 B | 64 B | **552 B** |
| 100 棵 / 深度 10 / int16 | emlearn loadable | 103,108 | 32 | 488 | 100.7 KB | 520 B | 212 B | 732 B |

† 已經扣掉 linker script 為 stack 保留的 4096 B。最壞 stack 是用 `-fcallgraph-info=su` 沿最深的呼叫路徑加總。

重點：
- 自寫 table 格式的實際大小和階段 2 的估算完全相同，每種設定都比 emlearn 小 12.5%–65%。
  emlearn 的 int16 節點因為 padding 是 8 B（我們是 7 B）；emlearn 的 float inline 把每個節點都編成程式碼。
- emlearn 的 float inline 用 `%.6f` 印門檻值，93% 的門檻值有最多 9.5e-7 的誤差。這次測試沒有任何預測因此改變，但仍然有風險。**建議用自寫的 table runtime。**
- C 端一定要用 `x < thr`。在 int16 下換成 `<=`，預測只有 99.70% 相同。
- **Cycle 數沒有量。** QEMU 和 Renode 都不模擬 Cortex-M7 的 pipeline、cache 和 Flash wait state，它們的 cycle 數其實是用指令數推算的，所以不報。
  要拿到真正的推論時間，就燒到 NUCLEO 板上讀 `g_cycles`（main.c 已經用 DWT CYCCNT 量好）。ARM 上的預測正確性也要在板子上確認。

---

## 5. 下一步

### 5.1 特徵擷取移植到 C
- **濾波**：把 4 階 Butterworth 帶通改成 4 個 biquad（SOS 形式），每個 channel 串流處理。
  上游用的是 `lfilter` 的 b/a 形式，每個 trial 都從 0 初始狀態開始；串流處理的初始狀態不同，所以要先在 PC 上確認 SOS 串流版和上游的特徵差多少（暫態大約在前 1 秒內衰減，而上游本來就只用後 1 秒）。
- **時域特徵**（RMS/WL/SSC/ZC/MAV/偏度）：單次掃過視窗就能算完。
- **頻域特徵**：Hamming（400 點，常數表放 Flash）+ CMSIS-DSP 的 `arm_rfft_fast_f32`（512 點）→ Welch PSD（257 個 bin）→ MNF/MDF/PKF/VCF。要逐項和 scipy 對照。
- **驗收方式**：用 dataset 的原始 EMG 在 PC 上跑 C 版特徵，和 `features_arm_position/` 比對誤差，再把 C 版特徵丟進 RF，確認準確率不變。
- **RAM 估算**：濾波後的 ring buffer 12.5 KB + IIR 狀態 0.25 KB + FFT 4 KB + PSD 1 KB ≈ **18 KB**（依設計計算，`results/ram_estimate.csv`）。

### 5.2 MCU 上自我校正需要的 RAM（估算，`src/ram_estimate.py` → `results/ram_scenarios.csv`）

| 項目 | 大小 | 依據 |
|---|---|---|
| Buffer 1500 × 80，float32 / int16 | 468.8 / 234.4 KB | 上游參數（論文寫「~500 KB」） |
| Calibration 資料 60 × 80，float32 / int16 | 18.8 / 9.4 KB | |
| 可替換的附加樹區塊（自我校正後，20 人 × 3 seed 中最大的一次）：50 棵深度 10 int16 / 200 棵深度不限 float32 | 38.8 / 267.8 KB | **實測**（`results/selfcal_sweep_trees.csv`，第 3.1 節） |
| RF 訓練暫存（一次訓練一棵樹） | 26.2 KB | 索引陣列、排序後的特徵值、2^11 個節點的建樹緩衝區 |
| K-Means（80 維） | 5.2 KB | |
| Barnes-Hut t-SNE（3 維，31 個鄰居） | 401 KB | 稀疏 P 矩陣 272.5 KB + 嵌入/梯度 70.3 KB + octree 58.6 KB |

| 情境 | 合計 | 放進 AXI 512 KB？ |
|---|---|---|
| A 照論文原樣：float32 buffer、400 棵（深度不限）、t-SNE + K-Means | **1208 KB** | 否（連全部 SRAM 都放不下） |
| B int16 buffer、100 棵、t-SNE + K-Means | 735 KB | 否（要拆到好幾塊 SRAM，沒有這麼大的連續區塊） |
| C int16 buffer、100 棵、只用 K-Means | **334 KB** | 是 |

（合計已包含推論 552 B、特徵擷取約 18 KB、偽標籤 1.5 KB、RF 訓練暫存 26 KB。）

**論文的核心問題就在這裡**：t-SNE 是最大的記憶體負擔，但論文的 ablation（Frontiers Table 1）顯示：
- 拿掉 t-SNE、只做 K-Means：81.0%
- t-SNE 和 K-Means 都拿掉：82.7%
- 完整模型：84.6%

也就是說，直接拿掉 t-SNE 會掉 3.6 個百分點。在記憶體預算內找到 t-SNE 的替代方案，就是論文的主要貢獻。

> **更新（3.4 節實測）**：上表都假設 buffer 是 1500 筆。實際上不必拿掉 t-SNE：buffer 存成 int16 並縮到 750 筆，
> t-SNE 版約 394 KB（估算）、增益 +4.15，放得進 512 KB。所以研究問題改成：能不能壓到 256 KB 以下，以及 t-SNE 在 MCU 上算不算得完。

### 5.3 具體待辦（依優先順序）
0. ~~量壓縮後模型的自我校正準確率~~（已完成，3.1 節）：推薦設定（100 棵、深度 10、int16）自我校正後 83.96%（seed 範圍 83.89–84.07），
   比完整模型（84.43%）低 0.47 個百分點；one-shot 階段的差距是 −0.35，自我校正後沒有明顯擴大。
   另外發現自我校正後的單棵附加樹比原本的近似值大約 1.6 倍（深度 10 最大 165 個內部節點）；5.2 節已改用實測的附加樹區塊大小重算。
1. ~~**限制自我校正新樹的大小**~~（已完成，3.3 節）：`max_leaf_nodes = 32` 讓附加樹區塊保證 ≤ 10.6 KB，準確率 83.90%（不限制 83.98%，p = 0.35）。
2. **低記憶體的偽標籤方法**：在 PC 上比較下面幾種，看準確率和 RAM 的取捨：
   - ~~K-Means 直接在 80 維做~~、~~不分群~~（已完成，3.2 節：增益只剩 +1.35 / +1.96 個百分點，t-SNE 版是 +4.30）
   - 先投影到低維（PCA 或用 calibration 資料訓練的 LDA）再做 K-Means
   - t-SNE 縮小 buffer（例如 500 筆）
   - 依信心門檻篩選樣本
3. ~~**Buffer 精度和大小**~~（已完成，3.4 節）：int16 buffer 無損失；750 筆 394 KB、增益 +4.15。
   ~~(a) 小 buffer ＋ 32 葉一起跑~~、~~(b) 往 256 KB 以下推~~（已完成，3.5 節：375 筆 219 KB、增益 +3.76）。
   接著要做：~~(c) 用 C 實作 Barnes-Hut t-SNE~~（已完成，6.1 節；Cortex-M7 上的時間要等板子）；
   ~~(d) 減少 t-SNE 迭代次數~~（已完成，3.7 節：500 次時間減半、−0.17 個百分點不顯著；400 次以下顯著變差）。
   ~~降低 perplexity~~（已完成，3.8 節：PC 上不省時間，只省近鄰表 RAM，準確率較低；維持 perplexity 10）。
4. ~~**特徵擷取移植到 C**~~（已完成，6.4 節：連續特徵相對誤差中位數 ≤ 1.3e-5，自我校正準確率不變）。
5. **上板**：設定好時脈（480 MHz）和 I/D-cache，量 `rf_predict` 和特徵擷取的 cycle 數，並在板上確認 `g_pred`。
6. ~~**MCU 上的 RF 訓練**~~（已完成，6.2 節：C 版 CART，max_features = 8（sklearn 的 sqrt(80)），暫存 5.0 KB，自我校正 −0.33 不顯著）。
7. ~~C 版 t-SNE、整個自我校正迴圈、Cortex-M7 編譯~~（已完成，6.1、6.3、6.5 節）。**剩下的都需要板子**：燒錄 `main_selfcal.c`，
   量 `sc_push`／`sc_end_block`／`fe_push` 的 cycle 數（480 MHz、開 I/D-cache），確認板上的預測和 PC 相同。

---

## 6. 上板前的 C 實作（實測，Docker；PC 驗證＋Cortex-M7 編譯）

推薦設定（100 棵、深度 10、int16、buffer 375 筆 int16、新樹 32 葉、t-SNE 500 次）的自我校正**整條管線都已經用 C 寫好**，
全部是靜態記憶體（沒有 malloc），並在 PC 上逐段和 sklearn／上游程式對照。彙整：`src/analyze_c_impl.py` → `results/c_impl_summary.csv`。
比較對象都是同一設定、同一次 Docker 執行的 sklearn 版（3.7 節，500 次 83.27%）；配對檢定為 seed 平均後 20 人的 Wilcoxon。

| 用 C 取代的部分 | 自我校正 | 增益 | vs sklearn | 較好／較差 | p |
|---|---|---|---|---|---|
| t-SNE（`src/c/tsne.c`），500 次 | 83.23 | +3.55 | −0.04 | 13 / 7 | 0.65 |
| t-SNE，1000 次（對照 sklearn 1000 次 83.44） | 83.59 | +3.91 | +0.16 | 14 / 6 | 0.14 |
| t-SNE＋K-Means（`kmeans.c`） | 83.23 | +3.55 | −0.04 | 13 / 7 | 0.65 |
| 建樹（`rf_train.c`） | 82.94 | +3.26 | −0.33 | 7 / 13 | 0.076 |
| 以上全部（Python 迴圈呼叫） | 83.23 | +3.55 | −0.04 | 9 / 11 | 0.70 |
| **整個韌體邏輯（`selfcal.c`，端到端）** | **83.04** | **+3.36** | −0.23 | 9 / 11 | 0.20 |
| 上游流程，但特徵改用 C 版（`features.c`） | 83.23 | +3.55 | −0.04 | 8 / 12 | 0.67 |

**沒有一項和 sklearn／上游有顯著差異。** 下面分段說明。

### 6.1 Barnes-Hut t-SNE（`src/c/tsne.c`；`src/check_tsne_c.py` → `results/tsne_c_check.csv`）
- 照 sklearn 1.5 的演算法寫：kNN（k = 31）＋困惑度二分搜尋、自由度 2、early exaggeration 12（前 250 次）、momentum 0.5 → 0.8、gains、
  learning rate auto、octree 用 sklearn 的近似條件（θ = 0.5）。輸入是 buffer 裡的 int16 列（用列指標，不複製），計算用 float32。
  和 sklearn 的差別：對稱化的 P 不轉成 CSR，改成每條 kNN 邊同時作用在兩端（數學上相同）；沒有實作「KL 沒進步就停」（實測從來沒觸發）。
- 20 位受試者的真實 buffer、同一個初始嵌入：精確 KL 500 次 C 0.735／sklearn 0.716，1000 次 0.584／0.596；
  K-Means 偽標籤 C 和 sklearn 的一致率 84%（500 次）／90%（1000 次）。t-SNE 對微小的數值差異很敏感（會收斂到不同的局部解），
  所以逐點不會相同，但接進自我校正之後準確率沒有差異（上表）。
- octree 最多用到 2.1 n 個 cell（當時配置 3 n，沒有溢位），最大深度 18。之後改配 2.5 n，見 7.5 節。
- PC 單執行緒時間（500 次）：C 0.30 s，sklearn 0.90 s。**這是 x86 的時間，不是 MCU 的時間。**

### 6.2 K-Means 與建樹（`src/c/kmeans.c`、`src/c/rf_train.c`；`src/c_train.py`）
- K-Means 照 sklearn 的 Lloyd（給定初始中心、相對 tol、空群重新指派）：自我校正的結果和 sklearn **逐位元相同**。
- 建樹照 sklearn 的 RandomForest 單棵樹：bootstrap、每個節點隨機 8 個特徵、Gini、max_leaf_nodes 時用 best-first 展開；資料直接用 int16。
  **門檻值的位置很重要**：一開始取「右側最小值」，在 60 筆 calibration 上準確率掉了約 12 個百分點；改成和 sklearn 一樣取中點（向上取整，
  使 `x < thr` 在訓練資料上的切法完全不變）之後就和 sklearn 一致（4 位受試者 80.5／80.4、54.7／55.8、83.7／84.5、77.3／77.1%）。
- C 建樹在自我校正裡 −0.33 個百分點（p = 0.076，不顯著）；和 C t-SNE、C K-Means 一起用時 −0.04。

### 6.3 整個自我校正韌體邏輯（`src/c/selfcal.c`；`src/check_selfcal_c.py` → `results/selfcal_c_check.csv`）
- 一位使用者的完整上游迴圈：一次性模型（50 棵剪枝後的預訓練樹＋50 棵 calibration 樹）在 Flash，**每次 calibration 只寫一次 Flash**，
  自我校正期間不寫 Flash；50 個可替換的位置，每個位置用原本的一次性樹（Flash）或新樹（RAM，≤ 32 葉）。
- 每來一筆特徵就 `sc_push()`（預測＋放進 buffer），block 結束時 `sc_end_block()`：用原始的一次性模型重新標記 buffer、類別平衡、
  t-SNE＋K-Means 偽標籤、訓練 20 棵新樹、隨機替換 20 個位置。buffer 的順序和淘汰規則和上游 `buffer_update` 相同，
  但不必把整個 block（48 KB）存在 RAM：串流版和整個 block 一次處理的結果**逐位元相同**。亂數用 C 自己的（xorshift）。
- **更新（2026-10-23，7.1 節）**：發現並修正樹的亂數種子相關的 bug，重跑後 C 韌體邏輯是 **83.22%**、增益 +3.54，
  和 sklearn 差 −0.05（p = 0.90）；下面這一點是修正前的數字，保留作紀錄（`results/selfcal_c_check.csv` 已是修正後的結果）。
- PC 端到端（20 人 × 3 seed）：一次性模型的預測和 Python 的 int16 預測**完全相同**（79.68%）；自我校正 **83.04%**、增益 +3.36，
  和 sklearn 差 −0.23（p = 0.20）。99.5% 的 block 有做 t-SNE 分群，新樹最多 31 個內部節點（32 葉），t-SNE 最多 372 點、792 個 cell。

### 6.4 特徵擷取（`src/c/features.c`；`src/check_features_c.py` → `results/features_c_check.csv`）
- 串流處理：每個樣本 4 個 biquad（SOS，float32，和上游一樣每段錄音從零狀態開始）→ 400 點 ring buffer → 每 200 點算一次 80 個特徵
  （Hamming＋512 點 FFT 算 Welch PSD）。PSD 的縮放在 4 個頻域特徵裡都會約掉，所以不算。
- 全部 20 人的原始資料（每種特徵 537,600 個值）：連續特徵的相對誤差中位數 2.6e-7（WL）到 1.3e-5（偏度）；
  SSC／ZC／MDF／PKF 分別只有 27／245／22／4 個值不同（≤ 0.05%）。
- 用 C 版特徵跑整個自我校正：一次性模型 660 個 block 中 658 個準確率完全相同，自我校正 83.23% vs 83.27%（p = 0.67）。

### 6.5 Cortex-M7 編譯（`src/build_arm_selfcal.py` → `results/arm_selfcal_size.csv`、`arm_selfcal_modules.csv`）
arm-none-eabi-gcc 10.3.1，旗標同第 4 節，`-Os`；`.bss` 放 512 KB AXI SRAM、stack 放 DTCM（`src/c/stm32h743_axi.ld`）。
一次性模型用 `build/d10_n100_i16/rf_model.h`（subject 0）。**以下是 linker 實測，不是估算。**

| 韌體 | Flash（text＋data） | AXI SRAM（.bss） | .data | 最壞 stack | RAM 合計 |
|---|---|---|---|---|---|
| 自我校正（重播 calibration 特徵） | 112.8 KB | 222.2 KB | 104 B | 1.27 KB | **約 223.6 KB** |
| 完整管線（原始 EMG → 特徵 → 推論 → 自我校正） | 181.1 KB | 243.1 KB | 104 B | 1.78 KB | **約 245.0 KB** |

- RAM 的組成（.bss）：自我校正狀態 89.5 KB（buffer 375 × 80 int16 = 58.6 KB、calibration 9.4 KB、RAM 樹 10.6 KB、工作陣列），
  t-SNE 121.8 KB（P 45.4 KB、octree 39.6 KB、近鄰表 22.7 KB、梯度等 17.6 KB），建樹 5.0 KB，K-Means 1.8 KB，特徵擷取 20.3 KB。
  3.5 節的估算是 219 KB（自我校正部分），實測 223.6 KB，相差 2%。
- **更新（2026-10-23）**：one-shot 的樹需要最多 64 片葉，`RFT_MAX_LEAVES` 由 32 改成 64，建樹的工作陣列多約 3 KB；
  同樣兩個版本重新編譯後是 226.7 KB／248.2 KB（`results/arm_selfcal_size.csv`）。正式的路線 B 韌體見 7.4 節。
- Flash 裡的 88 KB 是一次性模型；完整版另含 64 KB 的原始 EMG 範例資料（替代 ADC）、9.6 KB 的 calibration 範例資料，正式版不需要。
- `src/c/main_selfcal.c` 已經用 DWT 包好 `sc_push`、`sc_end_block`、`fe_push` 的 cycle 計數，**板子到了直接燒錄就能量時間**。
  沒有板子不報 cycle 數。
- octree 配置 3 n 個 cell，實測最多 2.11 n，若改配 2.5 n 可再省約 6.6 KB（已在 7.5 節完成）。

### 6.6 跨兩天的 demo 資料（實測，Docker；`results/c_impl_demo.csv`）
JNE 2025 的 demo 錄音（1 位受試者、10 個 block、跨兩天，上游 `demo_replay.py` 的預訓練模型 `model_pretrain.joblib`），10 個 seed：
`selfcal_sweep.py --dataset demo` 和 `check_selfcal_c.py --dataset demo`。

| 設定 | 一次性 | 自我校正（seed 範圍） | 增益 | 第 2 天後段 block 7–9：一次性 → 自我校正 |
|---|---|---|---|---|
| 完整模型（400 棵、不限深度，論文設定） | 82.40 | 89.33（87.33–90.83） | +6.93 | 74.8 → 92.0 |
| 100 棵、深度 10、int16，上游設定（buffer 1500） | 81.93 | 89.55（86.93–91.60） | +7.62 | 75.4 → 91.8 |
| MCU 設定（buffer 375 int16、32 葉、t-SNE 500 次），sklearn | 81.93 | 91.29（89.93–92.47） | +9.36 | 75.4 → 92.8 |
| **MCU 設定，C 韌體邏輯（`selfcal.c`）** | 81.93 | **91.30**（89.67–92.27） | **+9.37** | 75.4 → **92.8** |

- 第 2 天固定模型掉到約 75%，MCU 設定的 C 韌體邏輯把它拉回 93%，**跨日的自我校正增益在記憶體預算內保住了**。
  （修正樹的亂數種子之後重跑的數字；修正前是 90.89%、增益 +8.95、第 2 天後段 92.2%。）
- MCU 設定甚至比完整模型高（91.3 vs 89.3）；可能是較小的 buffer 對第 2 天的變化反應比較快，但**只有 1 位受試者**，不能下結論。
  跨日的效果要靠正式實驗（RQ2，每人兩天）驗證。
- Docker 上完整模型 89.33%，1.5 節的 Windows 結果是 90.02%（3 seed），差異和平台／seed 數一致（1.6 節）。


---

## 7. 韌體：one-shot 上 MCU、指令決策、路線 B（實測，Docker；PC 驗證＋Cortex-M7 編譯，2026-10-23）

板子改成 NUCLEO-H753ZI（和 H743 同一塊 MB1364 板，只多加密模組），**還沒到**。這一節的東西都只有「編譯通過、PC 驗證」。
完整的狀態和待辦見 `results/firmware_report.md`。

### 7.1 one-shot 校正搬上 MCU（`src/c/oneshot.c`；`src/check_oneshot_c.py`）
- MCU 自己做：校正特徵的平均和標準差（同 `pipeline.load_subject`）→ Q5.10 → 把上游 `emg_functions.prune` 移植成 C（Flash 裡的預訓練樹不動，
  剪枝結果是 RAM 裡的位元圖＋排序過的「節點 → 類別」清單）→ 用 `rf_train.c` 長 50 棵新樹（深度 10，葉數上限 64，60 筆資料實際最多 14 片葉）
  → 全部串流寫進 Flash 最後一個 128 KB sector 的 one-shot image（每個位元組只寫一次，PC 上用模擬 Flash 檢查）。
  工作記憶體借用 t-SNE 的工作區（約 39 KB），所以不多佔 RAM。
- **剪枝決策和 Python 逐節點相同：20／20 位受試者**（每人 370–934 個剪枝節點；`results/oneshot_prune_check.csv`）。
  比對時兩邊用同一組 Q5.10 校正資料，Python 端把門檻 T 換成 (T − 0.5)/1024，讓它的 `x <= thr` 等於 MCU 的 `x < T`。
- 端到端（20 人 × 3 seed；`results/oneshot_c_summary.csv`）：one-shot **79.40%** vs sklearn 79.68%（−0.28，p = 0.52）；
  自我校正後 **82.98%** vs 83.27%（−0.29，p = 0.28）。one-shot image 6.1–8.6 KB。
- **找到的 bug**：韌體用同一條 xorshift32 序列的連續輸出當每棵樹的種子，而 xorshift 是線性的，第 k+1 棵樹的亂數等於第 k 棵往後錯一步，
  bootstrap 幾乎一樣、樹高度相關。one-shot 因此低了 0.91 個百分點（p = 0.027）。消融（`src/diag_oneshot.py`，`results/oneshot_ablation_summary.csv`）
  顯示 Q5.10 剪枝、C 建樹各自都 ≤ 0.1 個百分點。改用 splitmix32 打散每棵樹的種子後就沒有差異；同一個 bug 也影響 `selfcal.c` 的新樹，
  修正後第 6 節的韌體邏輯從 83.04% 變成 83.22%，demo 從 90.89% 變成 91.30%。

### 7.2 多數決平滑＋低信心拒絕（`src/c/decision.c`；`src/eval_decision.py`）
- 每個 100 ms 視窗：最高票比例 < τ 就拒絕；連續 k 個被接受的視窗同一類才「確立」，確立時送一次該手勢的指令（Tripod＝夾、Open＝放、
  Power／Pointer＝預設位置 A／B，Lateral、Rest 不送），一直維持同一手勢不會重複送。
- 回放：MCU 韌體（MCU 上 one-shot＋自我校正）跑 20 人 × 3 seed，共 198,000 個視窗（330 分鐘）；C 的決策和 Python 重寫版在三組設定下逐窗相同。
- 自我校正後（`results/decision_sweep.csv`，圖 `results/decision_tradeoff.png`）：

| τ | k | 拒絕的視窗 | 被接受視窗的準確率 | 錯誤指令／分鐘 | 送對指令的試次 |
|---|---|---|---|---|---|
| 0（不平滑） | 1 | 0% | 83.0% | 26.1 | 86.8% |
| 0.5 | 1 | 25.6% | 91.5% | 7.3 | 82.9% |
| 0.6 | 3 | 43.0% | 95.4% | 1.17 | 58.7% |
| 0.7 | 3 | 59.6% | 97.8% | 0.40 | 41.4% |
| 0.8 | 3 | 76.3% | 99.1% | 0.05 | 22.1% |

- 這個資料集每個試次只有 1 秒（10 個視窗），k 越大越難在試次內確立；實際使用時手勢可以維持更久，所以「送對指令的試次」會被低估。
  門檻要用每位受試者第 1 天的資料決定（RQ1／RQ2 的實驗設計），這裡只提供工具和曲線。

### 7.3 路線 B：序列協定與即時迴圈（`src/c/protocol.c`、`src/c/rt.c`、`src/pc/`；`src/check_rt.py`、`src/pc/test_pc_tools.py`）
- 封包：`A5 5A | type | seq | len | payload | CRC-16/CCITT-FALSE`；樣本 int16、0.25 µV/LSB（±8.19 mV），每包 20 幀，32.9 KB/s（921600 baud 的 36%）。
- 解析器：故意損壞的串流（2% 位元翻轉、1% 掉包、2% 插入雜訊、隨機切段，5 組）中，每個完好的封包都依序收到、沒有損壞的封包被接受，C 和 Python 相同。
- 即時迴圈：UART 中斷裡做解析 → 特徵 → z-score → 推論 → 決策 → 指令；主迴圈做 one-shot 建模和自我校正。自我校正期間的視窗只分類不進 buffer；
  換樹時那個位置暫時改用 Flash 的 one-shot 樹，中斷不會讀到寫到一半的樹。
- 回放（原始 EMG → int16 → 封包 → `rt_rx`，校正也在「MCU」上做；`results/rt_summary.csv`）：自我校正若在 block 結束時立刻完成，
  準確率 **82.99%**，和用上游浮點特徵的同一套韌體（82.98%）相同（p = 0.87）；若自我校正跑 20／50 個視窗（2／5 秒），
  那段時間的視窗不進 buffer，準確率 82.46%／82.37%（−0.52，p = 0.006／−0.61，p = 0.040）。
- PC 工具（標準函式庫＋pyserial）：`trigno_bridge.py`（TCU 50040／50041 → CSV → 序列埠，同時記錄 MCU 回傳）、`mcu_logger.py`。
  整合測試：假的 TCU → bridge → TCP → C 的 `rt.c` → 回傳狀態 → CSV，24,000 幀逐筆正確（`results/pc_tools_test.csv`）。
  TCU 的實際協定（參照 pytrigno）和序列埠都要在實驗室電腦上驗證。

### 7.4 交叉編譯（`src/build_arm_selfcal.py` → `results/arm_selfcal_size.csv`、`arm_selfcal_modules.csv`）
arm-none-eabi-gcc 10.3.1，`-Os`，.bss 在 AXI SRAM，stack 在 DTCM，最後一個 Flash sector 保留給 one-shot image。**linker 實測：**

| 韌體 | Flash | .bss | .data | stack（thread＋中斷上界） | RAM 合計 |
|---|---|---|---|---|---|
| 路線 B 正式版（`main_rt.c`：協定、即時迴圈、MCU 上 one-shot、自我校正） | 115.6 KB | 246.4 KB | 108 B | 1,776 + 432 B | **248.7 KB** |
| 基準測試版（`main_selfcal.c` device：重播資料、MCU 上 one-shot） | 194.9 KB | 245.3 KB | 108 B | 2,272 B | 247.6 KB |

- 中斷的 stack：`rt_rx` 由 UART 中斷透過函式指標呼叫、封包處理又是函式指標，呼叫圖接不起來，所以用「`rt_rx` 深度＋`on_packet` 深度＋104 B 例外框架」當上界。
- 正式版的 Flash 裡沒有任何範例資料；約 89 KB 是預訓練的 50 棵樹（`main_rt.o` 的 text 91,037 B，表格在其中）。

### 7.5 硬體層（`src/c/board_h7.c`、`src/c/startup_h7.c`；**只編譯，沒有對照 RM0433／UM2407**）
- CMSIS 標頭檔（使用者同意後下載）：ST `cmsis-device-h7` v1.10.7、ARM `CMSIS_5` 5.9.0，來源、大小、SHA-256 見 `src/c/cmsis/README.md`。
- 480 MHz（HSE bypass 8 MHz、PLL1 M=1 N=120 P=2、VOS0、Flash 4 個等待週期）、I/D cache＋AXI SRAM 的 MPU 區、TIM2 1 MHz 時間戳、
  USART3（PD8／PD9、AF7、921600 baud）接收中斷 → 環形緩衝 → SysTick 1 kHz 交給 `rt_rx`、bank 2 sector 7 的抹除和 256-bit 寫入。
  暫存器名稱來自官方標頭檔（能編譯），**數值沒有對照手冊**（手冊不在授權下載範圍），程式裡每一處都標了 `check:`。
- 含硬體層的路線 B 韌體（`board` 版本，`-Os`，沒有警告）：Flash 117.5 KB、.bss 250.5 KB、stack 1,776 B＋中斷上界 836 B，
  **RAM 合計約 253.2 KB**，離 256 KB 只剩約 2.8 KB（`results/arm_selfcal_size.csv`）。

### 7.5 t-SNE octree 改配 2.5 n（省 6.6 KB）

- `src/c/tsne.h`：`TSNE_CELLS` 從 3 × 375 = 1,125 改成 2.5 × 375 = 937 個 cell。
- 重跑 `check_selfcal_c.py`（20 人 × 3 seed，660 列）和 `--dataset demo`（1 人 × 10 seed，100 列）：one-shot 和自我校正準確率**逐列完全相同**，實際最多用到 787／749 個 cell，沒有溢位（溢位時會合併點，準確率就會變）；`check_oneshot_c.py`、`check_rt.py` 的結果檔沒有變化。
- 每個版本的 .bss 都少 6,768 B，Flash 不變。含硬體層的完整系統（`board`，`-Os`）：**RAM 253.2 → 246.5 KB**，離 256 KB 的餘裕 2.8 → 9.5 KB；路線 B（`rt`）248.7 → 242.1 KB（`results/arm_selfcal_size.csv`）。

### 7.6 t-SNE 的 P 改存 16 位元（省 22.7 KB）

- `src/c/tsne.c`：P 原本存成 float32（375 × 31 條邊 × 4 B = 46.5 KB）。每個點的 31 個條件機率加起來等於 1，所以每個值都在 [0, 1]；
  改成存「條件機率 × 65535」的 uint16，正規化常數 1 / (2 Σ) / 65535 另存一個 float，計算吸引力時再乘回去（絕對誤差 ≤ 7.6e-6）。
  編譯選項 `TSNE_P16`（`tsne.h` 預設 1，韌體用）；`c_tsne.py`（3.7 節 sklearn 對照實驗）指定 `-DTSNE_P16=0`，之前的結果不受影響。
- t-SNE 的工作陣列併成一個結構，`tsne_scratch()` 借出整塊（約 70 KB），MCU 上的 one-shot 需要 39,915 B，仍然夠用。
- PC 驗證（和改之前的 float 版本配對 Wilcoxon，都在 Docker）：

| 檢查 | float32 | uint16 | 差 | p |
|---|---|---|---|---|
| 自我校正韌體（`check_selfcal_c.py`，20 人 × 3 seed） | 83.22% | 83.23% | +0.01 | 0.70 |
| 跨兩天 demo（1 人 × 10 seed） | 91.30% | 91.06% | −0.24 | 0.28 |
| MCU 上 one-shot＋自我校正（`check_oneshot_c.py`） | 82.98% | 83.06% | +0.08 | 0.38 |
| 即時迴圈回放（`check_rt.py`，延遲 0／20／50 視窗） | 82.99／82.46／82.37% | 82.94／82.40／82.54% | −0.05／−0.06／+0.16 | 0.26／0.73／0.26 |

  one-shot 準確率逐列完全相同（one-shot 不用 t-SNE，借工作區也正常）；自我校正只有第一個 block（還沒跑 t-SNE）相同，之後因為 t-SNE
  對微小數值差異敏感而不同，但平均沒有顯著差異。
- RAM（.bss 少 23,252 B）：含硬體層的完整系統 **246.5 → 223.8 KB**（離 256 KB 32.2 KB），路線 B 242.1 → 219.4 KB；Flash 多約 0.1 KB。
- 三個版本的 RAM 與各模組 .bss 整理在 `results/ram_history.csv`（`src/ram_history.py` 從各 commit 的結果檔讀出）。

## 8. 電極轉一格（45°）的模擬（實測，Docker，2026-10-25；`src/shift_sweep.py` → `results/shift_sweep*.csv`）

- 情境：第 1 天照原位置做 one-shot 校正；所有測試 block 都把電極環轉一格（模型的第 c 通道讀到第 c ± 1 個電極的 10 個特徵）。
  假設通道 1–8 依序繞前臂一圈（作者沒有寫明）。保留的 calibration 資料不轉（和裝置上一樣）。
- 設定：作者的 66 人模型＋推薦 MCU 設定（100 棵、深度 10、int16、375 筆 int16 buffer、20 棵 ≤ 32 葉新樹、t-SNE 500 次），20 人 × 11 block × 3 seed。
- 比較：本研究的 t-SNE＋K-Means 偽標籤，和 Campbell 等人（JNER 2024）的 UHC 基準：用目前模型自己的預測當偽標籤，只取最高票比例 ≥ 0.6 的列（少於 10 列就不更新）。

| 轉動 | 固定模型 | t-SNE 自我校正 | 差（p，贏的人數） | UHC | 差（p） | t-SNE − UHC（p） |
|---|---|---|---|---|---|---|
| 0（對照） | 79.68% | 83.27% | +3.59（< 0.001，19／20） | 80.02% | +0.34（0.31） | +3.25（< 0.001） |
| +1 格 | 52.18% | 58.08% | +5.90（< 0.001，18／20） | 52.39% | +0.21（0.84） | +5.69（0.002） |
| −1 格 | 50.09% | 54.36% | +4.28（0.009，16／20） | 49.68% | −0.40（0.29） | +4.68（0.004） |

- 轉 0 格時 t-SNE 版 83.27% 和 `selfcal_sweep` 的參考值相同，程式沒有改到原本的流程。
- 電極轉一格，固定模型掉約 28–30 個百分點；t-SNE 自我校正顯著拉回 4–6 個百分點，但最後幾個 block（8–10）也只有 58.1％／55.8％，
  離沒轉時差很遠。UHC 完全沒有效果（和 Campbell 2024 的結論一致）：轉動後符合門檻的列平均只有約 92 列（t-SNE 版 184–214 列），
  而且是模型自己的錯誤預測，重新訓練只會強化錯誤。
- 解讀：免標籤自我校正能處理小幅的日間變化，但處理不了整圈電極轉一格這麼大的偏移。正式實驗要在皮膚上標記電極位置；
  如果穿戴時可能轉動，需要另外的對策（例如重新做 one-shot、或通道重排對齊），這是待驗證的方向。

---

## 附錄：檔案
| 類別 | 檔案 |
|---|---|
| 程式 | `src/run_upstream.py`、`make_baseline.py`、`compare_paper.py`、`model_stats.py`、`rf_size.py`、`pipeline.py`、`compression_sweep.py`、`selfcal_sweep.py`、`plot_sweep.py`、`export_c.py`、`check_c.py`、`build_arm.py`、`ram_estimate.py`、`verify_platform.py`、`compare_features.py`、`compare_selfcal_platform.py`、`analyze_pseudo.py`、`analyze_leaf_buffer.py`、`tsne_cost.py`、`analyze_tsne_iter.py`、`analyze_tsne_px.py`、`c_tsne.py`、`c_train.py`、`check_tsne_c.py`、`check_selfcal_c.py`、`check_features_c.py`、`build_arm_selfcal.py`、`analyze_c_impl.py`、`check_oneshot_c.py`、`diag_oneshot.py`、`eval_decision.py`、`check_rt.py`、`src/pc/*`、`src/c/*`（`tsne.c`、`kmeans.c`、`rf_train.c`、`selfcal.c`、`features.c`、`oneshot.c`、`decision.c`、`protocol.c`、`rt.c`、`board.h`、`board_stub.c`、`main_selfcal.c`、`main_rt.c`、`stm32h743_axi.ld`） |
| 環境 | `docker/Dockerfile`、`docker/requirements.txt`、`docker/run.sh`、`docker/run_all.sh` |
| 結果 | `results/baseline*.csv`、`paper_comparison.csv`、`model_stats*.csv`、`sweep_*.csv`、`selfcal_sweep*.csv`（`_validation_linux` 是 Docker 的結果）、`c_check.csv`、`arm_size.csv`、`ram_estimate.csv`、`ram_scenarios.csv`、`ram_scenarios_pseudo.csv`、`pseudo_label_summary.csv`、`leaf_buffer_summary.csv`、`tsne_cost.csv`、`tsne_cost_iter.csv`、`tsne_iter_summary.csv`、`tsne_cost_px.csv`、`tsne_px_summary.csv`、`tsne_c_check.csv`、`selfcal_c_check*.csv`、`features_c_check.csv`、`arm_selfcal_size.csv`、`arm_selfcal_modules.csv`、`c_impl_summary.csv`、`c_impl_demo.csv`、`oneshot_*.csv`、`decision_*.csv`、`rt_*.csv`、`pc_tools_test.csv`、`firmware_report.md`、`*.png`、`stage*_summary.md`、`platform_check.md`、`advisor_summary.md`、`logs/`（`logs/linux/` 是 Docker 的紀錄） |
