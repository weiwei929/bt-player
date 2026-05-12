# Cursor Task 03：PureSource v0.3 方案评审 + 执行计划（只读、纯"谋"阶段）

> 角色：评审者 + 规划者
> 阶段：**纯"谋"，禁止"动"。本轮不允许修改任何文件、不允许新建文件、不允许执行迁移脚本、不允许跑测试以外的副作用命令。**
> 交付物：一份评审结论 + 一份可执行的实施计划，等用户审过后再切到执行阶段。

---

## 一、你的角色与硬约束

1. 你这一轮的工作是**读懂、对账、规划**，不是写代码。
2. 整个会话里，你**不得**：
   - 修改、新建、删除任何源码 / 配置 / 文档。
   - 调用 `git commit`、`git add`、`pip install`、`npm install` 等任何会改变工作区或环境的命令。
   - 启动 / 重启 systemd 服务、qBittorrent、Caddy 等任何长期进程。
3. 允许的操作：读文件、用 ripgrep/glob 搜索、跑 `pytest --collect-only` 这类**只读**命令、查看 `git status / git log / git diff`。
4. 如果你认为方案某处有问题，**先在评审里写出来**，禁止在执行计划里"悄悄按你认为对的方向改"。任何与原方案的偏离都必须在"分歧与建议"一节显式列出，并标注"待用户裁决"。

---

## 二、必读材料

请按顺序通读：

1. `docs/design/PureSource v0.3 资源探测与视频图书馆方案.md`（本轮评审主对象）
2. `docs/design/架构设计小结.md`（v0.3 的上位架构。重点看 §2.3.2 关于"PureSource 主服务不接 DHT/peer/qBittorrent"的红线，以及 §2.3.3 关于 PikPak/油猴 URL 的实证结论）
3. `puresource-playlist/app/models.py`（`ResourceStage` / `ResourceStatus` / `ResourceRecord` / `MagnetInfo` 的现有契约）
4. `puresource-playlist/app/main.py`（`/intake`、`/tasks`、`/tasks/{id}/probe`、`/tasks/{id}/enrich`、`/tasks/{id}/promote` 的现有实现）
5. `puresource-playlist/app/probe.py`（HTTP probe 的边界与超时设定）
6. `puresource-playlist/app/playlist.py` + `puresource-playlist/app/store.py`（M3U 输出与持久化）
7. `puresource-playlist/app/static/`（前端工作台现状）
8. `puresource-playlist/tests/`（已有测试覆盖面）

读完后，先在回复里用 1 段话告诉我："我已读完上述 N 个文件，对 v0.3 方案与现有代码的对账完成。"再进入下一节。

---

## 三、必须回答的四个问题

每个问题独立成节，**先给结论再给依据**。每节末尾必须有一个明确的"建议方向 + 待用户裁决项"。

### Q1. 契约兼容性

v0.3 方案要新增 `extract` 与 `bt-probe` 两个探针，并要展示文件树 / 候选 URL / 复检状态。

请回答：

- 现有 `ResourceStage` 枚举（`pending | probing | playable | external_ready | failed`）是否够用？如果不够，**列出最小新增枚举集合**及理由。
- 现有 `ResourceRecord` / `MagnetInfo` 字段是否够承载文件树和 yt-dlp 候选？如果不够，**列出最小字段扩展**（字段名、类型、上限、是否可选、是否参与持久化）。
- 现有 `promote` 校验只允许 `stage in {playable, external_ready}`。bt-probe 完成后用户拿到 PikPak / 油猴 URL 想 promote 时，stage 仍是 `pending`。请给出**至少两种解法**及各自影响面，并给出你的推荐。
- 列出所有需要做"向后兼容旧 `data/resources.json`"处理的字段，以及兼容策略（默认值 / 迁移脚本 / 读时补齐）。

### Q2. bt-probe 技术选型

架构小结明确写过红线："不应在 PureSource 主服务里默认接入 DHT、peer、libtorrent、qBittorrent 或 rqbit"。

请回答：

- 你怎么理解这条红线在 v0.3 语境下的边界？方案里把 `POST /tasks/{id}/bt-probe` 直接做进 `puresource-playlist`，**算不算违反**？给出明确判断（是 / 否 / 部分）并说明理由。
- 给出**两套以上**实现选项的对比表（最少包含：A. 主服务直连 qBittorrent Web API；B. 独立 `puresource-btprobe` 子服务；可加 C. 用 librqbit 进程内库；D. 完全外置成 CLI 工具）。对比维度至少包括：是否守红线、运维复杂度、失败隔离、上线时长、未来换 rqbit 的成本。
- 给出**你的推荐**及一句话理由。
- 不论选哪种，列出 **qBittorrent Web API 凭据**与 **VPS 出口 IP 暴露**这两件事的处置方案。

### Q3. yt-dlp 异步方案

`yt-dlp --dump-json` 在常见站点上耗时 5–30s，反爬场景可能 60s+。`puresource-playlist` 现有 probe 是 5s 同步上限，FastAPI 端点不能被这种耗时阻塞。

请回答：

- 给出**至少三套**异步方案的对比（例：FastAPI `BackgroundTasks` / `asyncio.create_task` + 内存任务表 / 独立 worker 进程 + 文件队列 / Celery / RQ 之类）。对比维度：实现复杂度、对现有代码侵入度、断电恢复行为、能否限并发、能否安全 kill 超时任务。
- 给出**你的推荐**及理由（注意这是 v0.3，不应过度工程化）。
- 设计 `extract` 的状态轮询契约：用户调一次创建任务，前端怎么知道结果回来了？给出端点形态与 stage 流转。
- `cookies_file` 路径如何避免"读取任意文件"漏洞？给出最小白名单方案。
- yt-dlp 进程的硬超时、内存上限、并发上限分别建议设多少？给出数字与理由。

### Q4. 实施顺序

v0.3 §六给了 Step 1–4，但每步只有"1–2 天"的时长估计，没有依赖关系、没有验收标准。

请回答：

- 用一张依赖图（文字表示即可）说清楚 4 个 Step 的依赖与可并行段。
- 对每个 Step 给出**显式验收判据**（一段 happy path 描述，必须包含可观察的接口调用与预期结果）。
- 指出方案里"哪些事可以推迟到 v0.4"，理由是"v0.3 主线不需要 / 风险高 / 与红线冲突"。
- 给出推荐的**第一周可落地范围**（3–5 天），定义清楚 in-scope 与 out-of-scope。

---

## 四、输出格式要求

按以下结构组织你的回复，缺一不可：

```
0. 已读文件清单
1. 总体评价（不超过 5 句）
2. 与原方案的分歧与建议（每条：原方案怎么写 → 你建议怎么改 → 影响面 → 待用户裁决/不必裁决）
3. Q1 契约兼容性（含所有要求子项）
4. Q2 bt-probe 技术选型（含对比表与推荐）
5. Q3 yt-dlp 异步方案（含对比表与推荐）
6. Q4 实施顺序（含依赖图、验收判据、可推迟项、第一周范围）
7. 执行计划（详见下面的"细化要求"）
8. 等待用户裁决的 N 项清单
```

### "执行计划"细化要求

执行计划必须**具体到文件与改动点级别**，而不是"新增 yt-dlp 模块"这种粗描述。每条任务遵循以下格式：

```
任务编号：T-<阶段>-<序号>，例如 T-1-01
标题：一句话
触达文件：
  - puresource-playlist/app/models.py（新增字段 X / 修改枚举 Y）
  - puresource-playlist/app/main.py（新增端点 Z）
  - puresource-playlist/app/static/app.js（新增按钮 W）
契约影响：是否破坏现有 API / 是否破坏 data/resources.json 兼容性
依赖：T-x-yy（必须先完成的任务）
验收：调用 `curl -X POST ...` 返回 ...，前端点击 ... 显示 ...
预估工时：<小时>
风险：一句话
```

---

## 五、分歧与裁决规则

1. 你**可以**反对方案的任何一点，但必须把反对意见放进"§2 分歧与建议"，并在执行计划里**保留原方案路径**，同时在该任务上加 `⚠️ 待裁决：见 §2 第 N 条`。
2. 你**不可以**在执行计划里直接按你的意见改，让我以为方案被你照搬了。
3. 如果你发现方案与架构小结红线冲突，必须在"§2 分歧与建议"显式列出，**不允许你单方面声明"红线已经被 v0.3 默认推翻"**。

---

## 六、本轮"完成"的定义

当且仅当下列条件全部满足时，视为本轮完成：

1. 0–8 节全部输出。
2. Q1–Q4 每个问题都有明确推荐 + 至少一项"待用户裁决"。
3. 执行计划里每条任务都符合 §四的细化格式。
4. 没有任何文件被修改、新建、删除。
5. 你在回复末尾明确写一句："本轮纯谋阶段已完成，等待用户审阅后切换到执行阶段。"

---

## 七、本轮**不要**做的事

- 不要写代码片段超过 5 行。需要展示契约时用 schema/伪代码，不要给 import 完整的实现。
- 不要画 ASCII 大图，文字依赖图就够。
- 不要去网上查 yt-dlp / qBittorrent 的最新版本号，用 README 已有版本即可；版本敏感的事项写"待 Step X 时确认"。
- 不要主动开 canvas 或额外文档。所有结论写在对话回复里。
