# BT-Player VPS 部署方案

> 日期：2026-05-07
> 目标 VPS：**甲骨文首尔 | ARM (aarch64) | Debian 12 | 11GB RAM | 45GB 磁盘**
> 架构变更：Tauri 桌面 → 纯 Web 服务（Rust HTTP 后端 + React 前端）

---

## 一、环境现状

| 组件 | 状态 | 操作 |
|------|------|------|
| Rust | ❌ 未安装 | `curl ... rustup.rs | sh` |
| Node.js | ✅ v22.22.2 (hermes) | PATH 需配置 |
| Caddy | ✅ 已运行 80/443 | 加反向代理配置 |
| Git | ✅ 2.39.5 | 直接使用 |
| libssl-dev | ✅ arm64 | 已有 |
| pkg-config | ✅ | 已有 |
| build-essential | ❌ 待装 | `apt install` |
| 磁盘 | 45GB / 33GB 空余 | 充裕 |

---

## 二、端口规划

| 端口 | 用途 | 访问范围 |
|------|------|---------|
| 443 | HTTPS（Caddy） | 公网 |
| 9527 | librqbit HTTP API（BT 流媒体） | 127.0.0.1 |
| 9528 | BT-Player HTTP 服务（REST API） | 127.0.0.1 |
| 50051 | BT 监听（peer 连接） | 公网 |

---

## 三、部署步骤

### 第 1 步：系统依赖

```bash
apt update
apt install -y build-essential cmake
```

### 第 2 步：安装 Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
rustc --version  # 验证
```

### 第 3 步：获取代码到 VPS

```bash
# 方式 A：从本机 SCP（先在本地 ~/BT-player 下执行）
tar czf bt-player.tar.gz --exclude=node_modules --exclude=src-tauri/target .
scp bt-player.tar.gz root@146.56.133.171:~

# 然后在 VPS 解压
cd /root
tar xzf bt-player.tar.gz
```

### 第 4 步：配置 Node.js PATH

```bash
export PATH="/root/.hermes/node/bin:$PATH"
echo 'export PATH="/root/.hermes/node/bin:$PATH"' >> ~/.bashrc

cd /root/BT-player
npm install
```

### 第 5 步：修改代码（关键步骤）

> 将 Tauri 桌面应用 → axum HTTP 服务 + React 浏览器前端

#### 5.1 替换 `src-tauri/Cargo.toml`

完整内容（复制后直接覆盖）：

```toml
[package]
name = "bt-player"
version = "0.1.0"
edition = "2021"

[lib]
name = "bt_player_lib"
crate-type = ["rlib"]

[dependencies]
tokio = { version = "1", features = ["full"] }
tokio-util = "0.7"
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
anyhow = "1"
url = "2"
reqwest = { version = "0.11", features = ["json"] }
hex = "0.4"
urlencoding = "2.1.3"
async-trait = "0.1"
scraper = "0.22"
regex = "1"
rusqlite = { version = "0.32", features = ["bundled"] }
chrono = "0.4"

# librqbit BT 引擎
librqbit = { git = "https://github.com/ikatson/rqbit", branch = "main", features = ["http-api", "default-tls"] }
librqbit-dualstack-sockets = "0.6"

# Web 框架
axum = "0.7"
tower-http = { version = "0.5", features = ["cors"] }
```

#### 5.2 替换 `src-tauri/src/main.rs`

```rust
// BT-Player VPS 版入口
// 启动 axum HTTP 服务 + librqbit BT 引擎

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use tokio_util::sync::CancellationToken;
use tracing::info;

mod ai_strategy;
mod db;
mod engine;
mod layer;
mod resolver;

use engine::{run_http_server, TorrentEngine};
use crate::db::{init_db, DbState};
use std::sync::Mutex;

const HTTP_PORT: u16 = 9527;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "bt_player=info,librqbit=info".into()),
        )
        .init();

    // 缓存目录
    let cache_dir = PathBuf::from("/root/bt_cache");
    tokio::fs::create_dir_all(&cache_dir).await.unwrap();

    // 初始化数据库
    let db_path = cache_dir.join("bt_player.db");
    let conn = init_db(&db_path).expect("数据库初始化失败");
    let db = DbState(Mutex::new(conn));

    // BT 引擎
    let engine = TorrentEngine::new(cache_dir.clone(), HTTP_PORT)
        .await
        .expect("BT 引擎初始化失败");
    let engine = Arc::new(engine);
    let session = engine.session();
    let cancel = CancellationToken::new();

    // 启动 librqbit HTTP API
    let cancel_clone = cancel.clone();
    let listen_addr: SocketAddr = ([127, 0, 0, 1], HTTP_PORT).into();
    tokio::spawn(async move {
        if let Err(e) = run_http_server(session, listen_addr, cancel_clone).await {
            eprintln!("HTTP API 服务异常: {:#}", e);
        }
    });

    // 启动 axum 服务（主应用 API）
    let app = bt_player_lib::create_app(engine, db);
    let addr = SocketAddr::from(([127, 0, 0, 1], 9528));
    info!("BT-Player API 服务启动: http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
```

#### 5.3 替换 `src-tauri/src/lib.rs`

```rust
// BT-Player VPS 版 API 路由
// axum HTTP handler 替代原有的 Tauri command

use std::sync::{Arc, Mutex};

use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};

use engine::{FileEntry, TorrentEngine};
use resolver::{MagnetResolver, M3u8Resolver, ResolverChain, WebPageResolver};
use layer::LinkTier;
use db::{get_play_history, get_progress, DbState};
use tokio::sync::Mutex as TokioMutex;

/// 共享应用状态
#[derive(Clone)]
pub struct AppState {
    pub engine: Arc<TorrentEngine>,
    pub resolver: Arc<TokioMutex<ResolverChain>>,
    pub db: Arc<Mutex<rusqlite::Connection>>,
}

/// 构建 axum 路由
pub fn create_app(engine: Arc<TorrentEngine>, db: DbState) -> Router {
    // 初始化解析器链
    let mut chain = ResolverChain::new();
    chain.register(Box::new(MagnetResolver::new(engine.clone())));
    chain.register(Box::new(M3u8Resolver));
    chain.register(Box::new(WebPageResolver));

    let state = AppState {
        engine,
        resolver: Arc::new(TokioMutex::new(chain)),
        db: Arc::new(db.0),
    };

    Router::new()
        .route("/api/resolve", post(handle_resolve))
        .route("/api/torrents", get(handle_file_tree))
        .route("/api/history", get(handle_get_history).post(handle_save_record))
        .layer(tower_http::cors::CorsLayer::permissive())
        .with_state(state)
}

// ─── 请求/响应类型 ───

#[derive(Deserialize)]
pub struct ResolveRequest {
    pub url: String,
}

#[derive(Serialize)]
pub struct ResolveResponse {
    pub stream_url: String,
    pub files: Vec<FileEntry>,
    pub source_type: String,
}

#[derive(Serialize)]
pub struct ErrorResponse {
    pub error: String,
}

#[derive(Deserialize)]
pub struct SaveRecordRequest {
    pub magnet: String,
    pub file_path: String,
    pub stream_url: String,
    pub is_suspected_ad: bool,
}

// ─── Handler ───

async fn handle_resolve(
    State(state): State<AppState>,
    Json(req): Json<ResolveRequest>,
) -> Result<Json<ResolveResponse>, (axum::http::StatusCode, Json<ErrorResponse>)> {
    let url = req.url.trim().to_string();
    if url.is_empty() {
        return Err((
            axum::http::StatusCode::BAD_REQUEST,
            Json(ErrorResponse { error: "URL 不能为空".into() }),
        ));
    }

    let mut chain = state.resolver.lock().await;
    let (tier, normalized_input) = chain.resolve(&url).await.map_err(|e| {
        (axum::http::StatusCode::BAD_REQUEST, Json(ErrorResponse { error: e }))
    })?;

    match tier {
        LinkTier::ReadyToPlay { stream_url, headers: _ } => {
            // 磁链 → 获取文件树
            if normalized_input.starts_with("magnet:") {
                let files = state.engine.get_file_tree().await.map_err(|e| {
                    (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
                })?;
                Ok(Json(ResolveResponse {
                    stream_url,
                    files,
                    source_type: "magnet".into(),
                }))
            } else {
                // HLS/直链 → 虚拟文件条目
                Ok(Json(ResolveResponse {
                    stream_url: stream_url.clone(),
                    files: vec![FileEntry {
                        index: 0,
                        path: "HLS 流".into(),
                        size_bytes: 0,
                        size_mb: 0.0,
                        stream_url: normalized_input,
                        is_suspected_ad: false,
                    }],
                    source_type: "hls".into(),
                }))
            }
        }
        LinkTier::NeedsCache { .. } => Err((
            axum::http::StatusCode::BAD_REQUEST,
            Json(ErrorResponse { error: "需要缓存后播放，暂不支持".into() }),
        )),
        LinkTier::DownloadOnly { .. } => Err((
            axum::http::StatusCode::BAD_REQUEST,
            Json(ErrorResponse { error: "仅支持下载，暂不支持".into() }),
        )),
        LinkTier::NotFound { reason } => Err((
            axum::http::StatusCode::NOT_FOUND,
            Json(ErrorResponse { error: reason }),
        )),
    }
}

async fn handle_file_tree(
    State(state): State<AppState>,
) -> Result<Json<Vec<FileEntry>>, (axum::http::StatusCode, Json<ErrorResponse>)> {
    state.engine.get_file_tree().await.map(Json).map_err(|e| {
        (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
    })
}

async fn handle_get_history(
    State(state): State<AppState>,
) -> Result<Json<Vec<db::PlayHistoryEntry>>, (axum::http::StatusCode, Json<ErrorResponse>)> {
    let conn = state.db.lock().map_err(|e| {
        (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
    })?;
    get_play_history(&conn, 50).map(Json).map_err(|e| {
        (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e }))
    })
}

async fn handle_save_record(
    State(state): State<AppState>,
    Json(req): Json<SaveRecordRequest>,
) -> Result<Json<()>, (axum::http::StatusCode, Json<ErrorResponse>)> {
    let conn = state.db.lock().map_err(|e| {
        (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
    })?;
    db::insert_play_history(&conn, &req.magnet, &req.file_path, &req.stream_url, 0.0, req.is_suspected_ad)
        .map(|_| Json(()))
        .map_err(|e| {
            (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e }))
        })
}
```

#### 5.4 删除不再需要的文件

```bash
cd /root/BT-player
rm -f src-tauri/src/mpv_player.rs
rm -f src-tauri/src/mpv_check.rs
rm -f src-tauri/src/video_window.rs
rm -f src-tauri/tauri.conf.json
rm -rf src-tauri/capabilities/
```

#### 5.5 简化 `src-tauri/build.rs`

```rust
fn main() {
    // VPS 版：无 Windows DLL 搜索，无 Tauri
    println!("cargo:rerun-if-changed=build.rs");
}
```

#### 5.6 替换 `package.json`

仅保留 Web 必需，移除 Tauri 依赖：

```json
{
  "name": "bt-player",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18",
    "react-dom": "^18"
  },
  "devDependencies": {
    "@types/react": "^18",
    "@types/react-dom": "^18",
    "@vitejs/plugin-react": "^4",
    "autoprefixer": "^10",
    "postcss": "^8",
    "tailwindcss": "^3",
    "typescript": "^5",
    "vite": "^5"
  }
}
```

删除 `package-lock.json` 和 `node_modules`，重新 `npm install`：

```bash
cd /root/BT-player
rm -rf node_modules package-lock.json
npm install
```

#### 5.7 替换 `src/App.tsx`

完整的浏览器版前端，将 Tauri IPC 改为 fetch，播放器改为 `<video>` 标签：

```tsx
import { useState, useEffect } from "react";

interface FileEntry {
  index: number;
  path: string;
  size_bytes: number;
  size_mb: number;
  stream_url: string;
  is_suspected_ad?: boolean;
}

interface PlayHistoryEntry {
  id: number;
  magnet: string;
  file_path: string;
  stream_url: string;
  played_at: string;
  progress_sec: number;
  is_suspected_ad: boolean;
}

const API_BASE = "";  // 同域下，Caddy 反向代理 /api/*

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || "请求失败");
  }
  return res.json();
}

function App() {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [sourceType, setSourceType] = useState<"magnet" | "hls" | null>(null);
  const [history, setHistory] = useState<PlayHistoryEntry[]>([]);
  const [playingUrl, setPlayingUrl] = useState<string | null>(null);
  const [playingTitle, setPlayingTitle] = useState<string | null>(null);

  const loadHistory = async () => {
    try {
      const list = await api<PlayHistoryEntry[]>("/api/history");
      setHistory(list);
    } catch {
      setHistory([]);
    }
  };

  useEffect(() => { loadHistory(); }, []);

  const handleResolve = async () => {
    const url = input.trim();
    if (!url) return;
    setLoading(true);
    setError(null);
    setFiles([]);
    setStreamUrl(null);
    setPlayingUrl(null);
    try {
      const result = await api<{ stream_url: string; files: FileEntry[]; source_type: string }>(
        "/api/resolve",
        { method: "POST", body: JSON.stringify({ url }) }
      );
      setStreamUrl(result.stream_url);
      setFiles(result.files);
      setSourceType(result.source_type as "magnet" | "hls");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6 flex flex-col">
      <div className="max-w-4xl mx-auto w-full flex-1 flex flex-col">
        <h1 className="text-2xl font-bold text-cyan-400 mb-4">BT-Player</h1>

        {/* 视频播放区域 */}
        {playingUrl && (
          <div className="w-full aspect-video max-h-[54vh] mb-4 rounded-lg bg-black/80 border border-slate-600 overflow-hidden">
            <video
              src={playingUrl}
              controls
              autoPlay
              className="w-full h-full"
              onError={() => setError("播放失败：流地址不可达或编码不支持")}
            />
          </div>
        )}
        {!playingUrl && (
          <div className="w-full aspect-video max-h-[54vh] mb-4 rounded-lg bg-black/80 border border-slate-600 flex items-center justify-center">
            <span className="text-slate-500 text-sm">
              解析链接后点击文件即可播放
            </span>
          </div>
        )}

        {playingTitle && (
          <div className="flex items-center mb-4 px-2">
            <span className="text-emerald-400 text-sm truncate max-w-xs">
              ▶ {playingTitle}
            </span>
          </div>
        )}

        {/* 输入区域 */}
        <div className="space-y-4 mb-6">
          <label className="block text-sm font-medium text-slate-300">
            磁链或 m3u8 地址
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="magnet:?xt=urn:btih:... 或 https://xxx.m3u8"
              className="flex-1 px-4 py-2 rounded-lg bg-slate-800 border border-slate-600 focus:border-cyan-500 outline-none"
            />
            <button
              onClick={handleResolve}
              disabled={loading}
              className="px-6 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 font-medium"
            >
              {loading ? "解析中..." : "解析"}
            </button>
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/50 border border-red-700 text-red-200">
            {error}
          </div>
        )}

        {/* 流 URL 显示 */}
        {streamUrl && (
          <div className="mb-4 p-3 rounded-lg bg-slate-800 border border-slate-600">
            <span className="text-slate-400 text-sm">流 URL: </span>
            <code className="text-cyan-300 text-sm break-all">{streamUrl}</code>
          </div>
        )}

        {/* 文件列表 */}
        <div className="rounded-lg border border-slate-600 bg-slate-800/50 overflow-hidden">
          <div className="px-4 py-2 border-b border-slate-600 font-medium text-slate-300">
            {sourceType === "hls" ? "HLS 流" : `文件列表 (${files.length})`}
          </div>
          <ul className="divide-y divide-slate-600 max-h-96 overflow-y-auto">
            {files.length === 0 && !loading && (
              <li className="px-4 py-8 text-center text-slate-500">输入地址后点击「解析」</li>
            )}
            {files.map((f) => (
              <li
                key={f.index}
                className="px-4 py-2 hover:bg-slate-700/50 flex items-center justify-between gap-4 cursor-pointer"
                onClick={() => {
                  if (f.stream_url) {
                    setPlayingUrl(f.stream_url);
                    setPlayingTitle(f.path);
                    setError(null);
                    // 记录播放历史
                    api("/api/history", {
                      method: "POST",
                      body: JSON.stringify({
                        magnet: input.trim(),
                        file_path: f.path,
                        stream_url: f.stream_url,
                        is_suspected_ad: f.is_suspected_ad ?? false,
                      }),
                    }).catch(() => {});
                  }
                }}
              >
                <span className="text-cyan-300 truncate flex-1 font-mono text-sm">{f.path}</span>
                {f.is_suspected_ad && <span className="text-amber-400 text-xs shrink-0">广告</span>}
                <span className="text-slate-400 text-sm shrink-0">{f.size_mb.toFixed(2)} MB</span>
              </li>
            ))}
          </ul>
        </div>

        {/* 播放历史 */}
        {history.length > 0 && (
          <div className="mt-6 rounded-lg border border-slate-600 bg-slate-800/50 overflow-hidden">
            <div className="px-4 py-2 border-b border-slate-600 font-medium text-slate-300">
              播放历史 ({history.length})
            </div>
            <ul className="divide-y divide-slate-600 max-h-48 overflow-y-auto">
              {history.slice(0, 10).map((h) => (
                <li key={h.id} className="px-4 py-2 text-sm text-slate-400 truncate" title={h.file_path}>
                  {h.file_path} · {h.played_at}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
```

#### 5.8 移除 `tsconfig.node.tsbuildinfo` 等缓存

如果之前有 `.tsbuildinfo` 文件，删掉重新生成：

```bash
rm -f /root/BT-player/tsconfig.node.tsbuildinfo /root/BT-player/tsconfig.tsbuildinfo
```

### 第 6 步：构建

```bash
# 后端（arm64 release 可能需要 5-15 分钟）
cd /root/BT-player/src-tauri
cargo build --release

# 前端
cd /root/BT-player
npm run build
```

### 第 7 步：配置 Caddy

编辑 Caddyfile：

```bash
vim /etc/caddy/Caddyfile
```

在现有配置之上，添加一个子域名块：

```
bt-player.你的域名.com {
    root * /root/BT-player/dist
    encode gzip

    try_files {path} /index.html

    handle_path /api/* {
        reverse_proxy 127.0.0.1:9528
    }

    handle_path /stream/* {
        reverse_proxy 127.0.0.1:9527
    }
}
```

重载 Caddy：

```bash
caddy reload
```

### 第 8 步：配置 systemd 服务

```bash
cat > /etc/systemd/system/bt-player.service << 'EOF'
[Unit]
Description=BT-Player Streaming Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/BT-player
ExecStart=/root/BT-player/src-tauri/target/release/bt-player
Restart=on-failure
RestartSec=5
Environment=RUST_LOG=bt_player=info,librqbit=info

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now bt-player
```

### 第 9 步：验证

```bash
# 服务状态
systemctl status bt-player

# 日志
journalctl -u bt-player -f

# API 测试
curl -s http://127.0.0.1:9528/api/resolve -X POST \
  -H "Content-Type: application/json" \
  -d '{"url":"magnet:?xt=urn:btih:AF89AB583826696F9E77D4CC07826E65ED831BF4"}'

# 浏览器访问
echo "打开 https://bt-player.你的域名.com"
```

---

## 四、文件变更总清单

### 修改

| 文件 | 说明 |
|------|------|
| `src-tauri/Cargo.toml` | 移除 tauri/libmpv，添加 axum/tower-http |
| `src-tauri/src/main.rs` | 重写为 axum 入口 |
| `src-tauri/src/lib.rs` | 重写为 HTTP handler |
| `package.json` | 移除 Tauri 依赖 |
| `src/App.tsx` | invoke → fetch，播放器改为 `<video>` |
| `src-tauri/build.rs` | 简化 |

### 删除

| 文件 | 原因 |
|------|------|
| `src-tauri/src/mpv_player.rs` | 桌面播放器，VPS 用不到 |
| `src-tauri/src/mpv_check.rs` | 桌面检查，VPS 用不到 |
| `src-tauri/src/video_window.rs` | 桌面子窗口，VPS 用不到 |
| `src-tauri/tauri.conf.json` | Tauri 配置，VPS 不用 |
| `src-tauri/capabilities/` | Tauri 权限配置，VPS 不用 |

### 完全不动的核心

```
src-tauri/src/layer/mod.rs
src-tauri/src/resolver/mod.rs
src-tauri/src/resolver/magnet.rs
src-tauri/src/resolver/m3u8.rs
src-tauri/src/resolver/webpage.rs
src-tauri/src/engine/mod.rs
src-tauri/src/db.rs
src-tauri/src/ai_strategy.rs (FROZEN)
```

---

## 五、注意事项

### 防火墙

```bash
# 确保 BT 监听端口开放（甲骨文控制台也需要开）
ufw allow 50051/tcp
```

### 内存

11GB 内存非常充裕。BT 缓存默认在 `/root/bt_cache/`，如果想限制：

```bash
# 在 systemd service 里加
Environment=LIBRQBIT_CACHE_SIZE_MB=2048
```

### 代理

这台 VPS 在境外，不需要配置任何代理。如果后续想用国内资源（如网页视频源提取），需单独配置。

---

*部署日期：2026-05-07*
*目标机器：甲骨文首尔 ARM Debian 12 | 146.56.133.171*
*域名：预设子域名 `bt-player.你的域名.com`*
