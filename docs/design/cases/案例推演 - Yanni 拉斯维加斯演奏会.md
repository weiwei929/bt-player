# 案例推演：Yanni 拉斯维加斯演奏会

> 目的：用具体案例验证 PureSource + BT-Player 架构的端到端流程
> 三种源类型：磁链 / 反盗链网页 / m3u8 直链

---

## 场景设定

用户在逛一个音乐论坛时，看到有人分享了 **Yanni Live at The Las Vegas Strip** 的资源。他想直接在 BT-Player 上看。

用户的操作路径：

```
论坛帖子
  │
  ├── 楼主贴了一个 magnet 磁链（种子包，含多文件）
  ├── 另一个回帖贴了视频站的播放页 URL（带反盗链）
  └── 还有人贴了 m3u8 直链
```

下面分别走三条管线。

---

## 管线一：磁链（magnet）

### ① 输入

用户在 BT-Player 前端粘贴：

```
magnet:?xt=urn:btih:9f3a7b2c...&dn=Yanni.Live.At.The.Las.Vegas.Strip.2024
```

### ② PureSource 提纯

#### 阶段 1：源发现

PureSource 的提取器链识别出是 magnet，交给 MagnetExtractor：

```
URL 匹配 → magnet: 前缀命中 → PureSource 内部 MagnetExtractor
  └── 通过 librqbit 添加磁链，获取文件列表
```

#### 阶段 2：文件筛选（规则引擎）

种子包里有 12 个文件：

```
  #  文件名                                    大小      结果
 ─── ────────────────────────────────────────── ──────── ──────
  1  Yanni.Live.2024.2160p.4K.HDR.x265.mkv     7.8 GB   ✅ 主视频
  2  Sample.Yanni.Live.2024.x265.mkv             48 MB   ❌ 样本
  3  Yanni.Live.2024.2160p.4K.HDR.x265.nfo       2 KB    ❌ NFO
  4  Yanni.Live.2024.2160p.4K.HDR.x265.jpg      320 KB   ❌ 封面
  5  Subs/English.srt                             45 KB   ✅ 字幕
  6  Subs/Chinese.srt                             42 KB   ✅ 字幕
  7  Subs/French.srt                              41 KB   ❌ 用户不关注
  8  Extra/Behind.The.Scenes.mkv                 620 MB   🟡 附加内容（标记但不主推）
  9  Extra/Interview.mkv                         380 MB   🟡 附加内容
 10  Ad_30s_Intro.mp4                             32 MB   ❌ 广告
 11  Ad_60s_Midroll.mp4                           65 MB   ❌ 广告
 12  Torrent-Download-Instructions.txt             1 KB    ❌ 说明文件
```

规则引擎的执行：

```json
{
  "filterRules": [
    "后缀过滤：只保留 .mkv .mp4 .srt → 排除 3, 4, 12",
    "大小过滤：< 50MB → 标记疑似广告 → 排除 10 (32MB)",
    "文件名规则：含 sample/Sample → 排除 2",
    "文件名规则：含 Ad_ → 排除 10, 11",
    "正片推荐：选最大文件 → 文件 1 (7.8GB)"
  ]
}
```

#### 阶段 3：ffmpeg 检测

```bash
# 文件开始通过 librqbit 下载，下载到 10% 左右时 ffprobe 读取元数据
ffprobe -v quiet -print_format json -show_format -show_streams \
  /root/bt_cache/torrent_9f3a7/Yanni.Live.2024.2160p.4K.HDR.x265.mkv
```

输出：

```json
{
  "streams": [
    {
      "codec_type": "video",
      "codec_name": "hevc",
      "width": 3840,
      "height": 2160,
      "r_frame_rate": "24000/1001"
    },
    {
      "codec_type": "audio",
      "codec_name": "dts",
      "sample_rate": 48000,
      "channels": 6
    }
  ]
}
```

检测结果：
- **moov**: N/A（MKV 不需要 moov，只需要 MP4 检测）
- **视频编码**: h.265 (HEVC)，4K
- **音频编码**: DTS 5.1

#### 阶段 4：AI 编目

LLM 收到文件名信息：

```
输入文件列表：
  1. Yanni.Live.2024.2160p.4K.HDR.x265.mkv — 7.8 GB
  2. Sample.Yanni.Live.2024.x265.mkv — 48 MB
  8. Behind.The.Scenes.mkv — 620 MB
  9. Interview.mkv — 380 MB
  Subs: English.srt, Chinese.srt
```

LLM 输出：

```json
{
  "title": "Yanni Live at The Las Vegas Strip 2024",
  "artist": "Yanni",
  "event": "Las Vegas Strip 演奏会",
  "year": 2024,
  "mainFeature": "文件 1 (2160p 4K HDR)",
  "confidence": 0.97,
  "tags": ["演奏会", "4K", "HDR", "古典跨界"],
  "description": "雅尼在拉斯维加斯的现场演奏会，包含经典曲目..."
}
```

### ③ PureSource 输出

```json
{
  "requestId": "p-20260509-yanni-001",
  "originalInput": "magnet:?xt=urn:btih:9f3a7b2c...",
  "sourceType": "magnet",
  "title": "Yanni Live at The Las Vegas Strip 2024",
  "confidence": 0.97,

  "purifiedFiles": [
    {
      "index": 1,
      "path": "Yanni.Live.2024.2160p.4K.HDR.x265.mkv",
      "sizeBytes": 8375186227,
      "sizeMb": 7987.2,
      "encoding": {
        "videoCodec": "h265",
        "audioCodec": "dts",
        "resolution": "3840x2160",
        "bitrate": 35000000
      },
      "moov": null,
      "isMainFeature": true,
      "confidence": 0.97,
      "tags": ["正片", "4K", "HDR", "演奏会"],
      "isSuspectedAd": false
    },
    {
      "index": 5,
      "path": "Subs/English.srt",
      "sizeBytes": 45000,
      "sizeMb": 0.04,
      "encoding": null,
      "moov": null,
      "isMainFeature": false,
      "confidence": 0.95,
      "tags": ["字幕"],
      "isSuspectedAd": false
    },
    {
      "index": 6,
      "path": "Subs/Chinese.srt",
      "sizeBytes": 42000,
      "sizeMb": 0.04,
      "encoding": null,
      "moov": null,
      "isMainFeature": false,
      "confidence": 0.95,
      "tags": ["字幕"],
      "isSuspectedAd": false
    }
  ],

  "filtered": {
    "totalFiles": 12,
    "kept": 3,
    "removed": 9,
    "removedReasons": ["样本文件", "广告", "NFO", "封面"]
  },

  "recommended": {
    "action": "play",
    "fileIndex": 1,
    "reason": "正片，4K HDR HEVC，7.98GB"
  }
}
```

### ④ BT-Player 接收

```
BT-Player 收到提纯结果
  │
  ├── 检查文件状态
  │     ├── 电量：由 librqbit 下载
  │     │     └── → 使用 /stream/torrents/... 边下边播
  │     │
  │     └── 下载完成 → 切换到 local-stream
  │           └── → 使用 /api/local-stream/... Range 流播
  │
  └── moov 处理
        └── MKV 格式不需要 moov，本地文件直接流播
```

### ⑤ 用户侧表现

```
BT-Player 前端显示：

Yanni Live at The Las Vegas Strip 2024
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▶  主视频：Yanni.Live.2024.2160p.4K.HDR.x265.mkv     7.98 GB ◎ 4K HDR
   ↳ Playing... 20% buffered  |  正在通过 BT 网络传输

◎ 附加：Behind.The.Scenes.mkv                       620 MB
◎ 附加：Interview.mkv                               380 MB
◎ 字幕：English.srt / Chinese.srt

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提纯报告：12 个文件中筛选出 3 个有效文件
已排除：9 个（广告 x2、样本、NFO、封面...）
```

---

## 管线二：反盗链网页

### ① 输入

用户在论坛看到一条回帖，贴了一个视频站的链接：

```
https://www.example-video-site.com/play/78945/yanni-las-vegas
```

用户把它粘贴到 BT-Player 输入框，点击"解析"。

### ② PureSource 处理

#### 阶段 1：规则引擎尝试

PureSource 服务端直接 HTTP GET 这个 URL：

```html
<html>
<head><title>Yanni 拉斯维加斯演奏会 - 在线观看</title></head>
<body>
  <div id="player-container">
    <!-- 视频播放器由 JS 动态加载 -->
    <script src="/assets/player.js"></script>
  </div>
  <!-- 页面元数据 -->
  <meta name="description" content="雅尼拉斯维加斯现场演奏会完整版">
</body>
</html>
```

规则引擎结论：**静态 HTML 中没有直接视频 URL**，播放器由 JS 动态创建。置信度低 → 转 AI。

#### 阶段 2：AI 分析

LLM 收到页面 HTML + URL：

```
LLM 分析结果：
  页面标题：Yanni 拉斯维加斯演奏会 - 在线观看
  页面描述：雅尼拉斯维加斯现场演奏会完整版
  页面结构：player-container 由 JS 动态渲染
  结论：无法从静态 HTML 中提取视频 URL
  建议：需要浏览器运行时捕获
```

#### 阶段 3：降级到浏览器代理

前端显示：

```
ℹ 该页面需要浏览器运行时捕获视频源。
请在浏览器中打开该页面，确保油猴脚本（PureSource Agent）已启用。
```

用户打开页面后，浏览器代理（解析器.md 改编版）开始工作：

```
① 页面加载 → 浏览器代理启动
② JS 执行 → player.js 创建 HLS 播放器
③ fetch() 请求 m3u8 → Response.prototype.text 钩子捕获
   └── 检测到 "#EXTM3U"
   └── URL: https://cdn.example-video.com/hls/yanni-2024/master.m3u8
④ 浏览器代理自动 POST 到 PureSource：
   POST /purify/batch
   {
     "source": "browser-agent",
     "tabUrl": "https://www.example-video-site.com/play/78945/yanni-las-vegas",
     "detectedUrls": [{
       "url": "https://cdn.example-video.com/hls/yanni-2024/master.m3u8",
       "detectMethod": "response_hook",
       "pageContext": {
         "title": "Yanni 拉斯维加斯演奏会",
         "referer": "https://www.example-video-site.com/play/78945/yanni-las-vegas"
       }
     }]
   }
```

### ③ PureSource 提纯

收到浏览器代理提交的 URL：

```
阶段 1：多码率解析
  └── hls_m3u8 crate 解析 master m3u8
  └── 发现 4 个码率：
        1920x1080  @ 8 Mbps  → 选此路（VPS 上最优）
        1280x720   @ 4 Mbps
        854x480    @ 2 Mbps
        640x360    @ 1 Mbps

阶段 2：加密检测
  └── 检查 m3u8 中 #EXT-X-KEY 标签
  └── 发现 AES-128 加密，密钥 URL 已知
  └── PureSource 使用 mp4decrypt 获取密钥→解密→输出解密流

阶段 3：防盗链头注入
  └── 附加 Referer: https://www.example-video-site.com/
  └── 附加 User-Agent: 浏览器 UA
```

### ④ BT-Player 播放

```json
{
  "requestId": "p-20260509-yanni-002",
  "originalInput": "https://www.example-video-site.com/play/78945/yanni-las-vegas",
  "sourceType": "hls",
  "detectMethod": "browser_agent_response_hook",
  "title": "Yanni 拉斯维加斯演奏会 - 在线观看",
  "confidence": 0.95,
  "purifiedFiles": [
    {
      "index": 0,
      "path": "Yanni 拉斯维加斯演奏会 (1080p).m3u8",
      "sizeBytes": 0,
      "encoding": {
        "videoCodec": "h264",
        "resolution": "1920x1080",
        "bitrate": 8000000
      },
      "isMainFeature": true,
      "confidence": 0.95,
      "tags": ["在线播放", "1080p"]
    }
  ],
  "headers": {
    "Referer": "https://www.example-video-site.com/",
    "User-Agent": "Mozilla/5.0..."
  },
  "recommended": {
    "action": "play",
    "fileIndex": 0
  }
}
```

```
BT-Player 接收 →
  流类型是 HLS，直接返回浏览器 <video> 播放
  <video> 的 src 指向 BT-Player 的反代流
  Caddy 的 flush_interval -1 确保流畅
```

### ⑤ 用户侧表现

```
BT-Player 前端显示：

Yanni 拉斯维加斯演奏会 - 在线观看
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▶  源：在线播放 (1080p)                            ◎ HLS 加密已解密
   ↳ 浏览器代理自动捕获 | 来源：example-video-site.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提纯方式：浏览器代理 → PureSource AI 识别 → 自动解密
```

---

## 管线三：m3u8 直链

### ① 输入

用户在论坛上直接看到一条 m3u8 链接：

```
https://cdn.media-server.com/hls/yanni-2024/master.m3u8
```

粘贴到 BT-Player，点击"解析"。

### ② PureSource 提纯

```
URL 匹配 → .m3u8 后缀 → M3u8Extractor
  │
  ├── hls_m3u8 crate 获取并解析 master.m3u8
  │     └── 1920x1080 @ 6Mbps → 选最优
  │     └── 1280x720  @ 3Mbps
  │     └── 854x480   @ 1.5Mbps
  │
  ├── 加密检测
  │     └── #EXT-X-KEY:METHOD=AES-128,URI="key.bin"
  │     └── 尝试获取 key.bin → 成功
  │     └── 标记为可解密
  │
  └── 防盗链检测
        └── 需要 Referer → 用户未提供
        └── 标记为"可能需要 Referer"，降低置信度
```

### ③ 输出

```json
{
  "requestId": "p-20260509-yanni-003",
  "originalInput": "https://cdn.media-server.com/hls/yanni-2024/master.m3u8",
  "sourceType": "hls",
  "title": "Yanni Live (m3u8流)",
  "confidence": 0.7,
  "purifiedFiles": [
    {
      "index": 0,
      "path": "Yanni Live (1080p, AES-128)",
      "encoding": {
        "videoCodec": "h264",
        "resolution": "1920x1080",
        "bitrate": 6000000
      },
      "isMainFeature": true,
      "confidence": 0.7,
      "tags": ["在线播放", "1080p", "已加密"]
    }
  ],
  "headers": {},
  "recommended": {
    "action": "play",
    "fileIndex": 0,
    "note": "该流需要 Referer 头，可能需要从原页面获取"
  }
}
```

### ④ 用户交互

```
PureSource 检测到"可能需要防盗链头" →
  前端提示用户：
  "该 m3u8 流可能需要 Referer 防盗链才能播放。
   你知道来源页面地址吗？粘贴一下我们会自动处理。
   
   [输入来源 URL（可选）] __________________
   [跳过，直接播放]"
```

如果用户提供了来源 URL，PureSource 用那个 URL 做 Referer 重试。

---

## 三条管线的对比总结

| 维度 | 磁链 | 反盗链网页 | m3u8 直链 |
|------|------|-----------|-----------|
| **输入方式** | 用户粘贴 magnet | 用户粘贴网页 URL → 转浏览器代理捕获 | 用户直接粘贴 m3u8 URL |
| **PureSource 核心工作** | 文件筛选 + ffmpeg 检测 + AI 编目 | AI 识别页面 → 降级到浏览器代理 → m3u8 解析 | m3u8 解析 + 加密检测 + 防盗链检查 |
| **提纯耗时** | 秒级（规则引擎）+ 异步（下载） | 数秒（浏览器代理 + AI 分析） | 毫秒级（纯规则引擎） |
| **回退 / 降级** | 无降级，磁链必须下载 | 规则引擎 → AI → 浏览器代理，三级降级 | 无降级，直链即播 |
| **播放方式** | 下载完成后 local-stream / 下载中边下边播 | 浏览器 <video> HLS | 浏览器 <video> HLS |
| **体验质量** | 最高（本地文件） | 受流源质量限制 | 受流源质量限制 |

---

## 关键发现

### 1. 磁链管线最复杂但也是价值最高的

种子包里一堆杂文件 → AI 自动识别正片 → 编码检测 → 推荐播放——全套自动化。这步做好了，用户搜到磁链就一键播放，体验接近 Netflix。

### 2. 浏览器代理是反盗链网页的必由之路

服务端再怎么 AI 也拿不到 JS 执行后的视频 URL。解析器.md 的 hook 机制是**唯一可靠**的方案。PureSource 的 AI 在这个过程中做的不是"找到 URL"，而是**判断"该降级到浏览器代理了"**。

### 3. m3u8 直链看似简单，防盗链是最头疼的

没有 Referer 就 403。目前的思路是让用户补充来源 URL，够用但不够优雅。后续如果 curl-impersonate 做好了，可以自动试常见 Referer 模式。

### 4. 用户交互点总结

在整个流程中，用户需要参与的只有：
1. **粘贴链接**（三种管线都一样）
2. **打开页面让浏览器代理捕获**（反盗链网页场景，可选回复来源 URL）
3. **点击播放**（所有场景）

其他都是 PureSource 自动化处理。
