//! @FROZEN
//!
//! 第四阶段：AI 策略引擎 - Metadata 启发式识别
//!
//! 当前状态：已冻结，等待架构重构后改造为真正的源解析器。
//! 当前功能：关键词匹配标记疑似广告文件，属纯启发式规则。
//!
//! 未来方向（Phase 3）：改造为 WebPageResolver，解析含防盗链的网页视频源。
//!
//! 当 Metadata（文件名列表）进来时，识别包含 AD、赌博、扫码等关键字的片段，
//! 标记为「疑似广告」并存入数据库。

use serde::Serialize;

/// 单文件分析结果
#[derive(Debug, Clone, Serialize)]
pub struct FileAnalysis {
    pub index: usize,
    pub path: String,
    pub is_suspected_ad: bool,
    pub matched_keywords: Vec<String>,
}

/// 启发式关键词（可扩展）
const AD_KEYWORDS: &[&str] = &[
    "ad", "ads", "advertisement", "广告", "推广",
    "赌博", "博彩", "casino", "bet",
    "扫码", "二维码", "qrcode", "wechat",
    "预告", "trailer", "promo", "sample",
];

/// 分析文件路径，返回是否疑似广告及匹配关键词
pub fn analyze_file_path(path: &str) -> (bool, Vec<String>) {
    let lower = path.to_lowercase();
    let mut matched = Vec::new();

    for kw in AD_KEYWORDS {
        if lower.contains(kw) {
            matched.push((*kw).to_string());
        }
    }

    let is_suspected = !matched.is_empty();
    (is_suspected, matched)
}

/// 批量分析文件列表
pub fn analyze_files(paths: &[String]) -> Vec<FileAnalysis> {
    paths
        .iter()
        .enumerate()
        .map(|(idx, path)| {
            let (is_suspected_ad, matched_keywords) = analyze_file_path(path);
            FileAnalysis {
                index: idx,
                path: path.clone(),
                is_suspected_ad,
                matched_keywords,
            }
        })
        .collect()
}
