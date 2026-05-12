# puresource-playlist — VPS 部署与安全收口（2026-05-11）

本文档描述当前 VPS 上的 **puresource-playlist** 部署事实、Caddy 路由与安全策略、验收与回滚。  
**范围**：仅 FastAPI 清单服务 + 反代收口；不含 qBittorrent / ffmpeg / yt-dlp；未改 Rust 主线仓库。

---

## 1. 服务路径与进程

| 项 | 值 |
|----|-----|
| 应用根目录 | `/opt/puresource-playlist` |
| Python 虚拟环境 | `/opt/puresource-playlist/.venv` |
| 应用包 | `app.main:app` |
| 进程管理 | `systemd` unit：`puresource-playlist.service` |
| 监听 | **`127.0.0.1:8090`**（不直接对公网绑定端口） |
| 运行用户 | `www-data` |
| 数据文件（运行时） | `/opt/puresource-playlist/data/resources.json`（由 `POST /intake` 写入；勿提交到 Git） |

启动命令（由 unit 执行）：

```bash
/opt/puresource-playlist/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090
```

---

## 2. systemd

- **Unit 文件**：`/etc/systemd/system/puresource-playlist.service`
- **常用命令**：
  - `systemctl status puresource-playlist.service`
  - `systemctl restart puresource-playlist.service`
  - `journalctl -u puresource-playlist.service -f`

---

## 3. Caddy 路由（`bt.mgtv.dev`）

站点块内 **在 `@api`、`@stream`、SPA `handle` 之前**，为 puresource 拆分为多条 `handle`，顺序有意义：

| 匹配 | 行为 | 公网 |
|------|------|------|
| `path /playlists/potplayer/*` | `reverse_proxy 127.0.0.1:8090` | **可读，无 Basic Auth**（PotPlayer 订阅） |
| `path /playlists/*` 且 **非** `potplayer` 前缀 | `respond 403` | 禁止（避免误落到前端 `try_files`） |
| `path /intake`、`path /resources` | **Basic Auth** 后 `reverse_proxy 127.0.0.1:8090` | 未认证 **401** |
| `path /health` | `reverse_proxy 127.0.0.1:8090` | **公网可读**（见下文策略说明） |

其余路径仍由既有 `@api`、`@stream` 与默认静态 SPA 处理。

**配置变更注意**：当前全局 `admin off`，不要用依赖 `localhost:2019` 的 `caddy reload`。修改 `Caddyfile` 后应：

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl restart caddy
```

---

## 4. 播放列表 URL（PotPlayer）

以下 URL **无需** 在播放器里配置用户名密码（与 Basic Auth 无关）：

- `https://bt.mgtv.dev/playlists/potplayer/default.m3u8`
- `https://bt.mgtv.dev/playlists/potplayer/recent.m3u8`

说明：列表为 **EXTM3U + `#EXTINF` + 媒体 URL**，**不是** HLS 分片；Caddy 为 **反向代理**，非 `file_server`。

---

## 5. 安全策略说明

### 5.1 Basic Auth（`/intake`、`/resources`）

- 在 **Caddy 层** 对 `path /intake`、`path /resources` 启用 `basic_auth`，**未改 Python**。
- 哈希与站点内既有 **`@api` 段中的 `admin` 用户**一致（同一密码即同时满足 API 与 puresource 管理路径；若需分离账户，可另增用户并单独 `caddy hash-password`）。

### 5.2 `/health` 为何保留公网

- 响应体仅为 `{"status":"ok"}`，**不暴露业务数据**。
- 便于公网/外部探活（监控、LB）；若你希望 **零公网面**，可改为仅内网访问（例如去掉公网 `handle @pure_health`，或改为内网域名/防火墙仅允许源 IP）。当前选择：**公网可读，低信息量**。

### 5.3 本机直连 `127.0.0.1:8090`

- **不经 Caddy**，Basic Auth **不生效**；仅本机或具备 SSH 的主体可访问。收口对象是 **经 HTTPS 的公网入口**。

### 5.4 PotPlayer / 浏览器「不受影响」的含义

- **PotPlayer**：只使用上述 **`.m3u8` 公网 URL**，不经过受保护路径，**无需** Basic Auth。
- **管理操作**（登记资源、查看 JSON）：浏览器或 `curl` 应对 `https://bt.mgtv.dev/intake`、`/resources` 提供 Basic Auth，例如：  
  `curl -u 'admin:你的密码' -X POST ... https://bt.mgtv.dev/intake`

---

## 6. 验收命令（公网经 Caddy，本机可用 `--resolve` 模拟）

```bash
HOST=https://bt.mgtv.dev
# 若在本机解析到本机：
# curl 加：--resolve bt.mgtv.dev:443:127.0.0.1

# 1) 播放列表仍可读（应 200，有 #EXTM3U）
curl -sS "$HOST/playlists/potplayer/default.m3u8" | head

# 2) 未认证访问 intake（应 401）
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$HOST/intake" \
  -H 'Content-Type: application/json' -d '{"title":"x","stream_url":"https://a/b.mp4","status":"external_ready"}'

# 3) 未认证访问 resources（应 401）
curl -sS -o /dev/null -w '%{http_code}\n' "$HOST/resources"

# 4) health（应 200）
curl -sS "$HOST/health"

# 5) 非 potplayer 的 /playlists/*（应 403）
curl -sS -o /dev/null -w '%{http_code}\n' "$HOST/playlists/other/x.m3u8"
```

带认证的 intake 示例（密码由运维掌握，勿写入仓库）：

```bash
curl -sS -u 'admin:你的密码' -X POST "$HOST/intake" \
  -H 'Content-Type: application/json' \
  -d '{"title":"x","stream_url":"https://example.com/a.mp4","status":"external_ready"}'
```

---

## 7. 配置备份与回滚

### 7.1 本次安全收口前的 Caddy 备份

- 备份文件示例（以机上实际文件名为准）：  
  **`/etc/caddy/Caddyfile.bak.secure-20260511-133612`**

部署早期另有一次备份（若存在）：  
`/etc/caddy/Caddyfile.bak.20260511-133301`

### 7.2 回滚 Caddy

```bash
cp -a /etc/caddy/Caddyfile.bak.secure-20260511-133612 /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl restart caddy
```

### 7.3 停用 puresource 服务（可选）

```bash
systemctl disable --now puresource-playlist.service
```

（回滚 Caddy 后，公网不再反代到 8090；是否删除 `/opt/puresource-playlist` 由运维决定。）

---

## 8. Caddy 修改摘要（相对「全开」验证期）

- **删除** 单一 `@puresource path /health /resources /intake /playlists/*` 无鉴权反代块。
- **新增**：
  - `path /playlists/potplayer/*` → 无鉴权反代；
  - 其余 `path /playlists/*` → **403**；
  - `path /intake`、`/resources` → **Basic Auth** + 反代；
  - `path /health` → 无鉴权反代。

---

## 9. 未做事项（有意不在本轮 MVP）

- Python 内 JWT / API Key、RBAC、审计日志。
- `/intake` 与 `/api` 凭据分离（当前复用同一 `admin` 哈希）。
- 限流、WAF、GEO 封锁。
- 将 `resources.json` 迁出本地盘或加密静态存储。

---

## 10. 文档存放位置

- VPS 文件路径：**`/opt/puresource-playlist/docs/vps/puresource-playlist-vps-deploy-2026-05-11.md`**  
  （与运行实例同目录，避免修改 Rust 事实源仓库。）
- 本机 Git 副本路径：**`D:\workspace\media\bt-player-new\docs\vps\puresource-playlist-vps-deploy-2026-05-11.md`**
