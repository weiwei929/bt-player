# puresource-playlist cutover 执行记录（2026-05-11）

> 状态：已执行并通过验收  
> 站点：`https://bt.mgtv.dev/`  
> 执行基线：`docs/vps/puresource-playlist-cutover-checklist.md`  
> 备份戳：`20260511-162317`

## 1. 结论

`bt.mgtv.dev` 已从旧 BT-Player 前端切换为 **PureSource 资源提纯工作台**。

现网闭环已成立：

```text
工作台创建任务
-> probe
-> promote
-> 写入 status/stream_url
-> /playlists/potplayer/default.m3u8
-> PotPlayer BT资源馆刷新
-> 播放成功
```

本次 cutover 没有下线旧 Rust 服务；旧 `/api/*`、`/stream/*` 反代仍保留，作为兼容/过渡路径。

## 2. 已执行动作

### 2.1 备份

已创建以下备份：

- `/etc/caddy/Caddyfile.bak.puresource-cutover-20260511-162317`
- `/opt/puresource-playlist/backups/resources.json.bak.20260511-162317`
- `/opt/puresource-playlist/backups/app-before-cutover-20260511-162317.tgz`
- `/opt/puresource-playlist/backups/var-www-bt-player-before-cutover-20260511-162317.tgz`

其中应用备份已确认不包含 `.venv/`。

### 2.2 FastAPI 升级

生产目录：

```text
/opt/puresource-playlist
```

已同步 v0.2 代码：

- `/tasks`
- `/tasks/{id}/probe`
- `/tasks/{id}/promote`
- `/static/index.html`
- `app/probe.py`
- `app/static/app.js`
- `app/static/app.css`
- `scripts/local-smoke.sh`

已安装新增依赖：

```text
httpx 0.28.1
```

服务：

```text
puresource-playlist.service active (running)
127.0.0.1:8090
User=www-data
```

执行中发现并修复了数据目录权限问题：

```text
/opt/puresource-playlist/data
```

需要归属：

```text
www-data:www-data
```

否则新版首次写入会因无法创建 `resources.tmp` 返回 HTTP 500。

### 2.3 Caddy 路由补丁

`@pure_private` 已从：

```caddy
@pure_private path /intake /resources
```

改为：

```caddy
@pure_private path /intake /resources /tasks /tasks/*
```

保持不变：

- `/playlists/potplayer/*`：公网无认证，供 PotPlayer 订阅。
- 其它 `/playlists/*`：403。
- `/health`：公网可读。
- `/api/*`、`/stream/*`：旧 Rust 反代仍保留。

### 2.4 静态首页切换

`/var/www/bt-player/index.html` 已替换为 PureSource 工作台。

同步时未使用 `--delete`，因此保留了验收样本：

```text
/var/www/bt-player/Cosmos_Laundromat.faststart.mp4
```

静态目录权限已设为：

```text
caddy:caddy
目录 755
文件 644
```

## 3. 验收结果

从 VPS 本机通过 Caddy 复核：

```text
200 https://bt.mgtv.dev/
200 https://bt.mgtv.dev/health
401 https://bt.mgtv.dev/tasks
401 https://bt.mgtv.dev/resources
200 https://bt.mgtv.dev/playlists/potplayer/default.m3u8
403 https://bt.mgtv.dev/playlists/other/x.m3u8
```

当前 `default.m3u8`：

```text
#EXTM3U
# PureSource playlist router — not HLS segments
# default: all eligible resources
#EXTINF:-1,Cosmos Laundromat (PotPlayer 手验) [external_ready]
https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4
#EXTINF:-1,https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4 [external_ready]
https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4
```

浏览器手验：

- `https://bt.mgtv.dev/` 显示 PureSource 资源提纯工作台。
- 创建 MP4 任务成功。
- `probe` / `promote` 后资源进入 `external_ready`。

PotPlayer 手验：

- `BT资源馆` 外部播放列表可刷新。
- 可见两条 Cosmos 条目。
- 点击后可播放。

## 4. 已知副作用

### 4.1 Cosmos 重复

当前列表里有两条 Cosmos：

1. 原生产 smoke：`Cosmos Laundromat (PotPlayer 手验)`
2. cutover 验收时通过工作台 promote 的同一 MP4

这是验收副作用，不影响功能。后续可做去重/删除/归档。

### 4.2 旧静态残留

`/var/www/bt-player/assets/` 仍保留。因为本次静态同步未使用 `--delete`，目的是保护 `Cosmos_Laundromat.faststart.mp4` 验收样本。

后续清理应单独执行，不与 cutover 混在一起。

### 4.3 `resources.json` 格式

生产 `resources.json` 已在首次写入后具备 v0.2 语义。回滚到 v0.1 代码前，应恢复：

```text
/opt/puresource-playlist/backups/resources.json.bak.20260511-162317
```

## 5. 后续建议

短期清理：

- 去重 Cosmos 条目。
- 已 `external_ready` 的任务隐藏或禁用 `promote` 按钮。
- 增加“已入列”提示。
- 单独清理 `/var/www/bt-player/assets/` 等旧 SPA 残留。

下一阶段开发：

- magnet metadata 解析。
- 文件树提取。
- 正片识别。
- 缓存成熟度与可播性评分。
- 从 `pending` 资源生成可 promote 的候选 `stream_url`。

## 6. 当前路线判断

本次 cutover 证明新的项目定位成立：

```text
PureSource / BT-Player = 资源提纯 + 播放路由
PotPlayer / VLC / mpv = 播放执行层
```

浏览器播放器、全量 HLS、ffmpeg relay 继续保持冻结，不作为主线。
