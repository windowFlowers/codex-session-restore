#!/usr/bin/env python3
"""Clone local Codex Desktop session logs into new App-visible conversations."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def uuidv7() -> str:
    """Generate a UUIDv7-like identifier matching Codex session id shape."""
    ts_ms = int(time.time() * 1000)
    rand = secrets.token_bytes(10)
    b = bytearray(16)
    b[0] = (ts_ms >> 40) & 0xFF
    b[1] = (ts_ms >> 32) & 0xFF
    b[2] = (ts_ms >> 24) & 0xFF
    b[3] = (ts_ms >> 16) & 0xFF
    b[4] = (ts_ms >> 8) & 0xFF
    b[5] = ts_ms & 0xFF
    b[6] = 0x70 | (rand[0] & 0x0F)
    b[7] = rand[1]
    b[8] = 0x80 | (rand[2] & 0x3F)
    b[9:16] = rand[3:10]
    h = "".join(f"{x:02x}" for x in b)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_stamp(dt: datetime | None = None) -> str:
    d = datetime.now() if dt is None else dt.astimezone()
    return d.strftime("%Y-%m-%dT%H-%M-%S")


def clean_extended_path(value: str | None) -> str | None:
    if not value:
        return value
    return value[4:] if value.startswith("\\\\?\\") else value


def db_cwd(value: str) -> str:
    clean = clean_extended_path(value) or value
    return clean if clean.startswith("\\\\?\\") else "\\\\?\\" + clean


def user_codex_home() -> Path:
    if os.environ.get("CODEX_HOME"):
        return Path(os.environ["CODEX_HOME"])
    return Path.home() / ".codex"


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    text = path.read_text(encoding="utf-8")
    ends_with_newline = text.endswith("\n")
    records: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception as exc:  # noqa: BLE001 - diagnostic script
            invalid.append({"line": index, "error": str(exc), "snippet": line[:200]})
    return records, invalid, ends_with_newline


def write_jsonl(path: Path, records: list[dict[str, Any]], trailing_newline: bool = True) -> None:
    text = "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in records)
    if trailing_newline:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def find_session_files(codex_home: Path, session_id: str) -> list[Path]:
    roots = [codex_home / "sessions", codex_home / "archived_sessions"]
    matches: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            if session_id in path.name:
                matches.append(path)
    return sorted(matches, key=lambda p: (0 if "sessions" in p.parts else 1, -p.stat().st_mtime))


def latest_index_title(codex_home: Path, session_id: str) -> str | None:
    index = codex_home / "session_index.jsonl"
    if not index.exists():
        return None
    title = None
    for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
        if session_id not in line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        title = item.get("thread_name") or title
    return title


def open_state_db(codex_home: Path, readonly: bool = False) -> sqlite3.Connection | None:
    path = codex_home / "state_5.sqlite"
    if not path.exists():
        return None
    if readonly:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    else:
        con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def get_thread_row(codex_home: Path, session_id: str) -> dict[str, Any] | None:
    con = open_state_db(codex_home, readonly=True)
    if con is None:
        return None
    try:
        row = con.execute("select * from threads where id=?", (session_id,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def make_title(prefix: str, index_title: str | None, db_row: dict[str, Any] | None, session_id: str) -> str:
    base = index_title or (db_row or {}).get("title") or session_id
    base = " ".join(str(base).split())
    if len(base) > 36:
        base = base[:36].rstrip()
    return f"{prefix}-{base}" if prefix else base


def infer_cwd(records: list[dict[str, Any]], db_row: dict[str, Any] | None, override: str | None) -> str:
    if override:
        return clean_extended_path(override) or override
    if db_row and db_row.get("cwd"):
        return clean_extended_path(str(db_row["cwd"])) or str(db_row["cwd"])
    for record in records:
        if record.get("type") == "session_meta":
            cwd = (record.get("payload") or {}).get("cwd")
            if cwd:
                return clean_extended_path(str(cwd)) or str(cwd)
    return str(Path.cwd())


@dataclass
class RestorePlan:
    old_id: str
    new_id: str
    title: str
    source: str
    restored_file: str
    line_count: int
    invalid_json_lines: int
    session_meta_updates: int
    structured_thread_id_updates: int
    cwd: str
    backup_dir: str


def backup_sqlite(codex_home: Path, destination: Path) -> None:
    source = codex_home / "state_5.sqlite"
    if not source.exists():
        return
    src = sqlite3.connect(source, timeout=10)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def copy_dynamic_tools(con: sqlite3.Connection, old_id: str, new_id: str) -> None:
    try:
        tool_cols = [row[1] for row in con.execute("pragma table_info(thread_dynamic_tools)").fetchall()]
        if not tool_cols:
            return
        con.execute("delete from thread_dynamic_tools where thread_id=?", (new_id,))
        rows = con.execute(
            "select * from thread_dynamic_tools where thread_id=? order by position",
            (old_id,),
        ).fetchall()
        placeholders = ",".join(["?"] * len(tool_cols))
        for row in rows:
            data = dict(row)
            data["thread_id"] = new_id
            con.execute(
                f"insert or replace into thread_dynamic_tools ({','.join(tool_cols)}) values ({placeholders})",
                [data.get(col) for col in tool_cols],
            )
    except sqlite3.Error:
        return


def upsert_thread_rows(codex_home: Path, plans: list[RestorePlan], original_rows: dict[str, dict[str, Any] | None]) -> None:
    con = open_state_db(codex_home, readonly=False)
    if con is None:
        return
    try:
        cols = [row[1] for row in con.execute("pragma table_info(threads)").fetchall()]
        placeholders = ",".join(["?"] * len(cols))
        now_s = int(time.time())
        now_ms = int(time.time() * 1000)
        for plan in plans:
            old = original_rows.get(plan.old_id) or {}
            row = {
                "source": "vscode",
                "model_provider": "openai",
                "sandbox_policy": "{\"type\":\"danger-full-access\"}",
                "approval_mode": "never",
                "tokens_used": 0,
                "has_user_event": 0,
                "archived": 0,
                "cli_version": "0.131.0-alpha.9",
                "memory_mode": "enabled",
                "thread_source": "user",
                **old,
            }
            row.update(
                {
                    "id": plan.new_id,
                    "rollout_path": plan.restored_file,
                    "created_at": now_s,
                    "updated_at": now_s,
                    "created_at_ms": now_ms,
                    "updated_at_ms": now_ms,
                    "cwd": db_cwd(plan.cwd),
                    "title": plan.title,
                    "first_user_message": plan.title,
                    "preview": plan.title,
                    "archived": 0,
                    "archived_at": None,
                }
            )
            con.execute(
                f"insert or replace into threads ({','.join(cols)}) values ({placeholders})",
                [row.get(col) for col in cols],
            )
            copy_dynamic_tools(con, plan.old_id, plan.new_id)
        con.commit()
    finally:
        con.close()


def append_session_index(codex_home: Path, plans: list[RestorePlan], timestamp: str) -> None:
    index = codex_home / "session_index.jsonl"
    text = index.read_text(encoding="utf-8") if index.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    for plan in plans:
        text += json.dumps(
            {"id": plan.new_id, "thread_name": plan.title, "updated_at": timestamp},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        text += "\n"
    index.write_text(text, encoding="utf-8")


def restore(args: argparse.Namespace) -> dict[str, Any]:
    codex_home = Path(args.codex_home).expanduser().resolve()
    backup_root = Path(args.backup_root).expanduser().resolve() if args.backup_root else Path.cwd() / "session-backups"
    timestamp = iso_z(now_utc())
    stamp = local_stamp()
    session_dir = codex_home / "sessions" / datetime.now().strftime("%Y") / datetime.now().strftime("%m") / datetime.now().strftime("%d")

    plans: list[RestorePlan] = []
    original_rows: dict[str, dict[str, Any] | None] = {}
    diagnostics: list[dict[str, Any]] = []

    for old_id in args.session_ids:
        matches = find_session_files(codex_home, old_id)
        if not matches:
            diagnostics.append({"old_id": old_id, "status": "not_found"})
            continue
        source = matches[0]
        records, invalid, trailing_newline = read_jsonl(source)
        db_row = get_thread_row(codex_home, old_id)
        original_rows[old_id] = db_row
        index_title = latest_index_title(codex_home, old_id)
        new_id = uuidv7()
        title = make_title(args.title_prefix, index_title, db_row, old_id)
        cwd = infer_cwd(records, db_row, args.cwd)
        restored_file = session_dir / f"rollout-{stamp}-{new_id}.jsonl"

        session_meta_updates = 0
        thread_id_updates = 0
        copied_records: list[dict[str, Any]] = []
        for record in records:
            item = json.loads(json.dumps(record))
            if item.get("type") == "session_meta" and isinstance(item.get("payload"), dict):
                item["payload"]["id"] = new_id
                item["payload"]["cwd"] = cwd
                item["payload"]["thread_source"] = "user"
                item["payload"].setdefault("originator", "Codex Desktop")
                if session_meta_updates == 0:
                    item["timestamp"] = timestamp
                    item["payload"]["timestamp"] = timestamp
                session_meta_updates += 1
            elif isinstance(item.get("payload"), dict) and item["payload"].get("thread_id") == old_id:
                item["payload"]["thread_id"] = new_id
                thread_id_updates += 1
            copied_records.append(item)

        backup_dir = backup_root / old_id
        plan = RestorePlan(
            old_id=old_id,
            new_id=new_id,
            title=title,
            source=str(source),
            restored_file=str(restored_file),
            line_count=len(records),
            invalid_json_lines=len(invalid),
            session_meta_updates=session_meta_updates,
            structured_thread_id_updates=thread_id_updates,
            cwd=cwd,
            backup_dir=str(backup_dir),
        )
        plans.append(plan)
        diagnostics.append(
            {
                **asdict(plan),
                "status": "planned" if args.dry_run else "pending_write",
                "source_candidates": [str(p) for p in matches],
                "invalid_examples": invalid[:3],
                "trailing_newline": trailing_newline,
            }
        )

    if args.dry_run:
        return {"dry_run": True, "codex_home": str(codex_home), "plans": diagnostics}

    if not plans:
        return {"dry_run": False, "codex_home": str(codex_home), "restored": [], "diagnostics": diagnostics}

    batch_backup = backup_root / f"batch-restore-{stamp}"
    batch_backup.mkdir(parents=True, exist_ok=True)
    if (codex_home / "session_index.jsonl").exists():
        shutil.copy2(codex_home / "session_index.jsonl", batch_backup / "session_index.before.jsonl")
    backup_sqlite(codex_home, batch_backup / "state_5.before.sqlite")
    session_dir.mkdir(parents=True, exist_ok=True)

    for plan in plans:
        backup_dir = Path(plan.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan.source, backup_dir / Path(plan.source).name)
        source_records, invalid, trailing_newline = read_jsonl(Path(plan.source))
        if invalid:
            raise RuntimeError(f"Refusing to restore {plan.old_id}: source JSONL has invalid lines")
        copied_records = []
        session_meta_updates = 0
        for record in source_records:
            item = json.loads(json.dumps(record))
            if item.get("type") == "session_meta" and isinstance(item.get("payload"), dict):
                item["payload"]["id"] = plan.new_id
                item["payload"]["cwd"] = plan.cwd
                item["payload"]["thread_source"] = "user"
                item["payload"].setdefault("originator", "Codex Desktop")
                if session_meta_updates == 0:
                    item["timestamp"] = timestamp
                    item["payload"]["timestamp"] = timestamp
                session_meta_updates += 1
            elif isinstance(item.get("payload"), dict) and item["payload"].get("thread_id") == plan.old_id:
                item["payload"]["thread_id"] = plan.new_id
            copied_records.append(item)
        write_jsonl(Path(plan.restored_file), copied_records, trailing_newline=trailing_newline)
        verify_records, verify_invalid, _ = read_jsonl(Path(plan.restored_file))
        if verify_invalid or len(verify_records) != plan.line_count:
            raise RuntimeError(f"Restored file verification failed for {plan.old_id}")
        (backup_dir / "latest-restore-info.json").write_text(
            json.dumps({**asdict(plan), "created_at": timestamp, "batch_backup_dir": str(batch_backup)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    append_session_index(codex_home, plans, timestamp)
    upsert_thread_rows(codex_home, plans, original_rows)

    return {
        "dry_run": False,
        "codex_home": str(codex_home),
        "batch_backup_dir": str(batch_backup),
        "restored": [asdict(plan) for plan in plans],
        "diagnostics": diagnostics,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_ids", nargs="+", help="Codex session UUIDs to restore")
    parser.add_argument("--codex-home", default=str(user_codex_home()), help="Codex home directory, default: CODEX_HOME or ~/.codex")
    parser.add_argument("--backup-root", help="Directory for backups, default: ./session-backups")
    parser.add_argument("--cwd", help="Workspace cwd to assign to restored sessions")
    parser.add_argument("--title-prefix", default="恢复副本", help="Prefix for restored App titles")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print planned changes without writing")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        result = restore(args)
    except Exception as exc:  # noqa: BLE001 - command-line diagnostics
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
