# BT-Player Phase 1 阶段性小结

> 日期：2026-05-07
> 范围：环境迁移、架构重构、功能精简、Windows 清理
> 对应 Phase：0（代码清理）→ 1（WSL 迁移）→ 2（架构重构）→ 3（源发现增强）→ 4（验证清理）

---

## 一、本轮完成的工作

### 1. 环境：Windows → WSL 迁移

| 项目 | 状态 |
|------|------|
| WSL Ubuntu 24.04 确认可用 | ✅ |
| 系统依赖安装（libwebkit2gtk, libmpv-dev, libsqlite3-dev 等） | ✅ |
| Rust 工具链（WSL 内，独立于 Windows 安装） | ✅ |
| npm install + cargo build 通过 | ✅ |
| WSLg 桌面窗口验证（tauri dev 正常弹窗） | ✅ |
| Windows Rust 工具链卸载（.cargo ~1GB + .rustup ~1.5GB） | ✅ |

**关键决策：** 项目从 Windows MSVC → WSL Linux 开发环境。原因：Windows MSVC 工具链无法正确链接（Git for Windows 的 `link.exe` 抢占 PATH，VS BuildTools 安装不一致）。

### 2. 架构：内联解析 → 四层架构 + 责任链模式

```
之前：lib.rs 内联判断 URL 类型 → 直接解析 → 播放
之后：ResolverChain.resolve(url) → 按注册顺序尝试 Resolver → 统一 LinkTier 返回
```

**新增文件：**

| 文件 | 行数 | 职责 |
|------|------|------|
| `src-tauri/src/layer/mod.rs` | 46 | LinkTier 枚举（四级分类）、SourceResolver trait |
| `src-tauri/src/resolver/mod.rs` | 59 | ResolverChain（责任链模式，按序尝试） |
| `src-tauri/src/resolver/magnet.rs` | 59 | MagnetResolver（磁链 + 裸 40 位 hash 自动补全） |
| `src-tauri/src/resolver/m3u8.rs` | 26 | M3u8Resolver（.m3u8 链接直通） |
| `src-tauri/src/resolver/webpage.rs` | 248 | WebPageResolver（网页视频源提取，4 种策略） |

**重构文件：**

| 文件 | 变更 |
|------|------|
| `lib.rs` | parse_url 改用 ResolverChain；play_stream 增加 Referer 头传递 |
| `mpv_player.rs` | 新增 set_referrer() 方法 |
| `engine/mod.rs` | get_file_tree 增加 AI 广告分析调用（ai_strategy） |

### 3. 功能：缩减 + 增强

**删除（HLS 录制，~370 行代码 + 前端 UI）：**
- `src-tauri/src/hls_engine.rs`（录制引擎）
- `Cargo.toml` 中录制相关依赖
- `lib.rs` 中 `RecordingState` + 3 个录制命令
- `App.tsx` 中录制 UI + 状态轮询

**冻结（保留但不演进）：**
- `src-tauri/src/ai_strategy.rs` → 标记 @FROZEN，关键词匹配广告识别逻辑保留

**增强：**
- 裸 magnet hash 自动补全（40 位 hex → magnet:?xt=urn:btih:...）
- WebPageResolver：网页链接自动提取视频源（4 级策略：video 标签 → iframe → JS 变量 → 页面搜索）
- Referer 防盗链：WebPageResolver 返回原始页面 URL 作为 Referer，play_stream 通过 mpv --referrer 注入
- StreamHeaders 缓存机制：在 parse_url 和 play_stream 之间传递 HTTP 头

### 4. Windows 清理（释放 ~2.5 GB）

已删除：
- `D:\UserData\.cargo`（1,059 MB）
- `D:\UserData\.rustup`（1,495 MB）
- `C:\Users\Admin\.cargo` / `.rustup` 符号链接
- `src-tauri/mpv/*.dll` 等 8 个 Windows 专用文件（~240 MB）
- `scripts/*.ps1` Windows 脚本（已替换为跨平台可用的脚本）
- Rust 相关 PATH 环境变量

---

## 二、当前架构总览

### 四层架构映射

```
输入（磁链/m3u8/网页URL）
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ 导入层（Import Layer）                              │
│ ResolverChain.resolve(url)                          │
│ → 按序尝试 MagnetResolver / M3u8Resolver / Web...   │
│ → 返回 LinkTier                                     │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ 解析层（Resolve Layer）                              │
│ MagnetResolver: magnet → BT stream URL              │
│ M3u8Resolver: .m3u8 → 直通                         │
│ WebPageResolver: 网页 → 提取视频源 + Referer        │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ 处理层（Process Layer）                              │
│ TorrentEngine.parse_magnet()                        │
│ TorrentEngine.get_file_tree()                       │
│ run_http_server()（librqbit HTTP API）              │
│ db.rs（播放历史/断点续播）                          │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ 呈现层（Present Layer）                              │
│ MpvPlayer（libmpv FFI 封装）                        │
│ React UI（App.tsx + Tailwind）                      │
│ video_window.rs（子窗口，仅 Windows）               │
└─────────────────────────────────────────────────────┘
    │
    ▼
        播放
```

### 链接分级系统（LinkTier）

| 级别 | 触发条件 | 处理方式 |
|------|---------|---------|
| ReadyToPlay | 解析到可直接播放的流 URL | 直接传给 mpv 播放 |
| NeedsCache | 需要先缓存（未来扩展） | 预留，暂不支持 |
| DownloadOnly | 仅支持下载（未来扩展） | 预留，暂不支持 |
| NotFound | 无法处理或解析失败 | 返回错误信息 |

### 文件清单

```
src-tauri/src/
├── main.rs              # 7 行   — 入口，调用 lib::run()
├── lib.rs               # 367 行 — Tauri setup + 5 个 command
├── layer/mod.rs         # 46 行  — LinkTier + SourceResolver trait
├── resolver/
│   ├── mod.rs           # 59 行  — ResolverChain
│   ├── magnet.rs        # 59 行  — 磁链解析
│   ├── m3u8.rs          # 26 行  — HLS 直通
│   └── webpage.rs       # 248 行 — 网页视频源提取
├── engine/mod.rs        # 278 行 — TorrentEngine + HTTP API
├── mpv_player.rs        # 231 行 — libmpv 安全封装
├── db.rs                # 112 行 — SQLite 持久化
├── mpv_check.rs         # 46 行  — mpv 可用性检查（Linux no-op）
├── video_window.rs      # 90 行  — 子窗口（Linux stub）
├── ai_strategy.rs       # 63 行  — [FROZEN] 关键词广告识别
└── build.rs             # 50 行  — 构建脚本（Windows DLL cfg）

src/
├── App.tsx              # 277 行 — 主界面
├── main.tsx             # 11 行  — React 入口
└── index.css            # 10 行  — Tailwind 样式

Rust 后端总计：~12 个文件，约 1,692 行
前端总计：3 个文件，约 298 行
```

### Tauri Commands

| Command | 参数 | 返回 | 功能 |
|---------|------|------|------|
| `parse_url` | url: String | ParseUrlResult { stream_url, files, source_type } | 统一解析入口 |
| `get_file_tree` | - | Vec\<FileEntry\> | 获取 BT 文件列表 |
| `play_stream` | stream_url, video_rect, magnet, file_path, is_suspected_ad | - | 播放流 |
| `get_history` | - | Vec\<PlayHistoryEntry\> | 播放历史 |
| `save_play_record` | magnet, file_path, stream_url, is_suspected_ad | - | 保存记录 |

---

## 三、WebPageResolver 策略详解

按优先级依次尝试，命中即返回：

1. **HTML5 标签提取** - `scraper` crate 解析 `<video src>` / `<video><source src>`
2. **iframe 检测** - 寻找包含 video/player/embed/m3u8/mp4 关键词的 iframe
3. **JS 变量提取** - 6 种正则模式匹配常见 JS 变量名（videoUrl, video_url, playUrl, file, link, src）
4. **页面文本搜索** - 在页面文本中直接搜索 .m3u8 / .mp4 URL

返回时自动设置 `Referer: <原始页面 URL>` 头，通过 StreamHeaders 缓存传递给 mpv。

---

## 四、当前问题与风险

### 待验证

| 问题 | 风险 | 说明 |
|------|------|------|
| 冒烟测试未执行 | 🔴 | 尚未用真实磁链 / m3u8 / 网页链接实际播放测试 |
| 断点续播未验证 | 🟡 | get_progress / update_progress 逻辑未在真实播放中验证 |
| WSL 离开后重建 | 🟡 | WSL 实例在 ~/BT-player 中，清理 WSL 数据会丢失构建缓存 |
| 长期开发环境 | 🟡 | 当前 WSL 在本地，若需迁移到 VPS 需额外配置 GPU/显示 |

### 代码质量观察

| 问题 | 位置 | 说明 |
|------|------|------|
| Resolver 不做 URL 可达性验证 | `resolver/m3u8.rs` / `webpage.rs` | 返回 ReadyToPlay 时未验证 URL 是否实际可访问，可能导致点击播放失败但无明确错误提示 |
| 硬编码 Tracker 列表 | `engine/mod.rs:96-104` | 8 个公共 Tracker 硬编码在 parse_magnet 中，部分可能已失效 |
| ai_strategy 悬空 | `engine/mod.rs:230` | FROZEN 模块仍被 engine 引用（`ai_strategy::analyze_file_path`），移除前需解耦 |
| 错误处理不一致 | `webpage.rs:86-108` | extract 系列函数返回 Option<String>，丢失具体失败原因；调用方只能给出通用错误 |
| `videoRect` 前端传递无效 | `App.tsx:188-199` | Linux 下 `_video_rect` 已标记未使用，但前端仍计算并传递 rect 值 |
| 无 React 错误边界 | `App.tsx` | invoke 失败时通过 setError 显示，但组件树无 ErrorBoundary 兜底 |

### 文档陈旧

| 文件 | 问题 |
|------|------|
| `SPEC.md` | 引用 Windows 开发环境、HLS 录制、AI 预留接口等已变更内容 |
| `ARCH.md` | 引用 rqbit-core（已改为 librqbit）、子窗口实现等 |
| `PLAN.md` | 需核对是否反映当前状态 |
| `PHASE_REPORT.md` | 需核对是否反映当前状态 |
| `MPV_SETUP.md` | Windows mpv DLL 配置指南，WSL 下不适用 |
| `CLEANUP_AND_DEV_REMINDER.md` | 需核对是否仍有参考价值 |

---

## 五、后续建议

### 优先级 1 — 冒烟测试（验证核心功能）
- [ ] 输入真实磁链，验证解析、文件列表、播放
- [ ] 输入 m3u8 链接，验证直接播放
- [ ] 输入网页链接（如视频站），验证 WebPageResolver 提取
- [ ] 验证断点续播（播放一半关闭，重新打开继续）
- [ ] 验证播放历史记录

### 优先级 2 — 文档整理
- [ ] 更新 SPEC.md 反映当前四层架构
- [ ] 更新 ARCH.md 反映实际技术选型（librqbit 替代 rqbit-core）
- [ ] 删除或归档不再适用的 Windows 专用文档
- [ ] 统一 README 级别文档为当前架构

### 优先级 3 — 代码强化
- [ ] WebPageResolver 的 extract 函数返回具体原因（String 替代 Option）
- [ ] 考虑为 M3u8Resolver 增加 HEAD 请求验证 URL 可达性
- [ ] 添加 React ErrorBoundary 组件兜底
- [ ] 前端移除 Linux 无用的 videoRect 计算

### 优先级 4 — 长期规划
- [ ] ai_strategy.rs：解耦或改造为真正的源解析器（原文意图）
- [ ] Cache / Download 层实现（NeedsCache / DownloadOnly 当前为空）
- [ ] libmpv 子窗口嵌入（Windows 下 HWND 传递 + WSLg 下 Wayland 方案）
- [ ] GPU 硬解码配置暴露给用户

---

## 六、路线图状态

```
Phase 0: 代码清理              ████████████████████ 100%
Phase 1: WSL 环境搭建          ████████████████████ 100%
Phase 2: 架构重构              ████████████████████ 100%
Phase 3: 源发现增强            ████████████████████ 100%
Phase 4: 验证 & 清理           ████████████████░░░  80%
  ├── status.md 更新           ✅
  ├── Windows Rust 清理        ✅
  └── 冒烟测试                 ⬜ 待执行

Next Phase: 冒烟测试 + 文档刷新
```

---

*本小结基于 2026-05-07 项目完整代码审查。*
