// BT-Player VPS 版入口

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use bt_player_lib::create_app;
use bt_player_lib::db::{claim_next_cloud_export_task, init_db, update_cloud_export_task_status, DbState};
use bt_player_lib::engine::{run_http_server, TorrentEngine};

const DEFAULT_STREAM_PORT: u16 = 9527;
const DEFAULT_API_PORT: u16 = 9528;
const DEFAULT_CACHE_DIR: &str = "/root/bt_cache";

fn env_u16(key: &str, default: u16) -> u16 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse::<u16>().ok())
        .unwrap_or(default)
}

fn env_bool(key: &str, default: bool) -> bool {
    std::env::var(key)
        .ok()
        .map(|v| {
            let v = v.trim().to_lowercase();
            matches!(v.as_str(), "1" | "true" | "yes" | "on")
        })
        .unwrap_or(default)
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "bt_player=info,librqbit=info".into()),
        )
        .init();

    let stream_port = env_u16("BT_PLAYER_STREAM_PORT", DEFAULT_STREAM_PORT);
    let api_port = env_u16("BT_PLAYER_API_PORT", DEFAULT_API_PORT);
    let cache_dir = PathBuf::from(
        std::env::var("BT_PLAYER_CACHE_DIR").unwrap_or_else(|_| DEFAULT_CACHE_DIR.to_string()),
    );
    let api_token = std::env::var("BT_PLAYER_API_TOKEN")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    let cloud_export_worker_enabled = env_bool("BT_PLAYER_CLOUD_EXPORT_WORKER_ENABLED", false);

    tokio::fs::create_dir_all(&cache_dir).await.unwrap();

    let db_path = cache_dir.join("bt_player.db");
    let conn = init_db(&db_path).expect("数据库初始化失败");
    let db = DbState(Mutex::new(conn));

    if cloud_export_worker_enabled {
        let db_path = db_path.clone();
        tokio::spawn(async move {
            info!("云导出占位 worker 已启用（不接入实时播放链路）");
            loop {
                match rusqlite::Connection::open(&db_path) {
                    Ok(mut conn) => match claim_next_cloud_export_task(&mut conn) {
                        Ok(Some(task)) => {
                            info!(
                                task_id = task.id,
                                provider = %task.provider,
                                resource_id = %task.resource_id,
                                "云导出任务已领取（占位逻辑）"
                            );
                            tokio::time::sleep(Duration::from_secs(1)).await;
                            if let Err(e) = update_cloud_export_task_status(&conn, task.id, "done", None) {
                                warn!(task_id = task.id, error = %e, "更新云导出任务状态失败");
                            } else {
                                info!(task_id = task.id, "云导出任务占位处理完成");
                            }
                        }
                        Ok(None) => {
                            tokio::time::sleep(Duration::from_secs(5)).await;
                        }
                        Err(e) => {
                            warn!(error = %e, "领取云导出任务失败");
                            tokio::time::sleep(Duration::from_secs(5)).await;
                        }
                    },
                    Err(e) => {
                        warn!(error = %e, "打开数据库失败，云导出 worker 暂停重试");
                        tokio::time::sleep(Duration::from_secs(5)).await;
                    }
                }
            }
        });
    } else {
        info!("云导出占位 worker 未启用（默认关闭）");
    }

    let engine = TorrentEngine::new(cache_dir.clone(), stream_port)
        .await
        .expect("BT 引擎初始化失败");
    let engine = Arc::new(engine);
    let session = engine.session();
    let cancel = CancellationToken::new();

    let cancel_clone = cancel.clone();
    let listen_addr: SocketAddr = ([127, 0, 0, 1], stream_port).into();
    tokio::spawn(async move {
        if let Err(e) = run_http_server(session, listen_addr, cancel_clone).await {
            eprintln!("HTTP API 服务异常: {:#}", e);
        }
    });

    let app = create_app(engine, db, api_token.clone());
    let addr = SocketAddr::from(([127, 0, 0, 1], api_port));
    info!("BT-Player API 服务启动: http://{}", addr);
    if api_token.is_some() {
        info!("API 鉴权已启用（Bearer 或 x-api-key）");
    } else {
        info!("API 鉴权未启用（仅限本机访问或反代层保护）");
    }

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
