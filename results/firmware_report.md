# 韌體工作報告（2026-10-23，依 HANDOFF_firmware.md 第 1–5 項）

板子是 NUCLEO-H753ZI，**還沒到**。所有程式都在 Docker（`rf-emg`）裡編譯、在 PC 上驗證。
**這份報告裡沒有任何「上板驗證」的結論**：MCU 上的時間、預測正確性、時脈、UART、Flash 寫入，都還沒在硬體上跑過。

## 1. 每一項的狀態

| 項目 | 狀態 | commit | 一句話 |
|---|---|---|---|
| 1. one-shot 校正搬上 MCU | **完成**（PC 驗證＋編譯）；Flash 寫入的硬體實作在第 5 項，只編譯 | `6302198` | 剪枝和 Python 逐節點相同（20/20 人）；準確率和 sklearn 無顯著差異；修正了一個樹種子的 bug |
| 2. 多數決平滑＋低信心拒絕 | **完成**（工具和曲線） | `8e91313` | `decision.c`；回放 198,000 個視窗；門檻要用第 1 天的資料決定 |
| 3. 路線 B 串流協定與即時流程 | **大致完成**：C 端和 PC 端都寫好並在 PC 上互測；**TCU 的實際協定和序列埠沒有驗證** | `6386864` | 封包解析在損壞串流下零錯收；即時迴圈回放和浮點版準確率相同 |
| 4. 交叉編譯整合、量 Flash／RAM、更新 report.md | **完成** | `e38957f` | 路線 B 正式韌體 RAM 248.7 KB、Flash 115.6 KB |
| 5. 硬體層 | **部分完成**：時脈、cache／MPU、計時器、USART3、Flash 抹除／寫入已寫好並**只編譯通過**；**沒有對照 RM0433／UM2407**；**路線 A 的計時器觸發 ADC＋DMA 沒有做** | `e6b1bcd` | 含硬體層的韌體 RAM 253.2 KB（餘裕約 2.8 KB） |
| 報告、report.md 第 7 節、CLAUDE.md | 完成 | 本報告的 commit | |

`HANDOFF_firmware.md` 沒有 commit（照指示留給使用者）；`slides/` 裡已刪除但未 commit 的檔案沒有動過，每次都只 `git add` 自己的檔案。

## 2. 數字和來源

| 數字 | 值 | 來源檔案 | commit |
|---|---|---|---|
| 剪枝決策和 Python 相同的受試者 | 20 / 20（每人剪 370–934 個節點） | `results/oneshot_prune_check.csv` | `6302198` |
| MCU 上 one-shot 的準確率 vs sklearn | 79.40% vs 79.68%（−0.28，7 人較好／13 人較差，p = 0.52） | `results/oneshot_c_summary.csv` | `6302198` |
| 接著自我校正後 vs sklearn | 82.98% vs 83.27%（−0.29，p = 0.28） | `results/oneshot_c_summary.csv` | `6302198` |
| one-shot image 大小 | 6,227–8,787 B（平均 7,269 B） | `results/oneshot_c_check.csv` | `6302198` |
| 修 bug 前 MCU 上 one-shot | 78.77%（−0.91，p = 0.027） | `results/logs/oneshot_c_check.log` 的第一次執行（commit 訊息有紀錄；檔案已被修正後的結果覆蓋） | `6302198` |
| 消融：Q5.10 剪枝／C 建樹各自的影響 | −0.006／−0.092 個百分點（都不顯著） | `results/oneshot_ablation_summary.csv` | `6302198` |
| 修 bug 後 C 自我校正韌體邏輯（PC 建 one-shot） | 83.22%（sklearn 83.27%，p = 0.90；修正前 83.04%） | `results/c_impl_summary.csv` | `6302198` |
| 修 bug 後跨兩天 demo（1 人 × 10 seed） | 91.30%，增益 +9.37，第 2 天後段 75.4 → 92.8%（修正前 90.89%） | `results/c_impl_demo.csv` | `6302198` |
| 決策：C 和 Python 重寫版逐窗相同 | 3 / 3 組設定，198,000 個視窗 | `results/decision_check.csv` | `8e91313` |
| 決策：不平滑 | 錯誤指令 26.1／分鐘，送對指令的試次 86.8% | `results/decision_sweep.csv` | `8e91313` |
| 決策：τ = 0.6、k = 3 | 拒絕 43.0%，被接受視窗 95.4%，錯誤指令 1.17／分鐘，送對 58.7% | `results/decision_sweep.csv` | `8e91313` |
| 決策：τ = 0.8、k = 3 | 拒絕 76.3%，99.1%，0.05／分鐘，22.1% | `results/decision_sweep.csv` | `8e91313` |
| 封包解析：損壞串流（5 組）中完好封包全部依序收到、損壞的全部擋下 | C 5/5、Python 5/5 | `results/rt_parser_check.csv` | `6386864` |
| 即時迴圈回放（自我校正立即完成） | 82.99% vs 浮點特徵 82.98%（p = 0.87） | `results/rt_summary.csv` | `6386864` |
| 自我校正跑 20 / 50 個視窗時，那段視窗不進 buffer | 82.46%（p = 0.006）／82.37%（p = 0.040） | `results/rt_summary.csv` | `6386864` |
| PC 工具整合測試（假 TCU → bridge → C 即時迴圈） | 24,000 幀逐筆相同，0 截斷，0 掉包，狀態封包回傳 | `results/pc_tools_test.csv` | `6386864` |
| 路線 B 正式韌體（`main_rt.c`，board stub） | Flash 115.6 KB，.bss 252,352 B，stack 1,776 + 432 B，RAM 248.7 KB | `results/arm_selfcal_size.csv`（variant rt，-Os） | `e38957f` |
| 基準測試韌體（MCU 上 one-shot＋重播資料） | Flash 194.9 KB，RAM 247.6 KB | 同上（variant device） | `6302198`、`e38957f` |
| 含硬體層（`board_h7.c`） | Flash 117.5 KB，.bss 256,496 B，stack 1,776 + 836 B，RAM 253.2 KB | 同上（variant board） | `e6b1bcd` |

所有實驗都是 Docker（Linux）上的結果，比較的對照組也都是 Docker 上的結果。

## 3. 只是「編譯通過、PC 驗證」的東西，以及板子到了要驗證什麼

**PC 驗證**（C 程式透過 ctypes 在 x86 上跑，和 Python 比對）：剪枝、one-shot 建模、Flash image 的格式（模擬 Flash）、決策、封包解析、即時迴圈、PC 工具。
**只編譯**（arm-none-eabi-gcc 10.3.1，沒有執行過）：所有 Cortex-M7 韌體，特別是 `board_h7.c`。

板子到了要做的事（依序）：
1. 時脈：確認真的跑在 480 MHz（例如用 MCO 輸出或 TIM2 對照 PC 時間），VOS0／overdrive、Flash 等待週期要先對照 RM0433 再上電。
2. UART：USART3 PD8／PD9 是不是 ST-LINK 的虛擬序列埠、921600 baud 是否穩定（`board_h7.c` 的 `check:` 註記）。
3. Flash：抹除 bank 2 sector 7、寫入 one-shot image，讀回和 PC 模擬的 image 逐位元組比對。
4. 燒 `main_selfcal.c`（selfcal／device 版本）量 `sc_push`、`sc_end_block`、`fe_push`、`os_calibrate` 的 cycle 數，確認板上的預測和 PC 相同。
5. 燒 `main_rt.c`（board 版本），PC 用 `src/pc/trigno_bridge.py` 轉送錄好的資料，量端到端延遲（PK_COMMAND 裡有 MCU 時間戳）。
6. 實驗室電腦：用真的 TCU 確認 50040／50041 的協定（版本字串、需要的指令、16 通道 float32、取樣率）、pyserial 離線安裝。

## 4. 遇到的問題、決定和理由

- **樹的亂數種子 bug（已修）**：韌體用同一條 xorshift32 序列的連續輸出當每棵樹的種子。xorshift 是線性的，所以第 k+1 棵樹的亂數序列就是第 k 棵往後錯開一步，
  bootstrap 幾乎相同，樹高度相關。MCU 上的 one-shot 因此低了 0.91 個百分點（p = 0.027）；消融實驗排除了 Q5.10 和 C 建樹本身。
  修法：在韌體呼叫端用 splitmix32 打散每棵樹的種子（`selfcal.c`、`oneshot.c`），`rf_train.c` 不改，所以 `c_train.py` 之前的結果仍可重現。
  `selfcal.c` 也有同樣的問題，所以 report 第 6 節的韌體數字已重跑、更新（舊數字在 report 裡註明保留）。**簡報 v8／v12 裡的舊數字沒有改**（規則：不動 `slides/`）。
- **剪枝的比對方式**：上游用 `x <= thr` 和浮點門檻，MCU 用 `x < T`（Q5.10）。為了逐節點比對，Python 端把門檻換成 (T − 0.5)/1024，兩邊的比較在 Q5.10 格點上完全等價。
  實際準確率則和原本的浮點 sklearn 流程比。
- **one-shot 的記憶體**：剪枝結果不複製樹，只存位元圖＋排序清單；建模時的工作記憶體借用 t-SNE 的工作區（校正時 t-SNE 不會跑），所以 one-shot 只多 4 B 的靜態 RAM。
  one-shot 的樹需要最多 64 片葉，`RFT_MAX_LEAVES` 從 32 改成 64（多約 3 KB）。
- **Flash image 的寫法**：串流寫入、每個位元組只寫一次、標頭最後寫（沒有標頭的 image 會被忽略），配合 STM32H7 每個 Flash word（32 B）只能寫一次的限制；PC 的模擬 Flash 會檢查重複寫入。
  保留 Flash 最後一個 128 KB sector（bank 2 sector 7，0x081E0000）給 image。
- **即時迴圈的兩個執行情境**：UART 中斷 → 環形緩衝 → SysTick 交給 `rt_rx`（解析、特徵、推論、決策、送指令）；主迴圈跑 one-shot 建模和自我校正。
  自我校正期間的視窗只分類、不進 buffer（避免和 t-SNE 同時讀寫 buffer），換樹時那個位置暫時改用 Flash 的 one-shot 樹，中斷不會讀到寫到一半的樹。
  代價是 buffer 少了那段時間的資料：回放顯示 20／50 個視窗會損失約 0.5–0.6 個百分點（顯著）。
- **stack 的上界**：`rt_rx`、封包處理、SysTick 交給 `rt_rx` 都是透過函式指標呼叫，`-fcallgraph-info` 的呼叫圖接不起來，所以分別算再相加（加上例外框架）當上界。
- **樣本格式**：int16、0.25 µV/LSB（±8.19 mV），實驗室最大的 MVC 是 1.85 mV；比 float32 少一半頻寬（32.9 KB/s，921600 baud 的 36%）。回放證明這個量化不影響準確率。
- **決策的語意**：同一個手勢一直維持只送一次指令，要等另一個類別（含 Rest）確立後才會再送；被拒絕的視窗會打斷連續計數。
- **硬體層數值沒有對照手冊**：RM0433／UM2407 不在授權下載範圍。暫存器名稱都來自官方標頭檔（能編譯），數值是這顆晶片常見的設定，程式裡每一處都標了 `check:`。
- **TCU 協定**：照 pytrigno 的做法寫（50040 指令以 `\r\n\r\n` 結尾、50041 為 16 通道 float32），沒辦法在 Docker 裡驗證，已在 `src/pc/README.md` 標「待在實驗室電腦上驗證」。
- Docker image 沒有 pyserial，也沒有中文字型：沒有改 image；PC 工具測試用 TCP 代替序列埠，`results/decision_tradeoff.png` 的文字用英文。
- `STMicroelectronics/cmsis_device_h7` 在 GitHub 上已改名為 `cmsis-device-h7`（自動轉址，同一個 repository id），從新名稱下載。CMSIS 5.9.0 的 `core_cm7.h` 需要 `cachel1_armv7.h`，一併從同一個 repo 下載。
  來源、版本、大小、SHA-256 見 `src/c/cmsis/README.md`（下方第 6 節也列出）。

## 5. 起床後需要決定或處理的事

1. **自我校正期間的視窗要不要排隊**：目前不進 buffer，損失約 0.5 個百分點（20 個視窗時 p = 0.006）。加一個待處理列的 FIFO（每列 160 B，20 列約 3.2 KB）可以避免，
   但含硬體層的韌體 RAM 已經 253.2 KB。如果要加，建議同時把 t-SNE 的 octree 從 3n 降到 2.5n 個 cell（實測最多 2.11n，可省約 6.6 KB）。
2. **RAM 餘裕只剩約 2.8 KB**（含硬體層）：要不要先把 octree 降到 2.5n、或把 UART 環形緩衝從 4 KB 降到 2 KB，換一點餘裕。
3. **τ 和 k**：工具和曲線已經有了（`results/decision_sweep.csv`、`decision_tradeoff.png`），要用每位受試者第 1 天的資料決定。`main_rt.c` 目前的預設 τ = 0.6、k = 3 只是佔位。
   這份資料每個試次只有 1 秒，所以「送對指令的試次」會被低估，實際實驗要用較長的維持時間重新評估。
4. **即時模式的 warmup**：`main_rt.c` 在每次串流重置後跳過 2 個視窗（200 ms），上游的離線資料是每 2 秒的試次跳過 9 個。實際要多少，看即時實驗的串流是否連續。
5. **簡報**：report 第 6 節有幾個數字因為種子 bug 修正而改了（韌體 83.04 → 83.22%、demo 90.89 → 91.30%），簡報 v8／v12 可能還用舊數字，要不要更新由你決定。
6. **硬體層**：上電前請對照 RM0433、UM2407 檢查 `board_h7.c` 所有 `check:` 註記（尤其 VOS0／overdrive、Flash 等待週期、HSE bypass 的 solder bridge、PD8／PD9）。
7. **路線 A（ADC＋DMA）沒有做**：需要先定 ADC 通道和分壓電路的腳位；這次沒有足夠資訊，也沒有板子可以測。
8. **Kortex 橋接**：HANDOFF 的架構有提到，但不在第 1–5 項裡，這次沒做。
9. 實驗室電腦要先準備 pyserial 的 wheel 檔（離線安裝）。

## 6. 下載的 CMSIS 檔案（使用者同意後，2026-10-23）

| 檔案 | 網址 | 版本 | 大小（bytes） |
|---|---|---|---|
| stm32h753xx.h | https://raw.githubusercontent.com/STMicroelectronics/cmsis-device-h7/v1.10.7/Include/stm32h753xx.h | v1.10.7（8f922cd） | 2,118,971 |
| stm32h7xx.h | …/cmsis-device-h7/v1.10.7/Include/stm32h7xx.h | v1.10.7 | 11,834 |
| system_stm32h7xx.h | …/cmsis-device-h7/v1.10.7/Include/system_stm32h7xx.h | v1.10.7 | 2,422 |
| system_stm32h7xx.c（只參考，沒有編譯） | …/cmsis-device-h7/v1.10.7/Source/Templates/system_stm32h7xx.c | v1.10.7 | 19,751 |
| LICENSE.md（ST，Apache-2.0） | …/cmsis-device-h7/v1.10.7/LICENSE.md | v1.10.7 | 11,348 |
| core_cm7.h | https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core/Include/core_cm7.h | 5.9.0（2b7495b） | 138,948 |
| cmsis_compiler.h | …/CMSIS_5/5.9.0/CMSIS/Core/Include/cmsis_compiler.h | 5.9.0 | 9,481 |
| cmsis_gcc.h | …/CMSIS_5/5.9.0/CMSIS/Core/Include/cmsis_gcc.h | 5.9.0 | 63,374 |
| cmsis_version.h | …/CMSIS_5/5.9.0/CMSIS/Core/Include/cmsis_version.h | 5.9.0 | 1,680 |
| mpu_armv7.h | …/CMSIS_5/5.9.0/CMSIS/Core/Include/mpu_armv7.h | 5.9.0 | 11,731 |
| cachel1_armv7.h | …/CMSIS_5/5.9.0/CMSIS/Core/Include/cachel1_armv7.h | 5.9.0 | 12,087 |
| LICENSE.txt（ARM，Apache-2.0） | …/CMSIS_5/5.9.0/LICENSE.txt | 5.9.0 | 11,357 |

SHA-256 見 `src/c/cmsis/README.md`。

## 7. 重跑方式（都在 Docker 裡）

```bash
R='docker run --rm --user 1000:1000 -e HOME=/tmp --shm-size=2g -v $PWD:/work -w /work -e PYTHONPATH=/work/src -e MPLCONFIGDIR=/tmp rf-emg'
$R python src/check_selfcal_c.py              # 自我校正韌體（PC 建 one-shot）
$R python src/check_oneshot_c.py              # 第 1 項：剪枝比對＋MCU 上 one-shot 端到端
$R python src/diag_oneshot.py                 # 第 1 項：消融
$R python src/eval_decision.py                # 第 2 項
$R python src/check_rt.py                     # 第 3 項：封包解析、即時迴圈回放
$R python src/pc/test_pc_tools.py             # 第 3 項：PC 工具整合測試
$R python src/build_arm_selfcal.py            # 第 4、5 項：交叉編譯、Flash／RAM
```
