# BT-Player 核心架构说明 (Architectural Decisions)

## 1. 模块化设计 (Modular Architecture)
本项目遵循“核心-适配器-插件”模式，确保基础版稳定，进阶版可扩展。

### 1.1 核心层 (Core Engine - Rust)
*   **TorrentHandle**: 封装 `rqbit-core` 的底层 Session。
*   **StreamServer**: 负责将 P2P 下载的数据块转换为符合 HTTP Range 请求的视频流。
*   **SequentialStrategy**: 强制顺序下载逻辑。**[注：CLI PoC 阶段仅实现最小可用子集，更复杂的预测算法延后至第二阶段]**。

### 1.2 接口定义 (Traits & Interfaces)
*   `trait MediaStream`: 定义统一的流操作（play, pause, seek, stop）。
*   `trait MetaProcessor`: 处理资源解析，并预留 `on_analyzed` 钩子供 AI 插件使用。

### 1.3 FFI 安全策略 (mpv Integration)
*   采用 `libmpv-sys` 的原生绑定。
*   **句柄传递**: 在 Windows 下，通过 Tauri 窗口的 HWND 句柄进行原生渲染注入。

## 2. 性能决策记录 (ADR)
*   **Memory Buffer**: 针对 32GB 内存，默认设置 256MB 的环形写缓冲。
*   **Sparse File**: 在 NTFS 下必须开启稀疏文件，以避免 SSD 在点播时的瞬时分配停顿。
*   **Networking**: 默认开启 DHT + PEX + LSD。端口映射优先使用 UPnP。

## 3. 进阶 AI 预留 (Advanced Hooks)
*   `VisionHook`: 暴露解码后的视频帧像素缓冲区指针（针对广告识别）。
*   `MetadataHook`: 在导入磁链时拦截 Metadata，并根据 AI 权重返回“安全评分”。

## 4. 变更记录 (Change Log)
*   **v0.1.0** (2026-02-14): 初始架构定义。
*   **v0.1.1** (2026-02-14): 遵循 Engineer (Cursor) 建议，精简 CLI 阶段目标，增加核心层实现的阶段说明。
*   **v0.2.0** (2026-02-14): 第四阶段完成。子窗口覆盖、rusqlite 媒体库、AI 策略引擎（启发式 AD/赌博/扫码识别）、播放历史、AI 助理抽屉。

---
*维护者: GitHub Copilot (Architect)*
