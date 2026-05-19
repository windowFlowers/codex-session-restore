# Codex Session Restore

[中文说明](README.zh-CN.md)

Recover local Codex Desktop sessions that still exist on disk but no longer open correctly in the Codex App.

This skill is useful when Codex reports that it cannot restore a conversation, when a session ID exists under `.codex/sessions` or `.codex/archived_sessions`, or when the local App index/database no longer points to the conversation correctly.

## What It Does

`codex-session-restore` creates a new App-visible copy of one or more existing Codex sessions.

It performs a non-destructive recovery flow:

- searches local Codex session logs by session UUID
- validates the JSONL log before writing anything
- backs up the source session, `session_index.jsonl`, and `state_5.sqlite`
- creates a new session UUID and restored JSONL copy
- updates structured session metadata without rewriting message text
- registers the restored session in `session_index.jsonl`
- inserts the restored conversation into `state_5.sqlite` so it can appear in Codex App recent conversations

The original session file is left unchanged.

## Install

PowerShell:

```powershell
$dest = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills\codex-session-restore' } else { Join-Path $HOME '.codex\skills\codex-session-restore' }; git clone https://github.com/windowFlowers/codex-session-restore.git $dest
```

macOS/Linux:

```bash
git clone https://github.com/windowFlowers/codex-session-restore.git "${CODEX_HOME:-$HOME/.codex}/skills/codex-session-restore"
```

Restart Codex App or open a new conversation after installing.

## Use In Codex

Ask Codex:

```text
Use codex-session-restore to restore this session ID: 019e36a8-1293-7823-9d23-ba047d04f385
```

Multiple sessions can be restored in one request:

```text
Use codex-session-restore to restore these sessions: <id-1>, <id-2>, <id-3>
```

## Direct Script Usage

From the skill directory:

```bash
python scripts/restore_codex_sessions.py <session-id> [<session-id> ...]
```

Preview without writing:

```bash
python scripts/restore_codex_sessions.py <session-id> --dry-run
```

Assign a specific workspace to restored sessions:

```bash
python scripts/restore_codex_sessions.py <session-id> --cwd "C:\Users\CZX\Desktop\low_light"
```

## Limits

This restores conversation history, tool-call records, and local App visibility. It cannot resurrect live runtime state such as terminal processes, SSH sessions, browser tabs, or background training jobs that already exited.
