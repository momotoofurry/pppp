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
| `run.bat` | 第 3 步：Trigno → STM32 整條路（`run.bat COM5 S01_d2_A` → `S01_d2_A_emg.csv`、`_mcu.csv`、`_ops.csv`） |
| `TaskScreen.exe`、`task.bat` | 第 4 步：正式實驗的提示畫面（有標籤段、練習、提示指令任務、非控制動作段）→ `S01_d2_A_task.csv` |
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

## 第 4 步：提示畫面（正式實驗，`PROTOCOL.md` 第 4.1、5、6 節）

1. 先開 `run.bat COM5 S01_d2_A`（檔名只用代號＿天＿條件；檔案已存在會拒絕，換名字）。照第 3 步做 `report 1`、`load`、
   `adapt`、`align`。`run.bat` 會把板子的指令和狀態用 UDP（本機 50555）轉給提示畫面，也把你打的每個指令記到 `_ops.csv`。
2. 另開一個命令提示字元：`task.bat S01 2 A`（代號、天、條件）。畫面全螢幕，**不顯示條件**（單盲）。
3. 每一段由實驗者按**空白鍵**開始，順序：有標籤段 → 練習 → 提示指令任務 → 有標籤段 → 非控制動作段（每一項也按空白鍵開始）。
   - 有標籤段：6 個手勢 × 5 次，提示 2 秒、休息 3 秒，隨機順序。
   - 提示指令任務：40 個試次，畫面顯示目標指令（夾／放／位置 A／位置 B），5 秒內板子送出的**第一個**指令是目標＝成功，
     試次之間休息 2.5 秒（畫面顯示對錯）。**每次做完要放鬆**：同一個指令要隔一個別的手勢（含 Rest）才會再送。
   - **Esc**：中止目前這一段（會記錄，可以按空白鍵重做；分析只用最後一次完整的）。等待時按 **Q** 離開。
4. 改設定（老師決定後）：`task.bat S01 2 A --n 40 --timeout 5 --commands grip,release,pose_A,pose_B,home`
   （`home`＝Lateral，要韌體也加了才有）、`--items 1,2,3,5`（非控制動作項目；預設第 1 天 1,2,3,5、第 2 天 1–8）。
   全部選項在 `src/pc/TaskScreen.cs` 開頭。
5. 沒有板子時演練：`task.bat S01 1 A --fake`，鍵盤 1–5 當作板子送出 位置 A／夾／位置 B／放／回原位。
6. 結果：結束畫面和 `_task.csv` 的最後一行有任務成功數與休息中誤觸發；帶回來用 `src/task_summary.py` 算主終點。
   PROTOCOL v3 的完整段落：`task.bat S01 2 A --segments labelled,practice,task,labelled,noncontrol,tlx --retry 1`
   （`--retry 1`：第一個指令錯了還可以再試一次，只記錄、主終點不變；`tlx`：NASA-TLX 6 題，← → 調整、Enter 確定）。
7. 板子接上但沒有 Trigno 時，可以先開 `task.bat T00 0 X`，再跑 `replay.bat COM5`：replay 也會把板子的指令轉給提示畫面
   （端到端測試；`T00_d0_X_task.csv` 不是實驗資料）。

## 對齊閘門、溫度、Kinova（2026-11-05）

- `run.bat` 的 TrignoBridge 預設開**對齊閘門**：`calibrate`、`load`、`adapt 1` 之後，板子的指令要等 `align` 成功才會送到提示畫面和機器人。
  畫面出現 `>>> ... <<<` 的提示就照著做（對齊太短 → 再打 `align`；沒把握 → 檢查記號再 `align`；板子沒回應 → 再打 `align`）。
  `calibrate` 之後等畫面出現 `calibrated (0 = ok)` 再打 `align`。
- 溫度：每個條件開始和結束時打 `note temp room 24.0 skin 31.5`（數字換成量到的），會記進 `_ops.csv`。
- 畫面一開始出現 `packets lost`，下面又註明「board was not reset」：這是板子沒重開就重跑，**不是掉資料**。
- 接 Kinova：`run.bat COM5 S01_d2_A --udp 50555,50556`，再開一個視窗跑
  `python kinova_bridge.py run --ip 192.168.1.10 --out S01_d2_A_robot.csv --poses poses.json`
  （要先 `pip install` Kinova 的 kortex_api、在那個視窗設好環境變數 `KINOVA_PASSWORD`；預設位置用 `kinova_bridge.py teach --ip ... --name pose_A` 存）。
  **按 e 急停**；c 解除；q 離開。真的手臂還沒測過，第一次要低速、手臂周圍淨空、旁邊有人拿急停。沒有手臂時可以加 `--sim` 演練。
- 在自己的電腦用 RViz 看模擬手臂（需要 WSL＋ROS 2 Humble＋`ros2_kortex`，安裝指令在 `src/pc/sim/gen3_sim.sh` 開頭）：
  WSL 裡依序跑 `bash src/pc/sim/gen3_sim.sh` 和 `python3 src/pc/sim/ros_relay.py`，
  Windows 這邊跑 `python kinova_bridge.py run --ros --poses poses_sim.json`，再加上 `TrignoBridge run --udp 50555,50556`。
  2026-11-06 用真板子測過（report 27.5）。只是流程演練，不能代替真手臂。

## 收尾

- 把 `S01_d2_A_emg.csv`（原始 EMG）、`_mcu.csv`（板子的預測、指令、狀態）、`_ops.csv`（實驗者指令）、`_task.csv`（提示與結果）、
  `emg_check.csv` 複製回來。所有檔案的時間都是 Unix 時間（ms，同一個時鐘），可以直接對齊。
- **檔名只用受試者代號（例如 S01_d2_A），不要用姓名。**
- 自己戴上去跑只用來驗證整套系統能動（代號 `T00`，資料不當研究結果、不放進論文的結果）；正式受試者（`S01` 起）的資料要等 IRB 通過才收。
  接 Kinova 時自己測也要低速、人在工作空間外、旁邊有人拿急停。

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

- 提示畫面（2026-11-02）：TaskScreen.exe 接假的板子（Python 送 UDP 指令，隨機時間、2 成的時間戳早 100 ms 模擬傳輸延遲）
  跑完五段：8 個試次目標平衡（各 2）、沒有連續相同目標；`src/task_summary.py` 用記錄的指令重算每個試次的結果，和畫面判定
  0 個不同。鍵盤（空白鍵、`--fake` 的 1–4、Esc 中止後重做）也測過：中止的那次分析時排除。
  改過的 TrignoBridge.exe 接模擬的 TCU：位元組不變（`check_bridge.py`：CRC 錯誤 0、88.00%），三個 CSV 都是 Unix 時間 ms，
  `_ops.csv` 記下每個指令。
- 2026-11-03 `pilot-freeze-4` 燒進板子：`replay` 88.00%／85.00%，和 PC 逐視窗 100% 相同、CRC 錯誤 0；板子 → UDP → 提示畫面收到的
  27 個指令和板子送出的逐一相同（report 第 26 節）。**這個資料夾的板子已經是 pilot-freeze-4，到實驗室不用重燒。**

- 2026-11-05：對齊閘門、`note`、`--udp 50555,50556` 用假 TCU 接真板子（pilot-freeze-4）測了 3 次：對齊前的指令都被擋下（2、3、3 個），
  「對齊太短」「板子沒回應」的提示都照預期出現，放行的 7 個指令提示畫面和 `kinova_bridge.py --sim` 都收到同一批（report 27.3）。
  TaskScreen 的 `--retry 1` 和 `tlx` 用模擬指令測過，`task_summary.py` 重算和畫面判定 0 個不同。

## 還沒在真機上確認的

- 真的 TCU 的協定（版本字串、START／STOP 的回應、16 通道 float32 的格式）是照 pytrigno 寫的。第 2 步就是在確認這件事：
  如果 `check.bat` 連不上或數值不合理，把畫面拍下來帶回來。
- `run.bat` 接真的 STM32＋真的 Trigno 的整條路（第 3 步）。
- `kinova_bridge.py` 接真的 Kinova（Kortex API）。
- 板子剛插上或剛重置時，ST-LINK 要幾秒才準備好；replay 一開始就出現「已中止 I/O 操作」的話，等 5 秒再跑一次。

## 重建這個資料夾（在開發電腦上）

```
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /optimize+ /codepage:65001 /target:exe /out:build\pc\TrignoBridge.exe src\pc\TrignoBridge.cs
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /optimize+ /codepage:65001 /target:winexe /out:build\pc\TaskScreen.exe src\pc\TaskScreen.cs
python src/board_replay.py make --blocks 2        (在 Docker 裡；產生 build/board_replay/)
```
（`/codepage:65001`：原始碼是沒有 BOM 的 UTF-8，不加的話中文字串會被當成 Big5 編譯成亂碼。）
再把 `build/pc/TrignoBridge.exe`、`build/pc/TaskScreen.exe`、`src/pc/kinova_bridge.py`、`lab_kit/*.bat`、`lab_kit/README.md`、`build/board_replay/{stream.bin,schedule.csv,windows.csv}`
複製到隨身碟的 `lab_kit/`（`board_replay/` 子資料夾）。測試：`src/pc/fake_tcu.py`（Windows 的 Python＋numpy）當 TCU，
`TrignoBridge.exe run --port file:bridge_out.bin --script script.txt`，再用 `src/pc/check_bridge.py` 檢查。
