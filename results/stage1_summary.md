# 階段 1：環境與重現 — 摘要

## 環境
- Python 3.12.4（Windows 11），venv：numpy 2.1.2、scipy 1.14.1、scikit-learn 1.5.2、joblib 1.6.0
- 上游 repo commit `48ea4d1fd22a525c88ffa5462b14dc7ccfa998ea`（2024-12-05）
- 上游程式完全沒設亂數種子；`src/run_upstream.py` 在執行前呼叫 `np.random.seed(N)`。
  同一個 seed 重跑兩次，demo 的結果逐位元相同（已驗證）。arm_position 跑了 seed 0/1/2。

## 方法整理（讀程式碼得到，括號是對應的位置）
**前處理／特徵**（`demo_feature_extract.py`）
- 每個 channel 用 4 階 Butterworth 帶通 10–500 Hz，`scipy.signal.lfilter`（單向、因果，初始狀態 0）。
- 視窗 200 ms（400 點），步長 100 ms（200 點）。每個 trial 4000 點 → 19 個視窗，只取後 1 秒（第 9–18 個視窗）＝ **每個 trial 10 筆**。
- 每個視窗、每個 channel 10 個特徵 → 80 維，順序為
  `[RMS, WL, SSC, ZC, MAV, SKW, VCF, MDF, MNF, PKF] × 8ch`（特徵為主序，同一特徵的 8 個 channel 相鄰）。
  SSC/ZC 門檻 = 0；頻域特徵用 Welch（Hamming、nperseg=400、nfft=512）。
- 正規化：用該受試者 calibration 資料的 mean/std 做 z-score，測試資料也套同一組。

**One-shot 校正**（`emg_functions.prune` + `append`）
- Calibration 是每個手勢 1 個 trial ＝ 6 × 10 = 60 筆樣本。
- 預訓練模型 200 棵樹 → 用 60 筆 calibration 資料做 **由下往上剪枝**：從最深的葉節點開始，看把父節點變成葉節點（標籤 = 落入該子樹的 calibration 樣本的眾數）後，calibration 準確率是否**嚴格提高**（`acc_prune > acc_node`）；有提高才剪。
- 再用同樣 60 筆從頭訓練 **200 棵新樹**（sklearn 預設參數），**附加**在後面 → 400 棵樹。

**自我校正**（`buffer_update` + `manifold_clustering` + `replace`）
- 每個 testing block（300 筆）結束後，把該 block 的特徵連同模型預測標籤放進緩衝區，**上限 1500 筆**（約 5 個 block）。滿了就從「目前數量最多的偽標籤類別」中刪掉最舊的一筆。
- **沒有信心門檻**：buffer 內所有樣本都會使用，`get_predictions` 回傳的 score 沒被拿來篩選。
- 偽標籤：用 RF 預測緩衝區 → 若每一類都至少 `min_sample_class = 10` 筆，就把每一類截到最少類的筆數（類別平衡），做 t-SNE（3 維、perplexity 10）→ 用各類中心當初始值做 K-Means（k = 6），用分群結果當偽標籤；如果有類別不到 10 筆，就直接用 RF 預測當偽標籤（同樣做類別平衡）。
- 用「偽標籤樣本 + 60 筆真標籤 calibration」訓練 **80 棵新樹**，隨機取代 200 棵附加樹中的 80 棵；200 棵剪過枝的預訓練樹永遠保留。

## 程式和論文描述不一致的地方（會影響之後的 C 移植）
1. **剪枝條件**：論文 Algorithm 1 寫 `Error(pruned) ≤ Error(tree)`（不變差就剪），程式寫 `acc_prune > acc_node`（嚴格變好才剪）。
2. **偽標籤初始化用的模型**：論文寫「current RF model」，程式每次都用 `mdl_prune_append`（一開始的 one-shot 模型），不是目前已更新的模型。
3. **比較方向**：`get_predictions` 用 `x < threshold` 往左，sklearn 和剪枝用的 `findLeafIdHeight` 用 `x <= threshold`。在 C 移植時要選定其中一種（階段 3 會驗證）。
4. Bootstrap 比例：JNE 寫 7%，Frontiers 寫 2%（只影響預訓練，我們直接用作者提供的模型，所以不受影響）。

## 結果（3 個 seed 平均，20 位受試者）
見 `baseline_by_position.csv`、`paper_comparison.csv`、`baseline_blocks.png`。

| 方法 | P2 | P4 | P5 | P6 | P8 | 全部 block |
|---|---|---|---|---|---|---|
| LDA（只用 calibration） | 69.59 | 70.15 | 75.99 | 71.47 | 73.06 | 72.41 |
| RF（只用 calibration） | 75.67 | 77.84 | 77.37 | 76.25 | 78.66 | 77.18 |
| 預訓練 RF（不校正） | 68.09 | 70.35 | 71.46 | 70.36 | 73.62 | 70.84 |
| **固定：one-shot RF** | 78.09 | 81.04 | 81.17 | 78.63 | 81.63 | **80.21** |
| **自我校正 RF** | 82.24 | 85.59 | 84.95 | 83.88 | 86.33 | **84.63** |

跟 Frontiers 2024 論文的文字/Table 1 數字比較：自我校正 RF 全部 block 平均 84.63 ± 8.58%（論文 84.6 ± 8.5%）；
LDA 的數字和論文到小數第一位都一樣（LDA 沒有亂數）；所有增益的差異都 < 1 個百分點。
one-shot 增益略低於論文（−0.1 到 −0.4），論文值都落在我們 3 個 seed 的範圍內；
自我校正增益略高於論文（+0.1 到 +0.8），P2（論文 3.3，我們 3.77–4.70）和 P8 的論文值落在我們 seed 範圍外。

Demo（JNE 2025 的 1 位受試者，3 個 seed）：固定 one-shot 81.9% → 自我校正 90.0%。
JNE 論文報告的是 28 人平均（固定模型 84.3% → 78.6%；自我校正 84.3% → 86.2%、第 2 天 82.8% → 86.5%），
不是這位受試者的數字，所以只能做趨勢比較，不能直接比數值。
