//! 源解析器注册链
//!
//! 采用"责任链"模式：按注册顺序依次尝试每个解析器，
//! 找到首个能处理且成功解析的返回结果。

mod magnet;
mod m3u8;
mod webpage;

pub use magnet::MagnetResolver;
pub use m3u8::M3u8Resolver;
pub use webpage::WebPageResolver;
use tracing::info;

use crate::layer::{LinkTier, SourceResolver};

/// 解析器链：按注册顺序尝试每个解析器
pub struct ResolverChain {
    resolvers: Vec<Box<dyn SourceResolver>>,
}

impl ResolverChain {
    pub fn new() -> Self {
        Self {
            resolvers: Vec::new(),
        }
    }

    /// 注册一个源解析器（先注册的优先匹配）
    pub fn register(&mut self, resolver: Box<dyn SourceResolver>) {
        self.resolvers.push(resolver);
    }

    /// 遍历所有注册解析器，返回第一个非 NotFound 的结果
    ///
    /// 如果某个解析器返回 NotFound，则继续尝试下一个。
    /// 如果所有解析器都无法处理，返回错误提示。
    pub async fn resolve(&self, input: &str) -> Result<(LinkTier, String), String> {
        let input = input.trim();
        for resolver in &self.resolvers {
            if resolver.can_handle(input) {
                info!(target: "resolver", input = %input, "尝试解析");
                match resolver.resolve(input).await {
                    Ok(LinkTier::NotFound { reason }) => {
                        info!(target: "resolver", input = %input, reason = %reason, "解析器返回 NotFound，尝试下一个");
                        continue;
                    }
                    Ok(tier) => {
                        info!(target: "resolver", "解析成功");
                        return Ok((tier, input.to_string()));
                    }
                    Err(e) => return Err(e),
                }
            }
        }
        Err("无法识别的链接类型，请输入 magnet: 或 .m3u8 地址".to_string())
    }
}
