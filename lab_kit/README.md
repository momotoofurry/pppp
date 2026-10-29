# 實驗室電腦測試包（路線 B）

實驗室電腦**不用安裝任何東西**（不用 Python、pyserial、PowerShell 權限）：`TrignoBridge.exe` 是用 Windows 內建的
C# 編譯器編的（.NET Framework 4，Windows 10／11 都有）。原始碼：`src/pc/TrignoBridge.cs`。

STM32（NUCLEO-H753ZI）裡已經燒好路線 B 的韌體（`app_rt.c`，921600 baud），**到實驗室不用重燒**。

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
   最後 `block 0: accuracy 88.00%`、`block 1: accuracy 86.67%`（和在我電腦上的結果相同）。

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
6. 之後板子自動即時分類，指令會顯示在畫面上（`MCU: command,...`）；每 10 秒有一行狀態（收到幾個樣本、實測取樣率、
   有沒有被截掉的樣本）。
7. 結束輸入 `quit`。

其他指令：`decision 600 3`（τ = 0.6、k = 3）、`report 0`（關掉每個視窗的回報）、`reset`（新的一段錄音）、
`calend`（提早結束這個手勢的收集）、`status`。

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
