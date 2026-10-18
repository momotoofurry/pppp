# slides/ — 產生「碩論題目討論」簡報的腳本

簡報檔本身不在 repo 裡，放在 Windows 的 `C:\Users\kirit\Downloads\`（WSL 裡是 `/mnt/c/Users/kirit/Downloads/`）。
每一版都是從上一版加內容，不覆寫舊檔：

| 腳本 | 輸入 → 輸出 | 內容 |
|---|---|---|
| `build.py` | `碩論題目討論_MOMO.pptx`（原檔）→ v2 | 前置結果①–③、改時程／設備／下一步（之後使用者手動改成 18 頁的 v2） |
| `build3.py` | 使用者改過的 v2 → v3 | 前置結果③換成實測、新增④（偽標籤方法） |
| `build5.py` | v3 → v5 | 新增⑤（int16 buffer、buffer 大小、32 葉樹限制、256 KB 以下）、⑥（t-SNE 運算時間）；④的說明框接到⑤（v4 是中間版，已被 v5 取代） |
| `build6.py` | v5（使用者確認未改動）→ v6 | 論點檢查：修正創新點（Zanghieri 2023 [19] 已在 GAP9 做免標籤特徵層對齊）、重要性補文獻 [17][18]、RQ 與方法依前置結果更新、避免過度宣稱（估算、目標）、新增「前置結果總結」與參考文獻 3/3、第 13 頁 552 B |
| `build7.py` | v6（使用者確認未改動，md5 2a41ba14…）→ v7 | 新增⑦（t-SNE 迭代次數：500 次時 PC 時間減半、準確率無顯著差異）；⑥指向⑦、總結頁加「運算」、頁碼 11–18（數字在 `nums5.json`） |

所有數字都從 `results/` 讀，不手打：

```bash
# repo 根目錄；Docker image 需含 python-pptx（docker/requirements.txt）
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -w /work rf-emg python slides/make_nums.py
D=/mnt/c/Users/kirit/Downloads
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -v "$D":/d -w /work rf-emg \
  python slides/build7.py /d/碩論題目討論_MOMO_v6.pptx /d/碩論題目討論_MOMO_v7.pptx slides/nums5.json
```

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
