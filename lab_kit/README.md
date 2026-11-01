# 實驗室電腦測試包（路線 B）

實驗室電腦**不用安裝任何東西**（不用 Python、pyserial、PowerShell 權限）：`TrignoBridge.exe` 是用 Windows 內建的
C# 編譯器編的（.NET Framework 4，Windows 10／11 都有）。原始碼：`src/pc/TrignoBridge.cs`。

STM32（NUCLEO-H753ZI）裡要是 2026-10-30 以後的路線 B 韌體（`app_rt.c`，921600 baud；z-score 更新後 buffer 轉座標、
開機對齊至少 60 個視窗，report 第 20 節；預測少於 5 類就不更新，第 22.1 節）。燒好以後**到實驗室不用重燒**。

## 資料夾內容

| 檔案 | 用途 |
|---|---|
| `TrignoBridge.exe` | check／run／replay 三種模式 |
| `check.bat` | 第 2 步：只測 Trigno（不用 STM32） |
| `replay.bat` | 第 1 步：只測 STM32（不用 Trigno），用錄好的資料 |
| `run.bat` | 第 3 步：Trigno → STM32 整條路 |
| `board_replay\` | 第 1 步用的錄好的串流（受試者 0，校正＋2 個 block，135 秒） |

## 第 1 步：只測 STM32 和 COM port（約 3 分鐘，不用 Trigno）

1. NUCLEO 用 USB 接 **ST-LINK 那一端**，按一下板子上**黑色的 RESET 鍵**（讓板子從頭開始）。
2. 「裝置管理員 → 連接埠 (COM 和 LPT)」找 **STMicroelectronics STLink Virtual COM Port (COMx)**，記下號碼。
   - 沒有出現的話：這台電腦缺 ST-LINK 驅動程式（STSW-LINK009，要先在別台電腦從 ST 官網下載帶過來）。
3. 在這個資料夾打開命令提示字元（檔案總管網址列輸入 `cmd` 按 Enter），執行（COM5 換成你的號碼）：
   ```
   replay.bat COM5
   ```
4. **應該看到**（約 140 秒後）：`calibration windows 60`、`calibrated (0 = ok) 0`、`self-calibration blocks 1`、`2`，
   最後 `block 0: accuracy 88.00%`、`block 1: accuracy 85.00%`（2026-10-30 韌體在我電腦上 PC 版的結果；
   舊韌體是 88.00%／86.67%，看到這組代表板子還是舊韌體）。

## 第 2 步：只測 Trigno（約 2 分鐘，不用 STM32）

1. 基地台接 USB，打開 **Trigno Control Utility**。不要同時開 Vicon／EMGworks 去收同一個基地台。
2. 8 顆感測器開機、配對到 **1–8 號**（第 1 號 = 第 1 通道），全部同一種模式。
3. 戴上束帶（感測器依 1→8 繞前臂一圈，皮膚和接觸點先用酒精擦）。
4. 執行：
   ```
   check.bat
   ```
   錄 60 秒，期間做幾次用力握拳和放鬆。
5. **看結果**：
   - `measured rate`：應該約 **2000 Hz**（如果明顯不是，記下數字，第 3 步加 `--rate <數字>`）
   - 每個通道的 `max|V|`：1–8 都要有訊號；不能出現 `WARNING: near the 8.19 mV limit`
   - 錄下的資料在 `emg_check.csv`，帶回來給我檢查

## 第 3 步：整條路（Trigno → PC → STM32）

1. TCU 開著、感測器戴好、NUCLEO 接好（按一下 RESET）。
2. 執行（COM5 換成你的號碼）：
   ```
   run.bat COM5
   ```
3. 先輸入 `report 1`（板子每個視窗都回報預測）。
4. **校正**，每個手勢一次（0 Power、1 Lateral、2 Tripod、3 Pointer、4 Open、5 Rest）：
   - 輸入 `cal 0`，**馬上做手勢並維持住**；2 秒後畫面出現 `calend (auto, 2 s): you can relax` 才放鬆
   - 手勢 1–5 照做（每次都等到出現 `calend (auto...)` 再輸入下一個）
   - 程式自動控制時間：每個手勢收 10 個視窗（和資料集一樣：前 0.9 秒是轉換期不收，之後 1 秒收 10 個），
     6 個手勢共 60 個。不用自己輸入 `calend`，也不會因為手勢維持太久而把名額用完
     （板子的上限是「總共 60 個」，不是每個手勢 10 個）
5. 輸入 `calibrate`。**應該看到** `MCU: status,...,calibration windows,60` 和 `calibrated (0 = ok),0`（約 1 秒）。
   **接著做校正檢查**：輸入 `verify 0`，馬上做 Power 並維持約 2 秒，畫面出現 `verify 0 (Power): x/10 right` 才放鬆；
   `verify 1`～`verify 5` 照做。6 個都做完會出現 `verify total: ... -> PASS` 或 `FAIL`。
   **FAIL（< 70%）就重做校正**（`cal 0`～`cal 5`、`calibrate`，再 `verify` 一次）。正常校正約 5% 會 FAIL 一次；
   出力太弱的校正約 9 成會被擋下來（report 第 22.1 節）。校正時要用平常使用的力氣，不要太輕。
6. 之後板子自動即時分類，指令會顯示在畫面上（`MCU: command,...`）；每 10 秒有一行狀態（收到幾個樣本、實測取樣率、
   有沒有被截掉的樣本）。
7. 結束輸入 `quit`。

其他指令：`decision 600 3`（τ = 0.6、k = 3）、`report 0`（關掉每個視窗的回報）、`reset`（新的一段錄音）、
`calend`（提早結束這個手勢的收集）、`status`。

### 第 2 天（或板子斷過電）：先 `load`

第 1 天的模型存在板子的 Flash 裡，斷電也不會消失。`run.bat` 開起來以後先輸入 `report 1`、`load`，**應該看到**
`MCU: status,...,day-1 model loaded (calibration rows; < 0 = none, calibrate),60`。看到負數代表板子裡沒有有效的模型，要重新校正。
`load` 也會把自我校正學到的東西清掉、回到第 1 天的狀態（正式實驗每個條件開始前都要做，`PROTOCOL.md`）。

### 實驗條件

- 固定模型（F）：`load`、`adapt 0`（不做開機對齊）
- 完整系統（A）：`load`、`adapt 1`、`align`

### 重新戴上感測器以後（例如第 2 天）：開機對齊

完整系統（`adapt 1`）時，重新戴上束帶後先做開機對齊（估計束帶整圈轉了幾格）：

1. 輸入 `align`，**接下來 8 秒依序做 6 個手勢，每個約 1 秒**：Power、Lateral、Tripod、Pointer、Open、Rest。
2. 8 秒後程式自動結束，**應該看到** `MCU: status,...,rotation,<數字>`（−1、0、1，束帶轉了幾格）。
   - 如果先看到 `alignment unsure, rotation kept 0`：板子沒把握，維持不轉（2026-11-02 起，report 25）。束帶有動過就調回記號位置、重新 `align`；記下這件事。只會修正 ±1 格，戴的時候對準記號。
   - 如果看到 `alignment too short, rotation unchanged`：收到的視窗不到 60 個（例如中途 `reset`），重新輸入 `align`。
3. **不要只做一種手勢或一直休息**：束帶真的轉了一格時，只休息的話 20 人裡 16 人修正不回來（report 第 25 節）。
4. 之後照常使用（不用重新 `cal`／`calibrate`）。

## 收尾

- 把 `emg.csv`（原始 EMG）、`mcu.csv`（板子的預測、指令、狀態）、`emg_check.csv` 複製回來。
- **檔名改成受試者代號（例如 S01_day1_emg.csv），不要用姓名。**
- 收你自己以外的受試者之前，IRB 要先通過。

## 已在我的電腦上測過的

- TrignoBridge.exe 接模擬的 TCU（`src/pc/fake_tcu.py`，受試者 0 的 6 段校正＋testing_block0，即時 2000 Hz），
  送出的位元組餵給 PC 版的 `rt.c` 檢查（`src/pc/check_bridge.py`）：CRC 錯誤 0、每段錄音 4000 個樣本、自動 calend 後
  校正 60 個視窗、one-shot 成功、300 個測試視窗準確率 88.00%（和 PC 模擬、板子回放相同）。
  1926 Hz 輸入＋`--rate 1925.926` 重新取樣也可用（86.67%），只當備案。
- replay：板子上 block 0／1 準確率 88.00%／86.67%，和 PC 逐視窗相同（report 第 19 節）；2026-10-30 用這個資料夾的
  `TrignoBridge.exe replay` 接板子重跑兩次，結果相同（校正 60、one-shot 成功、自我校正 2 次、CRC 錯誤 0）。
  以上是 2026-10-30 之前的韌體。新韌體燒進去後用 `serial_replay.ps1` 重跑：88.00%／85.00%，和 PC 逐視窗 100% 相同、CRC 錯誤 0。
- `align`（2026-10-30）：TrignoBridge.exe 接模擬的 TCU，校正後 `align` 送出 reset → ALIGN_START → 8 秒後 ALIGN_END，
  位元組餵給 PC 版 `rt.c`：回 `rotation 0`（資料沒轉）、之後正常分類。`src/check_align_rt.py`：PC 版 `rt.c` 的開機對齊
  在通道轉 0／1／2／−1 格時都估對，之後的預測和沒轉時逐視窗相同；只給 10 個視窗時回 `alignment too short`。

## 還沒在真機上確認的

- 真的 TCU 的協定（版本字串、START／STOP 的回應、16 通道 float32 的格式）是照 pytrigno 寫的。第 2 步就是在確認這件事：
  如果 `check.bat` 連不上或數值不合理，把畫面拍下來帶回來。
- `run.bat` 接真的 STM32＋真的 Trigno 的整條路（第 3 步）。
- 板子剛插上或剛重置時，ST-LINK 要幾秒才準備好；replay 一開始就出現「已中止 I/O 操作」的話，等 5 秒再跑一次。

## 重建這個資料夾（在開發電腦上）

```
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /optimize+ /target:exe /out:build\pc\TrignoBridge.exe src\pc\TrignoBridge.cs
python src/board_replay.py make --blocks 2        (在 Docker 裡；產生 build/board_replay/)
```
再把 `build/pc/TrignoBridge.exe`、`lab_kit/*.bat`、`lab_kit/README.md`、`build/board_replay/{stream.bin,schedule.csv,windows.csv}`
複製到隨身碟的 `lab_kit/`（`board_replay/` 子資料夾）。測試：`src/pc/fake_tcu.py`（Windows 的 Python＋numpy）當 TCU，
`TrignoBridge.exe run --port file:bridge_out.bin --script script.txt`，再用 `src/pc/check_bridge.py` 檢查。
