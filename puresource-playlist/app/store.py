from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from .models import (
    ResourceRecord,
    ResourceStage,
    ResourceStatus,
    infer_source_kind,
)

_LOCK = threading.Lock()


def _data_dir() -> Path:
    # 测试隔离：smoke / CI 可通过 PURESOURCE_DATA_DIR 指向独立目录，
    # 避免污染生产 data/resources.json。
    override = os.environ.get("PURESOURCE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "data"


def _resources_path() -> Path:
    p = _data_dir() / "resources.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _migrate_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """v0.1 -> v0.2 迁移：

    老记录只有 title / stream_url / status / note / created_at。
    迁移规则保持语义：
    - 老记录都已是入列态 → stage 兜底为 external_ready
    - source_url 兜底等于 stream_url（用户原始输入未保留时的合理近似）
    - source_kind 按 URL 后缀推断
    - probe_log 兜底为空
    """
    out = dict(raw)
    if "stage" not in out:
        out["stage"] = ResourceStage.external_ready.value
    if "source_url" not in out:
        out["source_url"] = out.get("stream_url")
    if "source_kind" not in out:
        out["source_kind"] = infer_source_kind(out.get("stream_url") or "")
    out.setdefault("probe_log", [])
    return out


def load_resources() -> list[ResourceRecord]:
    path = _resources_path()
    if not path.is_file():
        return []
    raw_text = path.read_text(encoding="utf-8")
    if not raw_text.strip():
        return []
    data: list[dict[str, Any]] = json.loads(raw_text)
    return [ResourceRecord.model_validate(_migrate_legacy(x)) for x in data]


def save_resources(items: list[ResourceRecord]) -> None:
    path = _resources_path()
    payload = [x.model_dump(mode="json") for x in items]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def append_resource(rec: ResourceRecord) -> list[ResourceRecord]:
    with _LOCK:
        items = load_resources()
        items.append(rec)
        save_resources(items)
        return items


def update_resource(
    rec_id: str,
    mutator: Callable[[ResourceRecord], ResourceRecord],
) -> Optional[ResourceRecord]:
    """加锁查找并替换单条记录；返回更新后的记录，找不到返回 None。"""
    with _LOCK:
        items = load_resources()
        for i, r in enumerate(items):
            if r.id == rec_id:
                new = mutator(r)
                items[i] = new
                save_resources(items)
                return new
    return None


def eligible_for_playlist(r: ResourceRecord) -> bool:
    """列表准入双保险：

    1. status 必须非空（pending/probing/failed 的 status 一律 None）
    2. status 必须在三态硬枚举范围内
    3. stream_url 必须非空（promote 才会写）
    """
    if r.status is None or not r.stream_url:
        return False
    return r.status in (
        ResourceStatus.stable,
        ResourceStatus.playable,
        ResourceStatus.external_ready,
    )
