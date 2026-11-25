# 系統架構（2026-11-25，板子 `rtl_task_s7f`）

早期隨機森林路線的架構（2026-10-30，韌體 v2）在 [`docs/history/ARCHITECTURE_RF_v2.md`](docs/history/ARCHITECTURE_RF_v2.md)。數字的出處都在 `report.md`，括號內是節次。

## 1. 資料流

```
 Delsys Trigno：4 顆 Avanti 貼在目標肌肉（伸指肌、屈指淺肌、橈側屈腕肌、尺側屈腕肌；slots 16:11:15:5），2 kHz
        │  Trigno Control Utility（只有 Windows 版）：TCP 50040 指令、50041 EMG
        ▼
 Windows PC：TrignoBridge.exe（C#，src/pc/TrignoBridge.cs）
        │  只轉送原始樣本：int16（0.25 µV）、每 10 ms 一包 → UART 921600（ST-LINK 虛擬 COM）
        │  同時記錄 <名稱>_emg.csv、_mcu.csv（板子回傳）、_ops.csv（操作）
        ▼
 ┌──────────────── STM32H753（NUCLEO-H753ZI，480 MHz）：rt_lda.c ────────────────┐
 │ features.c   帶通 10–500 Hz；200 ms 視窗、每 100 ms 一個；每通道 10 個特徵 → 80 維 │
 │              （4 顆感測器時 ch5–8 是 ch1–4 的複本，35.97）                     │
 │ 每次配戴     提示校正（每個手勢 2 輪）→ 本次的 z-score（平均、SD）→ Q5.10       │
 │ ldacal.c     收縮 LDA：只存累加量（每類的和、筆數、外積和），OAS 收縮、Cholesky │
 │              → 可以跨天累積、不存樣本；更新是閉式解（板上約 4 ms）              │
 │ 出力閘門     活動量低於門檻（0.5，模式 2）就當休息                             │
 │ decision.c   S7 類別遮罩；同一手勢連續 k = 5 個視窗才送指令，休息只要 2 個     │
 │ 標籤         最近 256 個視窗的緩衝；收到 RTL_LABEL_RANGE（first, last, class） │
 │              就把那段視窗加進累加量、重解 LDA（35.83）                         │
 └───────────────────────────────────────────────────────────────────────────────┘
        │  UART：指令事件（up / down / left / right / grip_open / grip_close / none=停）
        │        report 3：每個視窗一個 PRED（心跳，deadman 用）
        ▼
 TrignoBridge --udp 50555,50556 --fwd-pred 1 → TaskScreen（50555）、udp_tcp_relay.py（50556）
        │  udp_tcp_relay.py：UDP → TCP（WSL2 的 NAT 只轉 TCP）→ 127.0.0.1:50560
        ▼
 WSL（Ubuntu 22.04、ROS 2 Humble）：src/pc/sim/assist_ros.py board
        │  modes.py   兩種模式：模式 1 在架子前方平面上下左右；停下 → 鎖定物體或架子 → 模式 2 前後
        │  assist.py  模式 1 往可能的物體修正路徑；lock_rule intent：架子的意圖機率 ≥ 0.8 才立刻鎖
        │  labeler.py 放下成功後，回頭把這段操作的視窗標成「其實想做的方向」→ range 標籤
        │  kin.py     IK；安全：工作區邊界、deadman 0.5 s、追蹤誤差 > 4 cm 停住、起始移動限速
        ▼
 ros2_kortex（JointTrajectoryController）→ Kinova Gen3 7 軸＋Robotiq 2F-85
        ↑ 標籤回程：assist_ros → relay → TrignoBridge --task-udp 50559 → 板子
```

## 2. 手勢與指令（S7）

| 手勢 | 板子送出 | 模式 1 | 模式 2 |
|---|---|---|---|
| 手腕上翹 | up | 上 | 前進 |
| 手腕下壓 | down | 下 | 後退（退回前方平面就回模式 1） |
| 往拇指側偏 | left | 左 | 架子前方：回模式 1 |
| 往小指側偏 | right | 右 | 同上 |
| 握拳 | grip_close | 停 | 在鎖定的物體旁：夾 |
| 張開 | grip_open | 停 | 在架子裡、位置合法：放 |
| 放鬆 | none | 停；停在物體或架子前面 → 鎖定 | 停 |

握拳和張開要加 `assist_ros.py --grip gripper`；預設是「放鬆 1 秒夾取或放下」。

## 3. 既然頭尾都在 PC，為什麼要在 MCU 上算？

這是最常被問的問題。答案分兩層：

- **MCU 是「獨立穿戴式運算節點」的原型**。真正給使用者的裝置不會帶一台 PC：感測器、MCU、電池在前臂上，只把幾個位元組的指令用無線送給輔助手臂。現在經過 PC，只因為 Trigno 基地台只有 USB 輸出；PC 端**不做任何肌電運算**（不算特徵、不分類、不更新模型），只轉送原始樣本，所以換成 ADC 直接取樣或無線模組時，MCU 上的程式不用改。
- **要驗證的正是 MCU 的限制**：在 512 KB RAM、單精度浮點、沒有作業系統配置記憶體的條件下，能不能做到 (1) 確定性的即時分類（每 100 ms 一個視窗）、(2) 不存樣本的增量學習（只存累加量）、(3) 和 PC 參考逐位元相同。這三件事在 PC 上做不能證明什麼。

轉送層有沒有造成危險的延遲抖動：
- PC 送出完成一個視窗的封包 → 收到板子的結果：P50 6.70 ms、P95 7.20 ms、P99 7.38 ms；偶發的 10–25 ms 長尾在裸機版也有，最可能來自 Windows／USB（35.37）。
- 控制層 relay 的來回時間 1.0 ms（35.85）。
- 指令本身需要連續 5 個視窗（約 0.5 s）才成立，所以毫秒等級的抖動不影響控制；停止只要 2 個視窗。
- **還沒量**：從 EMG 樣本進 PC 到手臂開始動的完整端到端延遲分布（Windows 和 WSL 的時鐘不同步，不能直接相減，35.82；要用同一個時鐘的來回時間量）。

**誠實的限制**：
- EMG 仍經過 PC 轉送（Trigno 的限制），論文主張的「在 MCU 上」是解碼和校正學習。
- **跨天累積還沒有存進 Flash**：現在的韌體不讀寫 Flash，累加量在斷電後就沒了；跨天累積的效果是用錄音離線重播驗證的。要做成真的裝置，需要第 5 節的持久化設計。

## 4. 為什麼這樣設計（重點）

- **收縮 LDA 而不是隨機森林或神經網路**：每次配戴只有幾秒的校正資料，又要在 MCU 上每天增量更新；在這個條件下，可更新的 MLP 沒有贏過 LDA（35.38–35.39），短時有標籤校正比免標籤自我校正有效（35.3、35.16）。
- **PC 只轉送**：Trigno 基地台只有 USB 輸出，所以 EMG 要經過 PC；所有肌電運算都在 MCU 上，PC 端不算特徵、不分類。論文主張的「在 MCU 上」是解碼和校正學習，這個限制要寫清楚。
- **兩種模式**：只有 4 個方向，沒有辦法同時控制 3 個軸；鎖定後由系統對準，使用者只需要前後（35.62–35.63）。
- **意圖鎖定**：鎖錯大多是「經過的架子」；依移動方向算機率，只有很有把握才立刻鎖（35.88–35.89）。
- **安全層**：deadman（心跳斷 0.5 s 就停）、封包遺失就停、工作區邊界、追蹤誤差保護（35.85、35.92）。

## 5. 防護設計：已經有的、還沒做的

| 狀況 | 現在的處理 | 狀態 |
|---|---|---|
| 協方差接近奇異、Cholesky 失敗 | `ld_fit` 回傳錯誤（包含 NaN 的情況，因為用 `!(v > 0)` 判斷），**保留上一版的模型權重**；退化資料（變異只剩捨入誤差）另外擋下 | 已做（`ldacal.c`） |
| 分類器出錯 | 手臂速度有上限、只有離散方向；工作區邊界；需要連續 5 個視窗才成立；停止只要 2 個 | 已做 |
| 資料中斷 | 心跳斷 0.5 s（deadman）或封包遺失 → 停，之後要新的手勢才會再動 | 已做，故障注入測過（35.85） |
| 手臂沒跟上指令（被擋、故障） | 追蹤誤差 > 4 cm 連續 5 步 → 停住，放鬆才繼續 | 已做（35.92） |
| 感測器脫落（某通道全平） | 偏度、頻譜特徵會出現 0／0 = NaN；PC 分析用 `nan_to_num`，板子上的轉換結果依硬體而定 | **還沒做**：要在 `features.c` 明確把非有限值設為 0，並回報 |
| 累加量存 Flash | 沒有存 | **還沒做**：建議用兩個 sector 輪流寫（斷電時至少有一份完整的）、每份加版本號和 CRC32、讀回時檢查 CRC 和數值範圍，不通過就退回只用當天的校正 |

## 6. 模擬和測試的層級

| 層級 | 用什麼 | 檔案 |
|---|---|---|
| 單元測試 | 純 Python | `src/assist/*_test.py`、`src/pc/sim/kinova_trials_test.py` |
| C 和 PC 參考逐位元比對 | gcc 編 `src/c` 成 .so | `src/check_*.py` |
| 閉迴路（真韌體＋錄好的 EMG＋模擬使用者） | `librtl9.so` | `src/assist/closed_loop_fw.py`、`closed_loop_paired.py` |
| 手臂動力學 | Gazebo Classic＋Gen3＋2F-85 | `src/pc/sim/gen3_gazebo.sh`、`src/pc/s7_test/gz_*.sh` |
| 實機介面 | `kortex_bringup use_fake_hardware:=true` | `src/pc/s7_test/kortex_mock.sh` |
| 板子實測 | NUCLEO-H753ZI | `src/board_replay*.py`、`src/pc/s7_test/*.ps1` |
