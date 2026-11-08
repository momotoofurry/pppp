# PC 端工具（路線 B）

只用 Python 標準函式庫；連真正的序列埠時才需要 `pyserial`。實驗室電腦不能上網，所以要先在別台電腦下載
`pyserial` 的 wheel 檔，帶過去用 `pip install pyserial-<版本>-py2.py3-none-any.whl` 離線安裝。

| 檔案 | 用途 |
|---|---|
| `protocol.py` | 和 `src/c/protocol.h`、`src/c/rt.h` 相同的封包格式：同步碼、序號、長度、CRC-16/CCITT-FALSE |
| `trigno_bridge.py` | 連 TCU（50040 指令、50041 EMG）→ 存 `emg.csv` → 轉成 int16（0.25 µV/LSB）送到序列埠；同時記錄 MCU 傳回的封包到 `mcu.csv` |
| `mcu_logger.py` | 解 MCU 傳回的封包（指令、每個視窗的預測、狀態）存 CSV；bridge 內部會用到，也可以單獨解錄下來的位元組檔 |
| `test_pc_tools.py` | 沒有硬體時的整合測試：假的 TCU → bridge → C 的 `rt.c`（假的 MCU）→ 回傳 → CSV |
| `TrignoBridge.cs` | 實驗室用的 C# 版 bridge（不用安裝任何東西，`lab_kit/README.md`）；`run` 的 CSV 用 Unix 時間 ms，另存 `ops.csv`，指令與狀態用 UDP 轉給 TaskScreen |
| `TaskScreen.cs` | 正式實驗的提示畫面（`PROTOCOL.md` 第 4.1、5、6 節）→ `task.csv`；終點用 `src/task_summary.py` 算 |

## 用法

```
python trigno_bridge.py --tcu 127.0.0.1 --port COM5 --emg-csv emg.csv --mcu-csv mcu.csv
```
串流時在終端機輸入控制指令：`reset`、`cal <0-5>`、`calend`、`calibrate`、`decision <tau‰> <k>`、`report <0|1>`、`quit`。
手勢編號：0 Power、1 Lateral、2 Tripod、3 Pointer、4 Open、5 Rest。

校正流程（每個手勢做一次）：對每個手勢依序 `reset` → `cal <手勢>` → 做手勢約 2 秒 → `calend`；六個手勢都做完後 `calibrate`。
MCU 會回傳狀態：event 4（校正視窗收滿 60 個）、event 1（one-shot 模型建立結果，0 = 成功）。之後 MCU 自動進入即時推論。
MCU 每個手勢只收 warmup 之後的視窗，最多總共 60 個視窗；平均每個手勢 10 個視窗（1 秒），和上游的資料相同。

## 待在實驗室電腦上驗證

- 2026-11-08 對照 Delsys Trigno SDK 官方範例：伺服器預設 big-endian（C# 範例反轉位元組），`TrignoBridge.cs` 已改成連線後送
  `ENDIAN LITTLE` 並依 `ENDIANNESS?` 決定要不要反轉；`trigno_bridge.py`（Python 版）還沒改，實驗用 C# 版。
  感測器若是 IM／Avanti 類型，EMG 可能在 50043 而不是 50041（`probe` 會量各埠的流量）。
- TCU 的協定是參照 pytrigno：連線後 50040 會送版本字串、指令以 `\r\n\r\n` 結尾、50041 是 16 通道 little-endian float32、單位伏特。
  實際的版本字串、是否需要其他指令（例如 `BACKWARDS COMPATIBILITY`、`UPSAMPLE`）、取樣率是否真的是 2000 Hz，都還沒有在真的 TCU 上確認。
- 序列埠（pyserial、921600 baud）沒有在 Docker 裡測過；Docker 裡的測試用 TCP 取代序列埠。
