# BT-Player VPS Phase 0 验收记录

> 日期：2026-05-08  
> 文档性质：Phase 0 最终验收沉淀（长期复用）  
> 适用范围：仅限 VPS 现网基线（不含后续 HLS/PikPak/WebRTC 优化）

---

## 背景与范围

本记录用于固化 BT-Player 在 VPS 上的 Phase 0 生产基线验收结果，目标是确认服务可持续运行、对外入口受控、最低缓存保护可用、运维路径清晰。

本记录只覆盖 Phase 0，不包含功能扩展与播放链路升级。

---

## 当前服务状态

- `bt-player.service`：`active (running)`
- API 监听：`127.0.0.1:9528`
- Stream 监听：`127.0.0.1:9527`
- 健康检查：`/health` 返回 `200 {"status":"ok"}`

---

## Caddy 公网入口配置

- 公网入口由 Caddy 统一承载。
- 当前 Caddy 仅监听 `80/443`。
- Caddy admin 端口 `127.0.0.1:2019` 已关闭（`admin off`）。
- Caddy 配置路径：`/etc/caddy/Caddyfile`

---

## API 鉴权状态

- 公网匿名访问 `GET /api/cloud-exports`：`401`
- 带 token 访问 `GET /api/cloud-exports`：`200`
- 结论：API 已进入“默认拒绝匿名、凭 token 放行”状态。

---

## Stream 鉴权状态

- 公网匿名访问以下路径均返回 `401`：
  - `/stream/torrents`
  - `/stream/stats`
  - `/stream/torrents/playlist`
- 结论：Stream 出口已受保护，不再匿名暴露可读状态接口。

---

## systemd 服务状态

- 主服务单元路径：`/etc/systemd/system/bt-player.service`
- 当前可用状态：`active (running)`
- 当前运行用户：`User=root`（已记录为后续待办迁移项）

---

## cache_guard timer 状态

- 已安装：
  - `/etc/systemd/system/bt-player-cache-guard.service`
  - `/etc/systemd/system/bt-player-cache-guard.timer`
- timer 当前状态：`active (waiting)` 且已 `enable`

---

## 密钥与敏感信息存放位置

- 当前密钥临时存放路径：`/root/BT-player/.phase0b-secrets.txt`
- 权限状态：`600`
- 说明：文档不记录真实 token、basic_auth 明文或 hash。

---

## 已通过验收项

1. `bt-player.service` 运行正常（`active (running)`）。
2. API/Stream 均仅监听本机回环地址（`127.0.0.1`）。
3. `/health` 返回 `200 {"status":"ok"}`。
4. API 匿名访问受限（`/api/cloud-exports` 匿名 `401`）。
5. API token 访问可用（`/api/cloud-exports` 带 token `200`）。
6. Stream 匿名访问受限（关键 `/stream/*` 路径匿名均 `401`）。
7. Caddy admin 端口 `2019` 已关闭，仅保留 `80/443`。
8. cache_guard timer 已安装并处于 `active (waiting)`。

---

## 剩余待办

1. 将 `bt-player.service` 从 `User=root` 迁移到低权限用户。
2. 将密钥迁移到更规范位置（如 `/root/.secrets/bt-player/` 或 `/etc/bt-player/`）。
3. 实施应用级缓存淘汰策略；`cache_guard` 仅作 Phase 0 防写爆兜底，不替代最终缓存治理。
4. 形成运维操作规范：每次改 Caddy 前先执行  
   `caddy validate --config /etc/caddy/Caddyfile`，再执行  
   `systemctl restart caddy`。

---

## 后续禁止事项 / 边界提醒

1. 当前 Phase 不接入 PikPak 实时播放。
2. 当前 Phase 不做 HLS/fMP4 输出改造。
3. 当前 Phase 不做 WebRTC / 混合网关。
4. 本地旧项目代码仅作为历史参考；当前事实源以 VPS 现状与本验收文档为准。

