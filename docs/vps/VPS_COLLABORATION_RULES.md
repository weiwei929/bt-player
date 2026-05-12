# BT-Player VPS Collaboration Rules

本文档用于本地 Codex 与 VPS AI 协同开发 BT-Player。当前项目以 VPS 现网为事实源，本地 `bt-player-new` 作为大本营和审阅区。

## 角色分工

- 本地 Codex：负责判断路线、编写任务指令、审阅 diff、决定是否进入主线。
- VPS AI：负责在 VPS 上执行修改、构建、重启、验证、提交临时分支。
- GitHub 临时分支：作为 VPS 与本地之间的代码交接通道。

## 基本规则

1. 不直接修改或推送 `master`。
2. 每次任务只开一个临时分支。
3. 每个临时分支只解决一个主题。
4. 先构建和现网验证，再提交。
5. 提交只包含本主题相关文件。
6. 不把 secret、token、密码、Basic Auth、API key 写入 Git。
7. systemd、Caddy、环境变量、日志回报必须脱敏。
8. 不执行 `git checkout -- .`、`git reset --hard`、批量删除等清理动作，除非本地 Codex 明确要求。
9. 不自行扩大范围；遇到相邻问题，先回报，不顺手改。
10. 本地 Codex 负责最终审阅和主线判断。

## VPS AI 标准流程

```bash
cd /root/BT-player
git status --short
git switch master
git pull --ff-only
git switch -c <task-branch>
```

完成修改后：

```bash
git diff --stat
git diff -- <changed-files>
```

## 验证分层

- 只读审阅阶段：不构建、不重启。
- 只改 Rust 后端小逻辑：优先运行 `cargo check --manifest-path src-tauri/Cargo.toml`。
- 未改前端文件时：不运行 `npm run build`。
- 未准备替换现网二进制时：不运行 `cargo build --release`。
- 准备现网替换前：再运行 `cargo build --manifest-path src-tauri/Cargo.toml --release`。
- 只有明确需要验证前端产物时，才运行 `npm run build`。
- 只有本地 Codex 明确要求现网验证时，才重启 `bt-player.service`。

如需现网验证，必须先说明将替换哪个二进制、是否需要重启服务，并在执行后回报：

```bash
systemctl status bt-player.service --no-pager
curl -s http://127.0.0.1:9528/health
curl -I http://127.0.0.1:9527/
```

验证通过后：

```bash
git add <changed-files>
git diff --cached --stat
git diff --cached --name-only
git diff --cached | grep -iE "token|password|basic_auth|api[_-]?key|secret|authorization" || true
git commit -m "<type>: <short summary>"
git push origin <task-branch>
```

## 回报格式

VPS AI 每次任务完成后按以下格式回报：

```text
分支名：
commit hash：
修改文件：
构建结果：
现网验证结果：
敏感信息检查结果：
仍未提交的本地改动：
需要本地 Codex 判断的问题：
```

## 当前开发原则

- VPS 现网状态优先于旧 Windows/Tauri/WSL 文档。
- `docs/history/` 只作历史参考。
- `docs/design/` 是设计与方案池，不等于当前执行清单。
- `docs/vps/` 和 `deploy/` 是当前部署与运行规则的主要依据。
- Phase 1 优先巩固现有 VPS 路线，不急于展开 HLS/fMP4、WebRTC、PikPak 实时播放、Jellyfin/Plex、Debrid 等分支。
