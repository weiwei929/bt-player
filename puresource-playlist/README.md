# puresource-playlist

轻量 **PureSource / Playlist** 服务骨架：资源登记（`intake`）+ PotPlayer 可订阅的 **M3U 路由清单**（扩展名 `.m3u8`，**不是** HLS 分片）。

> **放置位置（本机事实源）**：建议整个目录位于  
> `D:\workspace\media\bt-player-new\puresource-playlist`  
> 若在其它环境生成，请复制到上述路径后再开发。

## 边界（勿越界）

- 不做 Web 播放器、不做全量 HLS/fMP4、不做 ffmpeg relay、不做本地 helper / 自定义协议。
- 不接 qBittorrent、ffmpeg、yt-dlp；存储为本地 **JSON 文件**（`data/resources.json`）。
- **不修改**本仓库外现网 `deploy` / Caddy；仅在下文给出反代建议。

## 产品边界：资源调度台，不重造下载器

PureSource 的定位不是替代 PikPak、qBittorrent、油猴脚本、资源站解析器或 PotPlayer。它负责统一登记资源、记录状态、接收外部工具产出的可用出口，并生成 PotPlayer/VLC/mpv 可消费的播放列表。

当前原则：

- PotPlayer 是播放执行层，要充分利用它的网络 URL、外部播放列表和格式兼容能力。
- PureSource 只做资源登记、状态、来源、候选出口和播放列表路由。
- 不强制把所有资源转成统一格式，不为了浏览器播放而过度清洗资源。
- 只要资源有一个 PotPlayer 可打开的出口，就可以进入 `external_ready`。
- PikPak、油猴脚本、外部解析器、人工提交的直链，都可以作为 PureSource 的上游输入。
- magnet enrich 第一阶段只做 URI 解析（`info_hash` / `dn` / `trackers`），不接 DHT、peer、libtorrent、qBittorrent 或 rqbit。

一句话：PureSource 是播放器生态的资源调度台，不是新的下载器或播放器内核。

## 准入规则

进入 `default.m3u8` / `recent.m3u8` 的资源：`status` 必须为 **`stable` | `playable` | `external_ready`**（`POST /intake` 由 Pydantic 枚举约束）。其它状态若未来扩展，需改模型后再进列表。

## 启动

```bash
cd puresource-playlist
python3 -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8090
```

健康检查：`GET http://127.0.0.1:8090/health`

## 提交样例资源（intake）

```bash
curl -sS -X POST http://127.0.0.1:8090/intake ^
  -H "Content-Type: application/json" ^
  -d "{\"title\":\"样例正片\",\"stream_url\":\"https://example.com/video.mp4\",\"status\":\"external_ready\",\"note\":\"演示\"}"
```

Linux/macOS 将 `^` 换为 `\`。

列出资源：

```bash
curl -sS http://127.0.0.1:8090/resources
```

拉取播放列表（PotPlayer 用「外部播放列表 / 网络播放列表」）：

```bash
curl -sS http://127.0.0.1:8090/playlists/potplayer/default.m3u8
curl -sS http://127.0.0.1:8090/playlists/potplayer/recent.m3u8
```

## 本机案例推演记录（2026-05-11）

结论：**PureSource 工作台第一阶段本机推演通过**。本次推演只验证本机 `127.0.0.1:8190`，不代表已经 cutover 到现网。

通过链路：

```text
输入 MP4 直链
→ 创建 task：stage=pending、status=None、stream_url=None
→ probe：stage=playable
→ promote：stage=external_ready、status=external_ready、stream_url 写入
→ default.m3u8 出现该资源
```

验证样本：

- 可播 MP4：`https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4`
- magnet 待提纯样本：`magnet:?xt=urn:btih:2CBB4A34738EEFC45A677E4848A303ABA9412798`

关键验收结果：

- MP4 直链经 `probe` 后可进入 `playable`，经 `promote` 后进入 PotPlayer 播放列表。
- magnet 仅登记为 `source_kind=magnet`、`stage=pending`，不自动 probe，不产生 `stream_url`，不进入 `default.m3u8`。
- 普通网页 URL 仅登记为 `source_kind=webpage`、`stage=pending`；第一版不抓网页正文、不解析 YouTube/嵌入播放器、不误判为 failed。
- `default.m3u8` 当前只输出 `status in {stable, playable, external_ready}` 且 `stream_url` 非空的资源。

本机实测 `default.m3u8` 输出示例：

```text
#EXTM3U
# PureSource playlist router — not HLS segments
# default: all eligible resources
#EXTINF:-1,https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4 [external_ready]
https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4
```

注意：浏览器打开 `.m3u8` 时可能显示黑色视频框，这是浏览器尝试按媒体播放导致；本文件的目标消费者是 PotPlayer 外部播放列表，**不是**浏览器 HLS 播放。

## PotPlayer 配置示例

1. 确认服务已监听（如上 `8090`）。
2. **收藏夹 / 外部播放列表**（不同版本菜单位置略有差异）→ 添加 **URL**：
   - `http://127.0.0.1:8090/playlists/potplayer/default.m3u8`
   - 或 `http://127.0.0.1:8090/playlists/potplayer/recent.m3u8`
3. 列表内每一行 `stream_url` 需为 PotPlayer 可直接打开的 **绝对 URL**（若需 Basic/API 头，由上游网关或 URL 内嵌凭证解决，本服务不处理）。

公网示例（部署后把主机与端口换成你的域名与 HTTPS）：

```text
https://playlist.example.com/playlists/potplayer/default.m3u8
```

## 后续 Caddy 反代建议（仅文档，不改现网）

在独立子域或路径下反代到本服务，例如：

```text
playlist.example.com {
    reverse_proxy 127.0.0.1:8090
}
```

若与现有站点同域，可增加 matcher 仅转发 `/playlists/*` 到本进程，**避免**被前端 `file_server` 吞掉。

## Cutover 前审查备忘（2026-05-11）

以下三点在同步回本机事实源后仍须保留，**上线 / cutover 前必须逐项验证**。

### 1. 管理工作台与 Basic Auth 的关系

若静态首页在公网**无** Basic Auth，而 `/tasks*`、`/intake`、`/resources` 由 Caddy 做 Basic Auth，则前端 `fetch('/tasks', …)` 在部分浏览器下可能**只收到 401**，**不一定会弹出**浏览器原生登录框，用户可能误以为工作台坏了。

**Cutover 前在现网（如 `bt.mgtv.dev`）手验：**

1. 打开工作台首页；
2. 点击「创建任务」等会调用 `/tasks` 的操作；
3. 确认浏览器能否完成 Basic Auth（弹窗或已缓存凭据）；
4. 在开发者工具 Network 中确认 `/tasks` 等请求是否携带 `Authorization` 头。

若体验不顺，建议将**工作台静态页本身**也纳入受保护路径（例如 `/admin` 或 `/workbench`），由 Caddy `basic_auth` 与私有 API 同一套凭据保护，避免「页面可见、接口全 401」的割裂体验。

### 2. Caddy cutover 与前端认证链路一体验证

Cutover **不是**仅把 `/tasks`、`/tasks/*` 加进 `@pure_private` 就结束：

- 工作台页面若仍由 `file_server` 在 `/` 公网提供，必须与「用户如何对 `/tasks*` 完成认证」**一起**验收整条链路（见上节）。
- **`/playlists/potplayer/*` 必须保持公网无认证**，供 PotPlayer 订阅；该约束在改 Caddy 时不得破坏；改完后用匿名请求再验一次 `default.m3u8` 仍为 200。

### 3. 数据迁移与回滚风险

首次以 v0.2 代码读写生产 `data/resources.json` 时，会把文件**重写为 v0.2 结构**（含 `stage`、`source_url` 等字段）。

**Cutover 前必须备份**（生产路径示例）：

- `/opt/puresource-playlist/data/resources.json`

若需回滚到仅理解 v0.1 的旧代码：要么**恢复上述备份**，要么手工从 JSON 中**剔除** v0.2 新增字段，否则旧版 Pydantic 可能因多余字段校验失败。

## 未做事项（第一版故意留空）

- 鉴权（API Key / Basic）、HTTPS 终止、限流。
- `movies.m3u8` / `debug.m3u8`、更细准入与去重策略。
- 与 BT-Player / rqbit 的自动同步；当前仅手工 `intake`。
- 数据库与迁移；仍以 `data/resources.json` 为准。
