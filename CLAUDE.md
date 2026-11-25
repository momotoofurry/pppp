# 專案：MCU 上每次配戴自我校正的肌電介面＋輔助機械臂（碩士論文）

用**繁體中文**溝通。先讀 `docs/接手指南.md`、`README.md`、`ARCHITECTURE.md`；研究紀錄的正本是 `report.md`（第 35 節是現在的主線，`docs/report索引.md` 依主題分類）。

## 執行環境
- 分析和模擬在 WSL2 的 Docker 裡跑：映像 `rf-emg`（`docker/run.sh build`）。
  單次指令：`docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --shm-size=2g -v "$PWD":/work -w /work rf-emg python ...`
  資料夾用 `-v` 掛進去（路徑見各程式開頭和 `docs/資料.md`）。
- 輔助控制的單元測試只要 numpy：`src/assist/*_test.py`、`src/pc/sim/kinova_trials_test.py`。
- ROS 2 Humble、Gazebo 在同一個 WSL；韌體在 Windows 用 STM32 的工具建置（`firmware/README.md`）。
- repo 放在 WSL 的檔案系統（`~/`），不要放 `/mnt/c`。

## 規則
1. **所有數字都要來自實際執行的結果**；估算一定標「估算」。沒有板子就不報 MCU 上的時間。
2. **要下結論的實驗，判準先寫好並 commit，再跑**；沒通過也照實寫進 report（新的一節：為什麼、怎麼做、數字、結果檔、限制）。
3. **凍結的東西不改**：板子韌體 `rtl_task_s7f`（git tag）、S7 判準（report 35.86）。要改就是新版本，重新登錄。
4. C 程式改了，要用 `src/check_*.py` 和 PC 參考逐位元比對；改了 `rt_lda.c`、`decision.c`，要重跑閉迴路模擬（`src/assist/closed_loop_fw.py`）確認預設值重現舊結果。
5. `src/assist/modes.py`、`src/pc/ExperimentPanel.cs`、`src/pc/sim/make_world.py` 是 CRLF 換行，修改時保留原本的換行。
6. 大小一律 1 KB = 1024 bytes。
7. 每完成一個階段就 commit；個人的 EMG 錄音不要放進 repo（公開）。
8. 實機一定要有人顧急停；作者以外的受試者要先有 IRB 和指導教授同意。
