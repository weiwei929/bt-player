# Cursor Task 04：PureSource v0.4 生产部署 + 生命周期闭环（只读、纯"谋"阶段）

> 角色：评审者 + 规划者
> 阶段：**纯"谋"，禁止"动"。本轮不允许修改任何文件、不允许新建文件、不允许执行 cutover、不允许跑测试以外的副作用命令。**
> 交付物：一份评审结论 + 一份可执行的 v0.4a / v0.4b 实施计划，等用户审过后再切到执行阶段。
> 上游：v0.3（T-0/T-1/T-2/T-3）已在开发实例 :8190 全部跑通，发布文档 `puresource-playlist/docs/vps/puresource-playlist-v0.3-cutover-checklist.md` 已落地，未切生产。

---

## 一、你的角色与硬约束

1. 你这一轮的工作是**读懂 v0.3 现状、评审 cutover 可行性、规划 v0.4**，不是写代码也不是切生产。
2. 整个会话里，你**不得**：
   - 修改、新建、删除任何源码 / 配置 / 文档（包括 systemd unit、Caddyfile、cookies 目录等）。
   - 调用 `git commit`、`git add`、`pip install`、`apt install`、`npm install` 等任何会改变工作区或环境的命令。
   - 启动 / 重启 / 安装任何 systemd 服务（`puresource-playlist` / `puresource-extract-worker` / `puresource-btprobe` / `qbittorrent-nox` / Caddy 等）。
   - 在生产 VPS 上执行任何写操作；只允许从开发工作区读文件 + 跑只读探测命令。
   - 真去装 qBittorrent 或起 worker 验证；任何"真实集成实验"都视为"动"，留到执行阶段。
3. 允许的操作：读文件、用 ripgrep/glob 搜索、跑 `pytest --collect-only` 这类**只读**命令、查看 `git status / git log / git diff`、对生产 VPS 跑只读探测（`systemctl status`、`ss -lnt`、`curl -sf $HOST/health` 等观察类命令）。
4. 与 cursor-task-03 同款规则：如果你认为 v0.3 cutover checklist 或本任务的 v0.4 分段有问题，**先在评审里写出来**，禁止在执行计划里"悄悄按你认为对的方向改"。所有偏离写到"§2 分歧与建议"并标 `⚠️ 待裁决`。

---

## 二、v0.4 的边界（用户已定调，不需要你再决定）

本轮**不接受**你重新设计 v0.4 的分段或纳入更多内容。下列定调由用户在 cursor-task-03 review 之后给出，按此推进：

| 子段 | 范围 | 不属于范围 |
|------|------|-----------|
| **v0.4a** | 把 v0.3 切到生产 :8090：systemd + Caddy + 真实 qBittorrent + 切流量 | 任何新功能开发 |
| **v0.4b** | 生命周期闭环：`expires_at` 复检 worker + 前端过期/即将过期标记 | UI 重设计、PotPlayer 订阅分桶 |
| **v0.5（不在本轮范围）** | 目录管理、标签/分组、搜索、批量操作 | n/a |

允许的偏离：你可以建议 v0.4a / v0.4b 内部任务的拆分粒度、顺序、依赖；但**不允许**把 v0.5 的内容拉进 v0.4，也不允许把 v0.4 的内容推迟到 v0.5。

---

## 三、必读材料

请按顺序通读。读完后用 1 段话回报："我已读完上述 N 个文件，对 v0.3 现状与 v0.4 范围的对账完成。"

### 3.1 v0.3 现状（必读，用以判断 cutover 可行性）

1. `puresource-playlist/docs/vps/puresource-playlist-v0.3-cutover-checklist.md`（v0.4a 的主对象；791 行，13 章；你要评审它**是否真的可以一把切完**）
2. `puresource-playlist/docs/vps/puresource-playlist-cutover-checklist.md`（v0.2 切生产的实际经验，参考其执行风格与坑警告）
3. `puresource-playlist/app/main.py`（确认 v0.3 端点全部到位：`/tasks/{id}/extract`、`/tasks/{id}/bt-probe`、`/internal/tasks/{id}/extract-result`、`/internal/tasks/{id}/bt-probe-result`、`/tasks/{id}/promote` 白名单扩展）
4. `puresource-playlist/app/models.py`（确认 `ResourceStage` / `ResourceRecord.extract` / `ResourceRecord.expires_at` / `ResourceRecord.last_success_at` 字段已落地）
5. `puresource-playlist/app/extract_worker.py`（worker 进程结构、stale claim 清理、callback 重试策略）
6. `puresource-btprobe/puresource_btprobe/{main,qbt,models}.py`（子服务结构、qBittorrent 调用、QBT_MOCK 路径、callback 模式）
7. `puresource-playlist/app/store.py`（`_migrate_legacy` 兼容策略；`jobs_dir()` 队列目录约定）
8. `puresource-playlist/app/static/{index.html,app.js,app.css}`（前端 in-flight 轮询、文件树、候选 promote 联动；判断 v0.4b 过期标记落在哪一块）

### 3.2 v0.3 设计与历史决策（必读，用以理解约束来源）

9. `docs/design/PureSource v0.3 资源探测与视频图书馆方案.md`（特别 §四 4.4「目录管理（后续迭代）」与 §五「失效检测」预告——这些是 v0.4b / v0.5 的源头）
10. `docs/design/架构设计小结.md`（§2.3.2 红线：主服务不接 DHT/peer/qBittorrent；v0.4a 接入真实 qBittorrent 时是否仍守红线？请确认）
11. `docs/design/cursor-task-03-review-and-plan.md` §8 的 10 项裁决（特别 #1 / #4 / #5 / #6 / #8 / #9——它们都将在 v0.4 接受真实流量的考验）

### 3.3 生产侧只读探测（必跑，用以摸清生产现状）

允许的探测命令（在生产 VPS 上跑），结果回报但**不要据此动手**：

```bash
# 主服务现状
systemctl status puresource-playlist.service --no-pager
ss -lntp | grep -E ':8090|:8091|:8080'

# 现有 resources.json 体量
wc -l /opt/puresource-playlist/data/resources.json 2>/dev/null || echo "no file"
ls -la /opt/puresource-playlist/data/

# yt-dlp / qBittorrent 是否已存在
which yt-dlp && yt-dlp --version
which qbittorrent-nox || echo "qBittorrent 未装"
dpkg -l | grep -E 'yt-dlp|qbittorrent' || echo "无 dpkg 包"

# Caddy 当前是否已经 deny /internal/*
caddy validate --config /etc/caddy/Caddyfile && echo "Caddy 配置可 validate"
grep -E "internal" /etc/caddy/Caddyfile || echo "Caddy 还没 deny /internal/*"

# 备份盘空间
df -h /opt /var/lib /var/log

# v0.3 开发实例是否还在跑（避免你以为 :8190 是生产）
ss -lntp | grep -E ':8190'
```

回报上述结果后再进入下一节。

---

## 四、必须回答的关键问题

每个问题独立成节，**先给结论再给依据**。每节末尾必须有"建议方向 + 待用户裁决项"。

### v0.4a（生产部署）

#### Q1. cutover 时序：一把切 vs 分批切

v0.3 checklist 写的是"一次性切完"（btprobe → 主服务 → worker → Caddy）。请评审：

- 这种一次性切法**在真实生产**上是否真的可以？还是应当拆成**两次 cutover**：
  - **cutover-1**：先上 worker + btprobe（QBT_MOCK=1）+ Caddy `/internal/*` deny，主服务沿用 v0.2；用户感知**零**变化。
  - **cutover-2**：再上 v0.3 主服务代码 + 前端 + 真 qBittorrent；用户首次看到新 stage / 文件树。
- 给出两套方案的对比（停机时间、回滚复杂度、可观察性、用户感知）。
- 给出推荐及一句话理由。

#### Q2. qBittorrent 上线策略

接入真实 qBittorrent 是 v0.4a 的关键风险点。回答：

- **安装方式**：`apt install qbittorrent-nox` vs 编译源码 vs 静态二进制？给出推荐，含版本固化策略（v0.4 时下 qbt 哪个版本？怎么防止 apt unattended-upgrades 滚版？）。
- **systemd 托管**：是否需要写自定义 unit，还是用 distro 自带的？给出关键 `[Service]` 字段（`User`、`WorkingDirectory`、`Environment`、`UMask` 等）。
- **配置初始化**：Web UI 端口、默认下载目录、默认文件优先级、`stopCondition: MetadataReceived`、tracker 列表——哪些必须改、哪些可以默认？给出**最小配置变更清单**。
- **存储与膨胀防护**：`add_paused=true` + `setFilePrio=0` + 探测完 `delete(deleteFiles=true)` 三保险已在代码层，但 qBittorrent 自己的 BT_backup / fastresume 文件会不会膨胀？给出磁盘配额建议（单位 GB）+ logrotate 策略。
- **凭据存储**：`/etc/puresource-btprobe.env` 是 v0.3 checklist 给的口子，权限 0600 root:root，systemd `EnvironmentFile=` 装载。这够安全吗？还是应该走 systemd credential / secret 管理？给出推荐。

#### Q3. 真实流量烟测计划

`QBT_MOCK=1` 跑了一堆假数据，但 v0.4a 切到真 qBittorrent 后必须有**可预测的真实烟测样本**。回答：

- 选**至少 3 个**烟测种子（公开、可信、metadata 易拉、文件结构稳定），列出每个的 magnet URI 形态、预期文件数、预期主文件大小、预期 peers/seeds 数量级。
- 给出验收脚本骨架（不要写实际 curl，给伪代码）：bt-probe 触发 → 等多久 → 检查 magnet.files 哪些字段必须非 null → 失败如何 demote。
- 如果烟测失败（拉不到 metadata），是 v0.4a cutover 阻塞项还是允许带病上线？

#### Q4. 观测与可恢复性

v0.4a 上生产后，怎么持续观测三个进程的健康？回答：

- 给出每个进程的关键观测点（日志关键字、jobs_dir 堆积量阈值、callback 失败率、qBittorrent metadata pending 数）。
- 是否需要给主服务加一个 `GET /diag` 或 `GET /metrics` 端点？给出端点形态（**仅本机可达**）与字段。注意：**这是新代码**，如果你认为必要，把它列为 T-4a-xx，但要说清是必需还是可选。
- `journalctl` 抓取规则：哪些 unit / 哪些字段 / 多久保留？给出推荐。
- 如果 worker 突然停了，新 extract 请求会落 job 文件但永不被处理，前端只能看到任务永远卡在 `extracting`。给出**至少一种**用户层可感知的失败信号机制（不要求自动恢复，只要求可见）。

#### Q5. 回滚演练

v0.3 checklist §11 写了 8 步回滚顺序，但**这条路从未在真实生产上演练过**。回答：

- 上 v0.4a 之前是否需要做一次"灰度演练"（在测试环境模拟一次完整 cutover + 回滚）？如果是，给出最小演练步骤（不超过 10 步）。
- §1.4 的字段丢失风险是否需要在演练里专门验证？给出最小验证方法（怎么造一条同时有 `extract` 和 `expires_at` 的记录，怎么验回滚后字段是否被擦）。
- 给出"回滚成功"的硬判据：什么时候可以确认回滚干净（resources.json 无脏化、PotPlayer 订阅可播、用户感知无差异）？

### v0.4b（生命周期闭环）

#### Q6. `expires_at` 写入时机与策略

v0.3 已经落地了 `ResourceRecord.expires_at` 字段但**没人写它**。回答：

- 哪些 `source_kind` 应该自动写 `expires_at`？哪些不写？给出映射表（建议覆盖：mp4 / m3u8 / magnet / webpage / other）。
- 自动写入的时机：`/intake` 时？`/promote` 时？两者都写？给出推荐。
- 默认 TTL：PikPak CDN 已知 24h；油猴脚本注入的 URL 可能更短；自托管 URL 可能永久。给出**source_kind → 默认 TTL** 映射，含理由。
- 用户是否能手动覆盖 `expires_at`？给出 API 形态（推荐：`PromoteRequest` 加 optional `expires_at` 字段，向后兼容）。

#### Q7. 复检 worker 设计

新增一个 `puresource-expiry-worker` 独立进程做"快到期 / 已过期"资源的复检。回答：

- 探活方式：HEAD vs GET Range vs ffprobe-light？对 m3u8 / mp4 / PikPak CDN 各自的判定差异是什么？给出对比表。
- 触发节奏：每隔多久扫一次？只扫 `expires_at < now + δ` 的资源吗？δ 取多大？
- 失败几次后降级 stage？失败时 stage 推到哪里（`failed` 还是新 `expired` 还是降回 `pending`）？给出推荐 + 是否需要新增 stage 枚举值。
- 复检结果写哪里？给出至少 2 个候选字段方案（在 `ResourceRecord` 新增 `last_check_at` / `last_check_status` 还是只更新 `last_success_at` 一个？）。
- 复检 worker 是否也通过 `/internal/*` callback 回写（与 extract / bt-probe 对称），还是直接读写 resources.json？给出推荐 + 理由。

#### Q8. 前端过期语义

UI 上"快过期 / 已过期"的呈现。回答：

- 在工作台列表里要不要单独的 stage tab？如果不要，过期资源怎么过滤出来给用户看？
- 徽章语义：`expires_at - now < 2h` 显示"即将过期"，`< 0` 显示"已过期"？给出阈值建议。
- `default.m3u8` 是否过滤掉已过期资源？这是行为变更，**影响 PotPlayer 客户端**——是开关式（默认关）还是强制（默认开）？给出推荐 + 兼容性影响。
- 用户能从 UI 触发"重新 extract / 重新 bt-probe"吗？给出按钮放在哪、复用现有端点还是新加。

#### Q9. v0.4b 数据迁移坑

v0.4b 又会引入新字段（`last_check_at` / `last_check_status` 之类）。这是否会**再次触发 v0.3 ⇄ v0.4b 的字段丢失风险**？回答：

- 列出 v0.4b 计划引入的所有新字段（参考你在 Q7 给的字段设计）。
- 这些字段是否要走 `_migrate_legacy` setdefault？给出每个字段的迁移条目。
- 是否要趁机给 `_migrate_legacy` 加一段"版本号检测"（在 `ResourceRecord` 加 `schema_version`），让未来回滚可以早 fail？给出推荐 + 影响面。

### 全局

#### Q10. v0.4a / v0.4b 时序

回答：

- v0.4a 与 v0.4b 是**串行**（先 cutover 再开发 expiry worker）还是**并行**（生产 cutover 期间在开发分支同步开发 expiry worker）？
- 推荐 + 理由 + 风险。

#### Q11. v0.4 完成的判据

什么时候可以说"v0.4 done 了"？给出可观察的硬判据（至少 5 条），每条都要可被 curl / SQL / journalctl 验证。

#### Q12. v0.5 边界守卫

目录管理 / 搜索 / 批量操作归 v0.5。回答：

- v0.4 是否需要为 v0.5 埋字段（如 `tags: list[str]` / `category: Optional[str]` / `favorited_at`）以避免再次数据迁移？
- 如果埋，请给出最小字段集 + 默认值；如果不埋，请说明为什么 v0.5 引入这些字段时不会再次触发 §1.4 类型的迁移坑。

---

## 五、输出格式要求

按以下结构组织你的回复，缺一不可：

```
0. 已读文件清单 + 生产侧只读探测结果（§3.3）
1. 总体评价（不超过 5 句）
2. 与本任务约定的分歧与建议（每条：原约定怎么写 → 你建议怎么改 → 影响面 → 待用户裁决/不必裁决）
3. Q1–Q5（v0.4a 生产部署）
4. Q6–Q9（v0.4b 生命周期闭环）
5. Q10–Q12（全局）
6. 执行计划 - v0.4a（按下面"细化要求"逐条列出 T-4a-XX）
7. 执行计划 - v0.4b（按下面"细化要求"逐条列出 T-4b-XX）
8. 依赖图（文字表示即可，覆盖 v0.4a + v0.4b 全部任务）
9. 等待用户裁决的 N 项清单
```

### "执行计划"细化要求

执行计划必须**具体到文件 / systemd unit / Caddy 段 / curl 命令级别**。每条任务遵循以下格式：

```
任务编号：T-<阶段>-<序号>，例如 T-4a-03、T-4b-02
标题：一句话
触达对象：
  - 系统：apt 包名 / systemd unit 文件路径 / Caddy 段标识
  - 仓库：puresource-playlist/app/models.py（新增字段 X）
  - 数据：/opt/puresource-playlist/data/resources.json（迁移影响）
契约影响：是否破坏现有 API / data/resources.json 兼容性 / Caddy 路由
依赖：T-x-yy（必须先完成的任务）
验收：可观察的 curl / systemctl / journalctl 输出
预估工时：<小时>，区分"运维"工时与"代码"工时
风险：一句话；任何"待用户裁决"必须在这里点名
```

**v0.4a 的任务类型**多数是**运维任务**（apt install / systemctl edit / rsync / curl 验收），少数是**配套小代码**（如果 Q4 你判断需要 `GET /diag` 端点）。

**v0.4b 的任务类型**多数是**代码任务**（新模型字段、新 worker 进程、前端徽章），少数是**部署任务**（worker 上 systemd）。

请明确区分两者，并在每条任务的"预估工时"里写清楚是运维还是代码。

---

## 六、分歧与裁决规则

1. 你**可以**反对 v0.3 checklist 的任何一点，但必须把反对意见放进"§2 分歧与建议"，并在执行计划里**保留原约定路径**，同时在该任务上加 `⚠️ 待裁决：见 §2 第 N 条`。
2. 你**不可以**在执行计划里直接按你的意见改，让我以为约定被你照搬了。
3. 如果你发现 v0.4a 接入真实 qBittorrent 触犯了"架构小结 §2.3.2 红线"，必须在"§2 分歧与建议"显式列出，**不允许你单方面声明"红线已经被 v0.3 默认推翻"**——v0.3 当时的论证是"qBittorrent 跑在独立子服务里、与主服务隔进程"，v0.4 要切真实流量时这条论证是否仍成立由用户裁决。
4. cursor-task-03 §8 已裁决的 10 项**仍然有效**，不要重复裁决。但如果 v0.4 真实流量暴露了某项裁决的潜在问题，可以在"§2 分歧与建议"里 reopen 该项，标注 `⚠️ 申请 reopen §8 #N`。

---

## 七、本轮"完成"的定义

当且仅当下列条件全部满足时，视为本轮完成：

1. 0–9 节全部输出。
2. Q1–Q12 每个问题都有明确推荐 + 至少一项"待用户裁决"或显式标注"不必裁决，建议直接采纳"。
3. 执行计划 v0.4a / v0.4b 两段分别列出，每条任务都符合 §五的细化格式。
4. 依赖图覆盖所有任务，并标出 v0.4a / v0.4b 内部的可并行段。
5. 没有任何文件被修改、新建、删除；生产 VPS 没有任何写操作。
6. 你在回复末尾明确写一句："本轮纯谋阶段已完成，等待用户审阅后切换到 v0.4a / v0.4b 执行阶段。"

---

## 八、本轮**不要**做的事

- 不要写代码片段超过 5 行。需要展示契约时用 schema/伪代码，不要给 import 完整的实现。
- 不要画 ASCII 大图，文字依赖图就够。
- 不要去网上查 qBittorrent / yt-dlp 的最新版本号——用 v0.3 已确定的版本约束即可，版本敏感事项写"待 T-4a-XX 时确认"。
- 不要主动开 canvas 或额外文档。所有结论写在对话回复里。
- 不要把 v0.5（目录管理 / 搜索 / 批量操作）的内容拉进 v0.4。如果你认为某个 v0.5 项必须前置，写到"§2 分歧与建议"申请 reopen，**不要直接做进 v0.4 计划**。
- 不要试图启动开发实例 :8190 来"重新验证 v0.3"。v0.3 已被用户审过，本轮聚焦 v0.4。
- 不要在评审里花篇幅赞美 v0.3 checklist。重点是**指出风险**和**起草 v0.4 计划**；任何对 v0.3 的肯定一句话带过即可。

---

## 九、附：v0.4 范围速查（用户已定调的取舍）

```
v0.4a 生产部署
  ├── 系统级：apt yt-dlp / qbittorrent-nox / cookies 目录
  ├── systemd：puresource-extract-worker / puresource-btprobe
  ├── Caddy：/internal/* deny
  ├── 主服务：补 Environment + 同步代码 + 静态页
  ├── qBittorrent：装 + 配 + 凭据 + 系统加固
  ├── 烟测：真实种子 metadata 拉取
  └── 回滚演练：dry-run 一次

v0.4b 生命周期闭环
  ├── 模型：expires_at 写入策略 / 新字段（last_check_*）
  ├── 进程：puresource-expiry-worker
  ├── 主服务：/internal/tasks/{id}/expiry-result + promote 自动写 expires_at
  ├── 前端：过期 / 即将过期徽章 + 重新探测按钮
  └── 部署：worker systemd unit + 接入生产

v0.5（不在本轮范围）
  ├── 标签 / 分组
  ├── 搜索
  ├── 批量操作
  └── PotPlayer 订阅分桶
```

v0.4 不增加 PotPlayer 订阅出口；不重写前端 IA；不引入数据库（仍是 resources.json）。
