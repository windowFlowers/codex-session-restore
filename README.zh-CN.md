# Codex 会话恢复 Skill

[English README](README.md)

这个 skill 用来恢复本地仍然存在、但 Codex App 无法正常打开的历史会话。

当 Codex 提示会话恢复失败，或者你手里有一个会话 ID，但 App 侧边栏无法重新打开对应对话时，可以使用 `codex-session-restore`。它会从本机 `.codex/sessions` 和 `.codex/archived_sessions` 中查找原始 JSONL 会话日志，并创建一个新的、能在 Codex App 最近会话中显示的恢复副本。

## 解决的问题

Codex Desktop 的会话通常同时依赖本地 JSONL 日志、本地索引和 SQLite 状态数据库。某些情况下，原始会话文件还在，但 App 无法恢复：

- `session_index.jsonl` 中的记录重复、过期或不一致
- `state_5.sqlite` 中缺少对应线程行
- 会话工作目录移动或状态记录不完整
- Codex 更新、异常退出或中断后，本地索引与原始 JSONL 脱节

这个 skill 不会修改原始会话，而是创建一个新的恢复副本。

## 它会做什么

恢复流程是非破坏性的：

- 按会话 UUID 搜索本地 Codex JSONL 日志
- 写入前先验证 JSONL 是否能完整解析
- 备份原始会话、`session_index.jsonl` 和 `state_5.sqlite`
- 生成新的会话 UUID
- 创建新的 JSONL 会话副本
- 只更新结构化字段，例如 `session_meta.payload.id` 和 `event_msg.payload.thread_id`
- 不全局替换消息正文或工具输出里的文本
- 将新会话登记到 `session_index.jsonl`
- 将新线程写入 `state_5.sqlite`，让 Codex App 可以在最近会话里看到它

原始会话文件会保持不变。

## 一条命令安装

PowerShell：

```powershell
$dest = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills\codex-session-restore' } else { Join-Path $HOME '.codex\skills\codex-session-restore' }; git clone https://github.com/windowFlowers/codex-session-restore.git $dest
```

macOS / Linux：

```bash
git clone https://github.com/windowFlowers/codex-session-restore.git "${CODEX_HOME:-$HOME/.codex}/skills/codex-session-restore"
```

安装后，重启 Codex App，或者打开一个新对话，让 Codex 重新发现这个 skill。

## 在 Codex 中使用

可以直接对 Codex 说：

```text
使用 codex-session-restore 恢复这个会话 ID：019e36a8-1293-7823-9d23-ba047d04f385
```

也可以一次恢复多个会话：

```text
使用 codex-session-restore 恢复这些会话：<id-1>, <id-2>, <id-3>
```

恢复完成后，Codex 会返回新的会话 ID、恢复副本标题、JSONL 文件路径和备份目录。你可以在 Codex App 左侧最近会话中查找 `恢复副本-...` 标题。如果侧边栏没有立即刷新，重启 Codex App。

## 直接运行脚本

进入 skill 目录后运行：

```bash
python scripts/restore_codex_sessions.py <session-id> [<session-id> ...]
```

只检查、不写入：

```bash
python scripts/restore_codex_sessions.py <session-id> --dry-run
```

指定恢复副本的工作目录：

```bash
python scripts/restore_codex_sessions.py <session-id> --cwd "C:\Users\CZX\Desktop\low_light"
```

## 注意事项

这个 skill 恢复的是会话历史、工具调用记录和 Codex App 可见性。它不能让已经结束的终端进程、SSH 连接、浏览器标签页或后台训练任务重新运行。
