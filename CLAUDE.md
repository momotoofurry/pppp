# 專案：在 STM32H7 上實現有記憶體預算、不需要標籤的自我校正 RF 肌電手勢控制（碩士論文前置研究）

使用者是碩士生，用**繁體中文**溝通。每完成一個階段先停下來報告；長時間的步驟要先說大概要多久。

## 位置
- 主要 repo：WSL 的 `~/model`（Windows：`\\wsl.localhost\Ubuntu-22.04\home\momo1234\model`）。舊的 `C:\Users\kirit\Downloads\model` 只保留、不再使用。
- 上游程式與資料：`external/self-calibrating-rf`（Jiang et al.，commit 48ea4d1，git-ignored，1.7 GB）。
- 簡報檔：`/mnt/c/Users/kirit/Downloads/碩論題目討論_MOMO_v*.pptx`；產生腳本在 `slides/`（見 `slides/README.md`）。
- 詳細結果與說明：`report.md`（總報告）、`results/stage*_summary.md`、`results/platform_check.md`、`results/advisor_summary.md`。

## 執行環境（一律在 Docker 裡跑）
- image `rf-emg`：`docker/run.sh build`；步驟見 `docker/run_all.sh`、`README.md`。
- 單次指令：`docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --shm-size=2g -v "$PWD":/work -w /work rf-emg python ...`
- 機器 20 核；`src/selfcal_sweep.py` 用 joblib 20 個 worker，t-SNE 版約每 60 個 task 15 分鐘，沒有 t-SNE 快很多。
- 平行的大實驗不要同時跑（會互搶 CPU）；量時間的實驗要在 CPU 空閒時跑。

## 規則（使用者明確要求或這次學到的）
1. **所有數字都要來自實際執行的結果**；跑不出來就說跑不出來，估算值一定要標「估算」。MCU 上的 cycle／時間沒有板子就不報。
2. **同一個比較只用同一個平台的數字**：report 第 1–5 節大多是 Windows 上的結果；Docker（Linux）上的自我校正結果不會逐位元相同（例：完整模型 84.66% vs Windows 84.43%）。新實驗都在 Docker 跑，對照組也要在 Docker 重跑。
3. 自我校正對執行緒數敏感：比對 commit 的結果時要單執行緒（`src/verify_platform.py` 已處理）。
4. **改簡報前先比對 md5，確認使用者有沒有手動改過上一版**；改過就以使用者的版本為底稿，另存新版本號，不覆寫舊檔。
5. 上游程式碼不改；新功能用選項加在 `src/selfcal_sweep.py`，預設值必須重現舊結果（用 `docker/run.sh verify` 確認）。
6. 每個階段完成就 commit（作者 kirit / kirito520530@gmail.com，訊息結尾加 Co-Authored-By 行）。

## 目前的結論（推薦設定：100 棵、深度 10、int16 門檻，Flash 88.1 KB，推論 RAM 實測 552 B）
- PC 重現：自我校正 84.63%（論文 84.6%）。完整模型的偽標籤 ablation 也重現了（84.66 / 80.89 / 82.16 vs 論文 84.6 / 81.0 / 82.7）。
- 拿掉 t-SNE（只用 K-Means／不分群）增益從 +4.30 掉到 +1.35／+1.96。
- 不必拿掉 t-SNE：int16 buffer 無損失；buffer 375 筆 ＋ 新樹 max_leaf_nodes 32 → 83.44%、增益 +3.76、RAM 估算 219 KB（< 256 KB），和基準無顯著差異；250 筆開始明顯變差。
- 下一個瓶頸：t-SNE 運算時間（PC 單執行緒 375 筆 2.1 s，每次都跑滿 1000 次迭代），MCU 上未量。
- t-SNE 迭代減到 500 次（`--tsne-iter`）：83.27%、增益 +3.59，vs 1000 次 −0.17 不顯著（p = 0.14），PC 時間 1.96 → 1.01 s；400 次以下顯著變差（report 3.7）。
- 降低 perplexity（`--tsne-perplexity` 3/5/7）：PC 上不省時間（時間在 octree 排斥力，不在近鄰項），只省近鄰表 RAM，準確率較低 → 維持 perplexity 10（report 3.8）。
- **上板前的 C 實作都完成了（report 第 6 節）**：`src/c/` 的 tsne.c、kmeans.c、rf_train.c、selfcal.c、features.c，全部靜態記憶體。
  PC 端到端 83.04%（sklearn 83.27%，p = 0.20），各段都無顯著差異；Cortex-M7 linker 實測 RAM 自我校正約 223.6 KB、完整管線約 245.0 KB。
  `src/c/main_selfcal.c` 已包好 DWT cycle 計數，板子到了直接燒錄量時間。selfcal_sweep 新選項：`--tsne-impl c`、`--kmeans-impl c`、
  `--train-impl c`、`--features-dir`、`--dataset demo`（預設值都重現舊結果）。

## 建議的下一步
1. ~~減少 t-SNE 迭代次數~~（完成，report 3.7）、~~降低 perplexity~~（完成，沒用，report 3.8）。
2. ~~C 版 t-SNE、K-Means、建樹、自我校正迴圈、特徵擷取~~（完成，report 第 6 節）。
3. 等 NUCLEO-H743ZI2：燒錄 `main_selfcal.c`（`build/selfcal_arm/`，`src/build_arm_selfcal.py`），量 cycle 數、確認板上預測和 PC 相同。
