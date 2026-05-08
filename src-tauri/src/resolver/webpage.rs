//! WebPageResolver: 网页链接视频源解析器
//!
//! 处理包含视频播放器的网页链接（非直接的 m3u8/mp4 链接），
//! 通过抓取页面 HTML 并提取视频源地址，支持防盗链 Referer 传递。

use async_trait::async_trait;
use scraper::{Html, Selector};
use tracing::{info, warn};

use crate::layer::{LinkTier, SourceResolver};

/// 浏览器 User-Agent，避免被 CDN/网站拒绝
const USER_AGENT: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

/// HTTP 客户端（带默认超时和 UA）
fn build_client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .user_agent(USER_AGENT)
        .redirect(reqwest::redirect::Policy::limited(10))
        .build()
        .map_err(|e| format!("创建 HTTP 客户端失败: {}", e))
}

pub struct WebPageResolver;

#[async_trait]
impl SourceResolver for WebPageResolver {
    fn can_handle(&self, input: &str) -> bool {
        let trimmed = input.trim().to_lowercase();

        // 仅处理 http/https 链接
        if !(trimmed.starts_with("http://") || trimmed.starts_with("https://")) {
            return false;
        }

        // 跳过已经是直接媒体链接的（由其他解析器处理）
        if trimmed.contains(".m3u8") {
            return false;
        }

        true
    }

    async fn resolve(&self, input: &str) -> Result<LinkTier, String> {
        let page_url = input.trim().to_string();

        info!(target: "webpage_resolver", url = %page_url, "开始解析网页视频源");

        let client = build_client()?;

        // 抓取页面 HTML
        let response = client
            .get(&page_url)
            .send()
            .await
            .map_err(|e| format!("请求页面失败: {}", e))?;

        if !response.status().is_success() {
            return Err(format!("页面请求失败: HTTP {}", response.status()));
        }

        let html_text = response
            .text()
            .await
            .map_err(|e| format!("读取页面内容失败: {}", e))?;

        // 从 HTML 中提取视频源
        let video_url = extract_video_source(&html_text, &page_url)?;

        info!(target: "webpage_resolver", video_url = %video_url, "成功提取视频源");

        Ok(LinkTier::ReadyToPlay {
            stream_url: video_url,
            headers: vec![("Referer".to_string(), page_url)],
        })
    }
}

/// 从 HTML 中提取视频源地址
///
/// 按优先级尝试以下策略：
/// 1. HTML5 `<video>` / `<source>` 标签
/// 2. 页面嵌入的 iframe 视频播放器
/// 3. JavaScript 变量中的视频地址（如 videoUrl、video_url、playUrl 等）
/// 4. 页面中直接引用的 .m3u8 或 .mp4 链接
fn extract_video_source(html: &str, page_url: &str) -> Result<String, String> {
    let document = Html::parse_document(html);

    // 策略 1: <video src="..."> 或 <video><source src="..."></video>
    if let Some(url) = extract_from_video_tag(&document, page_url) {
        return Ok(url);
    }

    // 策略 2: iframe src 包含视频播放器
    if let Some(url) = extract_from_iframe(&document, page_url) {
        return Ok(url);
    }

    // 策略 3: JavaScript 变量中的视频地址
    if let Some(url) = extract_from_js_vars(html, page_url) {
        return Ok(url);
    }

    // 策略 4: 页面中直接引用的流媒体链接
    if let Some(url) = extract_media_urls(html, page_url) {
        return Ok(url);
    }

    Err("未能从页面中提取到视频源".to_string())
}

/// 策略 1：从 HTML5 <video> / <source> 标签提取
fn extract_from_video_tag(document: &Html, page_url: &str) -> Option<String> {
    // <video src="...">
    let video_selector = Selector::parse("video[src]").ok()?;
    for element in document.select(&video_selector) {
        let src = element.value().attr("src")?;
        let absolute = resolve_url(src, page_url);
        warn!(target: "webpage_resolver", "发现 <video src={}>", absolute);
        return Some(absolute);
    }

    // <video><source src="..."></video>
    let source_selector = Selector::parse("video source[src]").ok()?;
    for element in document.select(&source_selector) {
        let src = element.value().attr("src")?;
        let absolute = resolve_url(src, page_url);
        warn!(target: "webpage_resolver", "发现 <source src={}>", absolute);
        return Some(absolute);
    }

    None
}

/// 策略 2：从 iframe 提取
fn extract_from_iframe(document: &Html, page_url: &str) -> Option<String> {
    let iframe_selector = Selector::parse("iframe[src]").ok()?;
    for element in document.select(&iframe_selector) {
        let src = element.value().attr("src")?;
        let lower = src.to_lowercase();
        // 跳过非视频类 iframe（广告、社交分享等）
        if lower.contains("video") || lower.contains("player") || lower.contains("embed")
            || lower.contains("m3u8") || lower.contains("mp4")
        {
            let absolute = resolve_url(src, page_url);
            warn!(target: "webpage_resolver", "发现视频 iframe: {}", absolute);
            return Some(absolute);
        }
    }
    None
}

/// 策略 3：从 JavaScript 变量中提取视频地址
///
/// 查找常见模式：
/// - videoUrl: "..." 或 videoUrl: '...'
/// - "videoUrl":"..."
/// - "video_url":"..."
/// - playUrl: "..."
/// - url: "....m3u8"
/// - "src":"....m3u8"
fn extract_from_js_vars(html: &str, page_url: &str) -> Option<String> {
    let patterns = [
        // videoUrl: '...' 或 "videoUrl":"..."
        r#"videoUrl["'\s:]+["']([^"']+\.(?:m3u8|mp4))["']"#,
        // video_url: '...'
        r#"video_url["'\s:]+["']([^"']+\.(?:m3u8|mp4))["']"#,
        // playUrl: '...'
        r#"playUrl["'\s:]+["']([^"']+\.(?:m3u8|mp4))["']"#,
        // url: "...m3u8" (within script context)
        r#"["']url["']\s*:\s*["']([^"']+\.m3u8[^"']*)["']"#,
        // src: "...m3u8"
        r#"["']src["']\s*:\s*["']([^"']+\.(?:m3u8|mp4)[^"']*)["']"#,
        // file: "...m3u8" (JW Player format)
        r#"["']file["']\s*[:=]\s*["']([^"']+\.(?:m3u8|mp4)[^"']*)["']"#,
        // link: "...m3u8"
        r#"["']link["']\s*[:=]\s*["']([^"']+\.(?:m3u8|mp4)[^"']*)["']"#,
    ];

    for pattern in &patterns {
        if let Ok(re) = regex::Regex::new(pattern) {
            if let Some(cap) = re.captures(html) {
                let url = cap.get(1).unwrap().as_str().to_string();
                // 跳过空或过短的 URL
                if url.len() > 5 {
                    let absolute = resolve_url(&url, page_url);
                    warn!(target: "webpage_resolver", "从 JS 变量提取到: {}", absolute);
                    return Some(absolute);
                }
            }
        }
    }
    None
}

/// 策略 4：在页面文本中搜索流媒体链接
fn extract_media_urls(html: &str, page_url: &str) -> Option<String> {
    let patterns = [
        // 引号包裹的 m3u8 URL
        r#"["']([^"']*\.m3u8[^"']*)["']"#,
        // 引号包裹的 mp4 URL（较长，避免片段）
        r#"["']([^"']{20,}\.mp4[^"']*)["']"#,
    ];

    for pattern in &patterns {
        if let Ok(re) = regex::Regex::new(pattern) {
            for cap in re.captures_iter(html) {
                let url = cap.get(1).unwrap().as_str();
                let absolute = resolve_url(url, page_url);
                // 跳过 data: URIs 和空字符串
                if absolute.starts_with("http://") || absolute.starts_with("https://") {
                    warn!(target: "webpage_resolver", "从页面提取到媒体链接: {}", absolute);
                    return Some(absolute);
                }
            }
        }
    }
    None
}

/// 解析相对 URL 为绝对 URL
fn resolve_url(url: &str, page_url: &str) -> String {
    if url.starts_with("http://") || url.starts_with("https://") {
        return url.to_string();
    }

    if url.starts_with("//") {
        // 协议相对 URL
        if page_url.starts_with("https://") {
            return format!("https:{}", url);
        }
        return format!("http:{}", url);
    }

    // 相对路径：基于页面 URL 的目录
    if let Some(base_end) = page_url.rfind('/') {
        if base_end > 8 {
            // 跳过 http:// 中的 //
            let base = &page_url[..=base_end];
            let clean_url = url.trim_start_matches("./").trim_start_matches('/');
            return format!("{}{}", base, clean_url);
        }
    }

    url.to_string()
}
