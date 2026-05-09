// BT-Player VPS 版 API 路由
// 声明所有子模块（lib 根目录）
pub mod engine;
pub mod db;
mod layer;
mod resolver;
mod ai_strategy;

use std::sync::{Arc, Mutex};

use axum::{
    body::Body,
    extract::{Path, State},
    http::{header, Request, StatusCode},
    middleware::{self, Next},
    routing::{get, post},
    response::Response,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use tracing::{info, warn};

use engine::{FileEntry, TorrentEngine};
use resolver::{MagnetResolver, M3u8Resolver, ResolverChain, WebPageResolver};
use layer::LinkTier;
use db::{get_play_history, list_cloud_export_tasks, DbState};
use tokio::sync::Mutex as TokioMutex;

fn torrent_id_from_stream_url(stream_url: &str) -> Option<usize> {
    stream_url
        .trim_matches('/')
        .split('/')
        .collect::<Vec<_>>()
        .as_slice()
        .windows(2)
        .find_map(|w| {
            if w[0] == "torrents" {
                w[1].parse::<usize>().ok()
            } else {
                None
            }
        })
}

/// 共享应用状态
#[derive(Clone)]
pub struct AppState {
    pub engine: Arc<TorrentEngine>,
    pub resolver: Arc<TokioMutex<ResolverChain>>,
    pub db: Arc<Mutex<rusqlite::Connection>>,
    pub api_token: Option<String>,
}

/// 构建 axum 路由
pub fn create_app(engine: Arc<TorrentEngine>, db: DbState, api_token: Option<String>) -> Router {
    let mut chain = ResolverChain::new();
    chain.register(Box::new(MagnetResolver::new(engine.clone())));
    chain.register(Box::new(M3u8Resolver));
    chain.register(Box::new(WebPageResolver));

    let state = AppState {
        engine,
        resolver: Arc::new(TokioMutex::new(chain)),
        db: Arc::new(db.0),
        api_token,
    };

    let api_router = Router::new()
        .route("/resolve", post(handle_resolve))
        .route("/torrents", get(handle_file_tree))
        .route("/local-stream/{torrent_id}/{file_idx}", get(handle_local_stream))
        .route("/history", get(handle_get_history).post(handle_save_record))
        // 云端导出是后续“缓存/归档/冷门兜底”层的占位接口，
        // 本 Phase 仅记录任务与状态，不接入任何实时播放依赖。
        .route("/cloud-exports", get(handle_list_cloud_exports).post(handle_create_cloud_export))
        .route("/cloud-exports/status", post(handle_update_cloud_export_status))
        .route_layer(middleware::from_fn_with_state(state.clone(), require_api_auth));

    Router::new()
        .route("/health", get(handle_health))
        .nest("/api", api_router)
        .layer(tower_http::cors::CorsLayer::permissive())
        .with_state(state)
}

async fn require_api_auth(
    State(state): State<AppState>,
    req: Request<Body>,
    next: Next,
) -> Result<axum::response::Response, StatusCode> {
    let Some(expected_token) = state.api_token.as_ref() else {
        return Ok(next.run(req).await);
    };

    let auth_header = req
        .headers()
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok());
    let api_key_header = req.headers().get("x-api-key").and_then(|v| v.to_str().ok());

    let bearer_ok = auth_header
        .and_then(|v| v.strip_prefix("Bearer "))
        .is_some_and(|token| token == expected_token);
    let api_key_ok = api_key_header.is_some_and(|token| token == expected_token);

    if bearer_ok || api_key_ok {
        Ok(next.run(req).await)
    } else {
        Err(StatusCode::UNAUTHORIZED)
    }
}

#[derive(Serialize)]
struct HealthResponse {
    status: &'static str,
}

async fn handle_health() -> Json<HealthResponse> {
    Json(HealthResponse { status: "ok" })
}

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

#[derive(Deserialize)]
pub struct CreateCloudExportRequest {
    pub provider: Option<String>,
    pub resource_id: String,
    pub source_type: String,
    pub source_locator: String,
}

#[derive(Serialize)]
pub struct CreateCloudExportResponse {
    pub id: i64,
    pub status: String,
}

#[derive(Deserialize)]
pub struct UpdateCloudExportStatusRequest {
    pub id: i64,
    pub status: String,
    pub error_message: Option<String>,
}

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

    let chain = state.resolver.lock().await;
    let (tier, _normalized_input) = chain.resolve(&url).await.map_err(|e| {
        (axum::http::StatusCode::BAD_REQUEST, Json(ErrorResponse { error: e }))
    })?;

    match tier {
        LinkTier::ReadyToPlay { stream_url, headers: _ } => {
            if stream_url.starts_with("/stream/torrents/") {
                let torrent_id = torrent_id_from_stream_url(&stream_url).ok_or((
                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                    Json(ErrorResponse { error: "无法从 stream_url 提取 torrent_id".into() }),
                ))?;

                let mut files = state.engine.get_file_tree_by_id(torrent_id).await.map_err(|e| {
                    (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
                })?;
                for file in &mut files {
                    file.stream_url = format!("/api/local-stream/{}/{}", torrent_id, file.index);
                }
                let default_file_index = files
                    .iter()
                    .filter(|f| !f.is_suspected_ad)
                    .max_by_key(|f| f.size_bytes)
                    .map(|f| f.index)
                    .unwrap_or(0);
                Ok(Json(ResolveResponse {
                    stream_url: format!("/api/local-stream/{}/{}", torrent_id, default_file_index),
                    files,
                    source_type: "magnet".into(),
                }))
            } else {
                Ok(Json(ResolveResponse {
                    stream_url: stream_url.clone(),
                    files: vec![FileEntry {
                        index: 0,
                        path: "HLS 流".into(),
                        size_bytes: 0,
                        size_mb: 0.0,
                        stream_url: stream_url.clone(),
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


fn parse_range_header(range_str: &str, total_len: usize) -> Result<Option<(usize, usize)>, &'static str> {
    if !range_str.starts_with("bytes=") {
        return Err("invalid range unit, expected 'bytes'");
    }
    let spec = &range_str[6..];

    if spec.contains(',') {
        return Err("multi-range not supported");
    }

    let parts: Vec<&str> = spec.split('-').collect();
    if parts.len() != 2 {
        return Err("invalid range format");
    }

    let start_str = parts[0];
    let end_str = parts[1];

    if start_str.is_empty() && end_str.is_empty() {
        return Err("invalid range format");
    }

    if start_str.is_empty() {
        let suffix = end_str.parse::<usize>().map_err(|_| "invalid suffix number")?;
        if suffix == 0 {
            return Err("suffix range must be > 0");
        }
        if suffix >= total_len {
            return Ok(Some((0, total_len - 1)));
        }
        let start = total_len - suffix;
        return Ok(Some((start, total_len - 1)));
    }

    if end_str.is_empty() {
        let start = start_str.parse::<usize>().map_err(|_| "invalid start number")?;
        if start >= total_len {
            return Err("range start >= file length");
        }
        return Ok(Some((start, total_len - 1)));
    }

    let start = start_str.parse::<usize>().map_err(|_| "invalid start number")?;
    let end = end_str.parse::<usize>().map_err(|_| "invalid end number")?;

    if start > end {
        return Err("range start > end");
    }
    if start >= total_len {
        return Err("range start >= file length");
    }

    let effective_end = std::cmp::min(end, total_len - 1);

    Ok(Some((start, effective_end)))
}

async fn handle_local_stream(
    Path((torrent_id, file_idx)): Path<(usize, usize)>,
    State(state): State<AppState>,
    req: Request<Body>,
) -> Result<Response, (axum::http::StatusCode, Json<ErrorResponse>)> {
    let file_path = state
        .engine
        .get_local_file_path_by_id_and_index(torrent_id, file_idx)
        .await
        .map_err(|e| {
            (
                axum::http::StatusCode::NOT_FOUND,
                Json(ErrorResponse {
                    error: format!("本地文件不存在: {}", e),
                }),
            )
        })?;

    let data = tokio::fs::read(&file_path).await.map_err(|e| {
        (
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: format!("读取文件失败: {}", e),
            }),
        )
    })?;
    let total_len = data.len();
    if total_len == 0 {
        return Err((
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: "文件为空".into(),
            }),
        ));
    }

    let content_type = match file_path.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase().as_str() {
        "mp4" => "video/mp4",
        "mkv" => "video/x-matroska",
        "webm" => "video/webm",
        "avi" => "video/x-msvideo",
        "mov" => "video/quicktime",
        _ => "application/octet-stream",
    };

    let range_header = req.headers().get(header::RANGE).and_then(|v| v.to_str().ok());

    if let Some(range_str) = range_header {
        match parse_range_header(range_str, total_len) {
            Ok(Some((start, end))) => {
                info!("local stream range: torrent={}, idx={}, range={}-{}, total={}", torrent_id, file_idx, start, end, total_len);
                let slice = &data[start..=end];
                let content_range = format!("bytes {}-{}/{}", start, end, total_len);
                return Response::builder()
                    .status(StatusCode::PARTIAL_CONTENT)
                    .header(header::ACCEPT_RANGES, "bytes")
                    .header(header::CONTENT_TYPE, content_type)
                    .header(header::CONTENT_LENGTH, slice.len().to_string())
                    .header(header::CONTENT_RANGE, content_range)
                    .body(Body::from(slice.to_vec()))
                    .map_err(|e| {
                        (StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: format!("build response failed: {}", e) }))
                    });
            },
            Ok(None) => {
                info!("local stream full: torrent={}, idx={}, total={}", torrent_id, file_idx, total_len);
            },
            Err(e) => {
                warn!("local stream bad range: torrent={}, idx={}, error={}", torrent_id, file_idx, e);
                return Response::builder()
                    .status(StatusCode::RANGE_NOT_SATISFIABLE)
                    .header(header::CONTENT_RANGE, format!("bytes */{}", total_len))
                    .header(header::ACCEPT_RANGES, "bytes")
                    .body(Body::empty())
                    .map_err(|e| {
                        (StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: format!("build response failed: {}", e) }))
                    });
            }
        }
    } else {
        info!("local stream full: torrent={}, idx={}, total={}", torrent_id, file_idx, total_len);
    }

    Response::builder()
        .status(StatusCode::OK)
        .header(header::ACCEPT_RANGES, "bytes")
        .header(header::CONTENT_TYPE, content_type)
        .header(header::CONTENT_LENGTH, total_len.to_string())
        .body(Body::from(data))
        .map_err(|e| {
            (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorResponse {
                    error: format!("构建响应失败: {}", e),
                }),
            )
        })
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

async fn handle_create_cloud_export(
    State(state): State<AppState>,
    Json(req): Json<CreateCloudExportRequest>,
) -> Result<Json<CreateCloudExportResponse>, (axum::http::StatusCode, Json<ErrorResponse>)> {
    if req.resource_id.trim().is_empty() || req.source_locator.trim().is_empty() || req.source_type.trim().is_empty() {
        return Err((
            axum::http::StatusCode::BAD_REQUEST,
            Json(ErrorResponse { error: "resource_id/source_type/source_locator 不能为空".into() }),
        ));
    }

    let provider = req.provider.unwrap_or_else(|| "pikpak".to_string());
    let conn = state.db.lock().map_err(|e| {
        (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
    })?;

    let id = db::create_cloud_export_task(
        &conn,
        &provider,
        req.resource_id.trim(),
        req.source_type.trim(),
        req.source_locator.trim(),
    )
    .map_err(|e| (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e })))?;

    Ok(Json(CreateCloudExportResponse {
        id,
        status: "queued".into(),
    }))
}

async fn handle_list_cloud_exports(
    State(state): State<AppState>,
) -> Result<Json<Vec<db::CloudExportTask>>, (axum::http::StatusCode, Json<ErrorResponse>)> {
    let conn = state.db.lock().map_err(|e| {
        (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
    })?;
    list_cloud_export_tasks(&conn, 100)
        .map(Json)
        .map_err(|e| (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e })))
}

async fn handle_update_cloud_export_status(
    State(state): State<AppState>,
    Json(req): Json<UpdateCloudExportStatusRequest>,
) -> Result<Json<()>, (axum::http::StatusCode, Json<ErrorResponse>)> {
    let status = req.status.trim();
    if req.id <= 0 || status.is_empty() {
        return Err((
            axum::http::StatusCode::BAD_REQUEST,
            Json(ErrorResponse { error: "id/status 参数非法".into() }),
        ));
    }

    let conn = state.db.lock().map_err(|e| {
        (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
    })?;
    db::update_cloud_export_task_status(&conn, req.id, status, req.error_message.as_deref())
        .map(|_| Json(()))
        .map_err(|e| (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e })))
}
