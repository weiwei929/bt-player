//! MagnetResolver: 磁力链接解析器
//!
//! 处理标准 magnet 链接 (magnet:?xt=urn:btih:...) 和裸 BTIH hash (40位hex)
//! 通过 librqbit BT 引擎解析磁链并返回 HTTP 流地址。

use std::sync::Arc;

use async_trait::async_trait;

use crate::engine::TorrentEngine;
use crate::layer::{LinkTier, SourceResolver};

pub struct MagnetResolver {
    engine: Arc<TorrentEngine>,
}

impl MagnetResolver {
    pub fn new(engine: Arc<TorrentEngine>) -> Self {
        Self { engine }
    }
}

#[async_trait]
impl SourceResolver for MagnetResolver {
    fn can_handle(&self, input: &str) -> bool {
        let trimmed = input.trim();
        // 标准 magnet 链接
        if trimmed.starts_with("magnet:") {
            return true;
        }
        // 40 位 hex = 裸 BTIH（BT 信息散列值）
        if trimmed.len() == 40 && trimmed.chars().all(|c| c.is_ascii_hexdigit()) {
            return true;
        }
        false
    }

    async fn resolve(&self, input: &str) -> Result<LinkTier, String> {
        let trimmed = input.trim();
        let magnet_url = if trimmed.starts_with("magnet:") {
            trimmed.to_string()
        } else {
            // 裸 hash → 自动补全 magnet URI
            format!("magnet:?xt=urn:btih:{}", trimmed)
        };

        let (stream_url, _torrent_id) = self
            .engine
            .parse_magnet(&magnet_url)
            .await
            .map_err(|e| format!("磁链解析失败: {}", e))?;

        Ok(LinkTier::ReadyToPlay {
            stream_url,
            headers: vec![],
        })
    }
}
