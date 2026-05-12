# PureSource + BT-Player 架构方案

> 日期：2026-05-09（v3，吸纳浏览器代理 + ffmpeg + 生态调研 + Web3 探索）
> 基于 BT-Player 现有代码（VPS axum 版）的演进方案
> 当前部署机器：Oracle 首尔 ARM Debian 12 | 11GB RAM | 45GB 磁盘

---

## 一、整体定位

```
PureSource = 视频资源图书馆
职责：采集、提纯、编目所有视频资源
不关心怎么看、在哪看

BT-Player = 播放厅
职责：接收提纯后的源，稳定流畅地播放
不关心源从哪来、怎么找到的
```

两个服务各自有独立存在的价值，互不耦合，通过数据契约通信。

### 1.1 三阶架构总览

PureSource 本身不直接接触用户浏览器环境。引入**浏览器代理层**后，完整的架构是：

```
浏览器代理层（Tampermonkey 油猴脚本）
  │  HTTPS
  │  从用户浏览的页面中主动捕获：m3u8 URL、<video> 元素、磁链
  │  将捕获结果提交给 PureSource 做提纯
  ▼
PureSource（VPS 9530）
  │  接收来自浏览器代理 / 用户直接输入 / API 调用的待提纯源
  │  执行规则引擎 + AI 分析 + ffmpeg 检测
  │  输出标准化资源目录
  ▼
BT-Player（VPS 9528）
    接收提纯结果，稳定播放
```

### 1.2 PureSource 的三种输入通道

| 通道 | 说明 | 典型场景 |
|------|------|---------|
| ① 浏览器代理捕获 | 油猴脚本自动检测当前页面的 m3u8/视频/磁链，POST 到 PureSource | 用户正在浏览视频网站，脚本自动发现资源 |
| ② 用户主动提交 | 在 BT-Player 前端粘贴 magnet/m3u8/网页 URL | 用户从其他渠道获得链接 |
| ③ API 批量导入 | 通过 `/purify/batch` 一次提交多个 URL | 批量整理、RSS 订阅、定时任务 |

---

## 二、浏览器代理层（PureSource Browser Agent）

### 2.1 定位

浏览器代理层基于现有的 `解析器.md`（Tampermonkey 油猴脚本）改编，是 PureSource 在**浏览器运行时的触角**。

它解决 PureSource 服务端无法解决的问题：**JS 动态加载的视频地址**。许多视频网站的视频 URL 只在 JS 运行时才出现，服务端静态抓取 HTML 无法捕获。

### 2.2 检测机制（来自 解析器.md 的成熟方案）

| 机制 | 实现方式 | 捕获内容 |
|------|---------|---------|
| **Response.prototype.text 钩子** | 拦截所有 `fetch()` 响应，检测是否以 `#EXTM3U` 开头 | m3u8 直播/点播流 |
| **XMLHttpRequest.prototype.open 钩子** | 劫持 XHR 的 load 事件，检测 responseText | XHR 加载的 m3u8 |
| **<video> 元素轮询** | 每 1 秒扫描页面新增的 `<video>` 元素 | 直接视频源 URL |
| **磁链正则扫描** | 在页面文本和元素属性中匹配 `magnet:?xt=urn:btih:` | 磁力链接 |
| **m3u8 解析** | 使用 `m3u8-parser` 库解析 manifest，提取分段/多码率信息 | 流时长、分辨率、码率 |

> 以上机制已在 解析器.md 中实现并验证，非理论设计。

### 2.3 与 PureSource 的集成模式

```
┌──────────────────────────────────────────────────────────────────┐
│ 浏览器 (用户正在浏览视频网站)                                      │
│                                                                  │
│ 油猴脚本（改编自 解析器.md）                                       │
│   ├── 捕获 m3u8 URL ──────────────────────────────────┐          │
│   ├── 捕获 <video> src ───────────────────────────────┤          │
│   ├── 捕获 magnet 链接 ───────────────────────────────┤          │
│   └── 解析 m3u8 manifest（时长/码率/多轨）──────────────┤          │
│                                                        │          │
│   对每个捕获到的 URL：                                            │
│     ① 显示浮层（原脚本 UI，保留）                                  │
│     ② 自动 POST 到 PureSource API（新增）                        │
│     ③ 返回提纯结果 → 用户可选「BT-Player 播放」或「下载」         │
└────────────────────────────┬─────────────────────────────────────┘
                             │ POST /purify/batch
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ PureSource (VPS)                                                 │
│  接收 → 去重 → 提纯 → AI 编目 → 入库                              │
└──────────────────────────────────────────────────────────────────┘
```

### 2.4 浏览器代理 → PureSource API 契约

```json
POST /purify/batch
{
  "source": "browser-agent",          // 来源标识
  "tabUrl": "https://example.com/play/12345",
  "tabTitle": "正在播放：某某视频",
  "detectedUrls": [
    {
      "url": "https://cdn.example.com/hls/12345.m3u8",
      "detectMethod": "response_hook",    // response_hook | xhr_hook | video_poll | magnet_scan
      "mimeType": "application/vnd.apple.mpegurl",
      "manifestInfo": {                   // m3u8-parser 解析结果
        "duration": 3660,
        "playlists": [
          {"uri": "...1080p.m3u8", "resolution": "1920x1080", "bandwidth": 8000000},
          {"uri": "...720p.m3u8",  "resolution": "1280x720",  "bandwidth": 4000000}
        ],
        "segments": 122
      },
      "pageContext": {
        "title": "某某视频",
        "referer": "https://example.com/play/12345"
      }
    }
  ]
}
```

响应：

```json
{
  "results": [
    {
      "requestId": "p-20260509-001",
      "originalInput": "https://cdn.example.com/hls/12345.m3u8",
      "sourceType": "hls",
      "title": "某某视频",
      "confidence": 0.95,
      "purifiedFiles": [...],
      "recommended": {
        "action": "play",
        "reason": "AI 确认正片"
      }
    }
  ]
}
```

### 2.5 浏览器代理保留的独立能力

即使不与 PureSource 配合，浏览器代理也应保留其独立功能（现 解析器.md 已有的）：

- **独立下载**：CORS fetch → FileSystem API → GM_xmlhttpRequest 三级降级策略
- **PikPak 播放**：一键发送到 PikPak 离线
- **复制链接**：复制原始 URL
- **浮层 UI**：拖拽、显隐、计数

新增的 PureSource 集成是**叠加**而非替代关系。

---

## 三、PureSource 视频资源图书馆

### 3.1 职能范围

PureSource 承担所有视频资源的**发现→提纯→编目**过程：

```
输入                                    PureSource 处理                   输出
────                                    ──────────────                   ────

浏览器代理捕获（m3u8/视频/磁链）         ① 源发现（归类+去重）              
  │                                        │                             
用户主动提交（magnet/URL/种子）           ② 提纯（筛选/过滤/ffmpeg检测）   
  │                                        │         标准化资源目录
API 批量导入                            ③ 编目（AI 分类/标记/评估）─────►  JSON 清单
  │                                        │                             
                                       ④ 入库（缓存/索引）               
```

#### ① 源发现

| 类型 | 检出方式 | PureSource 处理 |
|------|---------|----------------|
| **m3u8 URL（运行时捕获）** | 浏览器代理钩取 Response/XHR | 解析多码率 playlist，自动选最优线路，附加 Referer/Origin 防盗链头 |
| **<video> 元素 src** | 浏览器代理轮询 | 验证可访问性，提取编码格式 |
| **magnet 磁链** | 浏览器代理文本扫描 + 用户直接提交 | librqbit 解析，文件筛选，广告过滤，正片推荐 |
| **网页 URL（反盗链）** | 用户主动提交 | AI 理解页面结构，识别真实视频源；配合浏览器代理做 JS 运行时捕获 |
| **种子文件 .torrent** | 用户上传 / URL 提交 | 解析文件列表，等同 magnet 提纯流程 |

#### ② 提纯（核心加工环节）

| 操作 | 实现方式 | 说明 |
|------|---------|------|
| 文件筛选 | 规则引擎 | 从文件包中只保留视频文件（mp4/mkv/webm/avi），排除 NFO/样本/广告 |
| 广告过滤 | 大小 + 文件名规则 + AI 兜底 | 小于 50MB 的视频标记为疑似广告；文件名含 sample/sample 标记；AI 低置信度时做二次判断 |
| 正片推荐 | 文件大小排序 + AI 确认 | 默认选最大的视频文件为主片，AI 对文件名做语义确认 |
| **moov 检测/修复** | **ffprobe + ffmpeg** | **检测 moov atom 位置：头 → 直通，尾 → ffmpeg faststart 后交给 BT-Player** |
| **编码检测** | **ffprobe** | **识别视频编码（h264/h265/av1）、音频编码（aac/opus）、分辨率、码率，写入 purifiedFiles.encoding** |
| 防盗链增强 | 规则引擎 + 浏览器代理传递 | 自动附加 Referer/Origin/User-Agent；浏览器代理从页面上下文提取 Referer |
| 多码率选择 | m3u8-parser 分析 | 解析多码率 playlist，自动选最高带宽线路，支持用户手动切换 |

> **ffmpeg 相关操作均为异步**：将文件路径加入 ffmpeg 任务队列，处理完成后更新提纯结果。不阻塞主流程。

#### ③ 编目——AI 的核心应用场景

编目是 PureSource 引入 AI 的主要环节：

| AI 应用 | 输入 | AI 做什么 | 产出 |
|---------|------|----------|------|
| **网页源识别** | HTML + 页面 URL | 理解页面结构，识别真正的视频容器、播放器、广告区域 | 真实视频 URL 列表及置信度 |
| **内容质量判断** | 文件名/页面标题/元数据 | 判断资源是正片、预告、广告还是无关内容 | 质量评分 + 分类标签 |
| **元数据提取** | 页面内容 / 文件名 | 提取标题、描述、集数、分辨率等信息 | 结构化元数据 |
| **资源去重** | 多个候选源 | 判断多个 URL 是否指向同一内容 | 去重后的最优源 |
| **资源分类** | 提纯后的资源 | 标签化（电影/剧集/综艺/其他） | 分类标签 |

#### ④ 入库

- 提纯结果缓存到本地 SQLite DB
- 可选的 Temp 缓存目录（已下载的部分文件）
- 后续可扩展：PikPak 温层入库、Dropbox 归档

### 3.2 PureSource 的独立价值

PureSource 不依赖 BT-Player，可以独立服务：

```
PureSource
  │
  ├───→ BT-Player（主消费方，实时播放）
  ├───→ PikPak（转存云端，长期保存）
  ├───→ qBittorrent-nox（完整下载，seedbox）
  ├───→ Dropbox（精选归档）
  └───→ 直接输出给用户（文件清单浏览）
```

---

## 四、BT-Player 播放厅

### 4.1 职能范围

BT-Player 聚焦为"将提纯后的源解析并稳定播放"，不再承担源发现职责：

```
PureSource 提纯结果
  │
  ▼
BT-Player 接收
  │
  ├── ① 判断文件状态
  │     ├── 已下载完成 → 本地磁盘流播（local-stream）
  │     ├── 下载中 → librqbit 边下边播（/stream/）
  │     ├── moov 在末尾 → 等待 ffmpeg faststart 完成再播
  │     └── 冷门无种子 → 提示用户
  │
  ├── ② 执行播放
  │     ├── 浏览器 <video>（m3u8 直链）
  │     └── local-stream Range 响应（本地文件）
  │
  ├── ③ 管理
  │     ├── 播放历史
  │     ├── 断点续播
  │     └── 下载队列（可选）
  │
  └── ④ 缓存策略
        ├── 磁盘空间监测
        └── 缓存淘汰
```

### 4.2 当前 BT-Player 已有能力的保留

| 模块 | 保留 | 说明 |
|------|------|------|
| `engine/mod.rs` | ✅ | librqbit BT 引擎，核心下载能力 |
| `handle_resolve` | ✅ | 接收提纯源，返回流地址 |
| `handle_local_stream` | ✅ | 本地文件 Range 流播 |
| `db.rs` | ✅ | SQLite 播放历史/断点续播 |
| `handle_file_tree` | ✅ | 文件列表查询 |
| Cloud Export | ✅ | PikPak 转存占位接口 |

### 4.3 需要从 BT-Player 迁往 PureSource 的逻辑

| 代码 | 目标 |
|------|------|
| `resolver/webpage.rs` WebPageResolver | PureSource 网页源提纯 |
| `resolver/magnet.rs` 中的 can_handle | PureSource 源识别 |
| `ai_strategy.rs` 广告分析 | PureSource AI 编目 |
| `layer/mod.rs` LinkTier 部分逻辑 | PureSource 分类标准 |

---

## 五、VPS 部署方案

### 5.1 单机部署（当前阶段）

在同一台 VPS 部署两个服务 + Caddy 统一入口：

```
┌──────────────────────────────────────────────────────┐
│  Oracle 首尔 ARM (Debian 12)                          │
│                                                      │
│  Caddy (443)                                         │
│  │                                                    │
│  ├── bt.mgtv.dev/purify/*     ───────→ PureSource     │
│  │                                    (127.0.0.1:9530)│
│  ├── bt.mgtv.dev/agent/*      ───────→ 浏览器代理 API  │
│  │                                    (127.0.0.1:9530)│
│  ├── bt.mgtv.dev/api/*        ───────→ BT-Player      │
│  │                                    (127.0.0.1:9528)│
│  ├── bt.mgtv.dev/stream/*     ───────→ librqbit       │
│  │                                    (127.0.0.1:9527)│
│  ├── hermes.mgtv.dev/*        ───────→ Hermes Agent    │
│  │                                    (127.0.0.1:待确认)│
│  └── bt.mgtv.dev/             ───────→ 前端静态文件     │
│                                                      │
│  PureSource ──→ SQLite DB (共用或独立)                │
│  BT-Player  ──→ SQLite DB                            │
│  共用缓存目录：/root/bt_cache/                         │
│                                                      │
│  ffmpeg (系统安装) ──→ moov faststart + 编码检测       │
│  Hermes Agent ──→ PureSource AI 推理（M2.7→Gemini 路由）│
└──────────────────────────────────────────────────────┘
```

### 5.2 端口规划

| 端口 | 服务 | 访问范围 | 状态 |
|------|------|---------|------|
| 443 | Caddy HTTPS | 公网 | ✅ 已有 |
| 9527 | librqbit HTTP API (BT 流) | 127.0.0.1 | ✅ 已有 |
| 9528 | BT-Player REST API | 127.0.0.1 | ✅ 已有 |
| 9530 | PureSource 提纯 API | 127.0.0.1 | 🆕 新增 |
| ???? | Hermes Agent API | 127.0.0.1 | ✅ 已有（从 Caddyfile 确认端口） |
| 50051 | BT peer 连接 | 公网 | ✅ 已有 |

### 5.3 Caddy 配置

```
bt.mgtv.dev {
    encode gzip

    # PureSource API（含浏览器代理提交入口）
    handle_path /purify/* {
        reverse_proxy 127.0.0.1:9530
    }

    # BT-Player API
    handle_path /api/* {
        reverse_proxy 127.0.0.1:9528
    }

    # librqbit 流式 API
    handle_path /stream/* {
        uri strip_prefix /stream
        reverse_proxy 127.0.0.1:9527 {
            flush_interval -1
        }
    }

    # 前端静态文件
    handle {
        root * /root/BT-player/dist
        try_files {path} /index.html
        file_server
    }
}
```

> 去掉 `basic_auth`，实验性项目不再设置额外的鉴权层。如果后续需要简单防护，一个全局 `internal` 指令或 IP 白名单即可。

---

## 六、ffmpeg 集成方案

### 6.1 在 PureSource 中的位置

ffmpeg 作为**异步提纯工具**嵌入 PureSource 的处理管线，在源发现之后、编目之前执行：

```
源发现 → 文件筛选 → ┌── ffmpeg 检测 ──┐ → AI 编目 → 入库
                    │                  │
                    │ moov 检测        │
                    │ 编码检测         │
                    │ moov faststart   │
                    └──────────────────┘
```

### 6.2 ffmpeg 功能详表

| 操作 | 命令 | 产出字段 | 耗时 |
|------|------|---------|------|
| **moov 检测** | `ffprobe -v quiet -print_format json -show_format -show_streams <file>` | `moov: "front" | "back"` | 毫秒级（仅读元数据） |
| **编码检测** | `ffprobe -v quiet -print_format json -show_streams <file>` | `videoCodec`, `audioCodec`, `resolution`, `bitrate` | 毫秒级 |
| **moov faststart** | `ffmpeg -i <input> -c copy -movflags faststart <output>` | 产生优化后的新文件 | 取决于文件大小（数秒到数分钟） |
| **片段缩略图** | `ffmpeg -i <input> -ss 00:01:00 -vframes 1 <thumb.jpg>` | 缩略图路径（可选） | 秒级 |

### 6.3 异步处理策略

```
moov/编码检测 → 同步（毫秒级，立即返回结果）
moov faststart → 异步（文件下载完成后触发后台任务）
  ├── 任务队列（SQLite 或内存队列）
  ├── systemd 通知状态
  ├── 完成 → 替换缓存文件 → 更新提纯结果 moov: "front"
  └── 失败 → 标记 + 回退到原始文件
```

### 6.4 依赖

```bash
# VPS 安装
apt install ffmpeg   # Debian 12 官方源，约 50MB
```

---

## 七、数据契约

### 7.1 PureSource → BT-Player 提纯结果

这是两个服务之间的核心数据接口。PureSource 将提纯后的资源以如下格式交付：

```json
{
  "requestId": "p-20260509-001",
  "originalInput": "magnet:?xt=urn:btih:08ada5a7...",
  "sourceType": "magnet",
  "detectMethod": "browser_agent | user_submit | api_import",
  "originUrl": "https://example.com/play/12345",
  "title": "Sintel",
  "confidence": 0.95,

  "purifiedFiles": [
    {
      "index": 3,
      "path": "Sintel.mp4",
      "sizeBytes": 129761280,
      "sizeMb": 123.8,
      "encoding": {
        "videoCodec": "h264",
        "audioCodec": "aac",
        "resolution": "1920x1080",
        "bitrate": 12000000
      },
      "moov": "back",
      "moovOptimized": false,
      "isMainFeature": true,
      "confidence": 0.95,
      "tags": ["正片", "1080p"],
      "isSuspectedAd": false
    },
    {
      "index": 5,
      "path": "Sintel-Sample.mp4",
      "sizeBytes": 5242880,
      "sizeMb": 5.0,
      "encoding": null,
      "moov": null,
      "moovOptimized": false,
      "isMainFeature": false,
      "confidence": 0.3,
      "tags": ["样本"],
      "isSuspectedAd": true
    }
  ],

  "filtered": {
    "totalFiles": 12,
    "kept": 2,
    "removed": 10,
    "removedReasons": ["NFO 文件", "广告", "样本"]
  },

  "headers": {
    "Referer": "https://example.com/",
    "User-Agent": "Mozilla/5.0..."
  },

  "recommended": {
    "action": "play",
    "fileIndex": 3,
    "reason": "最大文件，正片"
  }
}
```

### 7.2 浏览器代理 → PureSource API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/purify/batch` | POST | 浏览器代理提交批量检测到的 URL |
| `/purify/agent/status` | GET | 获取浏览器代理连接状态 |

### 7.3 PureSource API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/purify/resolve` | POST | 提纯单个 URL（magnet/m3u8/网页） |
| `/purify/batch` | POST | 批量提纯 |
| `/purify/status/{requestId}` | GET | 提纯状态查询 |
| `/purify/detect` | GET | 编码检测、moov 位置等元数据 |

### 7.4 BT-Player API（已有，适配）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/resolve` | POST | 接收提纯结果或直接 URL，返回流地址 |
| `/api/local-stream/{torrentId}/{fileIdx}` | GET | 本地文件 Range 流式响应 |
| `/api/history` | GET/POST | 播放历史 |

---

## 八、AI 引入方案

### 8.1 AI 在 PureSource 中扮演的角色

AI 不负责整个提纯流程，而是作为**关键环节的智能增强器**，嵌入到 Pipeline 中：

```
输入 URL
  │
  ▼
源发现 + 浏览器代理捕获（规则引擎优先）
  │     └── 如果规则引擎失败或置信度低 → 交给 AI
  │
  ▼
AI 分析（关键场景）
  │     ├── 网页结构理解 → 提取真实视频 URL
  │     ├── 内容质量判断 → 正片 vs 广告
  │     ├── 元数据提取 → 标题/描述/集数
  │     └── 资源去重 → 多个候选源择优
  │
  ▼
规则引擎后处理（AI 产物的结构化）
  │
  ▼
输出标准提纯结果
```

### 8.2 AI 与浏览器代理的分工

```
浏览器代理（运行时）                    PureSource（服务端）
─────────────────                    ────────────────────
钩取 Response.text                   接收浏览器代理提交的 URL
钩取 XHR.open                        规则引擎去重/归类
轮询 <video> 元素                    AI 网页源识别（纯服务端抓不到时）
扫描页面磁链                          AI 内容质量判断
↓                                    AI 元数据提取
提交 URL 到 PureSource API           ↓
                                     返回提纯结果
```

**关键原则**：浏览器代理不负责判断内容质量，只负责"看见"；PureSource 负责"理解"。

### 8.3 AI 技术的选择

| AI 能力 | 推荐方式 | 说明 |
|---------|---------|------|
| **网页源识别** | LLM API（Claude / OpenAI） | 将网页 HTML + 用户意图发给 LLM，让 LLM 理解页面结构，找出视频源 URL。优势：可以适应任意网站结构，不需要写规则 |
| **内容质量判断** | LLM API + 规则辅助 | 文件名/页面标题 → LLM 判断是否为正片；规则引擎做大小/后缀过滤兜底 |
| **元数据提取** | LLM API | 从页面提取标题、描述、年份、国家等信息 |
| **资源去重** | 向量嵌入 (embedding) + 相似度匹配 | 多个候选源 → embedding 提取特征 → 判断是否同一内容 |
| **基础嗅探** | 规则引擎（还是需要） | 静态 HTML 标签、正则匹配——这些用 LLM 大材小用 |

### 8.4 AI 调用方式

PureSource 对 AI 采取**异步、降级友好**的调用模式：

```
                    ┌──────────────┐
                    │  LLM API     │
                    │ (Claude/其他) │
                    └──────┬───────┘
                           │ HTTP API 调用（异步）
                           ▼
┌──────────────────────────────────────┐
│ PureSource AI Agent                  │
│                                      │
│ ① 规则引擎先尝试（毫秒级）            │
│ ② 规则失败/置信度低 → 发起 LLM 调用   │
│ ③ LLM 返回结果 → 结构化 → 缓存       │
│ ④ 相同 URL 下次直接命中缓存           │
│ ⑤ LLM 不可用时优雅降级到规则引擎       │
└──────────────────────────────────────┘
```

### 8.5 初始阶段 AI 最值得投入的场景

按性价比排序：

1. **反盗链网页的源识别** — 当前 WebPageResolver 无法处理 JS 动态加载的页面，AI 可以理解页面内容找出视频源
2. **正片识别** — 从一堆文件里选出真正的视频，当前 `ai_strategy.rs` 用的是关键词匹配，AI 可以做得更准确
3. **元数据提取** — 为后续编目和搜索打基础

---

## 九、优选推荐引擎

这是一个你刚才点出来的关键洞察：**提纯不应该只"删减"，还应该"推荐"**。

同样的内容，在 4K 电视、电脑显示器、iPad、手机上，最优的播放参数完全不同。PureSource 应该在提纯产物中加入智能推荐层。

### 9.1 三个推荐维度

#### ① 链路推荐（多源择优）

当同一内容存在多个可用源时，按体验质量排序：

```
优先级  源类型                    体验说明
─── ────────────────────────── ───────────────────────
最高  磁链 + 已缓存到本地        local-stream，零延迟，不耗带宽
 高   磁链 + 正在下载            边下边播，初始需缓冲，后续流畅
 中   m3u8 直链（无加密）        依赖源站 CDN，流畅但受网络影响
 低   m3u8（需解密）             额外解密开销，可能延迟
 低   反盗链网页（浏览器代理）     依赖 Referer/Cookie 有效性，最脆弱
```

**典型场景**：Yanni 磁链种子下载到 60% 时 → 边下边播已经流畅。同时用户还有一个 m3u8 直链 → **推荐优先使用磁链播放**，因为本地体验 > 网络流。

#### ② 格式推荐（终端适配）

源文件可能有多种编码/清晰度，按终端能力推荐最佳匹配：

```
终端类型    分辨率上限  推荐编码          说明
───────    ───────── ─────────────── ──────────────────────
4K 电视     3840x2160  h.265 / AV1     大屏需要高码率，HDR 支持
电脑显示器   2560x1440  h.264 / h.265   性能充足，优先高质量
iPad Pro    2388x1668  h.264 / h.265   屏幕细腻，但无 HDR 需求
iPad mini   1488x2266  h.264            中等屏幕，省电优先
手机        1080p 以下  h.264            小屏幕，720p 已足够，省流量
```

**典型场景**：Yanni 种子包含两个版本——4K HDR h.265 (7.8GB) 和 1080p h.264 (2.1GB)：
- 连接电视 → 推荐 4K HDR
- 手机在外面看 → 推荐 1080p h.264（还省电，因为 h.265 解码更耗电）
- 电脑上但带宽有限 → 推荐 1080p，等下载完成再切 4K

#### ③ 体验方式推荐（场景匹配）

同一个视频在**不同的使用场景**下，最佳的播放方式不同：

```
场景                   推荐方式              说明
───                   ──────────          ──────────────────────
坐在电脑前看           直接播放              大屏 + 高码率
用 iPad 躺沙发上看      直接播放              中高码率，自适应
手机在外面/通勤         自适应 HLS            低码率，省流
大屏电视               AirPlay / DLNA      投屏播放，手机当遥控器
家里有 NAS             转存到 NAS + 播放     长期存储 + 随时播放
只想听背景音乐          仅音频模式            关掉视频，只播音频轨
```

**典型场景**：用户用手机打开了 BT-Player，但家里有大屏电视 → PureSource 推荐：
1. 磁链添加到下载队列（后台下载）
2. 先用 m3u8 流让手机直接看（即时满足）
3. 下载完成后提示"是否投屏到电视？"

### 9.2 推荐引擎的输出

PureSource 的提纯结果 JSON 增加 `recommendations` 块：

```json
{
  ...原有字段...,

  "recommendations": {
    "links": [
      {
        "type": "local_cache",
        "torrentId": "9f3a7b2c...",
        "fileIndex": 1,
        "quality": "4K HDR",
        "priority": 1,
        "status": "cached_60%",
        "eta": "2分钟"
      },
      {
        "type": "hls",
        "url": "https://cdn.example.com/hls/yanni/master.m3u8",
        "quality": "1080p",
        "priority": 2,
        "status": "ready"
      }
    ],
    "forDevice": {
      "profile": "ipad_pro",
      "suggestedIndex": 1,
      "suggestedQuality": "1080p",
      "suggestedCodec": "h264",
      "reason": "iPad Pro 屏幕优秀但 battery-aware，推荐 1080p h.264"
    },
    "forScene": {
      "mode": "direct_play",
      "actions": ["play_now", "download_then_cast"],
      "suggested": "play_now"
    }
  }
}
```

### 9.3 设备识别机制

推荐引擎需要知道客户端设备信息。有两种方式：

```
方式 A：前端主动上报（推荐）
  ┌──────────────────────────────────────────────┐
  │ BT-Player 前端启动时检测：                     │
  │  - screen.width × screen.height              │
  │  - navigator.userAgent                        │
  │  - connection.effectiveType (4G/5G/WiFi)     │
  │  - deviceMemory                               │
  │  - 硬件解码能力（video.canPlayType）            │
  │  然后附加在请求中：                              │
  │  POST /purify/resolve + { "client": {...} }   │
  └──────────────────────────────────────────────┘

方式 B：PureSource 按 UA 推断（降级方案）
  └── 如果前端未上报，根据 User-Agent 字符串推断设备类型
```

前端上报的 client 信息格式：

```json
{
  "client": {
    "deviceType": "tablet | phone | desktop | tv",
    "deviceModel": "iPad14,3",
    "screen": {
      "width": 2048,
      "height": 2732,
      "dpr": 2
    },
    "network": {
      "type": "wifi | cellular",
      "effectiveBandwidth": 50
    },
    "capabilities": {
      "codecs": ["h264", "h265", "av1"],
      "hdr": false,
      "maxResolution": "2048x2732"
    },
    "battery": {
      "level": 0.8,
      "charging": false
    }
  }
}
```

### 9.4 推荐引擎在管线中的位置

```
源发现 → 文件筛选 → ffmpeg 检测 → AI 编目 → ┌── 优选推荐 ──┐ → 入库
                                              │              │
                                              │ ① 链路推荐    │
                                              │ ② 格式推荐    │
                                              │ ③ 场景推荐    │
                                              └──────────────┘
                                                        ↑
                                                  需要设备信息
                                                  （前端上报）
```

### 9.5 对 BT-Player 前端的要求

要实现推荐引擎的价值，前端需要做两件事：

1. **设备检测**：启动时采集 screen/network/codec/battery 信息
2. **推荐展示**：在播放界面展示推荐理由

```
BT-Player 播放器 UI 示例：

▶ Yanni Live at The Las Vegas Strip 2024
   ┌─────────────────────────────────────────────┐
   │  ████████████████░░░░░░░░░░░░  60% 已缓存    │
   │                                              │
   │  ✦ 推荐：4K HDR 本地播放                       │
   │     理由：本机 4K 显示器 + WiFi，缓存即将完成     │
   │     备选：1080p 即刻播放（无需等待）              │
   │                                              │
   │  [▶ 播放 4K（等待缓存完成）] [▶ 即刻播放 1080p]  │
   └─────────────────────────────────────────────┘
```

### 9.6 实现路径

| 阶段 | 推荐能力 | 说明 |
|------|---------|------|
| Phase 1 | **纯规则推荐** | 按文件大小 > 编码优先级 > 分辨率排序，基于提纯结果的 encoding 字段做简单推荐 |
| Phase 2 | **设备感知推荐** | 前端上报 UA/Screen，PureSource 按终端推荐最优格式 |
| Phase 3 | **AI 增强推荐** | LLM 综合源质量、终端能力、网络状况做语义推荐，给出自然语言推荐理由 |
| Phase 4 | **场景理解推荐** | 结合历史行为（用户常投屏/常下载后看）+ 时段（晚上回家大概率用电视）做预测 |

---

## 十、实施建议（阶段更新）

### 10.1 推进顺序

```
Phase 0: 当前状态（已完成）
   BT-Player VPS 运行中，有 basic_auth + x-api-key
   librqbit 引擎正常
   local-stream 本地文件播放正常
   解析器.md（Tampermonkey 油猴脚本）已验证可用

Phase 1: BT-Player 沉淀（接下来）
   ① 去掉 Caddy basic_auth（简化安全策略）
   ② 确认 BT-Player 在当前已完成的架构上稳定运行
   ③ 修复当前已知问题（moov 优化、裸 hash 卡死等）

Phase 2: 搭建 PureSource（提纯层独立）
   ① 在 BT-Player 项目内新建 PureSource 子模块
   ② 迁入源发现逻辑（WebPageResolver、磁链筛选等）
   ③ 实现浏览器代理 → PureSource API 接收端点
   ④ 实现 ffmpeg 集成（moov/编码检测）
   ⑤ 定义并实现数据契约 API
   ⑥ 部署为独立服务，Caddy 统一入口

Phase 3: 浏览器代理集成（与 Phase 2 可并行）
   ① 基于 解析器.md 改编为 PureSource Browser Agent
   ② 在捕获 URL 后增加 POST 到 PureSource API 逻辑
   ③ 在前端 BT-Player UI 中增加"通过浏览器代理发现"入口
   ④ 验证端到端链路：浏览页面 → 脚本捕获 → PureSource 提纯 → BT-Player 播放

Phase 4: AI 引入
   ① 选定 AI 场景（建议从反盗链网页源识别开始）
   ② 接入 LLM API（Claude API 或其他）
   ③ 实现缓存/降级/异步调用机制
   ④ 验证 AI 提纯效果

Phase 5: 持续演进
   ① PikPak 转存环节的 AI 辅助
   ② 资源入库策略自动化
   ③ 图书馆功能完善（搜索、标签、收藏）
```

### 10.2 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| PureSource 语言 | Rust | 与 BT-Player 一致，共享基础库 |
| PureSource Web 框架 | axum | 与 BT-Player 一致 |
| BT-Player Web 框架 | axum | 现有 |
| BT 引擎 | librqbit 8.x | 现有，有 local patch |
| 数据库 | SQLite (rusqlite) | 现有，单机够用 |
| 反代 | Caddy | 现有 |
| **站点提取器（外部 fallback）** | **yt-dlp (Python CLI)** | **1800+ 站点支持，PureSource 提取器链无法处理时兜底** |
| **TLS 指纹伪装** | **curl-impersonate (系统工具)** | **绕过 Cloudflare 等反爬检测，借鉴 yt-dlp + curl_cffi 方案** |
| **HLS 解析** | **hls_m3u8 (Rust crate)** | **RFC 8216 兼容，PureSource 服务端原生解析 m3u8 manifest** |
| **HLS 解密** | **mp4decrypt / shaka-packager** | **AES-128/CENC 多密钥解密，借鉴 N_m3u8DL-RE 方案** |
| **ffmpeg** | **系统安装 ffmpeg/ffprobe** | **moov 检测+修复、编码检测、音视频合并** |
| **浏览器代理** | **Tampermonkey 油猴脚本** | **基于现有 解析器.md 改编** |
| **m3u8 解析（浏览器端）** | **m3u8-parser (JS 库, CDN)** | **浏览器代理中解析 manifest** |
| AI | LLM API（Claude API） | 能力最强，更适合理解复杂页面 |
| AI 缓存 | SQLite 缓存 LLM 结果 | 避免重复调用 |
| 前端 | React + Tailwind | 现有 |
| 部署 | systemd 双服务 | 现有 |

---

## 十一、生态借鉴：GitHub 成熟项目的设计启示

PureSource 的设计不必从零开始。GitHub 上有大量成熟项目解决了视频发现、爬取、下载中的各种难题。以下是针对 PureSource 各环节的借鉴分析。

### 11.1 源发现 / 站点提取器

#### yt-dlp（Python, 54k⭐, 1800+ 站点）— 提取器注册表模式的标杆

```
核心架构              PureSource 可借鉴
───────              ────────────────
CLI → YoutubeDL      提取器注册表（Registry）
  → Extractor Registry   → SourceExtractor trait + URL 正则匹配
  → Downloader           → 通用回退提取器（Generic fallback）
  → Post-Processor       → 标准化输出契约（类比 info_dict）
```

| 借鉴点 | 说明 |
|--------|------|
| **`_VALID_URL` 正则匹配** | 每个提取器通过正则声明自己能处理的 URL 模式，注册表按优先级匹配。PureSource 可为每个视频站（B站/抖音/YouTube）写一个 Rust 提取器 |
| **`GenericIE` 通用回退** | 当无专用提取器匹配时，尝试直接文件/HLS/DASH/嵌入检测。PureSource 也应实现"万能提取器"兜底 |
| **`info_dict` 标准输出** | 所有提取器输出统一格式的元数据。PureSource 的数据契约与之异曲同工 |
| **插件式加载** | 提取器可独立安装，不改核心代码。PureSource 后续也可支持外部提取器动态加载 |
| **TLS 指纹伪装 (`--impersonate`)** | 基于 `curl_cffi` 实现浏览器 TLS/JA3 特征模拟，绕过 Cloudflare 检测。PureSource 应集成 `curl-impersonate` 处理反爬站点 |
| **Cookie 注入** | `--cookies-from-browser` 从真实浏览器提取 Cookie。PureSource 的浏览器代理层天然可以传递页面 Cookie |

#### lux（Go, 28k⭐, 80+ 站点）— 策略模式的简洁实现

```go
// lux 的提取器接口（极简、清晰）
type Extractor interface {
    Support(url string) bool          // URL 匹配
    Extract(url string) ([]*Video, error)  // 提取视频信息
}
```

| 借鉴点 | 说明 |
|--------|------|
| **接口极简** | 每个站点一个 package，实现两个方法。PureSource 的 Rust trait 也应如此简洁 |
| **故障隔离** | 一个提取器崩溃不影响其他 |

#### gallery-dl（Python, 14k⭐）— 消息驱动的管线设计

借鉴点：提取器通过 yield `Message.Directory`、`Message.Url`、`Message.Queue` 与下载引擎通信。PureSource 内部管线也可采用类似的事件驱动模式。

### 11.2 HLS 流处理

#### N_m3u8DL-RE（C#, 5k⭐）— 当今最强 m3u8 下载器

| 能力 | 说明 | PureSource 可借鉴 |
|------|------|------------------|
| **多密钥解密** | 同时处理视频/音频不同加密密钥（AES-128/CENC/ChaCha20） | 集成 mp4decrypt 或 shaka-packager 做 DRM 解密 |
| **多码率选择** | 自动选最高带宽线路 | PureSource 提纯时选最优品质（已有计划） |
| **多线程下载** | 并发下载 TS 分片 | PureSource 做缓存预取时可参考 |
| **二进制合并** | >2GB 文件高效处理 | local-stream 处理大文件时参考 |

#### streamlink（Python, 15k⭐）— 直播流协议处理标杆

借鉴点：
- **协议前缀**：`hls://`、`dash://`、`httpstream://` 明确区分流类型
- **EXT-X-DATERANGE 广告检测**：通过 HLS 标签识别广告片段，PureSource + BT-Player 可借鉴做服务端广告跳过
- **低延迟模式**：prefetch segment、live edge 控制，对直播场景有参考价值

#### you-get（Python, 54k⭐）— 中文视频站覆盖最全

you-get 的最大价值是对**中文视频站**的专用提取器覆盖极广：B站、优酷、爱奇艺、腾讯视频、芒果TV、抖音、快手、斗鱼等。截至 2025 年支持 40+ 站点。

| 借鉴点 | 说明 |
|--------|------|
| **`url_to_module()` 域名路由** | URL 解析域名 → SITES 字典 → 动态 import 提取器。PureSource 可参考做 Rust 版 URL→Extractor 路由 |
| **通用提取器兜底** | 无专用提取器时从页面嗅探媒体资源 |
| **DASH 分离音视频** | 分别提取音视频流，下载时 ffmpeg 合并 |

#### Cobalt（Node.js, AGPL-3.0）— 自托管 API 设计标杆

极简的视频下载 API 服务，支持 20+ 站点。

```bash
curl -X POST 'https://your-instance/' \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.youtube.com/watch?v=...", "videoQuality": "1080"}'
```

| 借鉴点 | 说明 |
|--------|------|
| **极简 API** | 一个端点 + JSON body。PureSource API 设计参考 |
| **Docker 部署** | `docker run` 即用。PureSource 也应如此 |
| **客户端处理** | Cobalt 11 将转码推到浏览器端执行，减轻服务压力 |

### 11.3 浏览器端嗅探工具

#### 解析器.md（Tampermonkey, 已拥有）— 浏览器运行时捕获

PureSource 已拥有的资产。hook Response.text、XHR、轮询 `<video>`。这是 PureSource 处理 JS 动态加载页面的关键。

#### MediaGo（TypeScript/Electron, 5.8k⭐）— 商业级浏览器嗅探

跨平台桌面应用，内置浏览器引擎 + 浏览器扩展 + Docker 三合一。

| 借鉴点 | 说明 |
|--------|------|
| **浏览器扩展 → 服务端** | 用户浏览时点一下扩展按钮，URL 自动发到下载器。PureSource 浏览器代理同样模式 |
| **HTTP API** | `POST /api/download-now {"url": "...", "type": "m3u8"}`。PureSource API 参考 |
| **Docker 部署** | Docker 版可作为 LAN 内下载服务 |

#### CatCatch（猫抓, 浏览器扩展）

专精于从浏览器页面捕捉 m3u8 链接的扩展。与 解析器.md 定位类似，但更专注 m3u8 嗅探。

### 11.4 Rust 原生生态

PureSource 用 Rust 开发，以下 crate 可以直接复用：

| Crate | 用途 | 下载量 | 说明 |
|-------|------|--------|------|
| **hls_m3u8** | HLS manifest 解析+生成 | 138k+ | RFC 8216 完整支持，PureSource 服务端解析 m3u8 的首选 |
| **m3u8-rs** | HLS 解析（nom） | 6.8k+ | 备选方案 |
| **reqwest** | HTTP 客户端 | 标准 | 配合 `curl-impersonate` 做 HTTP 请求 |
| **tokio** | 异步运行时 | 标准 | 已有 |

### 11.5 AI 驱动提取

| 项目 | 方案 | 借鉴价值 |
|------|------|---------|
| **Crawl4AI** (50k⭐) | LLM-driven extraction、JS 渲染、stealth mode | **PureSource AI 网页识别的直接参考**：先 JS 渲染页面，再用 LLM 理解内容 |
| **Maxun** | 自然语言描述提取目标，AI 自动识别页面元素 | AI 网页源识别的交互范式参考 |
| **curl-impersonate** (7k⭐) | 修改版 curl，模拟浏览器 TLS 指纹 | PureSource 处理 Cloudflare/反爬站点的基础设施 |

### 11.6 全览：生态工具能力矩阵

| 工具 | 语言 | 站点数 | 核心能力 | 对 PureSource 的价值 |
|------|------|--------|---------|---------------------|
| **yt-dlp** | Python | 1800+ | 提取器注册表、TLS 指纹伪装、1800 站点、info_dict 标准输出 | **架构主参考** + 外部 fallback 首选 |
| **you-get** | Python | 40+ | 中文站覆盖广、通用提取器兜底 | 中文视频站提取参考 |
| **lux** | Go | 80+ | 极简 extractor 接口、goroutine 并发下载 | Rust trait 设计参考 |
| **gallery-dl** | Python | 大量 | 消息驱动管线、配置驱动自定义站点 | 管线架构参考 |
| **streamlink** | Python | 直播 | 协议前缀、HLS 广告检测、低延迟模式 | HLS 协议处理参考 |
| **N_m3u8DL-RE** | C# | m3u8 专精 | 多密钥解密、多码率选择、多线程分片 | HLS 解密能力参考 |
| **Cobalt** | Node.js | 20+ | 极简 API、Docker 部署、客户端处理 | API 设计参考 |
| **MediaGo** | TS/Electron | 各种 | 内置浏览器嗅探、扩展配合、Docker | 浏览器代理模式参考 |
| **Hitomi-Downloader** | Python | 1200+ | 基于 yt-dlp、桌面 GUI、多线程 | 验证 yt-dlp 作为基座的可行性 |
| **Crawl4AI** | Python | 通用 | LLM-driven extraction、JS 渲染 | AI 网页识别的直接参考 |
| **解析器.md** | JS (TM) | 通用 | hook 浏览器 API 检测 m3u8/video/磁链 | **PureSource 已拥有** |

### 11.7 对 PureSource 的具体影响

综合以上调研，对 PureSource 设计做以下调整：

```
调整 1: 提取器架构
  └── 从"硬编码解析器链" → 采用 yt-dlp/lux 风格的提取器注册表
      每个视频站（B站/抖音/YouTube/…）可注册独立 extractor
      通用回退提取器处理未知站点
      trait SourceExtractor {
          fn can_handle(&self, url: &str) -> bool;
          async fn extract(&self, url: &str) -> Result<PureSourceResult>;
      }

调整 2: 反爬策略
  └── 集成 curl-impersonate 做 TLS 指纹伪装
      浏览器代理层提供实时 Cookie/Header 注入
      JS 渲染页面 → 浏览器代理捕获（已有 解析器.md）
      静态可抓页面 → PureSource 服务端直接请求（curl-impersonate）

调整 3: HLS 解密能力
  └── 集成 mp4decrypt / shaka-packager
      PureSource 提纯阶段做 AES-128/CENC 解密
      输出为已解密的标准化流

调整 4: 广告跳过
  └── 借鉴 streamlink 的 EXT-X-DATERANGE 广告检测
      在提纯结果中标记广告段，BT-Player 播放时自动跳过

调整 5: 技术选型增强
  └── hls_m3u8 crate 替代手写 m3u8 解析
      curl-impersonate 系统工具替代纯 HTTP 请求
      mp4decrypt/shaka-packager 做 DRM 解密
```

---

## 十二、Web3 去中心化存储——探索性方向

> ⚠ 本节为**前瞻探索**，非近期实施计划。Web3 存储机制与视频资源的结合点值得关注，但短期不进入主链路。

### 12.1 核心思路：磁链本身就是 Web3

一个有意思的观察：BT-Player 已经在用**磁链（magnet:?xt=urn:btih:）**，它就是最朴素的去中心化存储——基于 DHT 网络的**内容寻址**。每个磁链通过 infohash 唯一标识一个资源，不需要中心服务器。

```
磁链        = DHT 网络上的内容寻址标识
IPFS CID    = IPFS 网络上的内容寻址标识
Arweave TX  = 永久存储网络上的内容寻址标识
```

从这个角度看，PureSource + BT-Player 已经半只脚踏在 Web3 里了。

### 12.2 各方案对比

| 方案 | 存储模式 | 费用 | 视频流播放 | 与当前项目的契合点 |
|------|---------|------|-----------|----------------|
| **磁链 / DHT**（已在用） | P2P 网络，依赖做种 | 免费 | 通过 librqbit 边下边播 | ✅ 已有，BT-Player 核心 |
| **IPFS** | P2P 内容寻址，需 pinning 持久化 | pinning 服务收费 | IPFS gateway 可串流，延迟偏高 | PureSource 输出 IPFS CID，作为可选寻址方式 |
| **Arweave** | 永久存储，一次性付费 | ~$5-20/GB 一次 | 通过 gateway 加载，适合归档 | 替代 Dropbox 做"精选永久归档" |
| **Storj** | S3 兼容去中心化存储 | $4-15/TB/月 | 标准 S3 对象存储访问 | 替代本地磁盘做缓存层，VPS 45GB 不够时 |
| **AIOZ** | DePIN 网络，peer CDN | 按使用付费 | 去中心化 CDN 加速流媒体 | 如果 VPS 带宽不够，可用作 CDN 卸载 |

### 12.3 IPFS——最值得关注的方案

IPFS 与 PureSource 的"图书馆"定位天然契合：

```
PureSource 提纯后的资源
  │
  ├── 本地缓存（VPS 磁盘，短期热数据）
  ├── IPFS（内容寻址，中期分发）
  │     └── BT-Player 可通过 IPFS gateway 加载，降低 VPS 带宽
  └── Arweave（永久归档，长期保存）
        └── 精选资源一次付费，永久可访问
```

**DTube** 已经在用 IPFS + Steem 做了去中心化 YouTube，说明这条路是走得通的。不过目前 IPFS 视频流的延迟还是偏高（学术界在推 prefetching + SVC 优化）。

### 12.4 PureSource 数据契约的 Web3 扩展

如果后续接入 Web3，数据契约可扩展一个可选字段：

```json
{
  "purifiedFiles": [
    {
      ...原有字段...
      "web3": {
        "ipfsCid": "bafybeig...",
        "ipfsGateways": ["https://ipfs.io/ipfs/", "https://gateway.pinata.cloud/ipfs/"],
        "arweaveTx": "abcdef...",
        "magnetUri": "magnet:?xt=urn:btih:..."
      }
    }
  ]
}
```

### 12.5 当前结论

| 方向 | 态度 |
|------|------|
| IPFS 作为提纯产物的可选输出 | 🟡 可探索，但暂不进入主链路 |
| Arweave 替代 Dropbox 做永久归档 | 🟢 方向合理，成本低，值得后续做技术验证 |
| Storj 替代或扩展 VPS 缓存 | 🟡 当 VPS 45GB 磁盘不够时可考虑 |
| Web3 作为播放主链路 | 🔴 不现实，延迟/稳定性远不及本地缓存 |

简单说：**磁链已经是 Web3，IPFS/Arweave 可以作为"图书馆存储层"的可选方案，播放层面用不到。**

---

## 十三、未定 & 待讨论

| 问题 | 建议方案 |
|------|---------|
| PureSource 建在独立仓库还是 BT-Player 仓库的子目录？ | 先子目录（共享依赖方便），后续视复杂度拆独立仓库 |
| AI 调用的 API Key 管理？ | 环境变量 + 请求频率限制 + 结果缓存 |
| PureSource 和 BT-Player 是否共用前端页面？ | 建议共用：前端统一入口，按需调不同 API |
| 浏览器代理的 PureSource API Key 存储？ | Tampermonkey GM_setValue 加密存储，或弹出输入框首次配置 |
| 浏览器代理提交频率限制？ | 同 URL 去重窗口 30 秒，防止重复提交 |
| ffmpeg faststart 触发时机？ | 文件下载完成后自动触发，或用户按需触发 |
| **提取器注册表：第一批支持的站点 extractor？** | **建议：yt-dlp 作为外部 fallback（Python subprocess），内部 Rust 先从 B站/抖音等常用站开始实现** |
| **curl-impersonate 集成方式？** | **建议：先作为系统 tool 调用（类似 ffmpeg），后续考虑 Rust 原生 TLS 指纹伪装** |
| **HLS 解密（DRM）支持范围？** | **建议初始仅支持 AES-128 无密钥 / 已知密钥流，暂不支持 Widevine L1** |
| **yt-dlp 集成深度？** | 轻度（subprocess 调用 --dump-json）还是重度（Python 嵌入 Rust 进程）？ |
