from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


# === 列表准入硬枚举：PotPlayer 闭环的唯一信号 ===
# 严格保留三态，不扩枚举、不重命名。新增"工作台"语义请走 ResourceStage。
class ResourceStatus(str, Enum):
    stable = "stable"
    playable = "playable"
    external_ready = "external_ready"


# === 工作台语义：提纯流程进度 ===
# 不直接决定列表准入；只供 /tasks 与 UI 使用。
class ResourceStage(str, Enum):
    pending = "pending"
    probing = "probing"
    playable = "playable"
    external_ready = "external_ready"
    failed = "failed"


HTTP_SCHEMES = ("http://", "https://")
MAGNET_SCHEME = "magnet:"

# probe_log 的截断与上限，避免 resources.json 无限膨胀。
PROBE_LOG_MAX_LINE = 200
PROBE_LOG_MAX_ENTRIES = 20

# magnet.enrich_log 上限（与 probe_log 同口径）。
ENRICH_LOG_MAX_LINE = 200
ENRICH_LOG_MAX_ENTRIES = 20
# trackers 数量上限：防止恶意 magnet 撑大 resources.json。
MAGNET_TRACKERS_MAX = 64


def infer_source_kind(url: str) -> str:
    """根据 URL 形态推断 source_kind。仅做后缀/前缀判定，不发请求。"""
    u = (url or "").strip().lower()
    if u.startswith(MAGNET_SCHEME):
        return "magnet"
    if u.startswith(HTTP_SCHEMES):
        path = u.split("?", 1)[0].split("#", 1)[0]
        if path.endswith(".m3u8"):
            return "m3u8"
        if path.endswith(".mp4"):
            return "mp4"
        return "webpage"
    return "other"


def status_to_stage(s: ResourceStatus) -> ResourceStage:
    """把"列表准入态"映射回"工作台进度态"，仅在 /intake 兼容路径用。"""
    if s == ResourceStatus.playable:
        return ResourceStage.playable
    return ResourceStage.external_ready  # stable / external_ready 都视作终态入列


# === 请求/响应模型 ===


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

    @field_validator("stream_url")
    @classmethod
    def must_be_http(cls, v: str) -> str:
        if not v.startswith(HTTP_SCHEMES):
            raise ValueError("stream_url 须为 http(s) 绝对 URL")
        return v


class TaskCreateRequest(BaseModel):
    """POST /tasks：从原始链接创建提纯任务；不强制可入列。"""

    source_url: str = Field(..., min_length=1, max_length=4096)
    title: Optional[str] = Field(None, max_length=512)
    note: Optional[str] = Field(None, max_length=2048)

    @field_validator("source_url")
    @classmethod
    def source_url_non_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("source_url 不能为空")
        return s


class PromoteRequest(BaseModel):
    """POST /tasks/{id}/promote：人工把任务推到可入列；唯一会写 status 的入口。"""

    stream_url: str = Field(..., min_length=1)
    target_status: ResourceStatus = ResourceStatus.external_ready
    title: Optional[str] = Field(None, max_length=512)

    @field_validator("stream_url")
    @classmethod
    def must_be_http(cls, v: str) -> str:
        if not v.startswith(HTTP_SCHEMES):
            raise ValueError("stream_url 须为 http(s) 绝对 URL")
        return v


class MagnetInfo(BaseModel):
    """magnet URI 解析产物（v0.3 PoC 1a）。

    刻意保留的边界：仅 URI 字符串解析，**不与 BT 网络交互**。
    不含 files[] / total_size / video_candidates / stream_url。
    """

    model_config = ConfigDict(extra="ignore")

    info_hash: Optional[str] = Field(
        None, description="v1 info_hash，归一化 40 位小写 hex"
    )
    info_hash_v2: Optional[str] = Field(
        None, description="v2 info_hash，64 位小写 hex（不含 multihash 前缀）"
    )
    info_hash_kind: str = Field(
        "unknown", description="v1 | v2 | v1+v2 | unknown"
    )
    display_name: Optional[str] = Field(None, max_length=512)
    trackers: list[str] = Field(default_factory=list)
    parsed_at: Optional[str] = None
    enrich_log: list[str] = Field(default_factory=list)

    @field_validator("trackers")
    @classmethod
    def cap_trackers(cls, v: list[str]) -> list[str]:
        clean: list[str] = []
        seen: set[str] = set()
        for t in v:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            clean.append(t[:PROBE_LOG_MAX_LINE])
            if len(clean) >= MAGNET_TRACKERS_MAX:
                break
        return clean

    @field_validator("enrich_log")
    @classmethod
    def cap_log(cls, v: list[str]) -> list[str]:
        clean = [line[:ENRICH_LOG_MAX_LINE] for line in v if isinstance(line, str)]
        return clean[-ENRICH_LOG_MAX_ENTRIES:]


class ResourceRecord(BaseModel):
    """资源/任务记录。同时承载"列表条目"与"提纯任务"两种角色。"""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    source_url: Optional[str] = None
    source_kind: str = "other"
    # 只有在 promote 后才会被填充；列表准入双保险之一。
    stream_url: Optional[str] = None
    stage: ResourceStage = ResourceStage.pending
    # 只有在 promote 后才会被填充；列表准入唯一信号。
    status: Optional[ResourceStatus] = None
    note: Optional[str] = None
    last_probed_at: Optional[str] = None
    probe_log: list[str] = Field(default_factory=list)
    # magnet 资源富化产物；仅 source_kind=="magnet" 时填充，且永不影响列表准入。
    magnet: Optional[MagnetInfo] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @field_validator("probe_log")
    @classmethod
    def cap_log(cls, v: list[str]) -> list[str]:
        clean = [line[:PROBE_LOG_MAX_LINE] for line in v if isinstance(line, str)]
        return clean[-PROBE_LOG_MAX_ENTRIES:]


class IntakeResponse(BaseModel):
    ok: bool = True
    resource: ResourceRecord


class ResourcesResponse(BaseModel):
    resources: list[ResourceRecord]


class TaskListResponse(BaseModel):
    tasks: list[ResourceRecord]
