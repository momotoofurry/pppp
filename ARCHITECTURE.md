# 目前的系統架構（2026-10-27，韌體 v2）

碩論：在 STM32H7（NUCLEO-H753ZI，Cortex-M7）上、RAM 256 KB 以內執行免標籤的自我校正隨機森林肌電控制，用 Kinova Gen3 的離散指令任務驗證。
所有數字都來自 `results/`（PC 模擬、linker 實測，或板子實測：第 18 節）。細節見 `report.md`（括號內是節號）。

## 1. 整體資料流

```
 Delsys Trigno（8 通道、2 kHz，固定在前臂束帶上）
        │  路線 B（現在）：Trigno Control Utility → TCP 50041 → PC 轉送原始樣本 → UART
        │  路線 A（之後）：類比輸出 → 分壓 0.3× + 1.65 V → STM32 ADC
        ▼
 ┌──────────────────────── STM32H7（韌體 v2）────────────────────────┐
 │ 即時（每 100 ms 一個視窗，中斷內，不做長工作）                       │
 │   features.c   帶通 10–500 Hz、200 ms 視窗、80 個特徵                │
 │   adapt.c      ad_map：依開機對齊的結果重排 8 個通道                  │
 │                ad_normalize：用「目前的」z-score 統計值 → int16 Q5.10 │
 │   selfcal.c    100 棵樹多數決（50 棵預訓練剪枝＋50 個可換的位置）       │
 │   decision.c   最高票比例 < τ 拒絕；連續 k 個視窗同一類別才送指令       │
 │   adapt.c      ad_observe：把這個視窗加到它預測類別的統計值             │
 │ 背景（main loop，每 300 個視窗一個 block）                            │
 │   selfcal.c    偽標籤（K-Means，80 維，不做 t-SNE）→ 訓練 20 棵新樹替換 │
 │   adapt.c      ad_end_block：類別平衡更新 z-score（a = 0.3）           │
 └──────────────────────────────────────────────────────────────────────┘
        │  UART：指令碼（Tripod＝夾、Open＝放、Power／Pointer＝預設位置 A／B；Lateral、Rest 不送）
        ▼
 PC 橋接（Python＋Kortex API，只轉送、記時間戳）→ Kinova Gen3（或同一組指令的抓放遊戲）
```

## 2. 使用流程

| 階段 | 使用者做什麼 | MCU 做什麼 | 控制指令 |
|---|---|---|---|
| 第 1 天：one-shot 校正 | 6 個手勢各做 1 次（約 60 個視窗） | 算 z-score 統計值、用校正資料剪枝 50 棵預訓練樹、訓練 50 棵新樹，寫進 Flash 一次（`oneshot.c`）；記下校正資料的通道輪廓（`ad_init`） | `RT_CAL_START`／`RT_CAL_END`／`RT_CALIBRATE` |
| 之後每次戴上：開機對齊 | 隨意做幾個動作（一段時間） | 比對 8 個通道的訊號大小輪廓和第 1 天，估計束帶整圈轉了幾格（−3～4），之後每個視窗都先重排通道 | `RT_ALIGN_START`／`RT_ALIGN_END` |
| 使用中 | 用手勢控制 | 即時分類與決策；每 300 個視窗自我校正一次並更新 z-score | — |

配戴要求：束帶上做對齊記號，偏移壓在 ¼ 格（約 0.7 cm）以內；整格的轉動由開機對齊處理（8.1）。

## 3. 演算法設定

| 步驟 | 設定 | 依據 |
|---|---|---|
| 特徵 | 10–500 Hz 4 階 Butterworth；200 ms 視窗、100 ms 步長；每通道 RMS、WL、SSC、ZC、MAV、偏態、VCF、MDF、MNF、PKF | 上游程式（第 1 節） |
| 預訓練 | 作者的 66 人模型，截到深度 10，前 50 棵放 Flash | 壓縮實驗（第 2 節） |
| 模型 | 100 棵樹、深度 10、門檻 int16 Q5.10 | int16 損失 ≤ 0.02 個百分點 |
| 自我校正 buffer | 375 筆 int16 | 第 3 節；不做 t-SNE 時更大反而更差（11.1） |
| 偽標籤 | 用原始 one-shot 模型重新標記 → 類別平衡取樣 → K-Means（80 維，以類別中心初始化） | 不做 t-SNE 和 t-SNE 無顯著差異（第 11 節） |
| 新樹 | 每 block 20 棵、深度 10、≤ 32 葉，替換附加樹 | 第 3 節 |
| z-score 更新 | 依預測類別分組（每類 ≥ 5 個視窗、≥ 2 類），6 類等權合併，a = 0.3 | 休息佔一半也有效（10.1） |
| 開機對齊 | log RMS／MAV／WL 的通道輪廓，8 種整數轉法取相關最高 | 整格轉動 20／20 估對（8.1） |
| 決策 | 預設 τ 0.6、k 3（v2：有效準確率 73.6%、錯誤指令 1.14／分）；正式值依任務選 | `eval_decision.py`（7.2）、`decision_v2.py`（15） |

## 4. 韌體模組（`src/c/`）與記憶體

Cortex-M7 交叉編譯、含 UART 硬體層（`board2`，-Os，linker 實測，`results/arm_selfcal_size.csv`、`arm_selfcal_modules.csv`）：

| 模組 | 功能 | .bss |
|---|---|---|
| `selfcal.c` | 推論、375 筆 buffer、偽標籤、換樹、校正資料、RAM 樹 | 88.2 KB |
| `oneshot.c` | 裝置上的 one-shot 校正（剪枝、建樹、寫 Flash）的工作區 | 40.0 KB |
| `features.c` | 串流濾波與特徵（含 FFT 與 ring buffer） | 20.3 KB |
| `rf_train.c` | 建樹（one-shot 與自我校正共用） | 6.5 KB |
| `kmeans.c` | K-Means（80 維與 3 維版） | 5.2 KB |
| `adapt.c` | 開機對齊、通道重排、類別平衡 z-score 更新 | 5.0 KB |
| `board_h7.c`、`rt.c`、`protocol.c`、`decision.c` | 硬體層、即時迴圈、序列協定、決策 | 5.5 KB |
| **合計 RAM**（.bss 170.7 KB＋.data＋最深 stack 2.4 KB） | | **175.9 KB**（預算 256 KB，餘裕 80.1 KB） |
| Flash | 含 88 KB 模型 | 111.1 KB |

RAM 的變化（`results/ram_history.csv`）：253.2 KB（加上硬體層）→ 246.5（octree 2.5n）→ 223.8（P 存 16 位元）→ **175.9（v2：不做 t-SNE＋adapt.c）**。
舊版（有 t-SNE、沒有輸入調整）仍可用 `-DSC_EMBED=1 -DRT_ADAPT=0` 編出。

## 5. 目前的準確率（PC 模擬，20 人 arm_position，每人 11 個 block × 3 seed）

| 情況 | 固定模型（只 one-shot） | 只自我校正 | 韌體 v2（自我校正＋z-score 更新） |
|---|---|---|---|
| 電極沒偏移 | 79.68% | 83.21% | **83.87%**（C 版，12） |
| 偏 ½ 格（最難的情況） | 67.70% | 71.17% | **74.74%**（C 版，12） |
| 整圈轉 1 格（有開機對齊） | 79.68% | 83.20% | 83.87% |
| 整圈轉 1 格（沒有對齊） | 45.90% | 49.99% | — |
| 對照：高信心自我訓練 UHC，轉 1 格 | | 43.74%（比固定模型差） | |

- 跨兩天 demo（作者另一份資料，只有 1 人）：固定模型第 2 天後段 75.4%，t-SNE 版自我校正拉回 92.4%（6.6）；v2 的 C 版還沒在這份資料上跑。
- 通道：8 個通道的環狀順序是 1-2-3-4-5-6-7-8（9）；6 通道（拿掉 4、8）和 8 通道無顯著差異，但有選擇偏差，正式實驗仍用 8 通道。

## 6. 驗證狀態

| 部分 | 狀態 |
|---|---|
| 特徵擷取、one-shot、自我校正、決策、序列協定（C） | PC 上和 Python 逐列或統計對照（6.x、7.x、12） |
| 韌體 v2（不做 t-SNE＋adapt.c） | PC 上 C vs Python：轉法 60／60 相同、準確率差 ≤ 0.21（p ≥ 0.058） |
| 即時迴圈 `rt.c` 串流回放 | 板子上實測（report 19）：PC 即時串流 1 人 2 個 block，和 PC 版逐視窗 100% 相同、端到端延遲中位 6.7 ms |
| 實驗室電腦的轉送程式 | `lab_kit/`：`TrignoBridge.exe`（不用安裝任何東西）check／run／replay；接模擬 TCU 測過（88.00%），replay 接板子測過（88.00%／86.67%）；真的 TCU、板子＋Trigno 的 run 還沒測 |
| 硬體層 `board_h7.c` | 只編譯，還沒對照 RM0433／UM2407，也沒上板 |
| MCU 上的時間、功耗 | 板子實測（report 18）：480 MHz＋I/D-cache 時每個 100 ms 視窗 2.75 ms（2.8%）、自我校正一次 0.125 s（最大 0.15 s）、one-shot＋寫 Flash 1.03 s；64 MHz 無快取 46.0 ms／1.65 s／2.0 s；功耗未量 |

## 7. 還沒做的事

1. 上板：時間（report 18：480 MHz＋快取，每個視窗 2.75 ms）、和 PC 逐位比對、路線 B 串流（report 19）都已做；還要功耗（量法 19.1，要電流表）、用 Trigno 實際資料跑（RQ3）。
2. v2 的即時迴圈串流回放已在板子上做（report 19）；還缺 PC 端送 `RT_ALIGN_START`／`RT_ALIGN_END`（開機對齊）的工具，回放裡也還沒測開機對齊。
3. 休息佔多數時整條流程（buffer 偽標籤會不會偏向 Rest）的模擬。
4. 決策模組：在 v2 上已做 τ × 平滑規則的取捨曲線（report 第 15 節，多數決變體沒有比較好）；要在先導實驗依任務能容忍的誤觸發率選定 τ、k。
5. 用獨立資料（PhysioNet 86 人或先導資料）確認通道結論；先導實驗時用訊號比對論文通道的位置（第 9 節）。
6. IRB；Kinova 任務與抓放遊戲；比較組（固定模型、不校正的預訓練模型、PCA 對齊）。PCA 對齊 [8] 已在 arm_position 上比過（report 第 17 節：v2 每種偏移都較好，對逐 block 版 +3.6～+32.9），先導資料上還要再跑。

## 8. 主要檔案

| 類別 | 檔案 |
|---|---|
| 韌體 | `src/c/`：`features.c`、`adapt.c`、`selfcal.c`、`kmeans.c`、`rf_train.c`、`oneshot.c`、`decision.c`、`protocol.c`、`rt.c`、`board_h7.c`、`main_rt.c` |
| 編譯與 RAM | `src/build_arm_selfcal.py` → `results/arm_selfcal_size.csv`；`src/ram_history.py` → `results/ram_history.csv` |
| C 對照 Python | `src/check_adapt_c.py`（v2）、`check_selfcal_c.py`、`check_oneshot_c.py`、`check_rt.py`、`check_features_c.py`（舊版） |
| 實驗 | `src/shift_sweep.py`（電極轉動、開機對齊）、`zscore_sweep.py`（z-score 更新）、`embed_sweep.py`（t-SNE／LDA／不嵌入、buffer 大小）、`aug_sweep.py`（校正資料轉動增強，不採用，第 13 節）、`pool_sweep.py`（從 100／200 棵挑 50 棵，不採用，第 14 節）、`decision_v2.py`（決策 τ × 平滑規則，第 15 節）、`filt_sweep.py`（偽標籤篩選，不採用，第 16 節）、`pca_baseline.py`（比較組 [8] PCA 對齊，第 17 節）、`channel_sweep.py`、`channel_order.py` |
| 紀錄 | `report.md`；Notion「碩論實驗紀錄」（韌體修改紀錄、設計決定、文獻追蹤） |
