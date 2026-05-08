//! M3u8Resolver: HLS 流媒体链接解析器
//!
//! 检测 .m3u8 链接并返回直接可播放的流地址。
//! libmpv 原生支持 HLS 播放，无需额外转换。

use async_trait::async_trait;

use crate::layer::{LinkTier, SourceResolver};

pub struct M3u8Resolver;

#[async_trait]
impl SourceResolver for M3u8Resolver {
    fn can_handle(&self, input: &str) -> bool {
        let trimmed = input.trim().to_lowercase();
        trimmed.contains(".m3u8") || trimmed.ends_with("m3u8")
    }

    async fn resolve(&self, input: &str) -> Result<LinkTier, String> {
        Ok(LinkTier::ReadyToPlay {
            stream_url: input.trim().to_string(),
            headers: vec![],
        })
    }
}
