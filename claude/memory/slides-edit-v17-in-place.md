---
name: slides-edit-v17-in-place
description: "Decks: old-direction v17, the 2026-11-13 proposal, and the 2026-12 progress report are each one file edited in place"
metadata:
  node_type: memory
  type: feedback
  originSessionId: c782b928-dcd9-4756-880c-3c824dcf5be9
  modified: 2026-11-18T13:38:36.427Z
---

From 2026-10-27 on, changes to the old-direction deck go into `C:\Users\kirit\Downloads\碩論題目討論_MOMO_v17.pptx` itself (overwrite that file); do not create `_v18.pptx`.

On 2026-11-13 the user chose to put the new-direction proposal ("計畫書") in a separate new file instead of v17 (v17 stays untouched as the old direction). That proposal deck is likewise a single file edited in place from then on; do not create further version files of it.

On 2026-11-14 the user asked for a December progress-report deck as its own file: `C:\Users\kirit\Downloads\進度報告_2026-12_MOMO.pptx` (builder `slides/progress.py`, reuses the proposal.py helpers and loader; md5 after the latest write 780a19f0961013329324838b587c6c18, 50 slides in conference order (7 sections with dividers); math written as native PowerPoint equations via slides/omml.py, with the computation steps shown). It is also a single file edited in place. The user wants it light: for every paper one slide with its method and one with its own reported results, then my comparison; one idea per slide, no cramming.

**Why:** the user said (2026-10-27) that they only want v17 and no new deck files; on 2026-11-13, asked about the proposal for the new direction, they picked "新增一份計畫書檔" over appending it to v17.

**How to apply:** one builder script per deck that reads the deck and writes it back (temp file first, then replace); before overwriting, check the file's mtime/md5 against the last write by Claude, and if the user edited it, build on their version. Supersedes the per-version builder rule in [[slides-keep-latest-builder]] for new versions.

**2026-11-17 rebuild (user: "PPT幫我大改", then "你直接給我新的PPT好了"):** the new deck is `C:\Users\kirit\Downloads\進度報告_2026-12_MOMO_新版.pptx`.
- 59 slides: main line 34, appendix 25. md5 f712e571a750582fbe868203e90cd608.
- `slides/progress.py` now builds this storyline: problem → why switch → methods → public-data validation (DB2, Ozdemir, GrabMyo) → MCU → self-test → conclusions, then the appendix.
- The old `進度報告_2026-12_MOMO.pptx` (md5 5cf27d63…) is left as it was.
- From now on, edit the 新版 file in place.

**2026-11-18 new deck (user: "每個論點都是有證據和數據支撐，做一個PPT告訴我"):** `C:\Users\kirit\Downloads\研究方向與證據_2026-11-18.pptx`, builder `slides/direction.py` (reuses proposal.py helpers; parses results/ text files), 17 slides (claim 6b added 2026-11-18), md5 41c070a819d61a68b590abd090c459e1. Each claim slide carries an evidence-level tag (公開資料模擬 / 板子實測 / 自己的錄製 / 文獻只讀摘要 / 尚無證據). Also a single file edited in place.

**2026-11-17 update (before the rebuild):** the progress deck now describes the 4-key-muscle / 9-gesture version.
- Slides 22, 35, 40 and 49 were updated; two slides were added: 47 (placement) and 48 (public-data check).
- 52 slides; md5 after this write: 5cf27d632e0e20732b716cf6d5505e96.
- Backup of the previous version: `D:\stm32\blink_leaf\backup\進度報告_2026-12_MOMO_before_4muscle_2026-11-17.pptx`.

2026-11-15: the user hand-edited the progress deck (merged the Jiang limits into the method slide, deleted the separate Jiang results slide, removed the conclusion bar on the reproduction slide). On an md5 mismatch: diff the user's file against a fresh build (slide texts and shape boxes; equation boxes sit inside mc:AlternateContent and are invisible to python-pptx), port the user's edits into slides/progress.py, rebuild, confirm only the intended differences remain, back up the user's file, then overwrite.
