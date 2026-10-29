# slides/ — 產生「碩論題目討論」簡報的腳本

簡報檔本身不在 repo 裡，放在 Windows 的 `C:\Users\kirit\Downloads\`（WSL 裡是 `/mnt/c/Users/kirit/Downloads/`）。
**2026-10-27 起只改 `碩論題目討論_MOMO_v17.pptx` 這一份（直接覆寫），不再新增簡報檔。** 之前每一版都是從上一版加內容，不覆寫舊檔。資料夾裡只留最新一版的腳本；下表是歷史紀錄，
`update17.py` 之前的腳本（和 `make_nums.py`、`nums*.json`）已刪除，要看可以從 git 歷史拿（`git log -- slides/`）：

| 腳本 | 輸入 → 輸出 | 內容 |
|---|---|---|
| `build.py` | `碩論題目討論_MOMO.pptx`（原檔）→ v2 | 前置結果①–③、改時程／設備／下一步（之後使用者手動改成 18 頁的 v2） |
| `build3.py` | 使用者改過的 v2 → v3 | 前置結果③換成實測、新增④（偽標籤方法） |
| `build5.py` | v3 → v5 | 新增⑤（int16 buffer、buffer 大小、32 葉樹限制、256 KB 以下）、⑥（t-SNE 運算時間）；④的說明框接到⑤（v4 是中間版，已被 v5 取代） |
| `build6.py` | v5（使用者確認未改動）→ v6 | 論點檢查：修正創新點（Zanghieri 2023 [19] 已在 GAP9 做免標籤特徵層對齊）、重要性補文獻 [17][18]、RQ 與方法依前置結果更新、避免過度宣稱（估算、目標）、新增「前置結果總結」與參考文獻 3/3、第 13 頁 552 B |
| `build7.py` | v6（使用者確認未改動，md5 2a41ba14…）→ v7 | 新增⑦（t-SNE 迭代次數：500 次時 PC 時間減半、準確率無顯著差異）；⑥指向⑦、總結頁加「運算」、頁碼 11–18（數字在 `nums5.json`） |
| `build8.py` | 使用者改過的 v6（2026-10-18 19:09，md5 62c1086b…：刪掉參考文獻 3/3 的「＊ 快速檢索」註）→ `build7.py` → v8 | 新增⑧（整條自我校正改用 C，準確率和 sklearn 相同）、⑨（Cortex-M7 linker 實測 RAM 245 KB）、⑩（跨兩天 demo，1 人）；⑥的 MCU 卡片指向⑧⑨、總結頁更新、頁碼 11–21（數字在 `nums6.json`） |
| `build9.py` | v8（使用者確認未改動，md5 27d8eb68…）→ v9 | 收斂方向：嵌入式自我校正為核心、Kinova Gen3 離散指令閉迴路任務為主要驗證（STM32 決策、PC 只用 Kortex API 轉送）、低信心拒絕、PCA 對齊基準 [19]；RQ2／RQ3、創新點③、總結、實驗設計、設備需求更新；新增「研究範圍」「閉迴路架構」「一年時程」三頁；高齡者改未來工作、int8 CNN 改選做；架構圖與流程圖是原簡報的圖片，只在下方加註記；頁碼依新舊對照自動重編 |
| `build10.py` | 使用者改過的 v9（2026-10-19 23:00，md5 b2e2960f…，27 頁）→ v10 | 精簡與去模板化：主線 20 頁（前置結果 10 頁併成 6 頁，加「前置結果」分隔頁），其餘移到「附錄」（不刪）；全部頁面拿掉深色「→ 下一步」長條、數字卡片外框，深色卡片改淺色細框，標題去掉「前置結果⑤：」等前綴並對齊；552 B、t-SNE ablation、C 端到端準確率併到保留的頁面；頁碼重新計算 |
| `build12.py` | 使用者的 v11（= v10 拿掉附錄，2026-10-19 23:10）→ v12 | 給教授的精簡版（16 頁）：新增「我想做的事」開場頁（一句話、已做到／還沒人做／接下來一年、需要老師同意的事，數字從結果頁讀）；只留最接近的研究、RQ、架構、方法、6 頁重現與前置結果、研究範圍；參考文獻只留有引用的 10 篇並重新編號 |
| `build13.py` | 使用者改過的 v12（2026-10-20 00:07，md5 577fc746…，只改第 2 頁第三欄）→ v13 | 加最新實驗（18 頁）：RAM 頁改成三個版本的 linker 實測（253.2 → 246.5 → 223.8 KB，`results/ram_history.csv`）、C 端到端 83.23%；demo 頁換成 16 位元 P 之後的曲線（92.4%）；新增「通道數」「電極轉一格」兩頁；第 2、3、5 頁的數字跟著更新，第 2 頁加兩點、開發板改 H753ZI；參考文獻加 [11] Campbell 2024、[12] Orlandi 2026。直接讀 `results/*.csv`，不用 nums*.json |
| `build14.py` | v13（使用者未改動，2026-10-25 20:32:58）→ v14 | 第 15 頁「電極轉一格」換成更正後的數字（轉原始 EMG 再標準化，`shift_sweep_raw*_uhc.csv`：固定 45.9％、UHC 比固定更差）；新增第 16 頁「束帶情境」（部分偏移＋開機對齊，`shift_sweep_raw*.csv`）；第 2 頁對應那一點與備註（19 頁） |
| `build15.py` | v14（使用者未改動，2026-10-25 21:41）→ v15 | 韌體 v2：第 10 頁換成「偽標籤不需要 t-SNE」（`embed_sweep_summary*.csv`）、第 11 頁換成「類別平衡 z-score 更新」（`zscore_sweep_summary_bal.csv`）、第 12 頁換成 v2 的 RAM 175.9 KB 與 C 對照 83.87%（`ram_history.csv`、`adapt_c_check*.csv`）；第 2–6、13、16 頁的 223.8 KB／t-SNE／87% 跟著更新（19 頁，t-SNE 迭代那頁被取代） |
| `build16.py` | v15（使用者未改動，2026-10-27 12:21）→ v16 | 參考文獻前加兩頁「工作紀錄」（10/17–10/24、10/25–10/27）：每天做了什麼與結果；10/24 之後的數字讀 `results/*.csv`，之前的數字是 report.md 摘要的數字（腳本檢查都出現在 report.md）；21 頁 |
| `build17.py` | v16（2026-10-27）→ v17 | 「工作紀錄（2/2）」加一列：比較組 Zanghieri 2023 [8] PCA 對齊（`pca_baseline_summary.csv`）；第 3 頁貢獻②和備註加上同資料比較的結果（v2 比 [8] 高 3.6–32.9 點）；21 頁 |
| `update17.py` | v17 → v17（直接修改，不再出新版） | 每次修改是一個會檢查是否已套用的步驟，可重跑；先寫暫存檔，全部成功才取代 v17。2026-10-29：第 12 頁的「MCU 時間：待上板」換成板子實測（`bench_board_64mhz_nocache.txt`）、工作紀錄（2/2）加 10/29 一列並改到 10/29、表頭改成含板子實測 |

所有數字都從 `results/` 讀，不手打：

```bash
# repo 根目錄；Docker image 需含 python-pptx（docker/requirements.txt）
# results/ram_history.csv comes from `python3 src/ram_history.py` on the host
D=/mnt/c/Users/kirit/Downloads
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -v "$D":/d -w /work rf-emg \
  python slides/update17.py /d/碩論題目討論_MOMO_v17.pptx
```

v15 的底稿是 Downloads 裡的 v14（`build14.py` 產生，已刪除；要重新產生 v14 得從 git 歷史拿回 `build14.py` 和 v13）。

改完先確認使用者沒有手動改過上一版（例如比對 md5）；改過的話要以使用者的版本為底稿，不要從舊版重新產生。

## 渲染檢查（PowerPoint，Windows）

`render.ps1` 用 PowerPoint COM 把每一頁輸出成 PNG（使用者有其他簡報開著時不會關掉 PowerPoint）。從 WSL 呼叫：

```bash
powershell.exe -ExecutionPolicy Bypass -File "$(wslpath -w slides/render.ps1)" \
  -In 'C:\Users\kirit\Downloads\碩論題目討論_MOMO_v5.pptx' -OutDir 'C:\Users\kirit\AppData\Local\Temp\slides_png'
```

## 注意（這份簡報的版面）

- CONTENT 版面配置沒有可用的標題佔位符：新頁的標題是複製既有頁面的標題形狀（`Text 0`）。
- 使用者用每頁左下角一個無填色的 `Rectangle` 蓋住頁尾文字；新頁也要複製一個放在最上層。
- 講者備註母片少了本文佔位符：新頁的備註要從既有頁面複製備註欄位。
- 逐點設定的資料標籤會丟掉數列的數字格式，要在 `<c:dLbl>` 裡自己加 `<c:numFmt>`。
