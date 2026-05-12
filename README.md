# BT-Player（VPS 基线）

本仓库当前以 **VPS 现网状态** 为事实源进行维护。

## 事实源与边界

- **事实源优先级**：
  1. VPS 实际运行状态（systemd/Caddy/网络与日志）
  2. `docs/vps/BT-Player VPS Phase 0 验收记录.md`
  3. `docs/design/UPGRADE_IMPLEMENTATION_GUIDE.md`
- **历史说明**：本地旧 Tauri 项目形态仅作为历史原型参考，不作为当前生产事实源。

## Phase 0 已完成（生产基线）

- Caddy 公网入口治理（`/etc/caddy/Caddyfile`）
- API token 鉴权（`BT_PLAYER_API_TOKEN`）
- Stream basic_auth 保护（匿名访问受限）
- `cache_guard` 最低磁盘保护（service + timer）
- systemd 托管与重启策略（`/etc/systemd/system/bt-player.service`）

对应验收记录见：`docs/vps/BT-Player VPS Phase 0 验收记录.md`

Phase 1 路线评估见：`docs/vps/BT-Player Phase 1 路线论证.md`

## 不在当前 Phase 的范围

- PikPak 实时播放接入
- HLS/fMP4 输出改造
- WebRTC / 混合网关

上述项均属于后续 Phase，不在当前基线提交中实现。

