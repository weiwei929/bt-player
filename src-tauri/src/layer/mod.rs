//! 四层架构定义
//!
//! 导入层 → 解析层 → 处理层 → 呈现层
//!
//! 本模块定义了各层之间的核心数据类型和接口。

/// 链接处理结果分层
///
/// 每个 Resolver 解析输入后返回这四种结果之一，
/// 上层根据分层决定后续处理策略。
#[derive(Debug)]
pub enum LinkTier {
    /// Tier 1: 找到源，可直接播放
    ReadyToPlay {
        stream_url: String,
        /// 播放时需要携带的 HTTP 头（如 Referer、Cookie 等防盗链参数）
        headers: Vec<(String, String)>,
    },
    /// Tier 2: 找到源，需要缓存/下载后再播放
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

/// 源查找器（导入层核心接口）
///
/// 每个协议（magnet、m3u8、网页等）实现此 trait，
/// 注册到 ResolverChain 后按顺序尝试。
#[async_trait::async_trait]
pub trait SourceResolver: Send + Sync {
    /// 判断此输入是否属于本解析器处理范围
    fn can_handle(&self, input: &str) -> bool;

    /// 解析输入，返回分层结果
    async fn resolve(&self, input: &str) -> Result<LinkTier, String>;
}
