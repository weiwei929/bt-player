# Hermes Agent 集成方案

> 目标：将已部署的 Hermes Agent 接入 PureSource + BT-Player 架构
> Hermes Agent = 模型路由网关（OpenAI 兼容 API），主模型 MiniMax M2.7，兜底 Gemini 2.5 Flash

---

## 一、集成架构

Hermes Agent 和 PureSource 跑在同一台 VPS 上，通过 localhost 通信，不绕公网：

```
┌─────────────────────────────────────────────────────────┐
│  Oracle 首尔 ARM (Debian 12)                             │
│                                                          │
│  PureSource ──HTTP──→ Hermes Agent (localhost:PORT)       │
│  (9530)                                                   │
│       ↓                                                   │
│  Hermes Agent 做模型路由：                                  │
│    ├── MiniMax M2.7 → 主模型（中文场景强，日常任务）          │
│    └── Gemini 2.5 Flash → 兜底（复杂推理，Hermes 兜底）     │
│                                                          │
│  BT-Player 不直接调用 AI                                   │
│  BT-Player 只接收 PureSource 的提纯结果                     │
└─────────────────────────────────────────────────────────┘
```

PureSource 是 Hermes Agent 的唯一消费方。BT-Player 不直接调用 AI。

### Caddy 集成总览

```
Caddy (443)
  │
  ├── bt.mgtv.dev/*          → BT-Player / 前端
  ├── bt.mgtv.dev/purify/*   → PureSource (127.0.0.1:9530)
  ├── hermes.mgtv.dev/*      → Hermes Agent (127.0.0.1:PORT)
  │                            （Web UI + OpenAI 兼容 API）
  │
  │  PureSource 调用 Hermes 不走公网
  └── 直接 localhost:PORT → 零网络延迟
```

---

## 二、找到 Hermes Agent 的内部端口

从 Caddy 配置中找到 reverse_proxy 指向的内部端口：

```bash
# 查看 Caddy 配置
cat /etc/caddy/Caddyfile
# 会看到类似：
#   hermes.mgtv.dev {
#       reverse_proxy 127.0.0.1:8080
#   }
#                  ^^^^^^^^^^^^^
#                  这个就是内部端口
```

确认端口后验证 API：

```bash
# 假设端口是 8080
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-m2.7",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

> 端口确认后，后续所有配置中的 `{PORT}` 替换为实际值。

---

## 三、PureSource 的 AI 配置

### 3.1 配置文件

PureSource 只需要配一个 AI provider——Hermes Agent，由 Hermes 内部做模型路由：

```toml
# PureSource 配置 (config.toml)

[ai]

# Hermes Agent（模型路由网关）
[ai.hermes]
enabled = true
provider = "openai_compatible"
base_url = "http://127.0.0.1:{PORT}/v1"    # ← 填入实际端口
api_key = ""                                 # 本地调用无需 key
model = "minimax-m2.7"                       # 主模型
timeout_seconds = 60
max_retries = 2

# Gemini 兜底由 Hermes 内部处理，PureSource 无需感知
# PureSource 只认 Hermes 一个端点
```

**Hermes 侧的路由配置**（在 Hermes Agent 的配置中，非 PureSource）：

```yaml
# Hermes Agent 配置（示意，具体格式视 Hermes 实现而定）
models:
  - name: minimax-m2.7
    provider: minimax
    api_key: ${MINIMAX_API_KEY}
    priority: 1           # 主模型

  - name: gemini-2.5-flash
    provider: google
    api_key: ${GEMINI_API_KEY}
    priority: 2           # 兜底：主模型失败时自动切换
```

### 3.2 AI 任务路由策略

不再需要 PureSource 层做复杂的任务分流。Hermes Agent 统一接管，内部自动降级：

```
PureSource → Hermes Agent → MiniMax M2.7（所有任务）
                               │ 成功 → 返回
                               │ 失败（超时/限流/报错）
                               └──→ Gemini 2.5 Flash（自动兜底）
```

| AI 任务 | 模型 | 理由 |
|---------|------|------|
| **文件筛选**（广告/样本识别） | MiniMax M2.7 | 中文文件名理解强，量最大 |
| **正片推荐**（多文件中选主片） | MiniMax M2.7 | 文件名语义判断，M2.7 绰绰有余 |
| **元数据提取**（标题/年份/标签） | MiniMax M2.7 | 结构化输出，可 prompt 约束 |
| **多语言识别**（俄文站/英文等） | MiniMax M2.7 | M2.7 多语言能力良好 |
| **反盗链网页源识别** | MiniMax M2.7 → Gemini | 复杂 HTML 理解，M2.7 先试，失败 Gemini 兜底 |
| **合集/系列识别**（多部电影） | MiniMax M2.7 → Gemini | 同上 |
| **全任务通用兜底** | Gemini 2.5 Flash | Hermes Agent 内部自动切换 |

### 3.3 调用实现

```rust
// PureSource 只调用 Hermes Agent 一个端点

async fn ai_analyze(task: AiTask) -> Result<AiResult> {
    let client = reqwest::Client::new();
    let resp = client
        .post("http://127.0.0.1:{PORT}/v1/chat/completions")
        .json(&json!({
            "model": "minimax-m2.7",       // 指定主模型
            "messages": [{
                "role": "system",
                "content": task.system_prompt
            }, {
                "role": "user",
                "content": task.user_input
            }],
            "response_format": { "type": "json_object" }
        }))
        .timeout(Duration::from_secs(60))
        .send()
        .await?;

    let body = resp.json::<OpenAiResponse>().await?;
    let content = body.choices[0].message.content;
    Ok(serde_json::from_str(&content)?)
}

// 错误处理：PureSource 只处理 Hermes 完全不可用的情况
// Hermes 内部的模型降级（M2.7 → Gemini）由 Hermes 自行处理
```

---

## 四、PureSource 中替换 AI 调用的具体位置

### 4.1 替换点一览

```
PureSource Pipeline                    之前方案            现在
─────────────────                    ──────────          ──────────
① 网页源识别（HTML 分析）               Claude API         → Hermes ✓
② 文件筛选（广告/样本判断）             Claude API         → Hermes ✓
③ 正片推荐（多文件选主片）              Claude API         → Hermes ✓
④ 元数据提取（标题/描述/标签）          Claude API         → Hermes ✓
⑤ 合集/系列识别                        Claude API         → Hermes ✓
⑥ 资源去重（embedding 相似度匹配）     Claude API         → Hermes ✓
⑦ AI 编目置信度 < 0.7 二次确认         Claude API         → Hermes ✓
```

**所有 AI 调用全部走 Hermes Agent 一个端点**。PureSource 的代码大幅简化——不再需要多 provider 路由逻辑，只需配一个 base_url。

### 4.2 对解析器.md（浏览器代理）无影响

浏览器代理只负责"捕获→提交 URL 到 PureSource"，不直接调 AI。

---

## 五、模型能力说明

### MiniMax M2.7 为何适合这个场景

| 特性 | 对 PureSource 的价值 |
|------|---------------------|
| **中文理解强** | 论坛帖子、中文种子名、中文视频站页面——M2.7 天然优势 |
| **长上下文** | 处理大 HTML 页面、长文件列表 |
| **JSON 输出稳定** | PureSource 需要结构化输出，M2.7 的 JSON mode 成熟 |
| **推理成本低** | MiniMax 定价在国产模型中属于中等偏低 |
| **响应速度快** | M2.7 首 Token 延迟和生成速度均优秀 |

### Gemini 2.5 Flash 作为兜底的价值

| 场景 | Gemini 优势 |
|------|------------|
| M2.7 超时/限流 | 自动接管，不影响用户体验 |
| 极端复杂推理 | 多语言混合页面、混淆极深的网页结构 |
| 超长上下文需求 | Gemini 的长上下文能力业界领先 |

### 成本估算

```
MiniMax M2.7：  ~¥0.005/次（简单任务）~¥0.02/次（复杂任务）
Gemini 2.5 Flash：~$0.0001/次（极低，仅兜底时产生）

日调用 100 次，95 次 M2.7 + 5 次 Gemini：
  ≈ ¥0.5/天 ≈ ¥15/月

对比 Claude API 做同样 100 次：
  ≈ $2-3/天 ≈ $60-90/月

月省 ~$60-90，同时所有调用走 Hermes 统一端点
```

---

## 六、推荐配置

### 6.1 Hermes Agent 侧

1. 确认 MiniMax API Key 和 Gemini API Key 已配置
2. 确认模型路由逻辑：M2.7 失败时自动切到 Gemini
3. 绑定 `127.0.0.1`（已有 Caddy 管理公网，内部不需要暴露）
4. 确认支持 `response_format: { "type": "json_object" }`

### 6.2 PureSource 侧

```toml
[ai.hermes]
base_url = "http://127.0.0.1:{PORT}/v1"
model = "minimax-m2.7"
```

填好端口，部署，完事。

### 6.3 快速验证

```bash
# 1. 测试 Hermes → MiniMax M2.7
curl http://127.0.0.1:{PORT}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-m2.7",
    "messages": [
      {"role": "system", "content": "输出 JSON"},
      {"role": "user", "content": "判断文件名 Yanni.2024.4K.mkv 是否为视频正片"}
    ],
    "response_format": {"type": "json_object"}
  }'

# 2. 测试 Hermes → Gemini (兜底)
curl http://127.0.0.1:{PORT}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.5-flash",
    "messages": [{"role": "user", "content": "hello"}]
  }'

# 3. PureSource 端到端验证
curl http://127.0.0.1:9530/purify/resolve \
  -H "Content-Type: application/json" \
  -d '{"url": "magnet:?xt=urn:btih:08ada5a7...", "ai": true}'
```
