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
    extract::State,
    http::{Request, StatusCode},
    middleware::{self, Next},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};

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

                let files = state.engine.get_file_tree_by_id(torrent_id).await.map_err(|e| {
                    (axum::http::StatusCode::INTERNAL_SERVER_ERROR, Json(ErrorResponse { error: e.to_string() }))
                })?;
                Ok(Json(ResolveResponse {
                    stream_url,
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
