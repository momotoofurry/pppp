# 跨平台驗證：Windows（原始結果） vs. Docker（Linux）

日期：2026-10-17。原本 commit 的結果都是在 Windows 11 上跑的
（conda-forge Python 3.12.3、numpy 2.1.2、scipy 1.14.1、scikit-learn 1.5.2、MinGW gcc 8.1、WSL2 裡的 arm-none-eabi-gcc 10.3.1）。
Docker image（`docker/Dockerfile`）：Ubuntu 22.04、Python 3.12.3（uv）、同樣的套件版本、gcc 11.4、arm-none-eabi-gcc 10.3.1，
numpy 用 scipy-openblas 0.3.27。在 WSL2 上執行，專案放在 `~/model`（Linux 檔案系統）。

## 結論
| 部分 | Linux vs. Windows | 證據 |
|---|---|---|
| 特徵擷取 | 10 種特徵中有 7 種**逐位元相同**；MNF、偏度、VCF 只差最後一位（相對誤差 ≤ 7e-15）。arm_position 1720/2400 個檔案、demo 79/110 個檔案逐位元相同 | `logs/linux/features_compare.log` |
| 預測（向量化 vs. 上游） | 相同 | `logs/linux/verify_platform_linux_features.log` [1] |
| 壓縮掃描（subject 0、seed 0，60 個設定 × 11 個 block） | 660/660 列**完全相同**（準確率和模型大小） | 同上 [2] |
| One-shot 準確率（20 人 × 3 seed × 11 block） | 660/660 列**完全相同**（80.03%） | `logs/linux/selfcal_linux_vs_windows.log` |
| C 匯出、PC 檢查、Cortex-M7 編譯 | text/data/bss/stack 和預測**完全相同**（只有建置時間、路徑字串不同） | `logs/linux/stage3_docker.log` |
| **自我校正準確率** | **不是逐位元相同**；只有 157/660 個 block 一樣 | 見下表 |

## 自我校正（400 棵、深度不限、float64，20 人 × 3 seed）
| | seed 0 | seed 1 | seed 2 | 平均 | seed 範圍 |
|---|---|---|---|---|---|
| Windows（commit 的結果） | 84.38 | 84.08 | 84.83 | 84.43 | 84.08–84.83 |
| Linux（Docker） | 84.68 | 84.50 | 84.81 | **84.66** | 84.50–84.81 |

- 每個 (seed, 受試者) 的差（Linux − Windows）：平均 +0.23 個百分點，SD 0.85，範圍 −1.30 到 +3.76（n = 60）。
- 20 人（seed 平均後）的 Wilcoxon 檢定：p = 0.040。Linux 略高，但差異小於 Windows 自己 seed 之間的差距（0.75 個百分點），而且只有 3 個 seed。
  目前的證據不足以判斷這是系統性的平台效應還是偶然。
- 兩邊都和論文（84.6%）、上游重現（84.63%）一致。

## 原因（實測）
- 自我校正的鏈條是 t-SNE → K-Means 偽標籤 → 重新訓練樹 → 下一個 block 的 buffer，對極小的浮點差異非常敏感：
  - Linux 單執行緒和多執行緒的結果也不一樣（subject 0：自我校正後附加樹的平均節點數差 4.28 和 7）。
  - **Windows 單執行緒**（和原本 joblib worker 的條件一樣）可以**逐位元重現**原本 commit 的結果（`verify_platform.py --full`）。
  - 所以 Windows 上的結果是可以重現的；差異來自平台的 BLAS / 編譯器 / 執行緒數，不是程式錯誤。
- 用 Linux 自己擷取的特徵和用 Windows 的特徵跑，自我校正的結果完全相同。所以特徵最後一位的差異沒有影響，差異完全出在自我校正這一段。

## 對論文的建議
1. **同一張表、同一個比較裡的數字要來自同一個平台和同樣的執行緒設定。** 之後新的實驗都在 Docker 裡跑，
   需要比較時，把對照組（例如完整模型的自我校正）也在 Docker 裡重跑，不要拿 Windows 的數字直接比。
2. 自我校正的準確率要報多個 seed 的平均和範圍。平台差異（0.23 個百分點）和 seed 差異同一個等級，所以單一 seed 的小差距不能當成結論。
3. 原本 report.md 的數字保留不變（Windows，可重現）。如果要改成全部用 Linux 的數字，就要在 Docker 裡重跑 `docker/run.sh all`（約 4 小時）。

## 重現方式
```bash
docker/run.sh build
docker/run.sh verify --full   # 單執行緒；Windows 上執行時會逐位元重現 commit 的結果
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --shm-size=2g -v "$HOME/model":/work -w /work rf-emg \
    python -u src/selfcal_sweep.py --configs 0 --suffix _validation_linux
```
注意：用 `wsl -- bash -c '...'` 從 Windows 呼叫時，`$PWD`、`$變數` 會被外層的 shell 先展開，
docker 可能因此掛載到錯的目錄。請在 WSL 的終端機裡直接執行，或用 `docker/run.sh`。
