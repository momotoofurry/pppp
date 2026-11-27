# Claude Code

專案的說明和規則都在 `AGENTS.md`（Claude、GPT／Codex、Gemini 共用），請先讀它：

@AGENTS.md

Claude Code 專用：`.claude/` 裡有子代理（explorer、fixer、checker）和一個改檔後自動跑對應檢查的 hook。工作記憶也在 `claude/memory/`；同一個 Windows 使用者的 `~/.claude/projects/.../memory/` 是同一份內容的自動載入位置（見 `docs/接續工作指南.md`）。
