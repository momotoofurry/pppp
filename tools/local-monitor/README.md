# 本地 AI 監看（local monitor）

實機實驗和日常使用時，即時讀紀錄檔、發現問題，並用**本機的 LLM** 寫成中文說明。全部在這台電腦上跑，資料不離開電腦；**只讀紀錄，不會送任何指令給手臂或板子**。report 35.108。

## 兩層設計

| 層 | 做什麼 | 為什麼這樣分 |
|---|---|---|
| **偵測**（`rules.py`） | 固定的規則：控制迴圈停頓、追蹤保護、deadman、掉封包、UART 錯誤增加、空抓、物體沒放在架子上、反覆鎖定、紀錄停止 | 安全和異常判斷要可驗證、可重現；每條規則都有單元測試，並在真實紀錄上檢查過誤報 |
| **解釋**（`explain.py`） | 把警示和最近 10 秒的紀錄交給本機的 qwen3（Ollama），寫成「發生什麼／可能原因／建議」三行 | LLM 擅長把數字翻成人看得懂的話；它不做判斷，也可能說錯，所以每則說明上方都列出規則和原始數據 |

- 嚴重度 high：手臂或資料路徑現在受影響，說明的第一句是請協助者準備急停。
- warn：值得注意。
- info：給摘要用，不呼叫 LLM。
- Ollama 沒開的時候，用規則本身的說明代替。

## 使用

Windows，Python 3（只用標準函式庫）；Ollama 已啟動並有 `qwen3:4b-instruct-2507-q4_K_M`（`ollama pull` 一次）。

```powershell
python tools\local-monitor\monitor.py --dir \\wsl.localhost\Ubuntu-22.04\home\<你>\kinova_k1
```

- `--replay`：一次讀完已結束的實驗，產生報告。
- `--no-llm`：只用規則的說明。
- `--model <名稱>`：換模型。
- `--out <資料夾>`：輸出位置，預設和 `--dir` 相同。

會讀 `--dir` 裡的 `*assist_board.csv`、`*board_events.csv`、`*task_events.csv`、`*_mcu.csv`，輸出：
- `alerts.jsonl`：每則警示、數據和說明；
- `report.md`：摘要。

## 規則

| 規則 | 嚴重度 | 條件 |
|---|---|---|
| `loop_stall` | warn／high | 兩個控制步相隔 > 0.3 s（> 1.0 s 為 high），**用紀錄的 `mono` 欄（單調時鐘）**；沒有 `mono` 的舊紀錄用牆上時鐘，可能是時鐘撥動（35.109）；2 s 內的慢步算同一次；新試驗回起點（`reset_done`）的 3 s 不算 |
| `tracking_hold` | high | 連續 5 步手臂離指令 > 4 cm（和 `assist_ros` 的追蹤保護一致） |
| `deadman_stop` | warn | 板子心跳斷 0.5 s，手臂停下 |
| `packets_lost` | high | `assist_ros` 或板子回報掉封包 |
| `uart_errors_rising` | warn | 板子的 UART 錯誤在第一次回報之後增加（開機時的 1 次不算，35.96） |
| `bytes_dropped` | high | 板子丟失 UART 資料 |
| `air_grasp` | warn | 空抓（`assist_ros --grip-check`，35.107） |
| `reset_refused` | info | 新試驗無法開始（手臂在架子裡或還夾著） |
| `putdown_off_shelf` | warn | 物體放下了但不在架子上 |
| `repeated_locks` | info | 一次放下之前鎖定 3 次以上 |
| `no_new_steps` | high | （即時模式）控制紀錄 3 s 沒有新的一列 |

測試：`python tools\local-monitor\test_rules.py`（22 項）。

## 還沒有的

- 60 Hz 干擾（等 R19 在下週的錄音上判定，35.106）。
- 肌肉疲勞、漂移等慢變化，需要多天的資料。
- 推送到 MQTT／Grafana（`tools/emg-iot`）。
