# 在微控制器上每次配戴自我校正的肌電介面，與輔助機械臂

碩士論文研究的程式、韌體、實驗工具和研究紀錄（2026-10 ～ 2026-11）。

**一句話**：sEMG 手勢介面每天重新戴上就會變不準。這個專案讓 STM32H753 上的分類器每次只做幾秒的校正，把歷次配戴累積起來，並在操作輔助機械臂（Kinova Gen3）時，用任務完成後確認的標籤持續更新模型。

> 第一次來？先讀 [`docs/接手指南.md`](docs/接手指南.md)：研究做到哪裡、先跑什麼、哪些試過沒用、哪些坑要避開。

## 研究問題

| | 問題 | 主要結果在 |
|---|---|---|
| RQ1 | 跨天累積：把每次配戴的校正存成充分統計量累積在 MCU 上，能不能比只用當天的校正更準？ | report 35.9–35.16、35.51、35.53、35.76 |
| RQ2 | 任務確認的標籤：輔助機械臂完成任務後回頭確認的標籤有多可靠、能帶來多少增益？ | report 35.17–35.27、35.55–35.56、35.65–35.71、35.83 |
| RQ3 | 可部署性：分類、校正、用標籤更新能不能在 MCU 上即時跑，而且和 PC 參考逐位元相同？ | report 35.10–35.14、35.22–35.25、35.36–35.39 |
| RQ4 | 應用：分類器不完美時，配合輔助控制能不能安全完成拿取和放置？ | report 35.57–35.72、35.82–35.101 |

## 系統一覽

```
Delsys Trigno（4 顆 Avanti，2 kHz）→ PC：TrignoBridge（只轉送原始樣本）→ UART →
STM32H753：濾波 → 200 ms 視窗 80 個特徵 → 本次配戴的 z-score → 收縮 LDA（累加量）→ 出力閘門 → 連續判定 → 指令
          ← 任務確認的範圍標籤（更新 LDA 累加量）
指令 → UDP → udp_tcp_relay.py → WSL / ROS 2 Humble：assist_ros.py（兩種模式＋意圖鎖定＋輔助）→ Kinova Gen3＋2F-85
```

詳細見 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 資料夾

| 位置 | 內容 |
|---|---|
| `src/c/` | MCU 上的 C 程式（特徵、收縮 LDA、即時迴圈 `rt_lda.c`、決策、通訊協定）；PC 上用同一份程式驗證 |
| `firmware/` | STM32 專案（CubeMX＋CMake）和建置腳本；可以逐位元重建板子上的韌體（[`firmware/README.md`](firmware/README.md)） |
| `src/*.py` | 分析和模擬（公開資料、自我測試、閉迴路模擬），每支檔案開頭的說明寫了對應的 report 節次 |
| `src/assist/` | 輔助控制（`modes.py` 兩種模式、`assist.py`、`labeler.py` 事後標籤）、閉迴路模擬（`closed_loop_fw.py` 用真韌體）和測試 |
| `src/pc/` | 實驗室電腦的工具：`TrignoBridge.cs`、`TaskScreen.cs`、`ExperimentPanel.cs`、`udp_tcp_relay.py` 等 |
| `src/pc/sim/` | ROS 2 / Gazebo：`assist_ros.py`（實機也用這支）、`kinova_trials.py`（實機試驗紀錄） |
| `src/pc/s7_test/` | 演練和檢查腳本（Gazebo 彩排、故障注入、時間穩定性） |
| `lab_kit/` | 實驗室用的操作程序：`SOP_自我測試.md`、`SOP_Kinova實機.md`、`實驗設計_Kinova實機.md` |
| `tools/emg-iot/` | 副專案：MQTT → TimescaleDB → Grafana 的訊號品質監控 |
| `docs/` | 接手指南、論文初稿、計畫書、設計筆記、文獻、資料取得方式、report 索引、早期路線的文件 |
| `report.md` | **研究紀錄的正本**：每個實驗的做法、判準、數字、結果檔，依時間排列（第 35 節是現在的主線） |
| `results/` | 每個 report 節次的輸出（CSV、文字報告） |
| `docker/` | 分析用的 Docker 環境（Python 3.12.3 和固定版本的套件、gcc、arm-none-eabi-gcc） |

## 快速開始（不需要任何硬體）

在 WSL2 / Linux：

```bash
git clone https://github.com/momotoofurry/pppp.git ~/emg && cd ~/emg
docker/run.sh build                      # 建分析用的映像檔（一次）
cd src/assist && for t in modes_test modes_assist_test labeler_test lockrule_test; do python3 $t.py | tail -1; done
python3 ../pc/sim/kinova_trials_test.py | tail -1
```

輔助控制的測試只需要 numpy。要跑閉迴路模擬或分析，需要資料（[`docs/資料.md`](docs/資料.md)）。

## 研究的方法慣例

- **判準先寫、再跑**：每個要下結論的實驗，判準都在算結果之前寫好並 commit（例如 `results/structure_97/PREREG_R16.md`）。沒通過的結果照樣寫進 report。
- **凍結**：錄資料前凍結的韌體和判準，錄的時候不改（現在的板子是 `rtl_task_s7f`，git tag 同名）。
- 大小一律 1 KB = 1024 bytes。
- report 每一節寫清楚：為什麼做、怎麼做、數字、結果檔、限制。

## 歷史

這個 repo 一開始是重現並壓縮「自我校正隨機森林」（Jiang 等，2024；上游 `self-calibrating-rf`），目標是放進 MCU（report 第 1–34 節）。外部資料驗證發現免標籤自我校正沒有確認的增益，而短時有標籤校正就有大部分的效果（report 24、35.3、35.16），之後改成現在的收縮 LDA＋任務標籤路線（report 35）。早期的 README、架構、實驗計畫放在 [`docs/history/`](docs/history/)。
