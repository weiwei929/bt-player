# puresource-playlist cutover checklist

> 状态：草案，供 cutover 前审查与 Cursor/VPS 执行使用。  
> 日期：2026-05-11  
> 范围：把本机已验证的 PureSource 工作台 v0.2 同步到 VPS，并让 `bt.mgtv.dev` 首页变为资源提纯工作台。  
> 原则：先备份、再同步、再最小 Caddy 补丁、最后验收；不在执行中重新设计。

## 0. 当前已验证边界

本机 `127.0.0.1:8190` 已完成第一阶段案例推演：

```text
MP4 直链
-> task pending
-> probe playable
-> promote external_ready
-> 写入 stream_url/status
-> 出现在 default.m3u8
```

同时已验证：

- `magnet` 只登记为 `pending`，不自动 probe，不进入 PotPlayer 列表。
- `webpage` 只登记为 `pending`，第一版不抓正文、不解析 YouTube/嵌入播放器、不误判 `failed`。
- `default.m3u8` 只输出 `status in {stable, playable, external_ready}` 且 `stream_url` 非空的资源。
- 浏览器打开 `.m3u8` 出现黑色视频框不是错误；该文件目标消费者是 PotPlayer 外部播放列表，不是浏览器 HLS。

## 1. 执行前硬性停顿点

开始前 Cursor 需要先回报以下事实，未确认不得执行 cutover：

```bash
pwd
systemctl cat puresource-playlist.service
systemctl status puresource-playlist.service --no-pager
caddy validate --config /etc/caddy/Caddyfile
```

必须确认：

- 生产应用目录是 `/opt/puresource-playlist`。
- 生产服务监听 `127.0.0.1:8090`。
- 生产 `data/resources.json` 存在或确认为空库。
- Caddy 当前配置可 validate。
- 当前不会触碰 `/root/BT-player` 和旧 Rust/Tauri 树。

## 2. 备份

执行前必须备份四类文件（含静态站点目录，便于与 §5 解耦；§5 不再重复备份命令）。

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"

cp -a /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.puresource-cutover-${STAMP}"

mkdir -p /opt/puresource-playlist/backups
if [ -f /opt/puresource-playlist/data/resources.json ]; then
  cp -a /opt/puresource-playlist/data/resources.json \
    "/opt/puresource-playlist/backups/resources.json.bak.${STAMP}"
fi

tar czf "/opt/puresource-playlist/backups/app-before-cutover-${STAMP}.tgz" \
  --exclude='puresource-playlist/.venv' \
  --exclude='puresource-playlist/backups' \
  -C /opt puresource-playlist

tar tzf "/opt/puresource-playlist/backups/app-before-cutover-${STAMP}.tgz" | grep -E '(^|/)\.venv/' && {
  echo "ERROR: backup tar contains .venv; stop and inspect tar --exclude order"
  exit 1
} || true

tar czf "/opt/puresource-playlist/backups/var-www-bt-player-before-cutover-${STAMP}.tgz" \
  -C /var/www bt-player
```

回报备份路径后再继续。

## 3. 同步代码到生产目录

源目录以 Cursor 当前 VPS 工作树为准：

```text
/root/bt-player-new/puresource-playlist
```

目标目录：

```text
/opt/puresource-playlist
```

建议同步命令：

```bash
rsync -avh \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='data/resources.json' \
  --exclude='data/resources.json.before-*' \
  --exclude='*.log' \
  --exclude='docs/' \
  /root/bt-player-new/puresource-playlist/ \
  /opt/puresource-playlist/

chown -R www-data:www-data /opt/puresource-playlist/app /opt/puresource-playlist/scripts /opt/puresource-playlist/requirements.txt /opt/puresource-playlist/README.md
chmod +x /opt/puresource-playlist/scripts/*.sh
```

注意：

- 不覆盖生产 `data/resources.json`。
- 不同步 `.venv`。
- 不同步本机测试日志。

## 4. 安装生产依赖

v0.2 新增 `httpx`，生产 venv 必须安装依赖。

```bash
cd /opt/puresource-playlist
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m py_compile app/models.py app/store.py app/playlist.py app/probe.py app/main.py
```

若依赖安装失败，停止 cutover，回滚应用目录或保留旧服务继续运行。

## 5. 同步静态工作台到 `/var/www/bt-player`

**执行顺序注意**：本节实际执行应放在第 6 节 Caddy 补丁 validate、第 7 节服务重启、第 8.1 节本机回环验收以及 `systemctl restart caddy` 之后。这样新首页上线前，公网 `/tasks*` 已经进入 Basic Auth + 反代路径，避免短暂落入 SPA `try_files` 返回 HTML 200。

本次选择方案 B：Caddy 继续用 `file_server` 托管首页，FastAPI 只负责 API/任务/播放列表。

**静态目录已在 §2 备份**（`var-www-bt-player-before-cutover-${STAMP}.tgz`），此处不再重复 `tar`；直接同步新静态页：

```bash
rsync -avh \
  /opt/puresource-playlist/app/static/ \
  /var/www/bt-player/

chown -R caddy:caddy /var/www/bt-player/
find /var/www/bt-player -type d -exec chmod 755 {} \;
find /var/www/bt-player -type f -exec chmod 644 {} \;
```

注意：

- 这是会改变 `bt.mgtv.dev` 首页的动作。执行前需要确认已经进入 cutover 阶段。
- 本次先不使用 `--delete`，因为 `/var/www/bt-player/Cosmos_Laundromat.faststart.mp4` 是 cutover 验收样本；若删除它，`https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4` 会变成 404，导致 probe/播放验收失效。
- 等 cutover 完成且样本资源迁出后，再单独清理旧 `assets/` 等残留文件。

## 6. Caddy 最小补丁

目标：把新增 `/tasks`、`/tasks/*` 纳入与 `/intake`、`/resources` 相同的 Basic Auth 私有保护面。

保持不变：

- `/playlists/potplayer/*`：公网无认证，供 PotPlayer 订阅。
- 其它 `/playlists/*`：403，避免被 SPA 吞掉。
- `/health`：公网可读。
- 旧 `/api/*`、`/stream/*`：本次 checklist 不主动删除，除非另有明确 cutover 决策。

期望 matcher 形态：

```caddy
@pure_private path /intake /resources /tasks /tasks/*
basic_auth @pure_private {
    admin <现有 bcrypt hash>
}
handle @pure_private {
    reverse_proxy 127.0.0.1:8090
}
```

建议先改 Caddy matcher 并 validate，但在新代码服务确认可启动前不要 restart Caddy。

修改后：

```bash
caddy validate --config /etc/caddy/Caddyfile
```

当前 Caddy 全局 `admin off`，不要使用依赖 `localhost:2019` 的 `caddy reload`。

## 7. 重启 puresource 服务

```bash
systemctl daemon-reload
systemctl restart puresource-playlist.service
systemctl status puresource-playlist.service --no-pager
journalctl -u puresource-playlist.service -n 80 --no-pager
```

若服务无法启动：

1. 不改 Caddy，或立即回滚 Caddy。
2. 查看是否缺 `httpx`。
3. 必要时恢复备份的应用目录和 `resources.json`。

## 8. 验收命令

### 8.1 本机回环

```bash
curl -sS http://127.0.0.1:8090/health
curl -sS http://127.0.0.1:8090/static/index.html | head -5
curl -sS http://127.0.0.1:8090/tasks
curl -sS http://127.0.0.1:8090/playlists/potplayer/default.m3u8 | head
```

本机回环确认后，再重启 Caddy 使公网路由补丁生效：

```bash
systemctl restart caddy
```

此时再执行第 5 节，把 `app/static/` 同步到 `/var/www/bt-player/`。

### 8.2 公网匿名路径

```bash
HOST=https://bt.mgtv.dev

curl -sS "$HOST/health"
curl -sS "$HOST/playlists/potplayer/default.m3u8" | head
curl -sS -o /dev/null -w '%{http_code}\n' "$HOST/playlists/other/x.m3u8"
curl -sS -o /dev/null -w '%{http_code}\n' "$HOST/resources"
curl -sS -o /dev/null -w '%{http_code}\n' "$HOST/tasks"
```

预期：

```text
/health -> 200
/playlists/potplayer/default.m3u8 -> 200
/playlists/other/x.m3u8 -> 403
/resources 未认证 -> 401
/tasks 未认证 -> 401
```

### 8.3 带认证管理路径

密码不得写入仓库。由运维在 shell 中输入或临时环境变量提供。

```bash
HOST=https://bt.mgtv.dev

curl -sS -u 'admin:你的密码' "$HOST/tasks"
curl -sS -u 'admin:你的密码' -X POST "$HOST/tasks" \
  -H 'Content-Type: application/json' \
  -d '{"source_url":"https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4","title":"Cosmos cutover smoke"}'
```

然后在工作台页面手验：

1. 打开 `https://bt.mgtv.dev/`。
2. 创建 MP4 任务。
3. 触发 `probe`。
4. 确认 `stage=playable`。
5. `promote` 后确认 `stage=external_ready`、`status=external_ready`。
6. 匿名打开 `https://bt.mgtv.dev/playlists/potplayer/default.m3u8`，确认该条出现。
7. PotPlayer 订阅 `https://bt.mgtv.dev/playlists/potplayer/default.m3u8`，确认可播放。

重点观察：

- 浏览器是否能对 `/tasks*` 完成 Basic Auth。
- Network 面板中 `/tasks`、`/tasks/{id}/probe`、`/tasks/{id}/promote` 是否带 `Authorization`。
- PotPlayer 拉 `/playlists/potplayer/*` 不应要求用户名密码。

## 9. 失败回滚

### 9.1 回滚 Caddy

```bash
cp -a "/etc/caddy/Caddyfile.bak.puresource-cutover-${STAMP}" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl restart caddy
```

### 9.2 回滚静态页

```bash
rm -rf /var/www/bt-player
mkdir -p /var/www
tar xzf "/opt/puresource-playlist/backups/var-www-bt-player-before-cutover-${STAMP}.tgz" -C /var/www
```

### 9.3 回滚数据

如果新版已经读写过 `resources.json`，旧版可能无法读取 v0.2 字段。回滚旧代码前必须恢复备份：

```bash
systemctl stop puresource-playlist.service
cp -a "/opt/puresource-playlist/backups/resources.json.bak.${STAMP}" \
  /opt/puresource-playlist/data/resources.json
chown www-data:www-data /opt/puresource-playlist/data/resources.json
systemctl start puresource-playlist.service
```

### 9.4 回滚应用目录

```bash
systemctl stop puresource-playlist.service
rm -rf /opt/puresource-playlist/app /opt/puresource-playlist/scripts /opt/puresource-playlist/requirements.txt /opt/puresource-playlist/README.md
tar xzf "/opt/puresource-playlist/backups/app-before-cutover-${STAMP}.tgz" -C /opt
chown -R www-data:www-data /opt/puresource-playlist
systemctl start puresource-playlist.service
```

## 10. 执行后记录

执行完成后，Cursor 需要回报：

- 实际备份文件路径。
- `systemctl status puresource-playlist.service` 摘要。
- Caddy validate/restart 结果。
- 匿名路径验收结果。
- 带认证 `/tasks` 验收结果。
- PotPlayer 是否仍可订阅并播放。
- 是否发生数据迁移，以及 `resources.json` 备份路径。

验收通过后，再把本文件更新为“已执行记录”或另存为带日期的执行记录。
