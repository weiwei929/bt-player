//! 第四阶段：媒体库 - rusqlite 持久化
//!
//! 存储：磁链记录、播放历史、播放进度、AI 广告标记

use rusqlite::{params, Connection};
use serde::Serialize;
use std::path::Path;
use std::sync::Mutex;

pub struct DbState(pub Mutex<Connection>);

#[derive(Debug, Clone, Serialize)]
pub struct PlayHistoryEntry {
    pub id: i64,
    pub magnet: String,
    pub file_path: String,
    pub stream_url: String,
    pub played_at: String,
    pub progress_sec: f64,
    pub is_suspected_ad: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct CloudExportTask {
    pub id: i64,
    pub provider: String,
    pub resource_id: String,
    pub source_type: String,
    pub source_locator: String,
    pub status: String,
    pub error_message: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

pub fn init_db(path: &Path) -> Result<Connection, String> {
    let conn = Connection::open(path).map_err(|e| e.to_string())?;

    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            magnet TEXT NOT NULL,
            file_path TEXT NOT NULL,
            stream_url TEXT NOT NULL,
            played_at TEXT NOT NULL,
            progress_sec REAL DEFAULT 0,
            is_suspected_ad INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_play_history_played_at ON play_history(played_at);
        CREATE INDEX IF NOT EXISTS idx_play_history_magnet ON play_history(magnet);

        CREATE TABLE IF NOT EXISTS cloud_export_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_locator TEXT NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cloud_export_tasks_created_at ON cloud_export_tasks(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cloud_export_tasks_status ON cloud_export_tasks(status);
        "#,
    )
    .map_err(|e| e.to_string())?;

    Ok(conn)
}

pub fn insert_play_history(
    conn: &Connection,
    magnet: &str,
    file_path: &str,
    stream_url: &str,
    progress_sec: f64,
    is_suspected_ad: bool,
) -> Result<i64, String> {
    let now = chrono::Utc::now().format("%Y-%m-%d %H:%M:%S").to_string();
    conn.execute(
        "INSERT INTO play_history (magnet, file_path, stream_url, played_at, progress_sec, is_suspected_ad) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![magnet, file_path, stream_url, now, progress_sec, is_suspected_ad as i32],
    )
    .map_err(|e| e.to_string())?;
    Ok(conn.last_insert_rowid())
}

/// 更新指定 stream_url 的最近一条记录的播放进度
pub fn update_progress(conn: &Connection, stream_url: &str, progress_sec: f64) -> Result<(), String> {
    conn.execute(
        "UPDATE play_history SET progress_sec = ?1 WHERE id = (SELECT id FROM play_history WHERE stream_url = ?2 ORDER BY id DESC LIMIT 1)",
        params![progress_sec, stream_url],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

/// 获取指定 stream_url 的播放进度（最近一条）
pub fn get_progress(conn: &Connection, stream_url: &str) -> Result<Option<f64>, String> {
    let mut stmt = conn
        .prepare("SELECT progress_sec FROM play_history WHERE stream_url = ?1 ORDER BY id DESC LIMIT 1")
        .map_err(|e| e.to_string())?;
    let mut rows = stmt
        .query(params![stream_url])
        .map_err(|e| e.to_string())?;
    if let Some(row) = rows.next().map_err(|e| e.to_string())? {
        let sec: f64 = row.get(0).map_err(|e| e.to_string())?;
        Ok(Some(sec))
    } else {
        Ok(None)
    }
}

pub fn get_play_history(conn: &Connection, limit: i32) -> Result<Vec<PlayHistoryEntry>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id, magnet, file_path, stream_url, played_at, progress_sec, is_suspected_ad FROM play_history ORDER BY played_at DESC LIMIT ?1",
        )
        .map_err(|e| e.to_string())?;

    let rows = stmt
        .query_map(params![limit], |row| {
            Ok(PlayHistoryEntry {
                id: row.get(0)?,
                magnet: row.get(1)?,
                file_path: row.get(2)?,
                stream_url: row.get(3)?,
                played_at: row.get(4)?,
                progress_sec: row.get(5)?,
                is_suspected_ad: row.get::<_, i32>(6)? != 0,
            })
        })
        .map_err(|e| e.to_string())?;

    rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
}

pub fn create_cloud_export_task(
    conn: &Connection,
    provider: &str,
    resource_id: &str,
    source_type: &str,
    source_locator: &str,
) -> Result<i64, String> {
    let now = chrono::Utc::now().format("%Y-%m-%d %H:%M:%S").to_string();
    conn.execute(
        "INSERT INTO cloud_export_tasks (provider, resource_id, source_type, source_locator, status, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
        params![provider, resource_id, source_type, source_locator, "queued", now],
    )
    .map_err(|e| e.to_string())?;
    Ok(conn.last_insert_rowid())
}

pub fn update_cloud_export_task_status(
    conn: &Connection,
    id: i64,
    status: &str,
    error_message: Option<&str>,
) -> Result<(), String> {
    let now = chrono::Utc::now().format("%Y-%m-%d %H:%M:%S").to_string();
    conn.execute(
        "UPDATE cloud_export_tasks SET status = ?1, error_message = ?2, updated_at = ?3 WHERE id = ?4",
        params![status, error_message, now, id],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn list_cloud_export_tasks(conn: &Connection, limit: i32) -> Result<Vec<CloudExportTask>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id, provider, resource_id, source_type, source_locator, status, error_message, created_at, updated_at
             FROM cloud_export_tasks
             ORDER BY id DESC
             LIMIT ?1",
        )
        .map_err(|e| e.to_string())?;

    let rows = stmt
        .query_map(params![limit], |row| {
            Ok(CloudExportTask {
                id: row.get(0)?,
                provider: row.get(1)?,
                resource_id: row.get(2)?,
                source_type: row.get(3)?,
                source_locator: row.get(4)?,
                status: row.get(5)?,
                error_message: row.get(6)?,
                created_at: row.get(7)?,
                updated_at: row.get(8)?,
            })
        })
        .map_err(|e| e.to_string())?;

    rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
}

/// 取出一条 queued 任务并标记为 exporting（用于占位 worker）。
pub fn claim_next_cloud_export_task(conn: &mut Connection) -> Result<Option<CloudExportTask>, String> {
    let tx = conn.transaction().map_err(|e| e.to_string())?;
    let next = {
        let mut stmt = tx
            .prepare(
                "SELECT id, provider, resource_id, source_type, source_locator, status, error_message, created_at, updated_at
                 FROM cloud_export_tasks
                 WHERE status = 'queued'
                 ORDER BY id ASC
                 LIMIT 1",
            )
            .map_err(|e| e.to_string())?;

        let mut rows = stmt.query([]).map_err(|e| e.to_string())?;
        if let Some(row) = rows.next().map_err(|e| e.to_string())? {
            Some(CloudExportTask {
                id: row.get(0).map_err(|e| e.to_string())?,
                provider: row.get(1).map_err(|e| e.to_string())?,
                resource_id: row.get(2).map_err(|e| e.to_string())?,
                source_type: row.get(3).map_err(|e| e.to_string())?,
                source_locator: row.get(4).map_err(|e| e.to_string())?,
                status: row.get(5).map_err(|e| e.to_string())?,
                error_message: row.get(6).map_err(|e| e.to_string())?,
                created_at: row.get(7).map_err(|e| e.to_string())?,
                updated_at: row.get(8).map_err(|e| e.to_string())?,
            })
        } else {
            None
        }
    };

    if let Some(task) = &next {
        let now = chrono::Utc::now().format("%Y-%m-%d %H:%M:%S").to_string();
        tx.execute(
            "UPDATE cloud_export_tasks SET status = 'exporting', updated_at = ?1 WHERE id = ?2",
            params![now, task.id],
        )
        .map_err(|e| e.to_string())?;
    }

    tx.commit().map_err(|e| e.to_string())?;
    Ok(next)
}
