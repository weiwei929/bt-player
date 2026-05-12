from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .magnet import parse_magnet
from .models import (
    ENRICH_LOG_MAX_ENTRIES,
    IntakeRequest,
    IntakeResponse,
    MagnetInfo,
    PromoteRequest,
    ResourceRecord,
    ResourceStage,
    ResourcesResponse,
    TaskCreateRequest,
    TaskListResponse,
    infer_source_kind,
    status_to_stage,
)
from .playlist import default_playlist, recent_playlist
from .probe import probe_record
from .store import append_resource, load_resources, update_resource

app = FastAPI(
    title="puresource-playlist",
    description="资源提纯工作台 + PotPlayer M3U 路由清单（非 HLS）",
    version="0.2.0",
)


# 开发期：本地直连 8090/8190 调试用，挂 /static
# 生产路径仍以 /var/www/bt-player（Caddy file_server）为准；这里不取代它。
_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.is_dir():
    app.mount(
        "/static",
        StaticFiles(directory=str(_STATIC_DIR), html=True),
        name="static",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# === v0.1 兼容：/intake 与 /resources ===


@app.post("/intake", response_model=IntakeResponse)
def intake(body: IntakeRequest) -> IntakeResponse:
    """登记一条已自行判定可入列的资源。契约同 v0.1。"""
    url = body.stream_url.strip()
    rec = ResourceRecord(
        title=body.title.strip(),
        source_url=url,
        source_kind=infer_source_kind(url),
        stream_url=url,
        stage=status_to_stage(body.status),
        status=body.status,
        note=body.note.strip() if body.note else None,
    )
    append_resource(rec)
    return IntakeResponse(resource=rec)


@app.get("/resources", response_model=ResourcesResponse)
def list_resources() -> ResourcesResponse:
    return ResourcesResponse(resources=load_resources())


# === 提纯工作台：/tasks 链路 ===


@app.post("/tasks", response_model=ResourceRecord)
def create_task(body: TaskCreateRequest) -> ResourceRecord:
    """从原始链接创建提纯任务。stage=pending、status=None、stream_url=None。"""
    url = body.source_url.strip()
    rec = ResourceRecord(
        title=(body.title or url[:120]).strip(),
        source_url=url,
        source_kind=infer_source_kind(url),
        stream_url=None,
        stage=ResourceStage.pending,
        status=None,
        note=body.note.strip() if body.note else None,
    )
    append_resource(rec)
    return rec


@app.get("/tasks", response_model=TaskListResponse)
def list_tasks(stage: Optional[ResourceStage] = Query(None)) -> TaskListResponse:
    """工作台筛选；不传 stage 返回全部。"""
    items = load_resources()
    if stage is not None:
        items = [r for r in items if r.stage == stage]
    return TaskListResponse(tasks=items)


@app.post("/tasks/{rec_id}/probe", response_model=ResourceRecord)
def probe_task(rec_id: str) -> ResourceRecord:
    """同步触发 probe；先把 stage 标 probing 再执行，便于 UI 显示中间态。"""
    marked = update_resource(
        rec_id,
        lambda r: r.model_copy(update={"stage": ResourceStage.probing}),
    )
    if marked is None:
        raise HTTPException(status_code=404, detail="task not found")
    after = probe_record(marked)
    saved = update_resource(rec_id, lambda _r: after)
    if saved is None:
        raise HTTPException(status_code=404, detail="task vanished mid-probe")
    return saved


@app.post("/tasks/{rec_id}/enrich", response_model=ResourceRecord)
def enrich_task(rec_id: str) -> ResourceRecord:
    """对 magnet 任务做**纯字符串**富化：解析 info_hash / dn / trackers。

    刻意保留的边界：
    - 不联网，不 DHT，不 peer，不调用任何 BT 客户端。
    - 不写 status；不改 stage 至 playable/external_ready/failed。
    - 失败一律保持 stage=pending，错误写入 magnet.enrich_log。
    """
    items = load_resources()
    cur = next((r for r in items if r.id == rec_id), None)
    if cur is None:
        raise HTTPException(status_code=404, detail="task not found")
    if cur.source_kind != "magnet":
        raise HTTPException(
            status_code=409,
            detail=f"enrich only applies to magnet tasks, got source_kind={cur.source_kind}",
        )
    if not cur.source_url:
        raise HTTPException(status_code=409, detail="task has no source_url")

    prev_log: list[str] = list(cur.magnet.enrich_log) if cur.magnet else []

    try:
        parsed = parse_magnet(cur.source_url)
    except ValueError as exc:
        log = prev_log + [f"enrich failed: {exc}"]
        new_magnet = MagnetInfo(
            info_hash=cur.magnet.info_hash if cur.magnet else None,
            info_hash_v2=cur.magnet.info_hash_v2 if cur.magnet else None,
            info_hash_kind=cur.magnet.info_hash_kind if cur.magnet else "unknown",
            display_name=cur.magnet.display_name if cur.magnet else None,
            trackers=cur.magnet.trackers if cur.magnet else [],
            parsed_at=cur.magnet.parsed_at if cur.magnet else None,
            enrich_log=log[-ENRICH_LOG_MAX_ENTRIES:],
        )
        saved = update_resource(
            rec_id,
            lambda r: r.model_copy(update={"magnet": new_magnet}),
        )
        if saved is None:
            raise HTTPException(status_code=404, detail="task vanished mid-enrich")
        return saved

    merged_log = (prev_log + list(parsed.enrich_log))[-ENRICH_LOG_MAX_ENTRIES:]
    new_magnet = MagnetInfo(
        info_hash=parsed.info_hash,
        info_hash_v2=parsed.info_hash_v2,
        info_hash_kind=parsed.info_hash_kind,
        display_name=parsed.display_name,
        trackers=parsed.trackers,
        parsed_at=parsed.parsed_at,
        enrich_log=merged_log,
    )

    def _mut(r: ResourceRecord) -> ResourceRecord:
        # 仅当 title 仍是原始 magnet URL（截断版）时，才用 display_name 替换更友好。
        new_title = r.title
        if parsed.display_name and r.source_url:
            if r.title == r.source_url[:120]:
                new_title = parsed.display_name[:120]
        return r.model_copy(update={"magnet": new_magnet, "title": new_title})

    saved = update_resource(rec_id, _mut)
    if saved is None:
        raise HTTPException(status_code=404, detail="task vanished mid-enrich")
    return saved


@app.post("/tasks/{rec_id}/promote", response_model=ResourceRecord)
def promote_task(rec_id: str, body: PromoteRequest) -> ResourceRecord:
    """把任务推到可入列：写 stream_url + status，stage 推到 external_ready。

    仅 stage=playable / external_ready 可 promote；其它状态返回 409。
    这是**唯一**会回填 status 的入口；pending/probing/failed 永远不会被写 status。
    """
    items = load_resources()
    cur = next((r for r in items if r.id == rec_id), None)
    if cur is None:
        raise HTTPException(status_code=404, detail="task not found")
    if cur.stage not in (ResourceStage.playable, ResourceStage.external_ready):
        raise HTTPException(
            status_code=409,
            detail=(
                "can only promote from stage=playable/external_ready, "
                f"got stage={cur.stage.value}"
            ),
        )

    stream_url = body.stream_url.strip()

    def _mut(r: ResourceRecord) -> ResourceRecord:
        return r.model_copy(
            update={
                "stream_url": stream_url,
                "title": body.title.strip() if body.title else r.title,
                "status": body.target_status,
                "stage": ResourceStage.external_ready,
            }
        )

    saved = update_resource(rec_id, _mut)
    if saved is None:
        raise HTTPException(status_code=404, detail="task vanished mid-promote")
    return saved


# === PotPlayer 订阅入口（保持公网无 auth；Caddy 路由层已限定 /playlists/potplayer/*） ===


@app.get("/playlists/potplayer/default.m3u8")
def playlist_default() -> PlainTextResponse:
    body = default_playlist(load_resources())
    return PlainTextResponse(
        content=body,
        media_type="application/vnd.apple.mpegurl; charset=utf-8",
    )


@app.get("/playlists/potplayer/recent.m3u8")
def playlist_recent() -> PlainTextResponse:
    body = recent_playlist(load_resources())
    return PlainTextResponse(
        content=body,
        media_type="application/vnd.apple.mpegurl; charset=utf-8",
    )
