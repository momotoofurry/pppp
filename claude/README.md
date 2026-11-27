# Claude 的工作記憶

`memory/` 是作者和 Claude Code 合作時累積的記憶檔（2026-11-28 的狀態）：作者的偏好和規則、做過的決定、進行中的工作。`MEMORY.md` 是索引，每一行指向一個檔案。

新的 Claude 工作階段或新帳號要接上時：
- 直接請它先讀 `claude/memory/MEMORY.md` 和列出的檔案；或
- 複製到 `~/.claude/projects/<專案代號>/memory/`，讓它自動載入（見 `docs/接續工作指南.md` 第 1 節）。

記憶反映寫下當時的狀態；提到的檔名、commit、設定，使用前先確認還存在。
