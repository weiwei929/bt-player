# BT-Player Deploy Baseline (Phase 0)

最小可运行基线，目标是“先可长期驻守，再做体验优化”。

## 1) 后端服务（systemd）

1. 复制并调整：
   - `deploy/bt-player.service.example` -> `/etc/systemd/system/bt-player.service`
2. 关键项按机器实际值修改：
   - `User/Group`
   - `WorkingDirectory`
   - `ExecStart`
   - `BT_PLAYER_CACHE_DIR`
   - `BT_PLAYER_API_TOKEN`（建议生产开启）
3. 启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bt-player
sudo systemctl status bt-player
```

## 2) Caddy 入口

1. 复制并调整：
   - `deploy/Caddyfile.example` -> `/etc/caddy/Caddyfile`
2. 替换域名和鉴权密码哈希（`basic_auth`）。
3. 重载：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## 3) 缓存防写爆（timer）

1. 复制并调整：
   - `deploy/bt-player-cache-guard.service.example` -> `/etc/systemd/system/bt-player-cache-guard.service`
   - `deploy/bt-player-cache-guard.timer.example` -> `/etc/systemd/system/bt-player-cache-guard.timer`
2. 启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bt-player-cache-guard.timer
sudo systemctl list-timers | grep bt-player-cache-guard
```

## 4) 快速验收

- `curl -sS http://127.0.0.1:9528/health` 返回 `{"status":"ok"}`
- 未携带 token 请求 `/api/*` 返回 401（启用 `BT_PLAYER_API_TOKEN` 时）
- `ss -lntup` 中后端端口仅监听 `127.0.0.1`
- `journalctl -u bt-player -n 100 --no-pager` 可看到启动与错误日志

## 5) 云导出占位链路验证（不接入实时播放）

脚本：`scripts/cloud_export_smoke.sh`

- 无 token:

```bash
API_BASE=http://127.0.0.1:9528 ./scripts/cloud_export_smoke.sh
```

- 有 token:

```bash
API_BASE=http://127.0.0.1:9528 API_TOKEN=your-token ./scripts/cloud_export_smoke.sh
```

可选：启用占位 worker（默认关闭）后，任务会自动从 `queued` 推进到 `exporting/done`：

```bash
sudo systemctl edit bt-player
# 增加：
# [Service]
# Environment=BT_PLAYER_CLOUD_EXPORT_WORKER_ENABLED=true
sudo systemctl restart bt-player
```

接口说明（本 Phase 占位版）：

- `POST /api/cloud-exports` 创建任务
- `GET /api/cloud-exports` 查询任务
- `POST /api/cloud-exports/status` 更新任务状态（`id` 在 JSON body 内）
