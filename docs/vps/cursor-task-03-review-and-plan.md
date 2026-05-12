# Cursor 任务 03：消化 v0.3 修订方案，给出执行计划

> 架构师：本地 Codex
> 阶段：谋（不写代码，只出执行计划）
> 日期：2026-05-12

---

## 背景

你之前审阅过的 `架构设计小结.md` 和 v0.3 方案，我和 Codex 已经对齐修订完毕。完整版在：

**`/root/bt-player-new/docs/design/PureSource v0.3 资源探测与视频图书馆方案.md`**

你的六条评审意见（bt-probe 独立服务、yt-dlp 异步、ResourceStage 扩展、结构化字段、promote 放宽、凭据隔离）已全部采纳并写入修订版。

---

## 你的任务

请**不要写代码**。按以下步骤消化方案，然后给出执行计划：

### 第一步：阅读以下文件

1. `/root/bt-player-new/docs/design/PureSource v0.3 资源探测与视频图书馆方案.md` — 修订后的完整方案
2. `/opt/puresource-playlist/app/models.py` — 当前数据模型
3. `/opt/puresource-playlist/app/main.py` — 当前端点
4. `/opt/puresource-playlist/app/static/app.js` — 当前前端

### 第二步：回答以下问题

1. **契约变更影响评估**
   - `ResourceStage` 新增 3 个枚举值后，现有 `data/resources.json` 中的存量数据能否正常加载？
   - `ResourceRecord` 新增 8 个字段后，现有的 enrich / probe / promote 端点是否需要改动？
   - 前端 stage tabs 和 actionBtn 逻辑需要改哪些地方？

2. **bt-probe 独立服务的技术选型建议**
   - 用什么语言/框架？（Python + FastAPI 复用技术栈，还是更轻量的方案？）
   - 与主服务之间的通信协议？（REST JSON？是否需要鉴权？）
   - qBittorrent Web API 的凭据如何安全注入？

3. **yt-dlp 异步实现方案**
   - 使用 `threading.Thread` + subprocess，还是 `asyncio` + subprocess？
   - 后台任务的结果如何回写到 store？（直接写 `data/resources.json`，还是通过回调？）
   - 需要新增哪些错误处理？（yt-dlp 未安装、超时、输出非 JSON、站点不支持）

4. **实施顺序建议**
   - v0.3 方案分了 4 个 Step。你建议的顺序是否需要调整？
   - 每个 Step 内，先改模型还是先改端点？先改后端还是先改前端？
   - 是否建议将某个 Step 拆得更细？

### 第三步：产出执行计划

按以下格式输出：

```
## Step 1: [步骤名]

### 1.1 修改文件清单
- /opt/puresource-playlist/app/models.py — 具体改动点
- ...

### 1.2 执行细节
每个文件的改动范围和注意事项

### 1.3 验收标准
具体的 curl 命令和预期输出

### 1.4 风险点
可能的坑和应对方案

## Step 2: ...
```

---

## 约束

- **不写代码**。这是谋的阶段。
- 如果方案中有什么你觉得不可行或有更好方案的点，**先提出来讨论**，不要在执行计划里悄悄改。
- 执行计划要具体到文件和改动点级别，不能只说"改 models.py"。
- 预计工时：这个执行计划本身应该在 30 分钟内完成（只读代码 + 写计划，不写代码）。
