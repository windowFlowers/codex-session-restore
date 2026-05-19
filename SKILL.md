---
name: codex-session-restore
description: Restore important Codex Desktop/App local sessions from session UUIDs or JSONL logs into new App-visible conversations. Use when a user says Codex cannot restore a conversation, asks whether a session ID exists locally, wants one or more Codex session IDs recovered, or wants the same non-destructive local recovery flow that clones JSONL session logs, updates session_index.jsonl, and inserts rows into state_5.sqlite.
---

# Codex Session Restore

## Overview

Use this skill to recover Codex Desktop local conversations when the original session exists on disk but the App cannot reopen it normally. The workflow creates new restored session copies and leaves original JSONL files unchanged.

## Quick Start

Run the bundled script from this skill folder:

```bash
python scripts/restore_codex_sessions.py <session-id> [<session-id> ...]
```

Useful options:

```bash
python scripts/restore_codex_sessions.py <ids...> --dry-run
python scripts/restore_codex_sessions.py <ids...> --cwd "C:\Users\CZX\Desktop\low_light"
python scripts/restore_codex_sessions.py <ids...> --title-prefix "恢复副本"
python scripts/restore_codex_sessions.py <ids...> --backup-root "C:\Users\CZX\Documents\Codex\session-backups"
```

If the shell is unreliable, run the script with the bundled Python through Node or another available execution path. Keep the operation local and do not browse.

## Workflow

1. Run `--dry-run` first unless the user explicitly asks to restore immediately.
2. Confirm the script finds each requested ID, validates the JSONL, and reports `invalid_json_lines: 0`.
3. Run without `--dry-run` to create restored copies.
4. Report the new session IDs, titles, restored JSONL paths, and backup directory.
5. Tell the user to look in Codex App recent conversations for the restored titles; if the sidebar does not refresh, restart Codex App.

## Safety Rules

- Never edit or delete the original session JSONL.
- Always keep backups of `session_index.jsonl`, `state_5.sqlite`, and each source JSONL before mutation.
- Create a new UUID for every restored session; do not reuse the old session ID.
- Update only structured `session_meta.payload.id`, `session_meta.payload.cwd`, and `event_msg.payload.thread_id` fields in the copied JSONL. Do not global-replace text inside messages or tool outputs.
- Prefer the original thread `cwd` from `state_5.sqlite` when it still exists. Use `--cwd` only when the user wants a specific workspace for the restored conversation.
- Treat restored conversations as historical records: message history and tool outputs can be recovered, but terminal processes, SSH sessions, browser state, and background jobs may not be alive.

## Output Expectations

Summarize results in Chinese when the user asks in Chinese. Include:

- old ID -> new ID
- restored title
- restored JSONL path
- JSON line count and parse result
- backup path

If a session ID is not found, report that clearly and do not fabricate a recovered conversation.
