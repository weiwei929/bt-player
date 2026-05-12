# PureSource v0.3：VPS 端资源探测 + 视频图书馆方案

> 日期：2026-05-12（Cursor 评审修订版）
> 基于架构设计小结的实证结论 + Cursor Canvas 契约审查反馈

---

## 一、定位修正：探测与播放分离

经过 2026-05-11 PotPlayer 闭环实证和 PikPak CDN 裸 URL 验证，一个关键事实已经明确：

> **VPS 不需要缓存视频文件本身。VPS 需要的是"知道资源里有什么、能不能播、播哪个 URL"。**

因此 qBittorrent 的角色从架构文档中的"BT 缓存执行器"修正为：

> **qBittorrent = BT 资源探测器（metadata + 文件树 + peer 状态），缓存是可选能力而非默认路径。**

同样，yt-dlp 的角色是：

> **yt-dlp = 网页/直链资源探测器，从站点页面提取可播放 URL，不下载媒体内容。**

---

## 一.三、边界声明（Cursor 评审 §1-2 决策）

### bt-probe 作为独立服务

遵循架构小结 §2.3.2 的红线——**不在 PureSource 主服务里默认接入 DHT、peer、libtorrent、qBittorrent 或 rqbit**：

```
puresource-playlist (8090)       # 主服务：调度台 + 播放列表
    │
    └── HTTP ──→ puresource-btprobe (8091)   # 独立服务：qBittorrent 探测
                     │
                     └── Web API ──→ qbittorrent-nox (8080)
```

- bt-probe 独立 systemd unit、独立端口、独立失败域
- 主服务只通过 HTTP 拉结果，不直接连 qBittorrent
- bt-probe 崩溃不影响播放列表生成
- 未来换成 rqbit/libtorrent Rust 实现只需换探针，主服务无感

### yt-dlp 走异步任务

`yt-dlp --dump-json` 耗时 5-30s+，不能同步阻塞 FastAPI 端点（现有 `probe_record` 的 `PROBE_TIMEOUT_S=5.0` 已确立"秒级返回"契约）：

- `POST /tasks/{id}/extract` **立即返回** `stage=extracting`
- 后台线程执行 yt-dlp，完成后回写 stage + 结构化结果
- 超时 45s，强制 kill 僵尸进程
- cookies 文件限定到 `/var/lib/puresource/cookies/` 白名单目录（不接受用户传任意路径，防文件读取漏洞）
- qBittorrent 凭据通过环境变量注入，**绝不写进 `data/resources.json`**

---

## 二、两把探测刀

### 2.1 yt-dlp 集成（网页 → 可播 URL）

**输入**：网页 URL
**输出**：候选 stream_url 列表（含格式、码率、容器信息）

**集成方式**：`puresource-playlist` 新增异步端点

```
POST /tasks/{id}/extract
  → 返回 202，stage=extracting
  → 后台线程: yt-dlp --dump-json <url>
  → 解析输出，写入 ResourceRecord.extract_candidates[]
  → stage 推进到 playable（有候选）或 failed（无候选）
  → 前端轮询 /tasks 获取结果
```

**为什么不做全自动 promote**：yt-dlp 可能产出多个候选（不同码率/格式），需要人工选择。

**边界**：
- 不下载媒体内容（`--dump-json` 只取元数据）
- 不处理需要浏览器 JS 执行的站点（交给油猴脚本补充）
- cookies 文件白名单目录 `/var/lib/puresource/cookies/`

### 2.2 qBittorrent 探测（magnet → 文件树 + peer 状态）

**输入**：magnet URI
**输出**：文件树（文件名、大小）、peer 数量、DHT 活跃度

**集成方式**：独立服务 `puresource-btprobe`（端口 8091），主服务通过 HTTP 调用

```
POST /tasks/{id}/bt-probe
  → puresource-playlist 发 HTTP 到 127.0.0.1:8091/probe
  → bt-probe 调用 qBittorrent Web API 添加 magnet
  → 轮询等待 metadata 下载完成
  → 获取文件列表 + peer 状态
  → 设置所有文件为"不下载"优先级
  → 返回结构化文件树
  → 主服务写入 ResourceRecord.magnet.files[] / .peers
  → stage 推进到 metadata_ready
```

**qBittorrent Web API 关键端点**：

| API | 用途 |
|-----|------|
| `POST /api/v2/torrents/add` | 添加 magnet，开始 metadata 下载 |
| `GET /api/v2/torrents/info` | 查询状态（state、progress、peers、seeds） |
| `GET /api/v2/torrents/files?hash=xxx` | 获取文件树（name、size） |
| `POST /api/v2/torrents/filePrio` | 设置文件优先级（0 = 不下载） |
| `POST /api/v2/torrents/delete` | 删除探测任务 |

**探测状态机**：

```
magnet 提交
  → bt_probing (qBittorrent 从 DHT/tracker 拉 metadata)
  → metadata_ready (已拿到文件树 + peer 状态)
  → 用户决策：
      ├── 正片有活跃 peer → 可选缓存（bt-probe 提供缓存接口）
      ├── 正片无活跃 peer → 标记 low_peer，不进播放列表
      └── 需要 PikPak 转存 → 人工操作，拿到 CDN URL 后 promote
```

**缓存策略（明确为可选，且不默认触发）**：

- 默认不缓存。PotPlayer 已能直接播放远程 URL，VPS 存储有限（25G 可用）。
- 仅在以下情况考虑缓存：冷门种子（peer < 3）、唯一来源、用户明确操作。
- 缓存通过 bt-probe 独立服务的 `/cache` 端点触发，主服务不发起缓存。

---

## 二.三、契约变更清单（Cursor 评审 §3-5 决策）

以下是实施方案前**必须先改**的现有代码契约。这些改动集中在 `models.py`，是后续所有探测器接入的基础。

### 1) ResourceStage 枚举扩展

```python
class ResourceStage(str, Enum):
    pending = "pending"            # 未探测
    probing = "probing"            # HTTP probe 中（已有）
    extracting = "extracting"      # yt-dlp 提取中（新增）
    bt_probing = "bt_probing"      # qBittorrent metadata 拉取中（新增）
    metadata_ready = "metadata_ready"  # 已获取文件树/peer，尚未确认 stream_url（新增）
    playable = "playable"          # 有 stream_url 候选，待确认
    external_ready = "external_ready"  # 已入列 PotPlayer
    failed = "failed"              # 探测失败
```

### 2) 新增结构化字段

**`ExtractCandidate`**（yt-dlp 输出，不在 probe_log 里截断）：

```python
class ExtractCandidate(BaseModel):
    title: str
    stream_url: str
    container: Optional[str] = None   # mp4 / m3u8 / ts
    resolution: Optional[str] = None  # "1920x1080"
    bitrate_kbps: Optional[int] = None
    extracted_at: str

# 上限
EXTRACT_CANDIDATES_MAX = 12
```

**`MagnetFile`**（bt-probe 文件树）：

```python
class MagnetFile(BaseModel):
    path: str
    size_bytes: int
    is_recommended_main: bool = False

MAGNET_FILES_MAX = 256
```

**`MagnetInfo` 扩展**（在现有字段基础上增加）：

```python
class MagnetInfo(BaseModel):
    # ... 现有字段 info_hash, display_name, trackers, enrich_log ...
    files: list[MagnetFile] = Field(default_factory=list)  # 新增
    peers: Optional[int] = None     # 新增：当前连接 peer 数
    seeds: Optional[int] = None     # 新增：当前做种数
    availability: Optional[float] = None  # 新增：0.0–1.0 可用度
```

**`ResourceRecord` 新增字段**：

```python
class ResourceRecord(BaseModel):
    # ... 现有字段 ...

    # === v0.3 新增 ===
    expires_at: Optional[str] = None           # stream_url 预计失效时间 ISO-8601
    verified_by: Optional[str] = None          # manual | yt_dlp | bt_probe | http_probe | pikpak_export | tampermonkey
    source_trust: Optional[str] = None         # manual_verified | auto_probe | external
    failure_reason: Optional[str] = None
    refresh_hint: Optional[str] = None
    extract_candidates: list[ExtractCandidate] = Field(default_factory=list)  # yt-dlp 结构化结果
    playback: Optional[PlaybackInfo] = None    # 标准播放对象（最小冻结版）
```

### 3) PlaybackInfo — 标准播放对象最小冻结版

只包含已验证的字段，不预设未实现能力：

```python
class PlaybackInfo(BaseModel):
    recommended_executor: str = "external_player"  # external_player | local_stream | hls_preview
    web_preview: str = "unavailable"               # available | available_but_not_primary | unavailable
    reason: Optional[str] = None                   # 如 browser_remote_mp4_pipeline_unstable
```

### 4) promote 放宽

当前 `promote` 限制 `stage in (playable, external_ready)`。bt-probe 产出 `metadata_ready` 后需要允许从 pending / metadata_ready promote：

```python
# 修改 main.py promote_task 的校验
ALLOWED_PROMOTE_STAGES = {ResourceStage.pending, ResourceStage.metadata_ready,
                          ResourceStage.playable, ResourceStage.external_ready}
```

约束：从 `pending` / `metadata_ready` promote 时必须提交 `stream_url`；从 `playable` / `external_ready` promote 时可选覆盖。

### 5) `/intake` 扩展

新增可选字段：`verified_by`、`expires_in_hours`。用于 PikPak 导出 / 油猴捕获等手动验证路径的溯源和过期标注。

---

## 三、数据流：从探测到入列

```
                     ┌──────────────────────────────┐
                     │    puresource-playlist        │
                     │      (VPS :8090)              │
                     │                               │
  网页 URL ─────────→│  POST /tasks                  │
                     │  POST /tasks/{id}/extract     │──→ yt-dlp (异步后台线程)
                     │                               │
  magnet  ──────────→│  POST /tasks                  │
                     │  POST /tasks/{id}/enrich      │──→ 纯字符串解析 (已有)
                     │  POST /tasks/{id}/bt-probe    │──→ HTTP → bt-probe (:8091)
                     │                               │
  mp4/m3u8 直链 ────→│  POST /tasks                  │
                     │  POST /tasks/{id}/probe       │──→ HTTP probe (已有)
                     │                               │
  PikPak CDN / 油猴 ─→│  POST /intake                 │──→ 直接入列 (已有，v0.3 扩展)
                     │                               │
                     │  人工确认 → promote            │
                     │  写入 stream_url + status      │
                     │                               │
                     │  GET /playlists/potplayer/     │
                     │      default.m3u8              │──→ PotPlayer 订阅
                     └──────────────────────────────┘

                     ┌──────────────────────────────┐
                     │    puresource-btprobe          │
                     │      (VPS :8091)              │
                     │                               │
  POST /probe  ──────→│  qBittorrent Web API 交互     │──→ qbittorrent-nox (:8080)
  POST /cache  ──────→│  可选：触发缓存                │
                     └──────────────────────────────┘
```

---

## 四、前端 UI：资源图书馆

当前工作台（`app/static/`）已有骨架：
- 任务列表 + stage 筛选 tabs
- probe / enrich / promote 操作按钮
- magnet info 展示区

需要新增：

### 4.1 stage tabs 扩展

```
[全部] [pending] [extracting] [bt_probing] [metadata_ready] [playable] [external_ready] [failed]
```

### 4.2 探测操作扩展

```
现有按钮：
  mp4/m3u8 → [probe]
  magnet   → [enrich]
  playable/external_ready/metadata_ready → [promote]

新增按钮：
  webpage/mp4/m3u8 → [extract]   （yt-dlp 提取）
  magnet           → [bt-probe]  （qBittorrent 探测文件树）
```

### 4.3 磁链文件树展示

bt-probe 完成后，magnet info 区域渲染文件树（数据来自 `MagnetInfo.files[]`）：

```
┌─────────────────────────────────────────────────┐
│ magnet  v1  info_hash: 2CBB4A...                │
│ peers: 12  seeds: 5  availability: 0.87         │
│                                                  │
│ 文件树:                                           │
│   📁 Sample/                                     │
│     📄 sample.mp4        15.2 MB                 │
│   📄 Yanni_LasVegas.mp4  4.3 GB  ★ 正片推荐      │
│   📄 Cover.jpg           0.2 MB                  │
│                                                  │
│ [promote 需要 stream_url]                        │
└─────────────────────────────────────────────────┘
```

### 4.4 生命周期展示

```javascript
// 每个 task 卡片展示
过期: 2026-05-13 18:00 (剩余 ~18h)    // 来自 expires_at
验证来源: pikpak_export                // 来自 verified_by
失败原因: peer=0, availability=0       // 来自 failure_reason
刷新方式: re-export from PikPak        // 来自 refresh_hint
推荐执行器: external_player            // 来自 playback.recommended_executor
```

---

## 五、凭据与异步约定

### 凭据来源和边界（硬验收项）

| 凭据类型 | 来源 | 约束 |
|---------|------|------|
| qBittorrent Web API 用户名/密码 | 环境变量 `BT_PROBE_USER` / `BT_PROBE_PASS` | **绝不写进** `data/resources.json` 或 git |
| yt-dlp cookies | `/var/lib/puresource/cookies/` 目录，用户 SCP 上传 | 不接受用户传任意路径；端点校验路径必须在白名单目录内 |
| PikPak URL 中的 `userid`/`sign` | 由外部工具（PikPak 客户端/油猴）提交到 `/intake` | `data/resources.json` 含短期凭据，不在公网暴露；部署文档注明不 rsync 出 VPS |

### 异步语义

| 端点 | 调用方式 | 返回时机 |
|------|---------|---------|
| `POST /tasks/{id}/probe` | 同步 | 秒级返回（≤5s） |
| `POST /tasks/{id}/enrich` | 同步 | 毫秒级（纯字符串计算） |
| `POST /tasks/{id}/extract` | **异步** | 立即返回 stage=extracting，后台线程跑 yt-dlp（≤45s） |
| `POST /tasks/{id}/bt-probe` | **异步** | 立即返回 stage=bt_probing，bt-probe 服务轮询 qBittorrent（≤120s） |

---

## 六、实施步骤

### Step 1：数据模型升级（先于所有探测器）

```
puresource-playlist 修改：
  models.py — ResourceStage 新增 3 枚举值
  models.py — 新增 ExtractCandidate / MagnetFile / PlaybackInfo
  models.py — ResourceRecord 新增生命周期字段 + extract_candidates + playback
  models.py — MagnetInfo 新增 files / peers / seeds / availability
  main.py   — promote 放宽 ALLOWED_PROMOTE_STAGES
  main.py   — intake 支持 verified_by / expires_in_hours
  app/static/app.js — stage tabs 扩展 + 生命周期信息展示
```

**验收**：curl `/intake` 传入 `verified_by=pikpak_export&expires_in_hours=24`，返回 resource 含 `expires_at`、`verified_by`、`source_trust`、`playback` 字段。旧 `/tasks` 端点仍正常。

### Step 2：bt-probe 独立服务 + qBittorrent 部署

```
VPS 侧：
  apt install qbittorrent-nox
  systemd unit: puresource-btprobe.service (端口 8091)
  systemd unit: qbittorrent-nox.service (端口 8080，仅 127.0.0.1)
  qBittorrent 默认：添加后不自动下载、文件优先级=0

puresource-btprobe 新服务：
  POST /probe  — 接收 magnet，返回文件树 + peer 状态
  POST /cache  — 可选触发正片缓存
  GET /health  — 探活

puresource-playlist 新增：
  POST /tasks/{id}/bt-probe — HTTP 调用 bt-probe (:8091)
  前端：magnet 任务增加 [bt-probe] 按钮
```

**验收**：POST 一个热门 magnet 到 `/tasks/{id}/bt-probe`，等待后返回文件树 JSON 含 ≥1 个文件。`stage` 推进到 `metadata_ready`。前端文件树正常渲染。

### Step 3：yt-dlp 集成

```
puresource-playlist 新增：
  .venv/bin/pip install yt-dlp
  app/extract.py — 异步 extract 逻辑
  POST /tasks/{id}/extract — 立即返回，后台跑 yt-dlp
  前端：webpage/mp4/m3u8 任务增加 [extract] 按钮
```

**验收**：对一个 BiliBili 短视频或 YouTube 视频 POST `/tasks/{id}/extract`，返回至少 1 个 `ExtractCandidate`。前端弹窗展示候选，选中一个 promote 后出现在 `default.m3u8`，PotPlayer 能播。

### Step 4：复检 + 降级（v0.3d）

```
puresource-playlist 新增：
  定时任务（systemd timer）：扫描 expires_at 过期的 external_ready 资源
  → 重新 probe → 403 则 stage → failed，写入 failure_reason
  → 仍 200 则更新 expires_at（延长有效期）
  前端：过期资源标记红色，提供"重新验证"和"重新导入"快捷操作
```

---

## 七、一句话总结

> **yt-dlp 负责把网页变候选 URL，qBittorrent（通过独立 bt-probe 服务）负责把磁链变文件树——两把探测刀都只做"发现和验证"，不默认占用 VPS 存储。探测结果汇入 PureSource 工作台形成"视频资源图书馆"，只有确认可播的资源才进 PotPlayer 的 m3u8 订阅列表。**
