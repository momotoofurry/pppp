# 給 AI 助手的專案說明（Claude、GPT／Codex、Gemini 共用）

專案：MCU 上每次配戴自我校正的肌電介面＋輔助機械臂（碩士論文）。`CLAUDE.md`、`GEMINI.md` 都引用這份；規則只改這裡。

## 先讀什麼
1. `claude/memory/MEMORY.md` 和它列出的檔案：作者的偏好、規則、做過的決定、進行中的工作。資料夾名稱是 claude，但內容給任何助手用。
2. `docs/接續工作指南.md` 第 3 節：目前進度和下一步。
3. `README.md`、`ARCHITECTURE.md`、`docs/接手指南.md`。
4. 研究紀錄的正本是 `report.md`：第 35 節是現在的主線，`docs/report索引.md` 依主題分類。數字一律以 report 和 `results/` 為準。

## 溝通
- 用**繁體中文**。
- 每完成一個階段先停下來報告；長的步驟先說大概要多久。
- 不確定就說不確定；推測要標明是推測。

## 執行環境（作者的電腦：Windows 11＋WSL2 Ubuntu 22.04）
- 分析和模擬在 WSL2 的 Docker 裡跑：映像 `rf-emg`（`docker/run.sh build`）。
  - 單次指令：`docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --shm-size=2g -v "$PWD":/work -w /work rf-emg python ...`
  - 資料夾用 `-v` 掛進去（路徑見各程式開頭和 `docs/資料.md`）。自我測試錄音在 `D:\selftest_data`，掛成 `/sd`。
- 輔助控制的單元測試只要 numpy：`src/assist/*_test.py`、`src/pc/sim/kinova_trials_test.py`、`tools/local-monitor/test_rules.py`。
- ROS 2 Humble、Gazebo 在同一個 WSL；韌體在 Windows 用 STM32 的工具建置（`firmware/README.md`）。
- repo 放在 WSL 的檔案系統（`~/model-leaf`），不要放 `/mnt/c`。
- 實機前一定要跑 `src/pc/s7_test/loop_jitter.py 300`，要 PASS：WSL 的 kernel tick 曾經被改掉，時鐘慢 5 %（report 35.109）。

## 規則
1. **所有數字都要來自實際執行的結果**；估算一定標「估算」。沒有板子就不報 MCU 上的時間。
2. **要下結論的實驗，判準先寫好並 commit，再跑**；沒通過也照實寫進 report（新的一節：為什麼、怎麼做、數字、結果檔、限制）。
3. **凍結的東西不改**：
   - 板子韌體 `rtl_task_s7f`（git tag）；
   - S7 判準（report 35.86）；
   - 預先登錄的判準（`results/*/PREREG_*.md`）。
   - 要改就是新版本，重新登錄。
4. C 程式改了，要用 `src/check_*.py` 和 PC 參考逐位元比對；改了 `rt_lda.c`、`decision.c`、`ldacal.c`，要重跑閉迴路模擬（`src/assist/closed_loop_fw.py`）確認預設值重現舊結果。
5. `src/assist/modes.py`、`src/pc/ExperimentPanel.cs`、`src/pc/sim/make_world.py` 是 CRLF 換行，修改時保留原本的換行。
6. 大小一律 1 KB = 1024 bytes。
7. 每完成一個階段就 commit；**push 前先問作者**。個人的 EMG 錄音不要放進 repo（公開）。
8. 實機一定要有人顧急停；作者以外的受試者要先有 IRB 和指導教授同意。
9. **論文的文字**（`docs/thesis/`）：
   - 只引用作者給的文獻，格式（作者，年份）；
   - 缺文獻寫【此處需補文獻】；
   - 缺結果寫【待填】，不要自己填數字。
   - 詳見 `claude/memory/thesis-writing-rules.md`。
10. LLM、語音、VLA 相關的是副專案或未來工作，不進論文主線。

## 更新工作記憶
- 有新的決定或進度時，在 `claude/memory/` 新增或更新一個 md 檔（開頭的 frontmatter 格式照現有的檔案），並在 `MEMORY.md` 加一行索引。
- 寫明日期，不要和現有的檔案重複。
