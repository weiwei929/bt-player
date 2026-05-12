# BT-Player 重构实施计划

> 目标：将 BT-Player 从"两条平行协议路径"重构为"链接→管道→播放"的四层架构，
> 迁移至 WSL 环境构建，并增强源发现能力。

---

## 总体路线图

```
Phase 0: 代码清理  →  Phase 1: WSL 环境  →  Phase 2: 架构重构  →  Phase 3: 源增强  →  Phase 4: 验证
  (2-3天)            (1-2天)              (2-3天)              (1-2天)              (1天)
```

---

## Phase 0: 代码清理（在 Windows 上直接做）

**目标：** 移除不服务于"直接播放"的模块，减少迁移时的编译负担。

### 0.1 删除 HLS 录制引擎

涉及文件：

| 文件 | 操作 | 说明 |
|------|------|------|
| `src-tauri/src/hls_engine.rs` | 删除文件 | 225 行，录制功能非核心 |
| `src-tauri/src/lib.rs` | 删除约 80 行 | `mod hls_engine`、`RecordingState` 结构体、三个录制命令、`start/stop/is_hls_recording` 的前端暴露 |
| `src-tauri/Cargo.toml` | 删除一行 | `hls_m3u8 = "0.5"`（reqwest 和 chrono 其他模块仍在用，保留） |
| `src/App.tsx` | 删除约 50 行 | 录制按钮 UI、录制状态轮询、`handleToggleRecord` |

### 0.2 冻结 AI 策略模块

| 文件 | 操作 | 说明 |
|------|------|------|
| `src-tauri/src/ai_strategy.rs` | 保留，加注释头 | 标记为 `@FROZEN`，注明"等待架构重构后接入真正的源解析器" |

### 0.3 清理 build.rs

| 文件 | 操作 | 说明 |
|------|------|------|
| `src-tauri/build.rs` | `#[cfg(windows)]` 包裹 Windows 特有逻辑 | 在 Linux 上不执行 DLL 搜索，减少编译报错可能 |

### Phase 0 产出

- 删除 ~1 个源文件，约 150 行代码
- Cargo.toml 减少 1 个依赖
- 前端 App.tsx 减少约 50 行 UI
- **核心功能（magnet + m3u8 播放）完全不变**

---

## Phase 1: WSL 环境搭建

**目标：** 在 WSL Ubuntu 24.04 中完成首次 `cargo build`。

### 1.1 确认 WSL 状态

```bash
wsl -l -v                    # 确认 Ubuntu 24.04 存在
wsl -d Ubuntu-24.04          # 进入 WSL
```

### 1.2 安装系统依赖

```bash
sudo apt update
sudo apt install -y \
  pkg-config \
  libssl-dev \
  libwebkit2gtk-4.1-dev \
  libgtk-3-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev \
  libmpv-dev \
  libsqlite3-dev \
  build-essential \
  cmake
```

### 1.3 安装 Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
rustup default stable
```

### 1.4 项目进入 WSL

方案 A（推荐）：在 WSL 内直接操作 Windows 文件

```bash
cd /mnt/d/workspace/media/BT-player
```

方案 B（性能更优）：复制到 WSL 内部文件系统

```bash
cp -r /mnt/d/workspace/media/BT-player ~/BT-player
cd ~/BT-player
```

### 1.5 安装前端依赖并构建

```bash
npm install
npm run build        # 先单独构建前端
cargo build          # 编译 Rust 后端（首次可能 5-15 分钟）
```

### 1.6 处理可能的编译错误

预期可能的问题：
- `libmpv-sys` 需要 `pkg-config` 能找到 `libmpv` → `apt install libmpv-dev` 解决
- WEBKIT_DISABLE_COMPOSITING_MODE 环境变量 → 若 WebKit 报错则设置
- 路径分隔符差异 → 检查 `PathBuf` 用法（已有，预计无问题）

### Phase 1 产出

- WSL 中 `cargo build` 成功
- `npm run tauri dev` 可启动开发模式（如有桌面环境）
- 或确认至少静态编译通过

---

## Phase 2: 架构重构——四层管道

**目标：** 将 `lib.rs` 中的散乱路由逻辑重组为"导入→解析→处理→呈现"四层结构。

### 2.1 定义核心类型

**新文件：`src-tauri/src/layer/mod.rs`**（或直接放在 `lib.rs` 顶部）

```rust
// === 核心枚举与 trait ===

/// 链接处理结果分层
pub enum LinkTier {
    /// Tier 1: 找到源，可直接播放
    ReadyToPlay {
        stream_url: String,
        headers: Vec<(String, String)>,  // Referer, Cookie 等
    },
    /// Tier 2: 需要缓存/下载后才能播放
    NeedsCache {
        source_url: String,
        estimated_size: u64,
    },
    /// Tier 3: 不能播放，但可转为下载链接
    DownloadOnly {
        download_url: String,
    },
    /// Tier 4: 源不存在或已失效
    NotFound {
        reason: String,
    },
}

/// 源查找器 trait（每个协议实现一个）
#[async_trait]
pub trait SourceResolver: Send + Sync {
    /// 判断是否能处理此输入
    fn can_handle(&self, input: &str) -> bool;

    /// 解析输入，产出一个可处理的源
    async fn resolve(&self, input: &str) -> Result<LinkTier, String>;
}

/// 统一解析结果（导入层 + 解析层的合并输出）
pub struct ResolveResult {
    pub stream_url: String,
    pub files: Vec<FileEntry>,
    pub source_type: String,
    pub headers: Vec<(String, String)>,
}
```

### 2.2 拆分为独立 Resolver

| Resolver | 文件 | 说明 |
|----------|------|------|
| `MagnetResolver` | `src-tauri/src/resolver/magnet.rs` | 从现有 `engine/mod.rs` 抽取，处理 `magnet:` 和裸 hash |
| `M3u8Resolver` | `src-tauri/src/resolver/m3u8.rs` | 从现有 `lib.rs::parse_url` 抽取 |
| `WebPageResolver` | `src-tauri/src/resolver/webpage.rs` | **Phase 3 实现**，先留空桩 |

**新目录结构：**

```
src-tauri/src/
├── lib.rs                # 入口，管理 Resolver 注册链
├── main.rs               # 不变
├── layer/
│   └── mod.rs            # LinkTier, SourceResolver trait, ResolveResult
├── resolver/
│   ├── mod.rs            # ResolverChain：顺序尝试所有 resolver
│   ├── magnet.rs         # 从 engine 抽取
│   └── m3u8.rs           # 从 parse_url 抽取
│   └── webpage.rs        # Phase 3 实现，目前为空柱
├── engine/
│   └── mod.rs            # BT 引擎（核心逻辑不动，只重构接口）
├── mpv_player.rs         # 不变
├── mpv_check.rs          # 不变
├── video_window.rs       # 不变
├── db.rs                 # 不变
└── ai_strategy.rs        # FROZEN
```

### 2.3 修改 lib.rs

**核心变化：**
- `parse_url` command 改为注册 `ResolverChain`，遍历所有 resolver
- 去掉协议硬编码的判断逻辑
- 加上 Tier 分类返回，前端可根据 tier 显示不同的 UI

**parse_url 新流程：**

```rust
#[tauri::command]
async fn parse_url(url: String, state: ...) -> Result<ResolveResult, String> {
    let chain = state.resolvers.lock()?;
    for resolver in chain.iter() {
        if resolver.can_handle(&url) {
            match resolver.resolve(&url).await? {
                LinkTier::ReadyToPlay { stream_url, headers } => {
                    // 对 magnet 调 get_file_tree
                    // 对 m3u8 生成虚拟条目
                    return Ok(ResolveResult { stream_url, files, ... });
                }
                LinkTier::NotFound { reason } => continue, // 试下一个
                LinkTier::NeedsCache { .. } => { /* 处理 */ }
                LinkTier::DownloadOnly { .. } => { /* 处理 */ }
            }
        }
    }
    Err("所有解析器均无法处理此链接".to_string())
}
```

### 2.4 调整 play_stream

添加 header 传递支持（针对防盗链）：

```rust
#[tauri::command]
async fn play_stream(
    stream_url: String,
    headers: Vec<(String, String)>,  // 新增
    ...
) -> Result<(), String> {
    // ... 现有逻辑 ...
    // 将 headers 传递给 mpv（通过 --http-header-fields 或 cookies）
    player.load_file_with_headers(&stream_url, headers, start_sec)?;
}
```

### 2.5 修改 mpv_player

添加 `load_file_with_headers` 方法，在 mpv 加载前通过 `--http-header-fields` 设置防盗链参数。

### Phase 2 产出

- 代码按四层组织
- magnet 和 m3u8 走同一管道
- Tier 分级到位（即使目前只有 Tier 1 和 Tier 4 被真正使用）
- 通过 `cargo build` 和冒烟测试

---

## Phase 3: 源发现增强

**目标：** 补齐你举的两个实际场景。

### 3.1 裸 magnet hash 补全（极低成本）

在 `MagnetResolver::can_handle` 中加一个判断：

```rust
fn can_handle(&self, input: &str) -> bool {
    let trimmed = input.trim();
    // 标准 magnet 链接
    if trimmed.starts_with("magnet:") { return true; }
    // 40 位 hex（BTIH）——裸 hash
    if trimmed.len() == 40 && trimmed.chars().all(|c| c.is_ascii_hexdigit()) {
        return true;
    }
    false
}

fn normalize(&self, input: &str) -> String {
    let trimmed = input.trim();
    if trimmed.starts_with("magnet:") {
        trimmed.to_string()
    } else {
        // 自动补全为 magnet URI
        format!("magnet:?xt=urn:btih:{}", trimmed)
    }
}
```

### 3.2 WebPageResolver（防盗链链接解析）

**新文件：`src-tauri/src/resolver/webpage.rs`**

策略：
1. 检测输入是否为 HTTP(S) 网页 URL（且非 m3u8 直接链接）
2. 发送 HTTP 请求获取页面 HTML
3. 从 HTML 中提取视频源：
   - `<video><source src="...">`
   - 页面内嵌的 `player.src`、`videoUrl` 等 JS 变量
   - 页面中引用的 `.m3u8` 或 `.mp4` 链接
4. 获取防盗链参数：`Referer: <原始页面URL>` + 可能的 Cookie
5. 返回 `LinkTier::ReadyToPlay { stream_url, headers: [(Referer, 页面URL)] }`

**依赖：** 只需要 `reqwest`（已有），外加一个 `scraper` crate 或手动 HTML 解析。

**注意：** 考虑是否需要 `reqwest` 的 cookie 支持，若需要则在 Cargo.toml 加 `reqwest = { features = ["cookies"] }`。

### Phase 3 产出

- 裸 hash `8012f3a7....` 自动识别并补全为 magnet 链接
- 网页链接 `https://hsex.tv/video-1193919.htm` 解析出视频源并携带防盗链参数播放
- 通过 `cargo build`

---

## Phase 4: 验证与收尾

### 4.1 编译验证

```bash
cargo build --release     # release 构建
npm run tauri build       # 完整 Tauri 构建
```

### 4.2 功能冒烟测试

| 用例 | 输入 | 期望结果 |
|------|------|----------|
| 标准磁链 | `magnet:?xt=urn:btih:...` | 解析文件树，点击可播放 |
| 裸 hash | `8012f3a7a2c41c2a75c938f7ba3f12b6fd363a3a` | 自动补全，同标准磁链 |
| HLS 直链 | `https://xxx.m3u8` | 点击播放 |
| 网页链接 | `https://hsex.tv/video-1193919.htm` | （Phase 3）解析后播放 |
| 无效链接 | `not-a-link` | 返回 Tier 4 错误提示 |
| 失效链接 | `https://example.com/expired.m3u8` | 返回 Tier 4 错误提示 |

### 4.3 文档更新

- 更新 `status.md` 记录 Phase 0-4 完成状态
- 更新 `PHASE_REPORT.md` 中关于架构的章节
- 更新 `SPEC.md` 中关于四层架构的描述

---

## 风险与备选

| 风险 | 概率 | 应对 |
|------|------|------|
| WSL 桌面环境缺失，无法启动 Tauri 窗口 | 高 | 先做 `cargo build` 确认编译通过，Tauri 窗口测试留到有桌面环境时 |
| libmpv-sys 在 Linux 下的绑定问题 | 低 | `apt install libmpv-dev` 后通常可用；参考 mpv_player.rs 中已有 `#[cfg(not(windows))]` 实现 |
| WebPageResolver 反盗链过于复杂 | 中 | Phase 3 可按需简化：先做 Referer 传递，Cookie 等高级处理可延后 |
| 重构过程中出现回归 | 低 | 每步保持 `cargo build` 通过，不过度一次改太多 |

---

## 执行顺序（推荐）

```
Phase 0 → Phase 1 → Phase 2 → Phase 3-4（按需）
  (清理)    (搭环境)   (重构)    (增强)
```

Phase 0 可以直接在 Windows 上执行，不需要构建环境。
Phase 1 完成后建议先 `cargo build` 验证，确认当前代码在 WSL 上能编译。
Phase 2 建议分步走：先建 layer 模块 + 定义类型 → 提取 resolver → 改 lib.rs → 编译验证。
Phase 3 可作为独立的 Phase，在 2 完成后随时开始。

---

*计划版本: v1.0 | 制定日期: 2026-05-07*
