# 交接：韌體工作（給 VS Code 的 Claude）

寫於 2026-10-23，來自 Claude Desktop 的 session。請先讀 `CLAUDE.md`、`report.md` 第 3.8 節以後和第 6 節，以及 `src/c/selfcal.h`。

## 背景（已經決定的事）

- **板子改成 NUCLEO-H753ZI**，不是 H743ZI2。H743ZI2 已經 NRND，經銷商多半標停產。H753 和 H743 只差加密模組，同一塊 MB1364 板。ST 版主說 H743 的專案可以直接燒到 H753ZI 執行。現有的 `stm32h743_axi.ld` 和 `startup_h743.c` 照用。**板子還沒到**，所有工作都只能在 Docker 裡編譯和在 PC 上驗證。
- **目前韌體的狀態**
  - 已完成，並在 PC 上和 Python 驗證過：特徵擷取（`features.c`）、推論（`rf_predict.c`）、自我校正（`selfcal.c` + `tsne.c` + `kmeans.c` + `rf_train.c`）。
  - **one-shot 模型還是在 PC 上做的**：`export_c.py` 剪枝預訓練樹、附加 50 棵新樹，再編進 `rf_model.h`。
  - `startup_h743.c` 沒有設定時脈（64 MHz HSI）、沒開 cache，也沒有 UART。
- **系統架構**：
  - **MCU 上**：EMG 輸入 → 濾波＋80 特徵 → z-score（用校正資料的平均和標準差）→ Q5.10 → RF 推論 → 多數決平滑＋低信心拒絕 → UART 指令碼。另外背景執行自我校正。
  - **PC 上**：只做三件事：路線 B 時轉送 Trigno 原始取樣、Kortex 橋接（把指令轉給 Kinova）、紀錄時間戳。
- **EMG 輸入兩條路線**
  - **路線 B（先做）**：實驗室電腦（Windows、**不能上網**）上的 Trigno Control Utility（TCU）用 TCP 提供資料：50040 是指令、50041 是 EMG，預設 2000 Hz、單位伏特。Python 讀出來後，用 UART 轉給 STM32。
  - **路線 A（之後做）**：基地台的 68 針類比輸出，±5 V，EMG 增益 909，延遲約 48 ms（舊版手冊）。經分壓 0.3 倍＋1.65 V（偏壓取 VREF+）和運算放大器緩衝後，接 STM32 ADC。
  - 實驗室的 MVC 錄音最大 1.85 mV，換算到類比輸出約 1.7 V，確定在 ±5 V 以內。
- **手勢**（標籤 0–5）：Power、Lateral、Tripod、Pointer、Open、Rest。Rest 是標籤 5，已用 20 人的 RMS 驗證。建議的指令對照（依 `results/confusion_oneshot_N100_d10_int16.csv`）：Tripod＝夾、Open＝放、Power／Pointer＝預設位置 A／B，Lateral 和 Rest＝不送指令。

## 規則（沿用 CLAUDE.md）

- 所有數字都要來自實際執行的結果。跑不出來就說跑不出來，不要把估計值寫成結果。
- 程式放 `src/`，結果放 `results/`，每支腳本都要能單獨重跑。都在 Docker（`rf-emg`）裡跑。同一組比較的數字只能來自同一個平台。
- 某一項卡住（例如驗證不過、需要使用者決定、需要下載但沒有授權）時：在報告裡寫清楚卡在哪裡、試過什麼，**不要硬做、不要把沒驗證過的東西寫成完成**，然後繼續做下一項。
- 不要做需要使用者確認的不可逆操作：不 push、不刪檔案、不改 `slides/`、不動 `external/`。
- **全部做完（或做到不能再做）後**，寫一份繁體中文報告 `results/firmware_report.md`：
  1. 每一項的狀態：完成／部分完成／沒做，以及原因。
  2. 每一個數字都附來源檔案（`results/` 下的 CSV 或 log）和 git commit。
  3. 哪些只是「編譯通過、PC 驗證」，哪些等板子到了要驗證。
  4. 遇到的問題、做過的決定和理由。
  5. 使用者起床後需要決定或處理的事。

  最後把這份報告也 commit。
- **注意**：`slides/build3.py`、`build5–10.py` 在工作目錄裡是「已刪除但未 commit」的狀態。這不是本次工作造成的，**不要動它們**，commit 時只 `git add` 你自己新增或修改的檔案。
- 板子沒到之前，任何「上板」的結論都不能寫成已驗證，只能寫「編譯通過、PC 驗證」。

## 要做的事（依順序，每項做完就 commit，接著做下一項）

### 1. one-shot 校正搬上 MCU（最重要、工作量最大）
目標：新使用者每個手勢做 1 次校正，MCU 自己就能做出 one-shot 模型，不需要 PC 重新燒錄。這也是 RQ1 的前提。
- **標準化**：從校正資料的特徵算每個特徵的平均和標準差（同 `pipeline.load_subject`），之後所有特徵都先做 z-score 再量化成 Q5.10。
- **剪枝**：把 `emg_functions.prune` 移植成 C。
  - 演算法：對每棵預訓練樹，把校正樣本送進去；從最深的葉往上看，如果把父節點改成葉節點（標籤取樣本的眾數）能提高校正樣本的準確率，就剪掉。要注意 `statistics.mode` 平手時的規則。
  - 預訓練樹（深度截到 10，取前 50 棵）放在 Flash 是唯讀的，剪枝結果用 RAM 裡的覆寫表表示，例如「這個節點現在是葉、類別是 c」，不要複製整棵樹。
- **附加 50 棵新樹**：用 `rf_train.c`，深度 10。one-shot 的新樹沒有葉數上限，60 筆資料最多約 60 片葉，要確認 `RFT_MAX_LEAVES`／`RFT_NMAX` 夠用，或者另外定義 one-shot 用的上限。
- **驗證**（比照 `check_selfcal_c.py`、`c_train.py`、`analyze_c_impl.py` 的做法）：
  - 剪枝：給 Python 和 C 一模一樣的 Q5.10 輸入，剪枝決策要逐節點相同。
  - 整體：20 人 × 11 個 block × 多個 seed，C 版 one-shot（加上自我校正）的準確率和 sklearn 版比較，做配對 Wilcoxon 檢定。新樹因為 RNG 不同不會逐位元相同，這是預期的。
  - 結果寫到 `results/`。
- **記憶體**：用 `build_arm_selfcal.py` 的方式交叉編譯，量 Flash 和 RAM，確認總 RAM 還在 256 KB 預算內（目前完整管線 245.0 KB）。
- **寫入 Flash**：這部分需要硬體層，先定義好介面：「把 one-shot 模型寫進 Flash 的某個 sector」。實作留到第 5 項。

### 2. 多數決平滑＋低信心拒絕
- 讓推論函式回傳票數，不要只回傳類別。
- **規則**：最高票比例 ≥ 門檻 τ，而且連續 k 個視窗都是同一個類別，才送出指令。Rest 和 Lateral 不送指令。
- **PC 上回放評估**：用現有的 20 人資料，掃描 τ 和 k，畫出「拒絕率 vs 被接受視窗的準確率」，以及「錯誤指令數／分鐘」（視窗 100 ms 一個）。結果寫到 `results/`。
- 門檻最後要用第 1 天的資料決定，這裡先提供工具和曲線。

### 3. 路線 B 的串流協定與即時流程（可攜 C＋PC 端 Python）
- **PC → MCU 封包**：同步碼、序號、8 通道一組取樣（int16，比例係數要寫清楚，或用 float32）、CRC。資料量 8 × 2000 Hz × 2 B = 32 KB/s，用 921600 baud。
- **MCU → PC 指令封包**：同步碼、序號、指令碼、票數比例、MCU 時間戳（之後用來量延遲）。
- **MCU 端解析**：用可攜的 C 寫狀態機，在 PC 上用錄好的資料回放測試，包括錯誤封包和掉封包的情況。
- **即時主迴圈**（可攜）：環形 buffer 400 點；每 200 點（100 ms）做一次特徵 → z-score → 量化 → 推論 → 平滑 → 輸出。說明自我校正在什麼時機、怎麼在背景跑，不能卡住即時推論。
- **PC 端 Python**（只用標準函式庫＋pyserial，要能離線安裝）：連 TCU 的 50040／50041 讀 EMG、存 CSV、轉送到序列埠；另外一支讀 MCU 的指令並存 CSV。TCU 的實際封包格式要參考 pytrigno 或 TCU 文件，並標註「待在實驗室電腦上驗證」。

### 4. 交叉編譯整合、量 Flash／RAM、更新 report.md

### 5. 硬體層（只有使用者在對話裡明確同意下載時才做）
需要 ST 官方的 CMSIS 標頭檔：ST 的 `cmsis_device_h7`（stm32h753xx.h、system_stm32h7xx.c）和 ARM 的 CMSIS core（core_cm7.h）。**只有使用者在給你的指令裡明確同意，才從這兩個官方 GitHub repo 下載**，並在報告裡記下檔名、來源網址、版本（tag 或 commit）和大小。沒有同意就跳過這一項，在報告裡註明。
- **480 MHz 時脈**：可能的設定是 Nucleo 由 ST-LINK MCO 提供 HSE bypass 8 MHz、PLL1 M=1 N=120 P=2、VOS0、Flash 等待週期，**一定要對照 RM0433 和 UM2407 確認**，不要憑印象。
- I/D cache 和 MPU（AXI SRAM）。
- USART3 虛擬序列埠：可能是 PD8/PD9、AF7，要用 UM2407 確認。
- 計時器觸發 ADC＋DMA（路線 A），Flash 寫入（one-shot 模型）。
- 全部都只能編譯，等板子到了才能驗證。

## 做完後
更新 `report.md`；`CLAUDE.md` 如果有新的規則也一併更新。寫好 `results/firmware_report.md` 並 commit。這份 HANDOFF 檔不要刪，也不要 commit，留給使用者決定。
