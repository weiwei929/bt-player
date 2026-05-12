"""puresource-btprobe 内部 / 对外的请求与响应契约（v0.3 T-2）。

刻意保留的边界：
- 仅承载"主服务下发探测任务"与"子服务回写结果"两条契约；不承载任何
  ResourceRecord / ResourceStage 状态机字段。
- BtProbeFile / BtProbeResult 与 puresource-playlist.app.models.MagnetFile /
  MagnetInfo 的字段名保持一致（path / size_bytes / is_recommended_main /
  peer_count / seed_count / probed_at / main_file_index），便于主服务回写时
  零拷贝拼装。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 与主服务 MAGNET_FILES_MAX 同口径，避免子服务返回值被主服务静默截断。
BTPROBE_FILES_MAX = 1024
BTPROBE_FILE_PATH_MAX = 512


class BtProbeFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = Field(..., max_length=BTPROBE_FILE_PATH_MAX)
    size_bytes: int = Field(..., ge=0)
    is_recommended_main: bool = False


class ProbeRequest(BaseModel):
    """POST /probe：主服务下发的探测任务。

    - magnet：magnet URI（必填，子服务自行解析 info_hash）
    - task_id：主服务侧 ResourceRecord.id；callback 需要回带
    - callback_url：完成后回写的主服务端点（绝对 URL）
    """

    task_id: str = Field(..., min_length=1, max_length=64)
    magnet: str = Field(..., min_length=1, max_length=8192)
    callback_url: str = Field(..., min_length=1, max_length=4096)

    @field_validator("magnet")
    @classmethod
    def must_be_magnet(cls, v: str) -> str:
        if not v.lower().startswith("magnet:"):
            raise ValueError("magnet 必须以 magnet: 开头")
        return v

    @field_validator("callback_url")
    @classmethod
    def must_be_http(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("callback_url 须为 http(s) 绝对 URL")
        return v


class ProbeAck(BaseModel):
    """POST /probe 立即返回的 ack；不含探测结果。"""

    accepted: bool = True
    task_id: str
    note: Optional[str] = None


class BtProbeResultPayload(BaseModel):
    """子服务 callback 主服务的载荷。

    这与 puresource-playlist 那边的 BtProbeResultRequest 是同一个契约
    （字段名一致），但物理上各自定义一份避免跨包导入。
    """

    status: str = Field(..., description='只接受 "ok" 或 "failed"')
    files: list[BtProbeFile] = Field(default_factory=list)
    peer_count: Optional[int] = Field(None, ge=0)
    seed_count: Optional[int] = Field(None, ge=0)
    probed_at: Optional[str] = None
    main_file_index: Optional[int] = Field(None, ge=0)
    error: Optional[str] = Field(None, max_length=512)
    log: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def status_enum(cls, v: str) -> str:
        if v not in ("ok", "failed"):
            raise ValueError('status must be "ok" or "failed"')
        return v
