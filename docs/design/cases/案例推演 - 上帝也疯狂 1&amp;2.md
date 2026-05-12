# 案例推演：上帝也疯狂 1 & 2

> 目的：用老电影场景验证 PureSource + BT-Player 架构对"冷门老片"的处理能力
> 对比 Yanni 案例：老片种子少、清晰度低、多语言混排，挑战不同

---

## 场景设定

用户想找 **The Gods Must Be Crazy (1980)** 和 **The Gods Must Be Crazy II (1989)**。这是 80 年代博茨瓦纳/南非合拍喜剧，中文俗称"上帝也疯狂"。

用户的操作路径：

```
用户想起小时候看过的老片
  │
  ├── 打开 BT-Player 搜索框（不是搜索，是贴链接）
  ├── 在论坛/豆瓣评论里翻到有人留了 magnet
  └── 顺便找到了一个俄文站的 m3u8
```

---

## 管线一：磁链（双片合包）

### ① 输入

```
magnet:?xt=urn:btih:e4b6f91a...&dn=The.Gods.Must.Be.Crazy.Collection
```

### ② PureSource 提纯

#### 阶段 1：源发现 → 阶段 2：文件筛选

种子包里 8 个文件：

```
 #  文件名                                    大小      结果
─── ────────────────────────────────────────── ──────── ────────
 1  The.Gods.Must.Be.Crazy.1980.720p.BluRay.x264.mkv   4.2 GB  ✅ 正片 1
 2  The.Gods.Must.Be.Crazy.II.1989.720p.BluRay.x264.mkv 3.8 GB  ✅ 正片 2
 3  Subs/English.srt                                     48 KB   ✅ 字幕
 4  Subs/Chinese.srt                                     45 KB   ✅ 字幕
 5  Subs/German.srt                                      46 KB   ❌ 不关注
 6  Extra/Interview.x264.mkv                            280 MB   🟡 附加内容
 7  Extra/Trailer.mkv                                    95 MB   🟡 附加内容
 8  Torrent-Download-Instructions.txt                     1 KB   ❌ 说明
```

规则引擎执行：

```json
{
  "filterRules": [
    "后缀过滤：只保留 .mkv .mp4 .srt → 排除 8",
    "大小过滤 + 文件名规则：排除 Trailer (95MB)",
    "正片识别：两个文件大小接近 (4.2GB vs 3.8GB)，文件名含年份区别 → 判断为两部正片"
  ]
}
```

#### 阶段 3：ffmpeg 检测

```json
{
  "streams": [
    {
      "codec_type": "video",
      "codec_name": "h264",
      "width": 1280,
      "height": 720,
      "r_frame_rate": "24000/1001"
    },
    {
      "codec_type": "audio",
      "codec_name": "aac",
      "sample_rate": 48000,
      "channels": 2
    }
  ]
}
```

> 老片特点：最高只到 720p，无 HDR，音轨仅 2.0 声道。与 Yanni 的 4K HDR DTS 5.1 形成鲜明对比。

#### 阶段 4：AI 编目

```
输入文件列表：
  1. The.Gods.Must.Be.Crazy.1980.720p.BluRay.x264.mkv — 4.2 GB
  2. The.Gods.Must.Be.Crazy.II.1989.720p.BluRay.x264.mkv — 3.8 GB
  Subs: English.srt, Chinese.srt
```

LLM 输出：

```json
{
  "title": "The Gods Must Be Crazy Collection",
  "series": [
    {
      "title": "上帝也疯狂",
      "originalTitle": "The Gods Must Be Crazy",
      "year": 1980,
      "fileIndex": 1,
      "director": "Jamie Uys",
      "confidence": 0.96
    },
    {
      "title": "上帝也疯狂 2",
      "originalTitle": "The Gods Must Be Crazy II",
      "year": 1989,
      "fileIndex": 2,
      "director": "Jamie Uys",
      "confidence": 0.96
    }
  ],
  "tags": ["喜剧", "经典", "博茨瓦纳", "720p"],
  "description": "80年代南非喜剧经典，讲述非洲卡拉哈里部落与现代文明的碰撞..."
}
```

> **关键差异**：Yanni 案例中 AI 输出单部作品，这里是**合集**。AI 需要从文件名中识别出这是两部独立电影而非不同版本。

### ③ PureSource 输出

```json
{
  "requestId": "p-20260509-gods-001",
  "sourceType": "magnet",
  "title": "The Gods Must Be Crazy Collection",
  "confidence": 0.96,
  "purifiedFiles": [
    {
      "index": 1,
      "path": "The.Gods.Must.Be.Crazy.1980.720p.BluRay.x264.mkv",
      "sizeMb": 4300,
      "encoding": {
        "videoCodec": "h264",
        "resolution": "1280x720",
        "audioCodec": "aac",
        "channels": 2
      },
      "isMainFeature": true,
      "confidence": 0.96,
      "tags": ["正片", "720p", "1980"]
    },
    {
      "index": 2,
      "path": "The.Gods.Must.Be.Crazy.II.1989.720p.BluRay.x264.mkv",
      "sizeMb": 3891,
      "encoding": {
        "videoCodec": "h264",
        "resolution": "1280x720",
        "audioCodec": "aac",
        "channels": 2
      },
      "isMainFeature": true,
      "confidence": 0.96,
      "tags": ["正片", "720p", "1989"]
    },
    {
      "index": 3,
      "path": "Subs/English.srt",
      "tags": ["字幕", "英文"],
      "isMainFeature": false
    },
    {
      "index": 4,
      "path": "Subs/Chinese.srt",
      "tags": ["字幕", "中文"],
      "isMainFeature": false
    }
  ],
  "recommended": {
    "action": "show_series",
    "note": "合集包含两部电影，推荐先播 1980 年版"
  }
}
```

### ④ BT-Player 播放

```
BT-Player 前端显示为合集卡片：

The Gods Must Be Crazy Collection
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────────────────────────────────┐
│  🎬 上帝也疯狂 (1980)                       │
│     720p BluRay · 4.2 GB                     │
│     [▶ 播放] [♡ 收藏]                        │
├──────────────────────────────────────────────┤
│  🎬 上帝也疯狂 2 (1989)                     │
│     720p BluRay · 3.8 GB                     │
│     [▶ 播放] [♡ 收藏]                        │
├──────────────────────────────────────────────┤
│  字幕：中文 · 英文 · 附加：Interview(280MB) │
└──────────────────────────────────────────────┘
```

---

## 管线二：俄文站 m3u8（冷门源挑战）

### ① 输入

用户在一个俄文论坛看到：

```
http://russian-video-site.ru/movies/1980/gods-must-be-crazy
```

### ② PureSource 处理

#### 规则引擎尝试

服务端 GET 该 URL → 页面全俄文，视频播放器由 JS 动态加载 → 规则引擎无法提取。

#### AI 分析

LLM 收到页面文字（俄文）：

```
LLM 识别：
  页面标题：Боги наверное сошли с умы (1980)
  页面描述：комедия, Ботсвана, семья
  内容结构：动态播放器，JS 渲染
  结论：俄文站，需要浏览器代理
  置信度：页面为视频页面 0.9，但无法直接提取源
```

#### 降级到浏览器代理

用户打开页面 → 浏览器代理（解析器.md）→ hook 到 m3u8 流：

```
https://cdn.russian-cdn.com/hls/gods-1980/master.m3u8
```

浏览器代理 POST 到 PureSource → PureSource 解析：

```
m3u8 manifest：
  854x480  @ 1.5 Mbps  → 唯一码率
  加密：无
  语言：俄语配音
```

> **老片冷门源的特点**：码率低（仅 480p），源站可能只有俄语配音版而非英语原声，字幕需要外挂。

### ③ PureSource 输出与推荐

```json
{
  "title": "Боги наверное сошли с умы (1980)",
  "sourceType": "hls",
  "confidence": 0.85,
  "purifiedFiles": [
    {
      "path": "1080p variant unavailable",
      "encoding": {
        "resolution": "854x480",
        "bitrate": 1500000
      },
      "tags": ["在线播放", "480p", "俄语配音"]
    }
  ],
  "recommendation": {
    "links": [
      {
        "type": "hls",
        "quality": "480p",
        "priority": 2,
        "note": "仅 480p，俄语配音，不理想"
      }
    ],
    "preferredSource": "magnet",
    "reason": "磁链 720p 英语原声 + 中文字幕，体验远优于俄文 m3u8"
  }
}
```

### ④ 用户交互

```
PureSource 检测到同一内容已有更优源（磁链 720p vs m3u8 480p）→

BT-Player 提示：
  "你已经在下载 720p 英语原声版（28%）。
   这个俄文源只有 480p 且是俄语配音。
   建议等下载完成，或直接播 720p 边下边看。
   
   [继续播放 480p 俄配] [等待磁链] [播 720p 边下边看（推荐）]"
```

---

## 对比：Yanni 案例 vs 上帝也疯狂

| 维度 | Yanni 拉斯维加斯 | 上帝也疯狂 1&2 |
|------|-----------------|---------------|
| **内容热度** | 2024 年新现场，热门 | 1980/89 年老片，冷门 |
| **源质量** | 4K HDR，DTS 5.1，多码率 | 最高 720p，2.0 声道 |
| **种子健康度** | 做种多，速度快 | 做种少，下载可能慢 |
| **文件结构** | 单正片 + 杂物 | 双正片合集（系列识别） |
| **反盗链难度** | JS 动态页面，Referer 防盗 | 俄文站，语言障碍 + 冷门 CDN |
| **多语言** | 中文/英文字幕可选 | 可能俄配、英配混杂 |
| **推荐引擎核心任务** | 格式适配（4K→电视/1080p→手机） | **源择优**（720p 磁链 > 480p m3u8） |

---

## 关键发现

### 1. 合集识别是 PureSource AI 的新能力需求

Yanni 案例是单部作品；上帝也疯狂是**双正片合集**。AI 需要从文件名语义判断"这是两部电影"而不是"一个电影的两个版本"。数据契约的 `recommended` 字段也需支持 `show_series` 模式。

### 2. 老片推荐引擎的核心是"源择优"而非"格式适配"

Yanni 的推荐优先考虑**终端适配**（4K→电视、720p→手机）。老片场景下，根本没有 4K 选项，推荐引擎的主任务是：
- **有源之间比**：磁链 720p 原声 > m3u8 480p 俄配
- **跨场景提示**：下载未完成时，推荐"边下边播"还是"等完成"

### 3. 冷门种子需要更长的等待和更好的反馈

Yanni 种子热门，几秒就有速度。上帝也疯狂做种者少，可能需要数分钟才能连上 peer。PureSource 在这个过程中需要：
- 给用户即时反馈（"已连接 0/5 peer，正在等待..."）
- 不阻塞——**先给 m3u8 直链让用户看起来，后台同时下载磁链**

### 4. 冷门源的跨语言识别

俄文站的页面标题是 `Боги наверное сошли с умы`，但 AI 需要通过页面描述和文件名判断它和"上帝也疯狂"是同一部电影。跨语言匹配在 AI 层面很好解决（LLM 天然支持多语言），但**规则引擎无法处理**。
