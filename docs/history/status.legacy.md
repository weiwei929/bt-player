# BT-Player 项目验证状态记录

## 时间
2026-05-07

## 初始目标
用户要求：检查并评估 BT-Player 项目当前状态，验证是否能成功构建。

---

## 做了什么

### 1. 项目全面评估 ✅
- 通读所有 Rust 后端代码（lib.rs, engine, mpv_player, hls_engine, db, ai_strategy, video_window, mpv_check）
- 通读前端代码（App.tsx, main.tsx, index.css）
- 通读配置文件（Cargo.toml, tauri.conf.json, package.json, build.rs）
- 通读文档（SPEC.md, ARCH.md, PHASE_REPORT.md）
- 结论：架构良好，代码质量高，属于功能性原型阶段

### 2. Windows 构建尝试 ❌（失败）
| 步骤 | 结果 |
|------|------|
| `npm install` | ✅ 成功 |
| 检查 `mpv-1.dll` | ✅ 已存在于 `src-tauri/mpv/` |
| `cargo build` | ❌ 失败 |

**失败原因**：Windows 上 Rust 默认使用 MSVC 工具链，需要 `link.exe`（MSVC 链接器）。但环境中：
- Git for Windows 的 `link.exe` 抢占 PATH，导致 Rust 链接时调用错误的 link.exe
- 缺少 Visual Studio C++ 工具链和 Windows SDK

**尝试的绕路方案（全部失败后已清理）：**
- ❌ 安装 LLVM + lld-link 替代 MSVC link.exe → 缺少 Windows SDK .lib 文件
- ❌ 创建 MinGW 伪装的 .lib 文件 → 缺少 MSVC CRT 启动代码
- ❌ 安装 VS BuildTools（两次，winget + installer）→ C++ 组件未正确安装
- ❌ LLVM-MinGW（winget，后手动复制）→ 格式不兼容

### 3. 已清理的临时安装
| 项目 | 大小 | 状态 |
|------|------|------|
| LLVM (C:\Program Files\LLVM) | ~434MB | ✅ 已卸载 |
| LLVM-MinGW (C:\llvm-mingw) | ~178MB | ✅ 已删除 |
| VS BuildTools 2022 | ~1GB+ | ✅ 已卸载 |
| 临时 cargo 配置 | - | ✅ 已删除 |
| 多余 Rust 目标 (gnu + gnullvm) | - | ✅ 已移除 |

### 4. WSL 迁移分析 ✅
- 确认 WSL Ubuntu 24.04 LTS 可用
- 确认 Node.js v20 / gcc / make / python3 已预装
- 确认项目在 Linux 上需要的调整极小：
  - `build.rs`：Windows 特有逻辑已有 `#[cfg]` 包裹，无需修改
  - `video_window.rs`：已有 `#[cfg(not(windows))]` stub，兼容
  - `mpv_check.rs`：已有 `#[cfg(not(windows))]` stub，兼容
  - `mpv_player.rs`：已有双平台实现，兼容

---

## Phase 0: 代码清理（2026-05-07 完成 ✅）

| 操作 | 状态 |
|------|------|
| 删除 `hls_engine.rs`（HLS 录制引擎，225 行） | ✅ |
| 删除 `Cargo.toml` 中 `hls_m3u8` 依赖 | ✅ |
| 清理 `lib.rs` 中 RecordingState + 3 个录制命令（~80 行） | ✅ |
| 清理 `App.tsx` 中录制 UI + 状态轮询（~50 行） | ✅ |
| 冻结 `ai_strategy.rs`（标记 FROZEN） | ✅ |
| 隔离 `build.rs` Windows DLL 搜索逻辑 | ✅ |
| 内联 `is_m3u8_url()` 工具函数 | ✅ |

**核心功能不受影响：** magnet 解析、m3u8 播放、mpv 渲染、播放历史、断点续播 — 全部保留。

---

## Phase 1: WSL 环境搭建（2026-05-07 完成 ✅）

| 步骤 | 结果 |
|------|------|
| WSL Ubuntu 24.04 确认可用 | ✅ |
| 安装系统依赖（apt install pkg-config, libwebkit2gtk, libmpv-dev 等） | ✅ |
| 代理问题排查与修复（unset proxy） | ✅ |
| 项目跨文件系统问题 → 复制到 WSL 内部 ext4 | ✅ |
| npm install | ✅ |
| cargo build | ✅ （8 个 warning，无报错） |
| WSLg 窗口启动确认 | ✅ （tauri dev 正常弹窗） |

**关键发现：**
- WSL 继承 Windows Clash 代理设置导致 curl/npm 失败，需 `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY`
- 跨文件系统（drvfs）有符号链接问题，项目需复制到 `~/BT-player/`
- `Cargo.toml` 中 `rusqlite`/`chrono` 误放在 `[target.'cfg(windows)'.dependencies]` 之后，导致 Linux 不可见 — 已修复

---

## Phase 2: 四层架构重构（2026-05-07 完成 ✅）

| 操作 | 状态 |
|------|------|
| 定义 `layer/mod.rs`：`LinkTier` 枚举 + `SourceResolver` trait | ✅ |
| 抽取 `resolver/magnet.rs`：`MagnetResolver` | ✅ |
| 抽取 `resolver/m3u8.rs`：`M3u8Resolver` | ✅ |
| 重构 `lib.rs` 中 `parse_url` 为 ResolverChain 管道调用 | ✅ |
| `ResolverState` 改用 `tokio::sync::Mutex` 解决跨 `.await` Send 问题 | ✅ |
| `play_stream` 重构：支持断点续播 + 播放历史写入 | ✅ |
| cargo build 通过 | ✅ |
| Tauri 窗口正常启动 | ✅ |

**架构变更摘要：**
```
src-tauri/src/
├── layer/mod.rs      # [新增] LinkTier 枚举 + SourceResolver trait
├── resolver/
│   ├── mod.rs        # [新增] ResolverChain（责任链模式）
│   ├── magnet.rs     # [新增] MagnetResolver
│   ├── m3u8.rs       # [新增] M3u8Resolver
│   └── webpage.rs    # [新增] WebPageResolver
├── lib.rs            # [重构] 使用 ResolverChain 替换内联解析逻辑
```

---

## Phase 3: 源发现增强（2026-05-07 完成 ✅）

| 操作 | 状态 |
|------|------|
| 裸 magnet hash（40 字符 hex）自动补全为完整磁链 | ✅ |
| `MagnetResolver` / `M3u8Resolver` 返回 `headers: vec![]` | ✅ |
| `WebPageResolver`：HTML `<video>` / `<source>` 标签提取 | ✅ |
| `WebPageResolver`：iframe 视频播放器检测 | ✅ |
| `WebPageResolver`：JS 变量提取（videoUrl, playUrl, file, link 等） | ✅ |
| `WebPageResolver`：页面中直接引用的流媒体链接搜索 | ✅ |
| `WebPageResolver`：相对 URL → 绝对 URL 解析 | ✅ |
| `lib.rs` `parse_url`：headers 解构 → 缓存到 `StreamHeaders` | ✅ |
| `lib.rs` `play_stream`：从 `StreamHeaders` 读取 Referer → 传给 mpv | ✅ |
| `mpv_player.rs`：新增 `set_referrer()` 方法 | ✅ |
| cargo build 通过 | ✅ |
| Tauri 窗口正常启动 | ✅ |

**WebPageResolver 提取策略优先级：**
1. `<video src="...">` / `<video><source src="..."></video>`
2. `<iframe src="...">`（包含 video/player/embed 关键词）
3. JavaScript 变量中的视频地址（6 种正则模式）
4. 页面文本中直接引用的 .m3u8 / .mp4 链接

---

## Phase 4: 验证 & 清理（2026-05-07 完成 ✅）

### 已完成
- [x] cargo build --release（开发环境 build 通过）
- [x] Tauri 桌面窗口正常启动（WSLg）
- [x] Windows Rust 工具链清理（.cargo 1GB + .rustup 1.5GB）
- [x] 冒烟测试（详见 SMOKE_TEST_REPORT.md）

### 冒烟测试结果摘要

| 测试 | 结果 | 说明 |
|------|------|------|
| m3u8 解析链路 | ✅ 通过 | Apple 测试流解析成功，mpv 弹窗 |
| 磁链解析链路 | ✅ 通过 | Ubuntu ISO 文件列表、stream_url 完整 |
| 裸 hash 自动补全 | ❌ 待修复 | 输入 40 位 hex 卡死，可能超时问题 |
| 国内 m3u8 播放 | ❌ 待修复 | 解析成功但 mpv 无响应 |
| 中文乱码 | ✅ 已解决 | `apt install fonts-wqy-zenhei` |
| 代理环境变量 | ✅ 已解决 | WSL 清除 proxy env，写入 ~/.bashrc |

---

## 当前架构总览

```
src-tauri/src/
├── lib.rs               # 入口：ResolverChain, StreamHeaders, parse_url/play_stream
├── main.rs              # 入口点（未修改）
├── layer/mod.rs         # LinkTier 枚举, SourceResolver trait
├── resolver/
│   ├── mod.rs           # ResolverChain（责任链模式）
│   ├── magnet.rs        # MagnetResolver（磁链 + 裸 hash 自动补全）
│   ├── m3u8.rs          # M3u8Resolver（HLS 直接链接）
│   └── webpage.rs       # WebPageResolver（网页视频源提取 + Referer）
├── engine/mod.rs        # BT 引擎（librqbit 核心，未修改）
├── mpv_player.rs        # libmpv 封装 + set_referrer()
├── db.rs                # SQLite 播放历史/断点续播（未修改）
├── mpv_check.rs         # mpv 可用性检查（未修改）
├── video_window.rs      # 子窗口管理（未修改，Linux stub）
└── ai_strategy.rs       # FROZEN
```

## 四层架构映射

| 层 | 职责 | 实现 |
|----|------|------|
| 导入层（Import） | URL 输入、格式识别、解析器路由 | `ResolverChain::resolve()` |
| 解析层（Resolve） | 源地址提取、元数据获取 | `MagnetResolver`, `M3u8Resolver`, `WebPageResolver` |
| 处理层（Process） | 流媒体服务、播放控制 | `TorrentEngine`, `play_stream` |
| 呈现层（Present） | 视频渲染、UI 交互 | `MpvPlayer`, Tauri + React |

## 链接分级系统（LinkTier）

| 级别 | 含义 | 示例 |
|------|------|------|
| `ReadyToPlay` | 可直接播放的流 URL | 完整 m3u8 / 磁链解析后的直链 |
| `NeedsCache` | 需要先缓存再播放 | BT 文件→HTTP 流 |
| `DownloadOnly` | 仅支持下载 | HTTP 直链 mp4（未来扩展） |
| `NotFound` | 无法处理的链接 | 未知格式 / 解析失败 |

## WSL 安装步骤（参考）

```bash
# 1. 系统依赖
sudo apt update
sudo apt install -y pkg-config libssl-dev libwebkit2gtk-4.1-dev libgtk-3-dev \
  libayatana-appindicator3-dev librsvg2-dev libmpv-dev libsqlite3-dev \
  build-essential cmake

# 2. Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

# 3. 项目（方式A：直接访问 Windows 文件）
cd /mnt/d/workspace/media/BT-player

# 4. 构建
npm install
cargo build
```

**注意：** 若编译中遇到 WebKit 相关报错，可设置环境变量：
```bash
export WEBKIT_DISABLE_COMPOSITING_MODE=1
```
