# Cursor 任务 02：数据模型升级 — 资源生命周期 + 标准播放对象

> 架构师：本地 Codex（与 Cursor 对齐后修订）
> 执行者：VPS Cursor
> 日期：2026-05-12
> 分支：`task/v0.3a-data-model`

---

## 背景

Cursor 在 Canvas 评审中指出：在接入 yt-dlp / qBittorrent 等探测器之前，`ResourceRecord` 需要先具备生命周期管理能力。当前模型缺少：
- 过期时间（PikPak 24h URL 实证）
- 失败原因（探测失败后无法解释）
- 验证溯源（`/intake` 手动入列 vs 自动 probe）
- 刷新提示（失效后用户该怎么做）

本任务只改数据模型，不改业务逻辑，不影响现有 API 契约（所有新字段 Optional，向后兼容）。

---

## 步骤 1：在 `app/models.py` 中新增 `PlaybackInfo` 模型

在 `MagnetInfo` 类定义之后、`ResourceRecord` 之前插入：

```python
class PlaybackInfo(BaseModel):
    """标准播放对象 — 最小冻结版（v0.3a）。

    字段取自架构文档 2.3 节实测结论，不预设未实现能力。
    """

    model_config = ConfigDict(extra="ignore")

    recommended_executor: str = Field(
        "external_player",
        description="external_player | local_stream | hls_preview | none",
    )
    web_preview: str = Field(
        "unavailable",
        description="available | available_but_not_primary | unavailable",
    )
    reason: Optional[str] = Field(
        None,
        description="例如 browser_remote_mp4_pipeline_unstable",
    )
```

---

## 步骤 2：在 `ResourceRecord` 中新增生命周期字段

在 `ResourceRecord` 现有字段之后（`created_at` 之前）插入以下字段：

```python
    # === v0.3a 生命周期字段（全部 Optional，向后兼容） ===

    expires_at: Optional[str] = Field(
        None,
        description="stream_url 预计失效时间 ISO-8601；PikPak CDN 通常签发后 24h",
    )
    verified_by: Optional[str] = Field(
        None,
        description="验证来源：manual | yt_dlp | bt_probe | http_probe",
    )
    source_trust: Optional[str] = Field(
        None,
        description="信任级别：manual_verified | auto_probe | external",
    )
    failure_reason: Optional[str] = Field(
        None, max_length=512,
        description="最近一次探测/验证失败的原因",
    )
    refresh_hint: Optional[str] = Field(
        None, max_length=512,
        description="失效后如何刷新，例如 're-export from PikPak'、're-run yt-dlp'",
    )

    # 标准播放对象（v0.3a 冻结版）
    playback: Optional[PlaybackInfo] = None
```

**注意**：`last_probed_at` 字段已经存在，无需重复添加。`last_success_at` 暂不加——当前 `stage=playable/external_ready` 已隐含"探测成功"，额外字段留到复检定时任务时再补。

---

## 步骤 3：更新 `IntakeRequest`，支持 `verified_by` 和 `expires_in_hours`

修改 `POST /intake` 的请求模型，让调用方（手动/PikPak/油猴）可标注验证来源和有效时长：

```python
class IntakeRequest(BaseModel):
    """POST /intake：调用方已自行判定可入列的快捷登记。契约保持 v0.1 兼容。"""

    title: str = Field(..., min_length=1, max_length=512)
    stream_url: str = Field(
        ..., min_length=1, description="PotPlayer 可打开的绝对 URL"
    )
    status: ResourceStatus = Field(
        ..., description="必须为 stable | playable | external_ready"
    )
    note: Optional[str] = Field(None, max_length=2048)

    # === v0.3a 新增（全部 Optional） ===
    verified_by: Optional[str] = Field(
        None, description="manual | pikpak_export | tampermonkey | external"
    )
    expires_in_hours: Optional[int] = Field(
        None, ge=1, le=8760, description="从当前时刻起的有效小时数，例如 24"
    )

    @field_validator("stream_url")
    @classmethod
    def must_be_http(cls, v: str) -> str:
        if not v.startswith(HTTP_SCHEMES):
            raise ValueError("stream_url 须为 http(s) 绝对 URL")
        return v
```

---

## 步骤 4：更新 `app/main.py` 中 `/intake` 端点

修改 `intake()` 函数，使用 `IntakeRequest` 的新字段填充 `ResourceRecord` 的生命周期字段：

```python
@app.post("/intake", response_model=IntakeResponse)
def intake(body: IntakeRequest) -> IntakeResponse:
    """登记一条已自行判定可入列的资源。契约同 v0.1，v0.3a 扩展生命周期字段。"""
    url = body.stream_url.strip()

    # 计算过期时间
    expires_at: Optional[str] = None
    if body.expires_in_hours is not None:
        from datetime import timedelta

        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=body.expires_in_hours)
        ).isoformat()

    rec = ResourceRecord(
        title=body.title.strip(),
        source_url=url,
        source_kind=infer_source_kind(url),
        stream_url=url,
        stage=status_to_stage(body.status),
        status=body.status,
        note=body.note.strip() if body.note else None,
        verified_by=body.verified_by,
        source_trust="manual_verified" if body.verified_by else "external",
        expires_at=expires_at,
        refresh_hint=(
            f"re-export from {body.verified_by}" if body.verified_by else None
        ),
        playback=PlaybackInfo(
            recommended_executor="external_player",
            web_preview="available_but_not_primary",
            reason="browser_remote_mp4_pipeline_unstable",
        ),
    )
    append_resource(rec)
    return IntakeResponse(resource=rec)
```

`main.py` 顶部可能需要新增 import：
```python
from .models import (
    # ... 现有 import ...
    PlaybackInfo,  # v0.3a 新增
)
```

---

## 步骤 5：更新前端 `app/static/app.js`

### 5.1 在 task 卡片中展示生命周期信息

在 `renderTask` 函数中，expires_at 和 failure_reason 展示（放在 probe_log 之前、magnet info 之后）：

```javascript
// 在 renderTask 函数中，magnet info 渲染之后、probe log 之前插入：
function renderLifeycleInfo(r) {
  const parts = [];
  if (r.expires_at) {
    const expDate = new Date(r.expires_at);
    const now = new Date();
    const hoursLeft = Math.max(0, Math.round((expDate - now) / 3600000));
    const expStr = expDate.toLocaleString();
    parts.push(`<span class="label">过期:</span> ${expStr} (剩余 ~${hoursLeft}h)`);
  }
  if (r.verified_by) {
    parts.push(`<span class="label">验证来源:</span> ${esc(r.verified_by)}`);
  }
  if (r.source_trust) {
    parts.push(`<span class="label">信任级别:</span> ${esc(r.source_trust)}`);
  }
  if (r.failure_reason) {
    parts.push(`<span class="label err">失败原因:</span> ${esc(r.failure_reason)}`);
  }
  if (r.refresh_hint) {
    parts.push(`<span class="label">刷新方式:</span> ${esc(r.refresh_hint)}`);
  }
  if (r.playback && r.playback.recommended_executor) {
    parts.push(`<span class="label">推荐执行器:</span> ${esc(r.playback.recommended_executor)}`);
  }
  return parts.length ? `<div class="lifecycle-info">${parts.join("<br>")}</div>` : "";
}
```

在 `renderTask` 返回的 HTML 中，`${renderMagnetInfo(r.magnet)}` 之后插入：
```javascript
${renderLifeycleInfo(r)}
```

### 5.2（可选）`/intake` 表单增加 `expires_in_hours` 字段

当前工作台主表单是 `/tasks` 创建，`/intake` 没有前端表单。暂不新增——`/intake` 主要供脚本/curl 调用。如果后续需要前端 `/intake` 表单，再加。

---

## 步骤 6：验证

```bash
# 1. 重启服务
systemctl restart puresource-playlist

# 2. 验证 /intake 新字段
curl -sS -X POST http://127.0.0.1:8090/intake \
  -H "Content-Type: application/json" \
  -d '{
    "title":"PikPak 测试 - Cosmos Laundromat",
    "stream_url":"https://dl-z01a-0027.mypikpak.com/download/?fid=xxx&expire=1778579884",
    "status":"external_ready",
    "verified_by":"pikpak_export",
    "expires_in_hours":24,
    "note":"PikPak CDN 导出，24h 有效"
  }' | python3 -m json.tool

# 3. 确认返回的 resource 包含新字段
# 检查: expires_at, verified_by, source_trust, refresh_hint, playback

# 4. 验证现有 /tasks 创建不受影响
curl -sS -X POST http://127.0.0.1:8090/tasks \
  -H "Content-Type: application/json" \
  -d '{"source_url":"https://example.com/video.mp4","title":"模型兼容性测试"}'

# 5. 验证现有 probe 不受影响
curl -sS -X POST http://127.0.0.1:8090/tasks/<rec_id>/probe
```

---

## 设计决策记录

| 决策 | 理由 |
|------|------|
| 所有新字段 `Optional` + 默认 `None` | 向后兼容现有 `data/resources.json` 中的数据 |
| `last_success_at` 暂不加 | 当前 `stage=playable/external_ready` 已隐含成功；等复检定时任务再补 |
| `PlaybackInfo` 只含 3 个字段 | 架构文档中 `playability` / `recommended` 的丰富字段属后续迭代，当前只冻结已验证的 |
| `/intake` 用 `expires_in_hours` 而非直接传 `expires_at` | 服务端统一计算，避免客户端时区问题 |
| 不建数据库迁移 | `data/resources.json` 是 JSON 文件，Pydantic `extra="ignore"` 保证旧数据可读，新字段自动填 `None` |

---

## 回报格式

```
分支名：task/v0.3a-data-model
commit hash：
修改文件列表：
curl 验证输出（/intake 返回的 resource JSON，确认新字段存在）：
前端截图/描述：
向后兼容验证（旧 /tasks 端点仍正常工作）：
已知问题：
```
