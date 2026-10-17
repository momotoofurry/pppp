# 階段 3：轉成 C 並編譯成 Cortex-M7 程式 — 摘要

腳本：`src/export_c.py`（匯出）、`src/check_c.py`（PC 正確性檢查）、`src/build_arm.py --wsl`（交叉編譯）；
C 程式：`src/c/`（`rf_predict.[ch]` 自寫的 table runtime、`main.c`、`startup_h743.c`、`stm32h743.ld`、`test_pc.c`）。
產生出來的 header 和 ELF 放在 `build/`（不進 git，可以重新產生）。

## 候選設定（subject 0、seed 0，建法和階段 2 的掃描一樣）
| 設定 | 樹數 | 深度 | 精度 | 內部節點 | Python 準確率（subject 0，3300 筆） |
|---|---|---|---|---|---|
| full_f32 | 400 | 不限 | float32 | 78,626 | 87.52% |
| d10_n400_i16 | 400 | 10 | int16 Q5.10 | 50,124 | 88.24% |
| d10_n100_i16 | 100 | 10 | int16 Q5.10 | 12,640 | 88.36% |

## 3.1 轉換
- **emlearn 0.23.2 可以用**，但需要兩個處理：
  1. 剪枝後被剪掉的節點還留在陣列裡，emlearn 會 assert「每個節點都走得到」→ 先用 `rf_size.compact_forest` 把走不到的節點移掉，再用 duck typing 把樹餵給 `emlearn.trees.Wrapper`。
  2. Python 3.12 沒有 `distutils` → 要另外 `pip install setuptools`。
  - float 用 `method='inline'`（每棵樹產生一個 if/else 函式）；int16 用 `method='loadable'`（節點表，門檻值事先量化成 Q5.10 整數）。
- **自寫的 table 格式**：struct-of-arrays，只存內部節點（feature u8 + threshold + left/right u16），child 的 bit 15 = 1 表示葉節點，低位元放類別。實際 byte 數和階段 2 的 compact 估算完全相同（709,234 / 352,468 / 88,880 B）。

## 3.3 PC 正確性檢查（MinGW-w64 gcc 8.1.0，`-O2`，3300 筆測試視窗，`c_check.csv`）
| 設定 | table vs Python | emlearn vs Python |
|---|---|---|
| full_f32 | 100%（0 筆不一致） | 100%（0 筆不一致） |
| d10_n400_i16 | 100% | 100% |
| d10_n100_i16 | 100% | 100% |

Python 參考答案用的運算方式和 C 完全一樣：float32 特徵和門檻值，或 int16 的 `rint(x·1024)`，並且 `x < thr` 往左。

要注意的地方：
- **比較方向會影響結果**：在 Python 裡把 `<` 換成 `<=`，預測只有 99.88%（float32）、99.79%、99.70%（int16）相同。
  int16 量化後特徵值剛好等於門檻值的情況更常見。上游的 `get_predictions` 和 emlearn 用 `<`，sklearn 和上游的 `prune()` 用 `<=`（這本身就是上游程式不一致的地方）。C 端一定要固定用 `<`，才會和重現的結果一致。
- 和原始 float64 模型相比：99.97% / 99.97% / 99.82% 相同（差異來自 float32 / int16 量化）。
- **emlearn 的 float inline 輸出用 `%.6f` 印門檻值**：78,626 個門檻值中有 73,213 個被改動，最大誤差 9.5e-7。
  這次測試沒有任何預測因此改變，但不保證之後不會。自寫的 table 用可以完整還原的 float32 寫法，沒有這個問題。
- 四捨五入必須用 round-half-even（`rintf`），才會和 numpy 的 `np.round` 一致。

## 3.4 交叉編譯（WSL2 Ubuntu 22.04，arm-none-eabi-gcc 10.3.1 20210621，`arm_size.csv`）
參數：`-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard -Os -ffunction-sections -fdata-sections -Wl,--gc-sections --specs=nano.specs --specs=nosys.specs`，
再加上自寫的 startup 和 H743 linker script（FLASH 2 MB @0x08000000；.data/.bss/stack 放 DTCM）。

| 設定 | 實作 | text | data | bss* | **Flash (text+data)** | 靜態 RAM | 最壞 stack | **推論 RAM 合計** |
|---|---|---|---|---|---|---|---|---|
| full_f32 | table | 710,480 | 4 | 324 | **693.8 KB** | 328 B | 72 B | 400 B |
| full_f32 | emlearn inline | 2,024,756 | 4 | 324 | **1977.3 KB**（佔 2 MB Flash 的 96.5%） | 328 B | 192 B | 520 B |
| d10_n400_i16 | table | 353,796 | 4 | 484 | **345.5 KB** | 488 B | 64 B | 552 B |
| d10_n400_i16 | emlearn loadable | 404,180 | 32 | 488 | **394.7 KB** | 520 B | 212 B | 732 B |
| d10_n100_i16 | table | 90,204 | 4 | 484 | **88.1 KB** | 488 B | 64 B | 552 B |
| d10_n100_i16 | emlearn loadable | 103,108 | 32 | 488 | **100.7 KB** | 520 B | 212 B | 732 B |

\* bss 已經扣掉 linker script 為 stack 保留的 4096 B。arm-none-eabi-size 的原始輸出是 bss = 4420 / 4580 / 4584。

- 靜態 RAM 的組成：特徵緩衝區 `g_features` float32×80 = 320 B，int16 設定再加量化後的緩衝區 160 B，再加 `g_pred` / `g_cycles` 和 newlib 的少量變數。
- 最壞 stack：用 `-fcallgraph-info=su`，從 Reset_Handler 開始沿最深的呼叫路徑加總。table 版本是 `Reset_Handler(8) → main(8) → rf_predict(48)`。
  newlib 的 `memcpy` 沒有 stack 資訊，但它在預測之前呼叫，不在最深的路徑上。
- 檢查過 ELF：模型陣列都在 Flash（`nm` 看得到 rf_thr 等陣列，大小和預期一樣）；`rintf` 被編成 `vrint` 指令，沒有用到 libm。
- emlearn 的 int16 節點因為 struct 有 padding，每個節點 8 B（我們的格式是 7 B）；inline float 把每個節點都編成程式碼，Flash 用量是 table 格式的 2.85 倍。

**結論**：推論本身只需要 < 1 KB RAM。完整的論文模型用 table float32 格式只要 694 KB Flash，放得進 H743；
d10_n100_i16 只要 88 KB。用 emlearn inline float 放完整模型雖然還放得下（1977 KB），但幾乎佔滿 2 MB Flash。

## 3.5 模擬量 cycle 數 — 沒有做
- QEMU 沒有 STM32H7 的機型，而且不模擬 cycle；`-icount` 只能數指令。
- Renode 有 STM32H743 平台，但它的 DWT CYCCNT 是用指令數推算的，沒有模擬 M7 的雙發射 pipeline、cache、Flash wait state、AXI 匯流排延遲，所以不是真正的 cycle 數。
- 所以這裡沒有報任何 cycle 數字。要得到實際的推論時間，就把 `build/<cfg>/arm_table.elf` 燒到 NUCLEO-H743ZI2，
  用除錯器讀 `g_cycles`（main.c 已經用 DWT CYCCNT 量好 `rf_predict` 前後的差值）。
  注意：目前的 startup 沒有設定時脈（HSI 64 MHz），也沒開 I/D-cache，正式量測前要先設定好。
- 也還**沒有在 ARM 上驗證預測正確性**（只在 PC 上驗證過）。燒到板子上之後，可以比對 `g_pred` 和 `SAMPLE_LABEL`／Python 的預測。
