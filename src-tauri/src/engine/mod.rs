//! BT-Player 核心引擎模块

use crate::ai_strategy;
use anyhow::{Context, Result};
use std::time::Duration;
use tokio::time::timeout;
use librqbit::{
    AddTorrent, AddTorrentOptions, AddTorrentResponse, Api,
    Session, SessionOptions,
    http_api::{HttpApi, HttpApiOptions},
};
use serde::Serialize;
use std::net::SocketAddr;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};
use url::Url;

#[derive(Debug, Clone, Serialize)]
pub struct FileEntry {
    pub index: usize,
    pub path: String,
    pub size_bytes: u64,
    pub size_mb: f64,
    pub stream_url: String,
    #[serde(default)]
    pub is_suspected_ad: bool,
}

pub struct TorrentEngine {
    session: Arc<Session>,
    stream_base_url: Url,
}

impl TorrentEngine {
    fn build_local_client() -> Result<reqwest::Client> {
        reqwest::Client::builder()
            .no_proxy()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .context("创建本地 HTTP 客户端失败")
    }

    pub async fn new(download_path: PathBuf, http_port: u16) -> Result<Self> {
        let cancel = CancellationToken::new();

        let opts = SessionOptions {
            cancellation_token: Some(cancel.clone()),
            disable_dht_persistence: false,
            fastresume: true,
            listen_port_range: Some(50051..50052),
            enable_upnp_port_forwarding: true,
            ..Default::default()
        };

        let session = Session::new_with_opts(download_path, opts)
            .await
            .context("初始化 Session 失败")?;

        info!("TorrentEngine 已初始化");

        let stream_base_url =
            Url::parse(&format!("http://127.0.0.1:{http_port}")).context("构造 stream base URL 失败")?;

        Ok(Self {
            session,
            stream_base_url,
        })
    }

    pub fn session(&self) -> Arc<Session> {
        self.session.clone()
    }

    pub fn stream_base_url(&self) -> &Url {
        &self.stream_base_url
    }

    pub async fn parse_magnet(&self, magnet: &str) -> Result<(String, usize)> {
        let extra_trackers = vec![
            "udp://tracker.opentrackr.org:1337/announce",
            "udp://opentracker.i2p.rocks:6969/announce",
            "http://tracker.openbittorrent.com:80/announce",
            "udp://open.stealth.si:80/announce",
            "udp://tracker.torrent.eu.org:451/announce",
            "udp://explodie.org:6969/announce",
            "udp://exodus.desync.com:6969/announce",
            "udp://tracker.tiny-vps.com:6969/announce",
        ];

        let mut magnet_url = magnet.to_string();
        for tr in extra_trackers {
            let encoded_tr = urlencoding::encode(tr);
            if !magnet_url.contains(&*encoded_tr) && !magnet_url.contains(tr) {
                magnet_url.push_str(&format!("&tr={}", encoded_tr));
            }
        }

        let add = AddTorrent::from_url(&magnet_url);
        info!("开始解析磁链");

        let session_clone = self.session.clone();

        let response = match timeout(
            Duration::from_secs(60),
            session_clone.add_torrent(add, Some(AddTorrentOptions {
                overwrite: true,
                ..Default::default()
            })),
        )
        .await
        {
            Ok(Ok(resp)) => resp,
            Ok(Err(e)) => {
                warn!("添加磁链失败: {:?}", e);
                anyhow::bail!("添加磁链失败: {:#}", e);
            }
            Err(_) => {
                anyhow::bail!("磁链解析超时（60s）");
            }
        };

        let torrent_id = match response {
            AddTorrentResponse::Added(id, handle) => {
                let info_hash = hex::encode(handle.info_hash().0);
                info!(info_hash = %info_hash, torrent_id = id, "新任务已添加");
                id
            }
            AddTorrentResponse::AlreadyManaged(id, _) => {
                info!(torrent_id = id, "磁链已存在");
                id
            }
            AddTorrentResponse::ListOnly(_resp) => {
                anyhow::bail!("意外 ListOnly 响应");
            }
        };

        let stream_url = format!("/stream/torrents/{}/stream/0", torrent_id);

        Ok((stream_url, torrent_id))
    }

    pub async fn get_file_tree_by_id(&self, torrent_id: usize) -> Result<Vec<FileEntry>> {
        let client = Self::build_local_client()?;
        let detail_url = self.stream_base_url.join(&format!("torrents/{}", torrent_id))?;
        let detail_res = client.get(detail_url).send().await.context("请求详情失败")?;
        if !detail_res.status().is_success() {
            anyhow::bail!("获取详情失败: {}", detail_res.status());
        }

        let detail: serde_json::Value = detail_res.json().await.context("解析详情失败")?;
        let empty: Vec<serde_json::Value> = vec![];
        let files = detail.get("files").and_then(|f: &serde_json::Value| f.as_array()).unwrap_or(&empty);

        let mut entries = Vec::with_capacity(files.len());
        for (idx, f) in files.iter().enumerate() {
            let path = f.get("name").and_then(|p: &serde_json::Value| p.as_str()).unwrap_or("?").to_string();
            let size = f.get("length").and_then(|l: &serde_json::Value| l.as_u64()).unwrap_or(0);
            let stream_url = format!("/stream/torrents/{}/stream/{}", torrent_id, idx);
            let is_suspected_ad = ai_strategy::analyze_file_path(&path).0;

            entries.push(FileEntry {
                index: idx, path, size_bytes: size,
                size_mb: size as f64 / 1024.0 / 1024.0,
                stream_url, is_suspected_ad,
            });
        }

        Ok(entries)
    }

    pub async fn get_local_file_path_by_id_and_index(&self, torrent_id: usize, file_idx: usize) -> Result<PathBuf> {
        let client = Self::build_local_client()?;

        let list_url = self.stream_base_url.join("torrents")?;
        let list_res = client.get(list_url).send().await.context("请求 torrents 列表失败")?;
        if !list_res.status().is_success() {
            anyhow::bail!("获取 torrents 列表失败: {}", list_res.status());
        }
        let list_body: serde_json::Value = list_res.json().await.context("解析 torrents 列表失败")?;
        let torrents = list_body
            .get("torrents")
            .and_then(|t| t.as_array())
            .cloned()
            .unwrap_or_default();
        let output_folder = torrents
            .iter()
            .find(|t| t.get("id").and_then(|v| v.as_u64()) == Some(torrent_id as u64))
            .and_then(|t| t.get("output_folder").and_then(|v| v.as_str()))
            .ok_or_else(|| anyhow::anyhow!("未找到 torrent 输出目录: {}", torrent_id))?;

        let detail_url = self.stream_base_url.join(&format!("torrents/{}", torrent_id))?;
        let detail_res = client.get(detail_url).send().await.context("请求详情失败")?;
        if !detail_res.status().is_success() {
            anyhow::bail!("获取详情失败: {}", detail_res.status());
        }
        let detail: serde_json::Value = detail_res.json().await.context("解析详情失败")?;
        let files = detail
            .get("files")
            .and_then(|f| f.as_array())
            .ok_or_else(|| anyhow::anyhow!("torrent 文件列表为空"))?;

        let file_name = files
            .get(file_idx)
            .and_then(|f| f.get("name"))
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("文件索引不存在: {}", file_idx))?;

        // --- Path Hardening Start ---
        if Path::new(output_folder).is_relative() {
            anyhow::bail!("output_folder must be absolute for torrent {} file {}", torrent_id, file_idx);
        }

        for component in Path::new(file_name).components() {
            match component {
                Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                    anyhow::bail!("invalid file_name component for torrent {} file {}", torrent_id, file_idx);
                }
                _ => {}
            }
        }

        let canonical_folder = Path::new(output_folder)
            .canonicalize()
            .map_err(|e| anyhow::anyhow!("canonicalize output_folder failed: {}", e))?;

        let full_path = canonical_folder.join(file_name);

        let canonical_full = full_path.canonicalize().map_err(|e| {
            anyhow::anyhow!("file not found or inaccessible: {}", e)
        })?;

        if !canonical_full.starts_with(&canonical_folder) {
            anyhow::bail!("path traversal detected for torrent {} file {}", torrent_id, file_idx);
        }

        if !canonical_full.is_file() {
            anyhow::bail!("not a regular file for torrent {} file {}", torrent_id, file_idx);
        }

        Ok(canonical_full)
        // --- Path Hardening End ---
    }

    pub async fn get_file_tree(&self) -> Result<Vec<FileEntry>> {
        let client = Self::build_local_client()?;
        let list_url = self.stream_base_url.join("torrents")?;
        let res = client.get(list_url).send().await.context("请求 torrents 列表失败")?;

        if !res.status().is_success() {
            anyhow::bail!("API 错误: {}", res.status());
        }

        let body: serde_json::Value = res.json().await.context("解析 JSON 失败")?;
        let torrents = body.get("torrents").and_then(|t| t.as_array()).cloned().unwrap_or_default();

        if torrents.is_empty() {
            return Ok(vec![]);
        }

        let latest_id = torrents
            .iter()
            .filter_map(|t| t.get("id").and_then(|v| v.as_u64()))
            .max()
            .unwrap_or(0) as usize;

        self.get_file_tree_by_id(latest_id).await
    }
}

pub async fn run_http_server(
    session: Arc<Session>,
    listen_addr: SocketAddr,
    cancel: CancellationToken,
) -> Result<()> {
    let api = Api::new(session.clone(), None);
    let http_api = HttpApi::new(api, Some(HttpApiOptions::default()));

    let listener = tokio::net::TcpListener::bind(listen_addr).await.context("绑定 HTTP 端口失败")?;
    let bound_addr = listener.local_addr().unwrap_or(listen_addr);
    info!(addr = %bound_addr, "HTTP 流服务已启动");

    let http_fut = http_api.make_http_api_and_run(listener, None);

    tokio::select! {
        _ = cancel.cancelled() => Ok(()),
        r = http_fut => r.map_err(|e| anyhow::anyhow!("HTTP 服务异常: {}", e)),
    }
}
