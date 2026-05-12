# Cursor Task 04：v0.4 评审 + 执行计划（纯"谋"阶段产出）

> 角色：评审者 + 规划者（响应 `cursor-task-04-v0.4-plan.md`）
> 阶段：纯"谋"，本轮无任何源码 / 配置 / 服务写操作。仅创建本份评审文档。
> 上游：v0.3 在 :8190 开发实例验证完毕、`puresource-playlist-v0.3-cutover-checklist.md` 已落地、生产仍跑 v0.2.0。
> 日期：2026-05-12

---

## 0. 已读文件清单 + 生产侧只读探测结果

### 0.1 已读文件（按 §三顺序）

**§3.1 v0.3 现状（8 个）**

1. `puresource-playlist/docs/vps/puresource-playlist-v0.3-cutover-checklist.md`（791 行 cutover 主对象）
2. `puresource-playlist/docs/vps/puresource-playlist-cutover-checklist.md`（v0.2 切生产执行风格参考）
3. `puresource-playlist/app/main.py`（端点齐：`/tasks/{id}/extract`、`/tasks/{id}/bt-probe`、`/internal/tasks/{id}/extract-result`、`/internal/tasks/{id}/bt-probe-result`、`promote` 白名单含 `metadata_ready`）
4. `puresource-playlist/app/models.py`（`ResourceStage` 含 `extracting/bt_probing/metadata_ready`；`ResourceRecord` 含 `extract` / `expires_at` / `last_success_at`；`MagnetInfo` 含 `files/peer_count/seed_count/probed_at/main_file_index`）
5. `puresource-playlist/app/extract_worker.py`（原子 `rename → .processing.json` 抢占、`stale claim` 清理 mtime>75s、callback 0 次重试、SIGTERM 优雅退出）
6. `puresource-btprobe/puresource_btprobe/{main,qbt,models}.py`（FastAPI 入口仅 `/health` + `/probe`；`asyncio.create_task` + `run_in_executor` 后台跑；`QBT_MOCK=1` 走假数据；callback 10s timeout、0 次重试；模型字段与主服务严格对齐）
7. `puresource-playlist/app/store.py`（`_migrate_legacy` 显式 setdefault 新字段；`jobs_dir() = data_dir()/"extract-jobs"`）
8. `puresource-playlist/app/static/{index.html,app.js,app.css}`（in-flight 集合 + 5s 自轮询；文件树、候选 promote 联动；`STAGE_ORDER/PROMOTABLE` 已扩 `metadata_ready`）

**§3.2 设计与决策（3 个）**

9. `docs/design/PureSource v0.3 资源探测与视频图书馆方案.md` §4.4 生命周期展示 + §「Step 4 失效检测」预告（systemd timer 扫 `expires_at` 过期、重新 probe → 403 则 stage=failed、前端红色标记 + "重新验证 / 重新导入"）
10. `docs/design/架构设计小结.md` §2.3.2 + 「生态分工与不过度提纯原则」（红线原文：**"除非另行立项并明确接受风险，不应在 PureSource 主服务里默认接入 DHT、peer、libtorrent、qBittorrent 或 rqbit"**——这是 v0.4a 接真实 qBittorrent 时的关键边界）
11. `docs/design/cursor-task-03-review-and-plan.md`（指令面）+ §8 十裁决（按上一轮对话裁决：B 子服务/C worker 队列/`metadata_ready` 入 promote 白名单/新增三 stage/加 `expires_at` 不加 expiry-worker/callback 0 次重试/上限 1024 与 32/无迁移脚本/接受 worker 重启丢任务/接受 IP 暴露给 localhost callback）

我已读完上述 11 个文件，对 v0.3 现状与 v0.4 范围的对账完成。

### 0.2 生产侧只读探测结果（2026-05-12 11:28 CST）

| 项 | 结论 | 关键证据 |
|----|------|---------|
| **主服务版本** | **仍是 v0.2.0**（未切 v0.3） | `app/main.py` 顶部 `version="0.2.0"`；19h uptime；进程只 import `models/playlist/probe/store`，**无 extract/extract_worker/jobs_dir** |
| **8090** | 生产主服务 LISTEN（PID 1808220 / uvicorn / www-data） | `ss -lntp` |
| **8091** | ⚠️ **已被昨天的开发实例 mock btprobe 占用**（PID 1894331，CMD `/root/bt-player-new/...uvicorn puresource_btprobe.main:app --host 127.0.0.1 --port 8091`，root 用户） | 部署 v0.4a `puresource-btprobe` 前必须先杀掉这个开发态进程 |
| **8190** | 开发实例 v0.3 主服务 LISTEN（PID 1893970） | 演练可用 |
| **resources.json** | 5 条记录、stages={pending, external_ready}、2456 字节、最近写时间 2026-05-12 08:59 | 体量轻，回滚演练成本低 |
| **yt-dlp** | **未装** | `which yt-dlp` 返回空 |
| **qBittorrent-nox** | **未装** | `which`、`dpkg -l` 双双 miss |
| **Caddy** | 配置 valid；`/internal/*` deny 已就位（4 处匹配：注释 + `@pure_internal` matcher + `handle` + `respond 403`） | 上一轮预热已完成 |
| **systemd unit** | 只有 `puresource-playlist.service`；`extract-worker` / `btprobe` 未注册 | T-4a 需新增两个 unit |
| **drop-in / Environment** | 当前 unit 只有 `Environment=PYTHONUNBUFFERED=1`；**没有** `PURESOURCE_BTPROBE_BASE` / `PURESOURCE_SELF_BASE` / `PURESOURCE_COOKIES_DIR` | T-4a 需 systemd drop-in |
| **⚠️ unit changed on disk** | systemd 提示"unit file changed on disk, run daemon-reload" | 当前 unit 本身可能被外部工具/编辑器触过，需要在 T-4a 开始前 `systemctl daemon-reload` 一次确认基线 |
| **cookies 目录** | `/var/lib/puresource/cookies` 不存在 | T-4a 需 `mkdir + chown + chmod 750` |
| **磁盘** | 单分区 45G，已用 18G，余 24G（43%） | qBittorrent metadata 阶段单种子峰值 < 50MB，余量充足 |

**两个意外发现需要在 §2 / Q1 处理**：
- 8091 被开发态 btprobe 占用 → 必须显式列为 cutover 阻塞项（T-4a-04）
- "unit changed on disk" → 进 cutover 前先 `daemon-reload` 做基线对齐，避免别人改过的 unit 与文档版本不一致

---

## 1. 总体评价

1. v0.3 cutover checklist 791 行写得**密集但偏理想化**：默认 cutover 一次性切完、未给灰度路径、未演练过回滚；这是本轮 §2 的主要分歧来源。
2. 生产侧探测发现 **8091 已被开发态进程占用** 且 **systemd unit 报 "changed on disk"**，这两个 housekeeping 项必须前置处理，否则 cutover 第一步就翻车。
3. v0.3 守红线靠"子服务隔离"，v0.4a 接真实 qBittorrent 会让 VPS 出现一个跑 DHT 的进程——**红线从"主服务隔离"扩展到"VPS 网络声誉"**，新风险待裁决。
4. v0.4b 的关键不在代码量，而在 `expires_at` 写入策略与"失败几次降级、降到哪里"的语义裁决；代码本身有 v0.3 的 worker/callback 模板可复用，工时主要花在测试和前端徽章。
5. 推荐 v0.4a 走**两步 cutover**（先 worker+btprobe 不动主服务、再切主服务+真 qbt），v0.4b **串行**追加。预估 v0.4a ≈ 12-15h（运维为主）、v0.4b ≈ 16-20h（代码为主）。

---

## 2. 与本任务约定的分歧与建议

### §2-D1：cutover 时序——建议拆成两次 cutover

- 原约定：v0.3 checklist §8 写"启动顺序 btprobe → 主服务 → worker → Caddy"，并未明确"一次切完 vs 分批切"，但全文叙事接近"一次性"。
- 建议改：v0.4a 走 **cutover-1（worker + btprobe + Caddy，主服务不动）**+**cutover-2（主服务切 v0.3 + 真 qBittorrent）**两步。详见 Q1。
- 影响面：cutover 总耗时 +30min（多一次窗口），但中段可观测、回滚只回单段。
- ⚠️ 待裁决：是否接受拆两步。

### §2-D2：真实 qBittorrent 触及"网络声誉"维度，超出 §2.3.2 红线既有论证范围

- 原约定（§2.3.2）："不应在 PureSource **主服务**里默认接入 DHT/peer/qBittorrent"——v0.3 用子服务隔离了**主服务进程**。
- 建议改：v0.4a 接入真实 qBittorrent 会让 VPS 上新增一个跑 DHT/peer 的进程（即使监听端口随机化、即使无公网入站）。这条**不在 v0.3 §8 的十裁决里**，应在 §2 显式 reopen 给用户裁决。
- 影响面：VPS 公网 IP 会出现在 BT swarm 中，运营商 / DC ToS 风险（Oracle 首尔 ARM 此前未跑过 BT 网络栈）。
- ⚠️ 待裁决：是否接受 VPS 出现 BT 网络栈足迹；如不接受，则 v0.4a 永驻 `QBT_MOCK=1`、真实 qBittorrent 部署延后至专项立项。

### §2-D3：cutover 前必须做一次灰度演练

- 原约定：checklist §11 给了 8 步回滚，但**从未在真实生产演练过**。
- 建议改：v0.4a 前置一项"在开发实例 :8190 完整跑一遍 cutover + 回滚"作为强制步骤（T-4a-13），并验证 §1.4 的字段丢失风险。
- 影响面：增加 1.5h 工时；显著降低真实 cutover 风险。
- 不必裁决（建议直接采纳）：演练成本对比生产事故成本是数量级差异。

### §2-D4：cutover 前必须 `daemon-reload`，对齐基线

- 原约定：checklist 未涉及。
- 建议改：开始 T-4a 前 `systemctl daemon-reload`、`systemctl cat puresource-playlist.service` 落一份 baseline 快照，再开工。
- 影响面：< 10min；防止"别人改过 unit 但没 reload，cutover 时不知不觉走偏"。
- 不必裁决（建议直接采纳）。

### §2-D5：开发态 8091 占用必须显式纳入 cutover 前置

- 原约定：checklist 未涉及。
- 建议改：T-4a-04 显式 `kill 1894331`（或要求用户在 v0.4a 开工前手动停掉开发实例 btprobe）。
- 影响面：不停的话 `systemctl start puresource-btprobe.service` 会直接失败（addr in use）。
- 不必裁决（建议直接采纳）。

### §2-D6：v0.3 方案文档预告但未落地的字段（`verified_by` / `source_trust`）

- 原约定：v0.3 方案 §三 5) 提到 `/intake` 应支持 `verified_by` 和 `expires_in_hours`，但 v0.3 实际只落了 `expires_at` 字段，**`verified_by` / `source_trust` 仍未实现**。
- 建议改：v0.4 **不补**这两个字段——它们更接近"目录管理 / 信任分级"语义，归 v0.5。但 v0.4b 的 `_migrate_legacy` 改动应预留这两个字段的 setdefault，避免 v0.5 再次踩 §1.4 坑（即 Q12 的"埋字段"问题）。
- 影响面：仅 1-2 行 setdefault；无 API 变更。
- ⚠️ 待裁决：是否在 v0.4b 顺手预埋 `verified_by=None` / `source_trust=None`。

---

## 3. Q1–Q5（v0.4a 生产部署）

### Q1. cutover 时序：一把切 vs 分批切

**结论：推荐两次 cutover。**

| 维度 | 一把切（原 checklist） | 两次切（推荐） |
|------|---------------------|--------------|
| **窗口数** | 1 次（~30min） | 2 次（~20min + ~15min，间隔可数小时～数天） |
| **回滚复杂度** | 高（任一环节失败要回滚 4 个东西：btprobe / 主服务 / worker / Caddy） | 低（cutover-1 回滚只 2 个：worker + btprobe；cutover-2 回滚只 1 个：主服务） |
| **可观察性** | 弱（4 个变更同时上线，故障归因难） | 强（cutover-1 后用户感知零，可观察 worker 是否真有 stale job、btprobe `/health` 是否稳） |
| **用户感知** | 一次性切到 v0.3 UI | cutover-1 用户感知零；cutover-2 才看到新 stage / 文件树 |
| **真实 qBittorrent 风险** | 与代码切换混在一起，故障无法二分定位 | cutover-1 已确认基础设施 OK，cutover-2 只剩"主服务代码 + 真 qbt"两项变更 |

**推荐方案明细**：

- **cutover-1**（约 20min）：
  - 系统级：装 yt-dlp、装 qBittorrent-nox（先停掉、配置文件就位但不起）、建 cookies 目录、写 `/etc/puresource-btprobe.env`（`QBT_MOCK=1` 留着）
  - systemd：装 `puresource-extract-worker.service`、`puresource-btprobe.service` 两个 unit；`puresource-playlist.service` drop-in 增 `Environment`（先不重启主服务）
  - 起服务：`extract-worker`（空跑等 job）、`btprobe`（QBT_MOCK=1 跑假数据）
  - 主服务**不动**，仍是 v0.2.0；前端用户访问 :8090 完全无感
  - 观察 24-72h：worker 日志干净（确认没有遗留 job、`stale claim` 不误判）、btprobe `/health` 稳、Caddy `/internal/*` 仍 403
- **cutover-2**（约 15min）：
  - 备份 `resources.json`、停主服务
  - rsync v0.3 主服务代码 → `/opt/puresource-playlist`
  - 把 `QBT_MOCK=1` 改为 `QBT_MOCK=0`，restart `puresource-btprobe`
  - start `puresource-playlist`（v0.3）
  - 跑 §Q3 的 3 个真实烟测种子
  - 烟测过则放行真实用户流量；不过则回滚到 v0.2.0（resources.json 备份回滚 + 代码目录回滚）

⚠️ 待裁决：是否接受拆两步。建议接受。

---

### Q2. qBittorrent 上线策略

**结论：apt + 版本锁定 + 自定义 systemd + 最小配置 + EnvironmentFile（已够）。**

#### Q2.1 安装方式

- **推荐**：`apt install qbittorrent-nox` + `apt-mark hold qbittorrent-nox`。
- **理由**：Debian 仓自带版本对 ARM 适配充分；编译 / 静态二进制带来的版本飘移和补丁丢失风险更大；用 hold 防 unattended-upgrades 滚版。
- **版本固化**：`apt-mark hold` 即可；具体版本号"待 T-4a-06 时确认" —— 安装当天 `apt show qbittorrent-nox | grep Version` 落档到 cutover 记录。
- ⚠️ 待裁决：是否需要更严格的版本固化（例如 pin 到具体 deb 文件并提交进仓）。建议**不必**——hold 已足够。

#### Q2.2 systemd 托管

**推荐**：写一份自定义 unit，不用 distro 自带（distro 自带 unit 通常假设以登录用户跑、配置目录在 `~/.config`，不适合服务化）。

关键 `[Service]` 字段（伪配置，具体写法待 T-4a 时落地）：

```
[Service]
Type=simple
User=qbt            # 新建专用用户，不和 www-data 混
Group=qbt
WorkingDirectory=/var/lib/qbt
UMask=0027
Environment=HOME=/var/lib/qbt
ExecStart=/usr/bin/qbittorrent-nox --webui-port=8080 --profile=/var/lib/qbt
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/qbt /var/tmp/qbt-downloads
```

#### Q2.3 配置初始化（最小变更清单）

| 配置项 | 建议值 | 理由 |
|-------|--------|------|
| `Preferences/WebUI/Address` | `127.0.0.1` | 不暴露公网 |
| `Preferences/WebUI/Port` | `8080` | 与 v0.3 默认一致 |
| `Preferences/Downloads/SavePath` | `/var/tmp/qbt-downloads`（tmpfs 或独立目录） | 探测完即 `delete(deleteFiles=true)`，但保险起见限定路径 |
| `Preferences/Downloads/TorrentExportDir` | 留空 | 不写 .torrent 副本，省 IO |
| `Preferences/Bittorrent/AddTorrentPaused` | `true` | 与代码 `add_paused=true` 对齐 |
| `Preferences/Bittorrent/DefaultDownloadingMode` | `Manual` | 不自动开始 |
| `Preferences/Queueing/QueueingEnabled` | `false` | 探测任务不该被排队 |
| `Preferences/Bittorrent/StopCondition` | `MetadataReceived` | metadata 拿到就停（v0.3 方案明确点名） |
| `Preferences/Connection/PortRangeMin` | 随机 30000-50000 | 不用默认 6881 避免广为人知 |
| `Preferences/Connection/UPnPEnabled` | `false` | 不要主动开 NAT |
| `Preferences/Bittorrent/Encryption` | `Forced` | 降低 ISP 流量识别 |
| Tracker 列表 | 默认空 | metadata 主要靠 DHT；额外 tracker 留待 v0.4a 烟测后视需要补 |

**其他都可以接受默认**（webui 用户密码必改）。

#### Q2.4 存储与膨胀防护

- 代码层 `add_paused=true` + `setFilePrio=0` + 探测完 `delete(deleteFiles=true)`，已是三保险。
- qBittorrent 自己的状态文件：
  - `BT_backup/*.fastresume` / `.torrent`：每探测一个种子会暂存一份，正常 `delete(deleteFiles=true)` 时被清理；但**异常退出会残留**。
  - 建议：**软配额 5GB**（`/var/lib/qbt` 单独 mount 或 quota），**硬上限**通过 cron 周扫 `find /var/lib/qbt/BT_backup -mtime +1 -delete` 兜底。
- 日志：qBittorrent 自己的 log 默认在 `/var/lib/qbt/qBittorrent/logs`，开 logrotate `daily / rotate 7 / compress / size 10M`。
- ⚠️ 待裁决：5GB 软配额是否够。建议够——单次探测 metadata 阶段峰值约 50MB，并发 10 个种子也才 500MB，5GB 留 10× 缓冲。

#### Q2.5 凭据存储

- **推荐**：保持 v0.3 checklist 的方案——`/etc/puresource-btprobe.env` mode 0600 root:root，systemd `EnvironmentFile=` 装载。
- **理由**：当前规模下 systemd credential / secret manager 是过度工程；EnvironmentFile 已经避开了"凭据走代码仓"、"凭据进 journalctl"两个主要风险面。
- **加固建议**：
  - 文件中只放 `QBT_USER` / `QBT_PASS` / `QBT_BASE_URL` / `QBT_MOCK`，不放任何 callback URL（callback URL 走主服务的 `PURESOURCE_SELF_BASE` 注入到 ProbeRequest）。
  - 密码由 `pwgen -s 24 1` 生成，不复用 webui 默认 admin/adminadmin。
- ⚠️ 待裁决：是否未来引入 systemd credential。建议**不必**——保留为 v0.5/v0.6 重构选项。

---

### Q3. 真实流量烟测计划

**结论：选 3 个稳定公开种子 + 1 个 yt-dlp 样本；任何一个失败均视为 cutover-2 阻塞项。**

#### Q3.1 三个烟测种子（备选清单，具体 magnet 在 T-4a 时再核对最新可用性）

| # | 种子 | 形态 | 预期文件数 | 预期主文件 | 预期 peers/seeds | 选它的理由 |
|---|------|------|---------|----------|----------------|----------|
| 1 | **Big Buck Bunny**（Blender 官方公开发布） | 单文件 `BigBuckBunny_320x180.mp4` ~64MB 或 `bbb_sunflower_1080p_60fps_normal.mp4` ~700MB | 1（外加 readme） | 显著最大文件 | 始终活跃（Blender 官方有做种） | metadata 极快、文件结构简单、`main_file_index` 选主逻辑必命中 |
| 2 | **Ubuntu LTS ISO**（任一近期 LTS） | 单 ISO 文件 ~5GB | 1 | 唯一 .iso | 高 peers / 高 seeds | 主流公开种子，metadata 不会拉不下来；适合验"大体量 metadata 不阻塞 ack" |
| 3 | **Internet Archive 公开影视种子**（如 Cosmos Laundromat） | 多文件（mp4 + jpg + srt） | 3-10 | 最大 mp4 | 中等 peers | 适合验文件树渲染 / `is_recommended_main` 标记 / 多文件 setFilePrio |

⚠️ 待裁决：是否还要加一个**预期失败**种子（比如冷门 / DHT 无 peer 的）以验证 `status=failed` 路径。建议**加**——T-4a-16 拆成 16a / 16b。

#### Q3.2 验收脚本骨架（伪代码）

```
# 对每个烟测种子：
TID = curl -sf -X POST $HOST/tasks -d '{source_kind: "magnet", magnet: "<URI>"}' | jq .id
curl -sf -X POST $HOST/tasks/$TID/bt-probe -d '{}' -o /dev/null
# 等 metadata，最多 120s
for i in 1..60:
  STAGE = curl -sf $HOST/tasks | jq ".[] | select(.id==$TID) | .stage"
  if STAGE in (metadata_ready, failed): break
  sleep 2

# 断言（status=ok 路径）：
assert STAGE == "metadata_ready"
TASK = curl -sf $HOST/tasks | jq ".[] | select(.id==$TID)"
assert TASK.magnet.files != null && len(TASK.magnet.files) > 0
assert TASK.magnet.main_file_index >= 0
assert TASK.magnet.probed_at != null
assert TASK.magnet.peer_count != null  # 哪怕是 0 也得有值
assert journalctl -u puresource-btprobe --since "5min ago" | grep "callback task_id=$TID status=ok"
```

#### Q3.3 失败处理策略

- **冷门种子拉不到 metadata**（120s 超时）：不视为 cutover 阻塞；产品逻辑上 metadata 拉不到本就是合法的 `status=failed`。
- **稳定种子（Big Buck Bunny / Ubuntu ISO）拉不到 metadata**：视为 cutover-2 阻塞，回滚到 v0.2.0，立 issue 排查（多半是 qBittorrent 网络出站被 DC 屏蔽、或 DHT 端口不通）。
- **stage 卡在 `bt_probing` 永不前进**：视为 callback 链路问题，先查 `journalctl -u puresource-btprobe` 看 callback 是否发出，再查 `journalctl -u puresource-playlist` 看 `/internal/tasks/{id}/bt-probe-result` 是否被拒（localhost 校验、字段校验）。

⚠️ 待裁决：是否在 cutover-2 阻塞策略上加一个"3 个种子至少 2 个过就放行"的容忍度。建议**不放宽**——v0.3 烟测应该 100% 过，否则信号污染。

---

### Q4. 观测与可恢复性

**结论：journalctl 关键字 + 一个新增的 `GET /diag` 端点（仅 127.0.0.1）。前端再加一个"in-flight 超时" 视觉提示。**

#### Q4.1 三个进程的关键观测点

| 进程 | 观测点 | 阈值 / 关键字 |
|------|--------|-------------|
| `puresource-playlist` | callback 拒收率（localhost 校验 / 字段校验失败）、`extract-result` / `bt-probe-result` 路径 5xx 数 | journalctl 关键字 `internal endpoint`、`422`、`localhost-only` |
| `puresource-extract-worker` | `data/extract-jobs/*.json` 堆积量、`*.processing.json` 残留（>75s 算 stale）、yt-dlp 进程超时数 | 阈值：pending 队列 > 5 报警；stale 数 > 0 报警 |
| `puresource-btprobe` | `/health` 200 率、`probe start` 与 `callback` 计数对账（diff > 0 说明有 task 卡在后台）、qBittorrent metadata pending 数（间接：通过 qbt webui /api/v2/torrents/info） | 阈值：后台 task 滞留 > 30min 报警 |

#### Q4.2 是否需要 `GET /diag` 端点

**推荐：需要**。理由是上面所有观测都依赖 journalctl + ls + curl 多源拼接，没有一个用户/运维一眼看全的口子。

```
GET /diag         (仅 127.0.0.1，复用现有 localhost 校验)
{
  "version": "0.3.0",
  "uptime_s": 12345,
  "extract_jobs": {
    "pending": 2,
    "processing": 0,
    "stale": 0,
    "newest_age_s": 12
  },
  "btprobe": {
    "health": "ok",        # 主服务 HEAD btprobe /health 缓存 60s
    "last_callback_age_s": 45
  },
  "callbacks": {
    "extract_ok": 102,     # 自启动以来累计计数
    "extract_fail": 1,
    "bt_probe_ok": 18,
    "bt_probe_fail": 0
  }
}
```

- **是必需还是可选**：建议**必需**（列为 T-4a-OPT-01，但优先级 P1）。如果用户决定不要，可改为 P3 推迟，但 v0.4b 引入 expiry worker 后这个端点几乎是必须的，提前做一次更经济。
- **新代码量**：约 80-120 行（路由 + helper + 计数器），单测 ~30 行。

#### Q4.3 journalctl 抓取规则

- 三个 unit 一律 `SystemdJournal::Persistent`（默认即可）。
- 保留期：`/etc/systemd/journald.conf` 设 `MaxRetentionSec=30day`、`SystemMaxUse=2G`。
- 关键关键字提取（运维 cheat sheet，落在 cutover 文档里）：
  - `journalctl -u puresource-extract-worker --since "1 hour ago" | grep -E "claimed|completed|stale|timeout"`
  - `journalctl -u puresource-btprobe --since "1 hour ago" | grep -E "probe start|callback|run_probe unexpected"`
  - `journalctl -u puresource-playlist --since "1 hour ago" | grep -E "/internal/|422|429|5[0-9][0-9]"`

#### Q4.4 用户层失败信号（worker 宕机）

**推荐**：前端 `in-flight` 任务在客户端测到"超过 N 秒仍未转出 `extracting` / `bt_probing`"时，把 task 卡片置为黄色，并显示"⚠️ 探测异常超时（worker 可能宕机）"。

- N 取**前端层 600s**（10 分钟，远大于 yt-dlp 超时 90s 和 btprobe metadata 期望 120s）。
- 实现：现有 `IN_FLIGHT` 集合记录任务进入 in-flight 的时间戳，render 时计算差值，超阈值加 css class `task.in-flight-stale`。
- 这是**纯前端 5-15 行 JS + 5 行 CSS**，不依赖后端 push。
- 同时主服务 `/diag` 端点的 `extract_jobs.newest_age_s` / `btprobe.last_callback_age_s` 给了运维侧另一条独立信号。

⚠️ 待裁决：N=600s 是否合适。建议保持。

---

### Q5. 回滚演练

**结论：必须做一次完整灰度演练；建议在 :8190 开发实例 + 一份临时 resources.json 副本上完成。**

#### Q5.1 最小演练步骤（10 步内）

1. 把 `/opt/puresource-playlist/data/resources.json` 拷一份到开发工作区 `/root/bt-player-new/puresource-playlist/data/resources.demo.json`（包含真实 5 条记录形态）。
2. 在 :8190 实例上启动 v0.3，用步骤 1 的副本启动；记录一份"v0.2 基线 JSON"。
3. POST 一个 `extract` 任务，造出含 `extract` 字段的记录；POST 一个 `bt-probe` 任务（QBT_MOCK=1），造出含 `magnet.files` 的记录。
4. 手动构造一条带 `expires_at` + `last_success_at` 的记录写入 JSON。
5. 模拟 cutover-2 失败：停 :8190 v0.3 主服务。
6. 把 :8190 的代码 checkout 回 v0.2 commit；启动 v0.2 主服务（指向同一份 JSON）。
7. **验证字段是否被擦**：v0.2 主服务读取 JSON 时，未知字段（`extract` / `expires_at` / `last_success_at` / `magnet.files` / `magnet.peer_count`）应被 pydantic `extra="ignore"`（或当时的等价策略）保留在 JSON 文件原始字节上，**但**当 v0.2 经过任何写入路径（如 `append_resource` / `update_resource`）后这些字段会被剥离。
8. 通过 `intake` 在 v0.2 上新增一条记录，触发一次 JSON 写盘；用 `diff` 比对：未触发写盘的旧记录字段是否仍在；触发写盘的新记录是否丢字段。
9. 把 :8190 切回 v0.3 + 用备份的 JSON 还原，验证仍能读出步骤 3-4 造的字段。
10. 记录演练结果到 cutover 文档 §11.x（包含具体哪个写入路径会剥字段、哪个不会）。

#### Q5.2 §1.4 字段丢失验证（最小方法）

- 造 1 条同时有 `extract.candidates[]` 和 `expires_at` 的记录。
- 在 v0.2 主服务上对该 task `POST /tasks/{id}/probe`（v0.2 已存在端点），观察 JSON 写盘后这条记录是否仍然保留 `extract` / `expires_at`。
- 如果丢失：明确"v0.2 路径任何 `update_resource` 都会擦字段"，回滚顺序必须是"先停 v0.3 → 恢复 JSON 备份 → 再起 v0.2"。这与 checklist §1.4 / §11 已写一致。
- 如果意外没丢失：补一句"v0.2 的 pydantic 模型 extra 行为友好，理论上字段会保留——但**仍按悲观路径执行回滚**，避免依赖隐式行为"。

#### Q5.3 "回滚成功"的硬判据

| # | 判据 | 验证手段 |
|---|------|--------|
| 1 | `/health` 200 | `curl -sf http://127.0.0.1:8090/health` |
| 2 | `version` 是 `0.2.0` | `curl -sf http://127.0.0.1:8090/openapi.json \| jq .info.version` |
| 3 | `resources.json` MD5 与备份完全一致 | `md5sum data/resources.json /tmp/resources.json.bak.v0.2` |
| 4 | `default.m3u8` 可由 PotPlayer 拉取且条目数与 v0.3 切换前一致 | `curl -sf http://bt.mgtv.dev/playlists/potplayer/default.m3u8 \| wc -l` 比对 |
| 5 | systemd 中 `puresource-extract-worker` / `puresource-btprobe` 已 `stop` 且 `disable`（不残留尝试启动） | `systemctl is-active`、`is-enabled` |
| 6 | journalctl 自回滚后 5min 内 0 个 5xx、0 个 `Exception` | `journalctl -u puresource-playlist --since "5min ago" \| grep -E "ERROR\|Exception\|5[0-9][0-9]"` |

⚠️ 待裁决：硬判据 #5 是 stop 还是 disable？建议**两者都做**——stop 防止当前进程留尾巴，disable 防止 reboot 后自动起被自动连到旧 callback URL（残留请求会污染 v0.2 JSON）。

---

## 4. Q6–Q9（v0.4b 生命周期闭环）

### Q6. `expires_at` 写入时机与策略

**结论：`/intake` 与 `/promote` 都写；`source_kind` → 默认 TTL 由表驱动；`PromoteRequest` 可显式覆盖。**

#### Q6.1 source_kind → 是否写 expires_at + 默认 TTL

| source_kind | 自动写 expires_at | 默认 TTL | 理由 |
|------------|----------------|---------|------|
| `mp4` | 是 | **72h** | 自托管 / 友站直链多数稳定，但仍允许失效（域名换、备案变更） |
| `m3u8` | 是 | **24h** | HLS Token / Cookie 多数 1 天周期 |
| `magnet` | **否** | — | magnet 本身永久；`stream_url` 如有则按其类型走（一般是 PikPak/油猴注入的 mp4/m3u8） |
| `webpage` | **否** | — | 网页本身不需要过期；extract 出来的候选 `stream_url` 在 promote 时按 mp4/m3u8 规则写 |
| `other` | 是 | **24h**（保守） | 未知来源，悲观假设 |

#### Q6.2 写入时机

- **`/intake`**：如果 payload 显式带 `expires_in_hours`（v0.3 方案 §三 5) 预告字段，v0.4b 实装），按用户值写入 `expires_at = now + h`；否则按表查默认 TTL。
- **`/promote`**：promote 是"用户确认要进 PotPlayer 列表"的语义节点，**总应**写 `expires_at`（如果 `PromoteRequest` 没传，按 source_kind 默认 TTL）。已有 promote 走 `external_ready` 的资源在 v0.4b 上线时一次性脚本回填（可选；如不做则它们 `expires_at=None` 等下次手动 promote 时再补）。

#### Q6.3 用户手动覆盖

```
# PromoteRequest 新增可选字段（向后兼容）：
class PromoteRequest(...):
    target_status: ...
    stream_url: ...
    title: ...
    expires_in_hours: Optional[int]   # 新增，0 < val ≤ 24*30 (30 天)
    expires_at: Optional[str]         # 新增，ISO-8601，与 expires_in_hours 二选一
```

- 二选一：传 `expires_at` 优先；都不传走默认表。
- ⚠️ 待裁决：是否允许"永不过期"（传 `expires_at=null` 显式抑制）。建议**允许**——业务上自托管资源确有此需求；语义是 `expires_at=None`。

#### Q6.4 关键约束

- `expires_at` 永远是 ISO-8601 字符串（UTC，带 Z 后缀），不是 datetime；与 `last_success_at` / `probed_at` 等字段保持一致。
- 时区：服务器使用 UTC（v0.3 已是），前端展示按浏览器本地时区。

---

### Q7. 复检 worker 设计

**结论：HEAD + 失败 3 次降级到新增的 `expired` stage；触发节奏每 5min；callback 复用 `/internal/*` 模式。**

#### Q7.1 探活方式对比

| 方式 | mp4 直链 | m3u8 | PikPak CDN | 优缺点 |
|------|---------|------|-----------|--------|
| **HEAD** | ✓ 看 status 与 `Content-Length` | ✗ 部分服务器对 HEAD 不返回 m3u8 正文 | ✓ 但 PikPak 偶尔对 HEAD 返 405 | 最轻；首选 |
| **GET Range bytes=0-0** | ✓ | ✓（拿第一行 `#EXTM3U`） | ✓ | 兜底；多 1 字节流量 |
| **ffprobe-light**（远程） | ✓ 验容器完整性 | ✓ 验 manifest | ✓ | 太重；v0.4b 不做，留 v0.6 质量分级线 |

**推荐**：**HEAD first，405 / 不支持 时降级 GET Range bytes=0-0**。不引入 ffprobe。

#### Q7.2 触发节奏

- **扫描周期**：每 **5 分钟**全表扫一次。
- **扫描范围**：`stage ∈ {external_ready, playable}` AND `expires_at IS NOT NULL` AND `expires_at < now + δ`。
- **δ 取值**：**2h**（即"距过期 2h 以内"开始预热复检）。
- 这样的频率单次扫描读 resources.json（< 100KB 量级）只做内存过滤，CPU/IO 可忽略；命中的资源才走 HTTP HEAD。

#### Q7.3 失败几次降级 + 降到哪里

- **失败 3 次**（连续，间隔 ≥ 5min）后降级。
- **降到新 stage `expired`**——不复用 `failed`（`failed` 当前语义是"探测过程失败"，与"链接失效"语义不同；复用会破坏既有 UI 含义）。
- ⚠️ 待裁决：是否新增 `expired` stage 还是用 `failed` + `failure_reason="expired"`。建议**新增 `expired`**——见上理由；且代价仅一行枚举 + 一行 setdefault。

#### Q7.4 复检结果写哪里

**推荐字段方案 A（新增两个字段，与 `last_success_at` 协作）**：

```python
class ResourceRecord(BaseModel):
    # ... 既有字段 ...
    expires_at: Optional[str]         # v0.3 已有
    last_success_at: Optional[str]    # v0.3 已有，含义不变：上次"被业务用过"
    last_check_at: Optional[str]      # 新增：上次 expiry-worker 探活时间
    last_check_status: Optional[str]  # 新增：ok | failed | unreachable
    consecutive_check_failures: int   # 新增：连续失败计数，默认 0
```

候选方案 B（只更新 `last_success_at`）：太弱，无法区分"业务用过"和"探活成功"，**不推荐**。

#### Q7.5 callback 模式

**推荐**：与 extract / bt-probe **对称**——expiry-worker 完成一批后逐条 `POST http://127.0.0.1:8090/internal/tasks/{id}/expiry-result`，主服务负责字段更新和 stage 推进。

- 理由 1：保持 ResourceRecord 写入路径单一（主服务），expiry-worker 不直接读写 resources.json（否则会与主服务 `update_resource` 抢锁，引入并发坑）。
- 理由 2：与 v0.3 的 worker / 子服务架构一致，新代码 diff 最小。
- 理由 3：方便未来加观测点（`/diag.callbacks.expiry_ok` 一行加上）。

#### Q7.6 进程形态

- 与 extract-worker 一样，**独立 Python 进程 + systemd unit**（`puresource-expiry-worker.service`）。
- 不用 systemd timer + oneshot，理由：常驻进程才能持有内存状态（最近一次 scan 的时间、连续失败计数缓存），timer 模式每次冷启不便。
- 但**也可以**走 timer + 持久化失败计数到 ResourceRecord 的 `consecutive_check_failures` 字段。⚠️ 待裁决。

---

### Q8. 前端过期语义

**结论：不增 stage tab；徽章 + 滤镜；`default.m3u8` 默认过滤已过期（开关式但默认开）；不复用现有按钮，单独"重新探测"按钮。**

#### Q8.1 是否要单独 stage tab

**不要**。`external_ready` / `playable` tab 里直接展示，加徽章区分即可。理由：过期是属性，不是状态机阶段；用户的诉求是"在我熟悉的可播列表里挑出哪些快不行了"，而不是"切到一个新 tab 看"。

但 `expired` stage（Q7.3 新增）应该有独立 tab，因为它是终态，与 `failed` 并列展示有意义。

#### Q8.2 徽章阈值

| 时距 | 徽章 | CSS class |
|------|------|----------|
| `expires_at - now > 6h` | 不显徽章 | — |
| `2h ≤ expires_at - now ≤ 6h` | 黄色 "⏳ N 小时内过期" | `badge.expiring-soft` |
| `0 < expires_at - now < 2h` | 橙色 "⏳ N 分钟内过期" | `badge.expiring-hard` |
| `expires_at - now ≤ 0` | 红色 "❌ 已过期" | `badge.expired` |

⚠️ 待裁决：阈值（2h / 6h）是否合适。建议保持，理由是给用户 6h-2h 主动操作窗口，2h 以内是紧急区。

#### Q8.3 `default.m3u8` 是否过滤已过期

**推荐**：**开关式但默认开**——环境变量 `PURESOURCE_M3U8_FILTER_EXPIRED=1`（默认 1，可显式设 0 关闭）。

- 理由：默认开符合"PotPlayer 用户期望看到能播的"；默认关相当于把烂链接推给客户端，UX 不可接受。
- 兼容性影响：v0.3 → v0.4b 升级后，PotPlayer 订阅条目数可能突然变少（如果有过期资源）。这是行为变更，**必须**在 cutover 文档明确告知用户。
- 关闭场景：用户主动决定"我自己看列表分辨"。

#### Q8.4 重新探测按钮

**推荐**：单独按钮 `[重新探测]`，复用现有端点：

- 对 `mp4` / `m3u8` → 调 `POST /tasks/{id}/probe`
- 对 `magnet` → 调 `POST /tasks/{id}/bt-probe`
- 对 `webpage` → 调 `POST /tasks/{id}/extract`（cookies 名复用上次或弹框）

不引入新端点；按钮在过期 / 即将过期资源卡片右上角加一个独立位（不挤现有 `[promote]` / `[enrich]`）。

#### Q8.5 expiry stage tab 与 demote 操作

`expired` stage tab 给用户看"已经失效的资源墓地"，用户可：
- 点 `[重新探测]` 尝试复活（成功则 stage 推回 `external_ready` 并刷新 `expires_at`）
- 点 `[delete]`（沿用现有端点）从 resources.json 中移除

---

### Q9. v0.4b 数据迁移坑

**结论：4 个新字段全部走 `_migrate_legacy` setdefault；加 `schema_version` 字段，回滚时早 fail。**

#### Q9.1 v0.4b 引入的所有新字段

| 字段 | 类型 | 默认值 | 来源 |
|------|------|------|------|
| `last_check_at` | `Optional[str]` | `None` | Q7.4 |
| `last_check_status` | `Optional[str]` | `None` | Q7.4 |
| `consecutive_check_failures` | `int` | `0` | Q7.4 |
| `schema_version` | `str`（不是 int，便于 `"0.4b"` / `"0.5.1"` 这种语义） | `"0.4b"`（v0.4b 默认值） | Q9.3 |
| `ResourceStage.expired` | enum 值 | — | Q7.3 |
| `PromoteRequest.expires_in_hours` / `.expires_at` | 入参，不进 ResourceRecord | — | Q6.3 |

#### Q9.2 `_migrate_legacy` setdefault 项

```python
# app/store.py _migrate_legacy 在 v0.3 已有的基础上追加：
rec.setdefault("last_check_at", None)
rec.setdefault("last_check_status", None)
rec.setdefault("consecutive_check_failures", 0)
rec.setdefault("schema_version", "0.4b")  # 旧记录读上来后被打标
# 若 §2-D6 裁决"预埋 v0.5 字段"，则追加：
# rec.setdefault("verified_by", None)
# rec.setdefault("source_trust", None)
# rec.setdefault("tags", [])
# rec.setdefault("category", None)
```

#### Q9.3 是否加 `schema_version`

**推荐：加。**

- **预期效果**：v0.5+ 引入新字段时，启动期一眼看出"这份 JSON 是 v0.4b 写的，要走 v0.5 升级路径"；回滚时如果 v0.3 主服务读到 `schema_version="0.4b"` 的记录可以**显式日志告警**（不必硬阻断）。
- **实现成本**：models 加一行 `schema_version: str = "0.4b"`、store 加一行 setdefault、可选加一段启动期 `WARN if schema_version > self_version`，总计 < 20 行。
- **影响面**：完全向后兼容（旧 JSON 进来直接 setdefault）；向前兼容（v0.3 主服务读 v0.4b JSON 时这个字段被 pydantic 忽略）。
- **风险**：极小；唯一陷阱是字符串比较要小心（`"0.10"` vs `"0.4b"` lex 比较不准），所以纯做日志，不参与决策。

⚠️ 待裁决：是否加 `schema_version`。建议**加**——成本极低，长期收益高。

---

## 5. Q10–Q12（全局）

### Q10. v0.4a / v0.4b 时序

**结论：串行（v0.4a 完成 → 稳定运行 1 周 → 开 v0.4b 分支开发）。**

- **串行理由 1**：v0.4a 切生产期间的注意力带宽不能再分给 v0.4b 设计/编码。
- **串行理由 2**：v0.4b 的 `expires_at` 写入策略（Q6）需要观察真实生产 1 周以上才能调出合理 TTL；提前并行只能拍脑袋。
- **串行理由 3**：v0.4b 的 expiry-worker 与 extract-worker / btprobe 共用主服务 callback 通路；只有 v0.4a 切完了 callback 路径才是稳定地基。
- **并行风险**：v0.4b 的代码改动主要在 `app/main.py` / `app/models.py` / `app/store.py`，恰好是 v0.4a 切换的核心文件——并行会增加 merge conflict 与"哪个版本上生产"的混淆。
- **推荐节奏**：
  - W1：v0.4a cutover-1 + 灰度演练
  - W2：v0.4a cutover-2 + 生产稳定观察
  - W3-W4：v0.4b 开发（开发实例 :8190 上）
  - W5：v0.4b cutover（无 systemd 加固分裂，因为基础设施已就位）

⚠️ 待裁决：是否接受串行。建议接受。

---

### Q11. v0.4 完成的判据

**至少 5 条硬判据（实际给 7 条）**：

| # | 判据 | 验证手段 |
|---|------|--------|
| 1 | 生产 `puresource-playlist /health` 返 200 且 `version >= 0.4b` | `curl -sf http://127.0.0.1:8090/health`、`curl -sf http://127.0.0.1:8090/openapi.json \| jq .info.version` |
| 2 | 三个 unit 全部 `active (running)` 且 `enabled` | `systemctl is-active puresource-{playlist,extract-worker,btprobe,expiry-worker}` 四个均 `active`；`is-enabled` 均 `enabled` |
| 3 | 真实 qBittorrent 烟测 3 种子全 `metadata_ready` 且 callback 链路无 5xx | journalctl 自烟测起 0 个 `callback failed` |
| 4 | 至少 1 条真实资源因 `expires_at` 到点被 expiry-worker 推到 `expired`，且前端展示红色徽章 | `curl /tasks \| jq '.[] \| select(.stage=="expired")'` 非空；UI 截图 |
| 5 | `default.m3u8` 自动过滤已过期（默认开） | 造一条 expired 资源，确认 `curl /playlists/potplayer/default.m3u8` 不含其 stream_url |
| 6 | Caddy `/internal/*` 公网仍 403；`/health`、`/tasks`、`/playlists/*` 公网仍 2xx | `curl -sI https://bt.mgtv.dev/internal/foo`、`/tasks`、`/playlists/potplayer/default.m3u8` |
| 7 | 灰度演练记录已落档（cutover 文档新增 §11.x 演练结果） | `grep "演练" puresource-playlist-v0.3-cutover-checklist.md` 命中 |

---

### Q12. v0.5 边界守卫

**结论：埋字段——但只埋"几乎确定要的"，不埋"可能要的"。**

#### Q12.1 哪些字段必须 v0.4b 预埋

| 字段 | v0.5 是否一定要 | 是否预埋 | 默认值 |
|-----|--------------|---------|------|
| `tags: list[str]` | 大概率（标签管理） | **预埋** | `[]` |
| `category: Optional[str]` | 大概率（分组） | **预埋** | `None` |
| `favorited_at: Optional[str]` | 中概率 | **预埋** | `None`（成本极低） |
| `verified_by: Optional[str]` | 高（v0.3 方案已预告） | **预埋** | `None` |
| `source_trust: Optional[str]` | 中（与 verified_by 配对） | **预埋** | `None` |
| `notes: Optional[str]` | 低（不确定 v0.5 要不要） | 不埋 | — |
| `play_count: int` | 低（统计类，v0.6+） | 不埋 | — |

#### Q12.2 为什么不全埋

- 字段越多，pydantic 模型越大，写盘 JSON 越啰嗦；
- 真正会触发"再次数据迁移坑"的是 v0.5 引入字段时把 v0.4b 已有的数据**结构性改写**（比如把 `stage` 字符串改成 enum 的 int）；只新增 setdefault 字段不会触发坑。
- 所以应避免的是"v0.5 引入 stage 重命名 / 字段类型变更"这种**破坏性**变更；新增 `tags=[]` 本身不破坏什么，但提前埋可避免一次 setdefault 心智成本。

#### Q12.3 不埋字段的兜底

- v0.5 引入新字段时仍走 `_migrate_legacy` setdefault 模式（与 v0.4b 同款）；
- 唯一前提是 v0.4b 已经把 `schema_version` 落地（见 Q9.3），v0.5 启动期能感知"我读到的是 0.4b 数据，需要走 0.5 升级"。
- 因此 §2-D6（预埋 verified_by/source_trust）和 Q12（预埋 tags/category/favorited_at）合并成一项裁决：**裁决"v0.4b 顺手预埋"清单**。

⚠️ 待裁决：预埋清单是否采纳本节表中的 5 个（tags / category / favorited_at / verified_by / source_trust）。建议采纳。

---

## 6. 执行计划 - v0.4a（生产部署）

> 工时单位：小时。运维工时 = 跑命令 + 写 / 改 unit / Caddy 段；代码工时 = 写 Python / 前端。
> 凡注 `⚠️ 待裁决` 的任务必须先得到用户决断才能开工。

### T-4a-00 基线对齐（前置 housekeeping）

- 触达对象：systemd unit 视图、生产端口占用
- 操作：
  - `systemctl daemon-reload` 清掉"unit changed on disk"告警
  - `systemctl cat puresource-playlist.service > /tmp/unit-baseline-v0.2.txt` 落档
  - `ss -lntp | grep :8091` 确认 8091 占用情况（应仍是 PID 1894331）
- 契约影响：无
- 依赖：无
- 验收：`systemctl status puresource-playlist` 不再有"changed on disk"提示；`/tmp/unit-baseline-v0.2.txt` 存在
- 工时：0.3h 运维
- 风险：极低

### T-4a-01 cookies 目录建立

- 触达对象：`/var/lib/puresource/cookies/`
- 操作：`install -d -m 0750 -o root -g www-data /var/lib/puresource && install -d -m 0750 -o root -g www-data /var/lib/puresource/cookies`
- 契约影响：无（v0.3 代码已支持 `PURESOURCE_COOKIES_DIR` 环境变量，缺省 `/var/lib/puresource/cookies`）
- 依赖：T-4a-00
- 验收：`stat /var/lib/puresource/cookies` 权限 `drwxr-x--- root www-data`
- 工时：0.2h 运维
- 风险：低

### T-4a-02 yt-dlp 安装 + 版本锁定

- 触达对象：`/opt/puresource-playlist/.venv`（不污染系统 Python）
- 操作：`/opt/puresource-playlist/.venv/bin/pip install yt-dlp==<具体版本>`；版本在执行日确认；记录到 cutover 文档
- 契约影响：无
- 依赖：T-4a-00
- 验收：`/opt/puresource-playlist/.venv/bin/yt-dlp --version` 输出预期版本号
- 工时：0.3h 运维
- 风险：低；如果走系统 apt，则 unattended-upgrades 滚版风险大——venv 内 pip 是更稳妥的选择，但需在 extract.py 里确认 yt-dlp 可执行路径（v0.3 代码当前 hardcode `yt-dlp` 走 PATH，T-4a-02 完成后需在 systemd unit 的 `PATH` 中显式加 venv/bin）

### T-4a-03 杀掉 8091 开发实例占用（⚠️ 需用户确认）

- 触达对象：PID 1894331（开发态 mock btprobe）
- 操作：先 `ss -lntp | grep :8091` 二次确认，再 `kill 1894331`，等 3s，再 `ss -lntp | grep :8091` 确认空闲
- 契约影响：无（开发实例的影响仅限开发态）
- 依赖：T-4a-00
- 验收：8091 端口空闲
- 工时：0.2h 运维
- 风险：低；但 **⚠️ 待裁决**：是否由用户手动 kill（避免我误杀同时也跑着其他 dev 服务）
- 备注：如果用户想保留开发 btprobe，可改为 T-4a-03b "迁移 dev btprobe 到 8092"

### T-4a-04 部署 puresource-btprobe 子服务代码

- 触达对象：`/opt/puresource-btprobe/`（新建目录）
- 操作：
  - `install -d -m 0755 -o root -g root /opt/puresource-btprobe`
  - `rsync -a --exclude='__pycache__' --exclude='.pytest_cache' /root/bt-player-new/puresource-btprobe/ /opt/puresource-btprobe/`
  - `python3 -m venv /opt/puresource-btprobe/.venv && /opt/puresource-btprobe/.venv/bin/pip install -r /opt/puresource-btprobe/requirements.txt`
  - `chown -R root:root /opt/puresource-btprobe`
- 契约影响：无
- 依赖：T-4a-03
- 验收：`/opt/puresource-btprobe/.venv/bin/python -m puresource_btprobe.main --help` 不报错（虽然实际启动靠 systemd）
- 工时：0.6h 运维

### T-4a-05 puresource-extract-worker systemd unit

- 触达对象：`/etc/systemd/system/puresource-extract-worker.service`
- 操作：写 unit；关键字段（伪配置）：

```
[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/puresource-playlist
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/opt/puresource-playlist/.venv/bin:/usr/bin
Environment=PURESOURCE_SELF_BASE=http://127.0.0.1:8090
Environment=PURESOURCE_COOKIES_DIR=/var/lib/puresource/cookies
ExecStart=/opt/puresource-playlist/.venv/bin/python -m app.extract_worker
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
```

- 契约影响：无（worker 通过 `PURESOURCE_SELF_BASE` 回写主服务，路径与代码默认值一致）
- 依赖：T-4a-01、T-4a-02
- 验收：`systemctl daemon-reload && systemctl enable puresource-extract-worker.service` 无报错；先**不** start
- 工时：0.5h 运维
- 风险：低

### T-4a-06 qBittorrent-nox 安装 + 版本 hold

- 触达对象：apt `qbittorrent-nox` 包
- 操作：
  - `apt update && apt install -y qbittorrent-nox`
  - 立即 `systemctl stop qbittorrent-nox.service`（distro 自带 unit）
  - `systemctl disable qbittorrent-nox.service`（不用 distro unit）
  - `apt-mark hold qbittorrent-nox`
  - `apt show qbittorrent-nox | grep Version` 记录版本
- 契约影响：无
- 依赖：T-4a-00
- 验收：`which qbittorrent-nox` 命中；`apt-mark showhold | grep qbittorrent-nox` 命中
- 工时：0.5h 运维
- 风险：⚠️ 待裁决见 §2-D2（VPS 网络声誉风险）；如裁决"暂不接真 qBittorrent"，本任务可不执行，QBT_MOCK 永驻 1

### T-4a-07 qBittorrent 配置初始化 + 系统加固

- 触达对象：`/etc/systemd/system/qbittorrent-nox.service`（自定义 unit）、`/var/lib/qbt/qBittorrent/qBittorrent.conf`、专用用户 `qbt`
- 操作：
  - `useradd -r -d /var/lib/qbt -s /usr/sbin/nologin qbt`
  - `install -d -m 0750 -o qbt -g qbt /var/lib/qbt`
  - 写自定义 unit（见 Q2.2 伪配置）
  - 第一次启动用 `sudo -u qbt qbittorrent-nox --webui-port=8080 --profile=/var/lib/qbt` 跑 30 秒生成默认配置，然后 Ctrl-C
  - 编辑 `qBittorrent.conf` 按 Q2.3 最小变更清单
  - 设置 webui 用户密码（pwgen -s 24 1）
  - `systemctl daemon-reload && systemctl enable qbittorrent-nox.service`（暂不 start）
- 契约影响：无（不影响主服务）
- 依赖：T-4a-06
- 验收：`systemctl is-enabled qbittorrent-nox` = `enabled`；`/var/lib/qbt/qBittorrent/qBittorrent.conf` 含 Q2.3 表中关键项
- 工时：1.5h 运维
- 风险：中（qBittorrent.conf 字段名 distro 间略有差异，需现场对照）

### T-4a-08 qBittorrent 凭据文件

- 触达对象：`/etc/puresource-btprobe.env`
- 操作：
  - `install -m 0600 -o root -g root /dev/null /etc/puresource-btprobe.env`
  - 写入：
    ```
    QBT_BASE_URL=http://127.0.0.1:8080
    QBT_USER=puresource_bot
    QBT_PASS=<pwgen 出来的 24 位>
    QBT_MOCK=1
    ```
  - 注意 `QBT_MOCK=1`，cutover-1 阶段先用 mock；cutover-2 时再改成 0
- 契约影响：无
- 依赖：T-4a-07
- 验收：`stat /etc/puresource-btprobe.env` 权限 `0600 root:root`；内容可被 systemd `EnvironmentFile=` 加载
- 工时：0.3h 运维

### T-4a-09 puresource-btprobe systemd unit

- 触达对象：`/etc/systemd/system/puresource-btprobe.service`
- 操作：
  - 写 unit；关键字段（伪配置）：

```
[Service]
Type=simple
User=root          # 因为读 /etc/puresource-btprobe.env；btprobe 进程本身不读 resources.json
Group=root
WorkingDirectory=/opt/puresource-btprobe
EnvironmentFile=/etc/puresource-btprobe.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/puresource-btprobe/.venv/bin/uvicorn puresource_btprobe.main:app --host 127.0.0.1 --port 8091
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
```

- 契约影响：无
- 依赖：T-4a-04、T-4a-08
- 验收：`systemctl daemon-reload && systemctl enable puresource-btprobe.service` 成功
- 工时：0.5h 运维
- 风险：⚠️ 待裁决：是否将 btprobe 进程的 User 从 root 改为专用 `qbt`（贴 qBittorrent 权限）。建议保持 root —— 简化文件权限，且 btprobe 不接触 resources.json，攻击面有限

### T-4a-10 部署 v0.3 主服务代码

- 触达对象：`/opt/puresource-playlist/`（增量同步）
- 操作：
  - 准备阶段：开发实例 `/root/bt-player-new/puresource-playlist/` 已是 v0.3 代码
  - `rsync -a --delete-after --exclude='.venv' --exclude='data' --exclude='__pycache__' --exclude='.pytest_cache' /root/bt-player-new/puresource-playlist/ /opt/puresource-playlist/`
  - `/opt/puresource-playlist/.venv/bin/pip install -r /opt/puresource-playlist/requirements.txt --upgrade`
  - `chown -R www-data:www-data /opt/puresource-playlist/app /opt/puresource-playlist/static`
  - **不重启**主服务（保留 v0.2 在跑，等 cutover-2 时再 restart）
- 契约影响：无（仅落代码，不切换）
- 依赖：T-4a-05、T-4a-09
- 验收：`ls /opt/puresource-playlist/app/extract*.py` 命中两个文件；`grep version /opt/puresource-playlist/app/main.py` 含 `version="0.3.0"`（或当前版本号）
- 工时：0.5h 运维
- 风险：低

### T-4a-11 主服务 unit drop-in 增 Environment

- 触达对象：`/etc/systemd/system/puresource-playlist.service.d/override.conf`
- 操作：
  - `install -d -m 0755 /etc/systemd/system/puresource-playlist.service.d`
  - 写 override.conf：
    ```
    [Service]
    Environment=PURESOURCE_BTPROBE_BASE=http://127.0.0.1:8091
    Environment=PURESOURCE_SELF_BASE=http://127.0.0.1:8090
    Environment=PURESOURCE_COOKIES_DIR=/var/lib/puresource/cookies
    ```
  - `systemctl daemon-reload`
- 契约影响：无（这些 env 只在 v0.3 代码路径上被读取）
- 依赖：T-4a-10
- 验收：`systemctl cat puresource-playlist.service | grep PURESOURCE_BTPROBE_BASE` 命中
- 工时：0.3h 运维
- 风险：低

### T-4a-12 备份 resources.json + 校验回滚路径

- 触达对象：`/opt/puresource-playlist/data/resources.json`
- 操作：
  - `TS=$(date +%Y%m%d-%H%M%S)`
  - `install -m 0600 -o root -g root /opt/puresource-playlist/data/resources.json /var/backups/resources.json.bak.v0.2.${TS}`
  - `md5sum /var/backups/resources.json.bak.v0.2.${TS}` 落档
- 契约影响：无
- 依赖：T-4a-00
- 验收：备份文件存在 + md5 已记录
- 工时：0.2h 运维

### T-4a-13 灰度演练（dry-run cutover + rollback）

- 触达对象：开发实例 :8190、`/root/bt-player-new/puresource-playlist/data/resources.demo.json`
- 操作：按 Q5.1 的 10 步演练；产出演练报告
- 契约影响：无
- 依赖：T-4a-12（保证有备份对照）
- 验收：演练报告含 §1.4 字段保留 / 丢失结论；至少 1 次完整 cutover-1 + cutover-2 + rollback 路径走通
- 工时：1.5h 运维
- 风险：低；但若演练发现"v0.2 update_resource 路径会擦字段"且严重，需要把 cutover-2 改为"resources.json 备份后只追加不更新"——见 §2-D6 衍生裁决

### T-4a-14 cutover-1：上 worker + btprobe（QBT_MOCK=1）

- 触达对象：systemd 三个 unit
- 操作：
  - `systemctl start puresource-extract-worker`
  - `systemctl start puresource-btprobe`（QBT_MOCK=1）
  - 主服务**不动**
  - 24-72h 观察窗口
- 契约影响：无（QBT_MOCK 模式不触网）
- 依赖：T-4a-05、T-4a-09、T-4a-11
- 验收：
  - `curl -sf http://127.0.0.1:8091/health` → 200
  - `journalctl -u puresource-extract-worker --since "10min ago"` 无 `ERROR` / `Exception`
  - 24h 后 `ls /opt/puresource-playlist/data/extract-jobs/` 仍为空（无遗漏 job）
- 工时：0.5h 运维（被动观察不计入）

### T-4a-15 cutover-2：切真 qBittorrent + 主服务 v0.3

- 触达对象：`/etc/puresource-btprobe.env`、`puresource-btprobe.service`、`qbittorrent-nox.service`、`puresource-playlist.service`
- 操作（按序）：
  1. `sed -i 's/^QBT_MOCK=1/QBT_MOCK=0/' /etc/puresource-btprobe.env`
  2. `systemctl start qbittorrent-nox` + 验 `curl -sf -u puresource_bot:<pass> http://127.0.0.1:8080/api/v2/app/version` 拿到版本
  3. `systemctl restart puresource-btprobe`
  4. `systemctl restart puresource-playlist`（主服务首次切到 v0.3 代码）
  5. `curl -sf http://127.0.0.1:8090/health`
- 契约影响：主服务版本 0.2 → 0.3；行为变更
- 依赖：T-4a-14（cutover-1 观察期完成）、T-4a-12（备份就位）
- 验收：四个 `systemctl is-active` 全部 `active`；`curl /openapi.json | jq .info.version` = `"0.3.0"`
- 工时：0.5h 运维
- 风险：中；失败回滚顺序按 Q5.3 + checklist §11

### T-4a-16 烟测真实种子

- 触达对象：HTTP 接口、journalctl
- 操作：按 Q3.2 验收脚本骨架，对 3 个种子（Big Buck Bunny / Ubuntu LTS / Internet Archive 影视）+ 1 个预期失败种子各跑一遍
- 契约影响：无
- 依赖：T-4a-15
- 验收：3 成功烟测全 `stage=metadata_ready`、`magnet.files` 非空、`main_file_index` 合理；1 预期失败种子最终 `stage=failed`、`magnet.error` 含 metadata timeout 含义
- 工时：1h 运维
- 风险：中（受 DC 网络出站策略 / DHT 端口可达性影响）；失败 → 阻塞，回滚

### T-4a-17 烟测 yt-dlp 真实抽取

- 触达对象：HTTP 接口
- 操作：选一个公开的、稳定的 video 网页 URL（如 Blender 官网 demo），POST `/tasks/{id}/extract` → 等 `stage=playable` → 验 `extract.candidates` 非空、`stream_url` 形态合理
- 契约影响：无
- 依赖：T-4a-15
- 验收：candidates 数 ≥ 1，且至少有一个 `container ∈ {mp4, m3u8, webm}`
- 工时：0.5h 运维

### T-4a-18 滚动观测 24h

- 触达对象：journalctl、/diag（如做了 T-4a-OPT-01）
- 操作：每 6h 一次 `journalctl -u puresource-{playlist,extract-worker,btprobe} --since "6 hours ago" | grep -E "ERROR|Exception|callback failed"`；落 24h 观察报告
- 契约影响：无
- 依赖：T-4a-15
- 验收：24h 内零 5xx、零 callback failed
- 工时：0.5h 运维（被动观察）

### T-4a-OPT-01（可选小代码任务）`GET /diag` 端点

- 触达对象：`puresource-playlist/app/main.py`（约 +120 行）、`tests/test_main.py`（约 +30 行）
- 操作：
  - 新增 endpoint `GET /diag`，仅 127.0.0.1
  - 引入轻量计数器（main.py 模块全局变量足够，进程重启清零，可接受）
  - 缓存 btprobe `/health` 响应 60s
- 契约影响：新端点（不影响既有）
- 依赖：T-4a-10 之前完成（这样 T-4a-15 切过去就有 `/diag` 可用）
- 验收：`curl -sf http://127.0.0.1:8090/diag` 返回 Q4.2 schema；从公网 curl 返 403
- 工时：3h 代码 + 0.5h 运维（部署即 rsync 一遍 main.py）
- 风险：低；⚠️ 待裁决（Q4.2 是否做）

---

## 7. 执行计划 - v0.4b（生命周期闭环）

### T-4b-01 ResourceRecord 新增字段 + `_migrate_legacy`

- 触达对象：`app/models.py`、`app/store.py`、单测
- 操作：
  - models 新增 `last_check_at` / `last_check_status` / `consecutive_check_failures` / `schema_version`（默认 `"0.4b"`）
  - 若 §2-D6 / Q12 裁决埋字段，则同步加 `tags` / `category` / `favorited_at` / `verified_by` / `source_trust`
  - store `_migrate_legacy` setdefault 全部新字段
  - 单测覆盖：旧 JSON 加载 → 字段补齐 + schema_version 标为 0.4b
- 契约影响：ResourceRecord 字段新增（向后兼容）
- 依赖：T-4a 全部完成 + 生产稳定 1 周
- 验收：单测全过；`/tasks` 返回包含新字段
- 工时：2h 代码

### T-4b-02 `/promote` 与 `/intake` 自动写 `expires_at`

- 触达对象：`app/main.py`、`app/models.py`（PromoteRequest 新增 expires_in_hours / expires_at）、单测
- 操作：
  - source_kind → 默认 TTL 表（Q6.1）
  - PromoteRequest 新字段 + 校验（二选一）
  - intake / promote 路径写入 expires_at
- 契约影响：API 入参向后兼容（新字段可选）；ResourceRecord.expires_at 现在会被自动填充
- 依赖：T-4b-01
- 验收：curl 不带新字段时按表写入；带 expires_in_hours 时按用户值；单测含 5 个 source_kind 的默认 TTL 验证
- 工时：2h 代码

### T-4b-03 `puresource-expiry-worker` 进程

- 触达对象：`puresource-playlist/app/expiry_worker.py`（新建，约 200-300 行）、单测
- 操作：
  - 模仿 extract_worker 结构
  - 5min 扫一次 resources.json（通过 `GET /tasks` 而不是直接读文件，避免锁问题）
  - 命中 `expires_at < now + 2h` 的 `external_ready/playable` 资源
  - HEAD 探活（405 降级 GET Range）
  - 失败计数 < 3 → 仅更新 `last_check_status="failed"` + `consecutive_check_failures+=1`
  - 失败计数 = 3 → 推 stage → `expired`
  - 成功 → 刷新 `last_check_status="ok"`、`last_check_at=now`、`consecutive_check_failures=0`、可选刷 `expires_at`（视服务器 Cache-Control 而定，初版不刷）
  - 回写都通过 `POST /internal/tasks/{id}/expiry-result`
- 契约影响：新进程；不直写 resources.json
- 依赖：T-4b-01
- 验收：单测覆盖 happy / failed / timeout / 405-fallback；造 5 条 expires_at 已过的资源，run 一轮后全部进入 `expired`
- 工时：4h 代码

### T-4b-04 主服务 `/internal/tasks/{id}/expiry-result` 端点

- 触达对象：`app/main.py`、`app/models.py`（ExpiryResultRequest 新模型）、单测
- 操作：
  - 与 extract-result / bt-probe-result 对称
  - localhost 校验
  - 接受 status / last_check_at / last_check_status / consecutive_check_failures / 新 stage（如降级）
  - 更新 ResourceRecord 相应字段
- 契约影响：新端点
- 依赖：T-4b-01
- 验收：curl 内部端点 200；公网 curl 仍 403（Caddy `/internal/*` deny）
- 工时：2h 代码

### T-4b-05 新增 `ResourceStage.expired` 枚举

- 触达对象：`app/models.py`、`app/store.py`、前端 `static/app.js` STAGE_ORDER、`static/app.css` badge.expired
- 操作：枚举加值；`_migrate_legacy` 不需要改（stage 字段已存在）；前端加 tab + badge
- 契约影响：API 返回的 stage 集合扩大
- 依赖：T-4b-01
- 验收：`/tasks` 可返回 stage=expired；UI 有独立 tab
- 工时：0.5h 代码

### T-4b-06 前端徽章 + 重新探测按钮

- 触达对象：`static/{index.html,app.js,app.css}`
- 操作：
  - renderTask 加 expires_at 计算 + 徽章 class
  - 加"重新探测"按钮（按 source_kind 调相应端点）
  - in-flight 超时（Q4.4）的视觉提示一并做（虽然是 v0.4a 设计的，落代码在 v0.4b 一起）
- 契约影响：纯前端
- 依赖：T-4b-01、T-4b-02
- 验收：jsdom 端到端测试：构造 4 类 expires_at 状态（不显 / 软 / 硬 / 已过期），分别命中 4 种 css class
- 工时：3h 代码

### T-4b-07 `default.m3u8` 过滤已过期

- 触达对象：`app/playlist.py`、单测
- 操作：
  - 读 env `PURESOURCE_M3U8_FILTER_EXPIRED`（默认 `"1"`）
  - 过滤 `expires_at` 已过期的资源
- 契约影响：行为变更（默认开）；通过 env 关闭
- 依赖：T-4b-02
- 验收：造一条 expired 资源，确认 playlist 不含；env 设 0 后含
- 工时：1h 代码

### T-4b-08 `puresource-expiry-worker` systemd unit + 部署

- 触达对象：`/etc/systemd/system/puresource-expiry-worker.service`
- 操作：与 extract-worker unit 结构相同；`ExecStart=/opt/puresource-playlist/.venv/bin/python -m app.expiry_worker`
- 契约影响：新 unit
- 依赖：T-4b-03 部署完成
- 验收：`systemctl is-active puresource-expiry-worker` = `active`；24h 内观察 stage=expired 资源数量符合预期
- 工时：0.5h 运维

### T-4b-09 端到端 + 文档更新

- 触达对象：单测、`puresource-playlist-v0.4-cutover-checklist.md`（v0.4 整体 cutover 文档新增）
- 操作：
  - 端到端造一条 mp4 任务，TTL 设 1min，等 6min 后断言 stage=expired
  - 端到端造一条 magnet，重新探测按钮触发 bt-probe，等 metadata_ready
  - 更新 cutover checklist 含 v0.4b 上线步骤
- 契约影响：无
- 依赖：T-4b-01..T-4b-08
- 验收：端到端 pass + 文档存在
- 工时：3h 代码 + 1h 文档（运维）

---

## 8. 依赖图（覆盖 v0.4a + v0.4b 全部任务）

### v0.4a 依赖图

```
T-4a-00 (基线对齐)
  ├─→ T-4a-01 (cookies 目录)
  │     └─→ T-4a-05 (extract-worker unit)
  ├─→ T-4a-02 (yt-dlp 装)
  │     └─→ T-4a-05
  ├─→ T-4a-03 (kill 8091 dev) ⚠️
  │     └─→ T-4a-04 (rsync btprobe 代码)
  │            └─→ T-4a-09 (btprobe unit) ←──── T-4a-08 (凭据文件) ←── T-4a-07 (qbt 配置) ←── T-4a-06 (apt 装 qbt) ⚠️
  ├─→ T-4a-06 ⚠️
  ├─→ T-4a-12 (备份 resources.json)
  │     └─→ T-4a-13 (灰度演练)
  └─→ T-4a-OPT-01 (可选 /diag)  ⚠️
          └─→ T-4a-10 (rsync 主服务代码)

T-4a-05, T-4a-09, T-4a-OPT-01 都 → T-4a-10 (rsync v0.3)
T-4a-10 → T-4a-11 (drop-in Environment)
T-4a-11, T-4a-13 都 → T-4a-14 (cutover-1)
T-4a-14 (观察期完毕) → T-4a-15 (cutover-2)
T-4a-15 → T-4a-16 (烟测种子) + T-4a-17 (烟测 yt-dlp)
T-4a-16 + T-4a-17 → T-4a-18 (24h 滚动观测)
```

**可并行段（v0.4a）**：
- T-4a-01 / T-4a-02 / T-4a-06 / T-4a-12 互相独立，可并行
- T-4a-04 与 T-4a-05 互相独立
- T-4a-16 与 T-4a-17 可并行

### v0.4b 依赖图

```
T-4a-18 ✓ (v0.4a 稳定 1 周) → T-4b-01 (新字段 + migrate)
T-4b-01
  ├─→ T-4b-02 (intake/promote 自动写 expires_at)
  ├─→ T-4b-03 (expiry-worker 代码)
  ├─→ T-4b-04 (/internal/expiry-result 端点)
  └─→ T-4b-05 (expired stage 枚举)

T-4b-02 + T-4b-05 → T-4b-06 (前端徽章 + 重新探测)
T-4b-02 → T-4b-07 (m3u8 过滤)
T-4b-03 + T-4b-04 (双方都需要先在主服务上线) → T-4b-08 (worker systemd 部署)
T-4b-06, T-4b-07, T-4b-08 都 → T-4b-09 (端到端 + 文档)
```

**可并行段（v0.4b）**：
- T-4b-02 / T-4b-03 / T-4b-04 / T-4b-05 互相独立，可并行（前提是 T-4b-01 已 merge）
- T-4b-06 与 T-4b-07 互相独立

### 跨段（v0.4a → v0.4b）依赖

仅一条：**T-4a-18（v0.4a 完成 + 1 周稳定）→ T-4b-01**。其余 v0.4b 不依赖 v0.4a 具体任务。

---

## 9. 等待用户裁决的 N 项清单

| # | 来源 | 裁决项 | 建议 | 阻塞性 |
|---|------|------|------|------|
| **D1** | §2-D1 / Q1 | cutover 时序：一次切完 vs 两次拆分 | **两次拆分** | 阻塞 T-4a 整体编排 |
| **D2** | §2-D2 | VPS 上跑真实 qBittorrent（出现 DHT 足迹）是否触犯红线 §2.3.2 的精神 | 用户决定；**若否决**，QBT_MOCK 永驻 1，T-4a-06/07 跳过 | 阻塞 T-4a-06、T-4a-15 |
| **D3** | §2-D6 + Q12.1 | v0.4b 顺手预埋 5 个字段（tags / category / favorited_at / verified_by / source_trust） | **采纳** | 阻塞 T-4b-01 字段清单 |
| **D4** | Q2.1 | qBittorrent 是否需要更严格版本固化（pin deb 文件） | **不必**，apt-mark hold 足够 | 不阻塞 |
| **D5** | Q2.4 | qBittorrent 软配额 5GB 是否合适 | **合适** | 不阻塞 |
| **D6** | Q3.1 | 烟测是否加一个预期失败种子 | **加**（T-4a-16 拆 16a / 16b） | 不阻塞 |
| **D7** | Q3.3 | cutover-2 烟测容忍度："3 中 2 过"放行还是必须 3 中 3 过 | **3 中 3 过**（不放宽） | 不阻塞 |
| **D8** | Q4.2 | 是否做 `GET /diag` 端点（T-4a-OPT-01） | **做**（P1） | 不阻塞 cutover，但强烈建议 |
| **D9** | Q4.4 | in-flight 超时阈值 N=600s 是否合适 | **保持** | 不阻塞 |
| **D10** | Q5.3 | 回滚硬判据 #5：stop 还是 disable | **两者都做** | 不阻塞 |
| **D11** | Q6.3 | 允许"永不过期"（`expires_at=null` 显式抑制） | **允许** | 不阻塞 |
| **D12** | Q7.3 | 新增 `expired` stage vs 用 `failed + failure_reason="expired"` | **新增 `expired`** | 阻塞 T-4b-05 |
| **D13** | Q7.6 | expiry-worker：常驻进程 vs systemd timer + oneshot | **常驻进程**（与 extract-worker 对称） | 阻塞 T-4b-08 unit 形态 |
| **D14** | Q8.2 | 徽章阈值 6h / 2h / 0 | **保持** | 不阻塞 |
| **D15** | Q8.3 | `default.m3u8` 默认过滤已过期资源 | **默认开**（PURESOURCE_M3U8_FILTER_EXPIRED=1） | 阻塞 T-4b-07 默认行为 |
| **D16** | Q9.3 | 加 `schema_version` 字段（仅日志，不参与决策） | **加** | 阻塞 T-4b-01 字段清单 |
| **D17** | Q10 | v0.4a 与 v0.4b 串行 vs 并行 | **串行**（v0.4a 稳定 1 周后开 v0.4b） | 影响排期 |
| **D18** | T-4a-03 | 是否由用户手动 kill 开发态 PID 1894331 | **由用户手动 kill** 或确认 Cursor 代杀 | 阻塞 T-4a-04 |
| **D19** | T-4a-09 | btprobe 进程 User=root 还是新建 `qbt` 专用户 | **root**（btprobe 不读 resources.json，权限收益小） | 不阻塞 |
| **D20** | §2-D2 衍生 | 若 D2 否决：是否仍部署 puresource-btprobe（QBT_MOCK 永驻 1） | **仍部署**（保留代码路径，便于未来翻转） | 不阻塞 |

---

本轮纯谋阶段已完成，等待用户审阅后切换到 v0.4a / v0.4b 执行阶段。
