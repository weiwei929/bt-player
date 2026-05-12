"""puresource-btprobe FastAPI 入口（v0.3 T-2-01 + T-2-04）。

边界：
- 仅暴露 GET /health 和 POST /probe 两个端点。
- 不读 puresource-playlist 的 resources.json；不持有任何主服务状态。
- POST /probe 立即返回 ack；metadata 拉取在后台 asyncio.create_task() 跑。
- 完成后 callback 主服务给的 callback_url；调用失败仅日志，不重试。
- 重启后正在拉 metadata 的任务会丢失（v0.3 §8 #9 裁决：0 次重试是可接受的）；
  主服务侧的 stale 检测留到 v0.4。

启动：
    cd /root/bt-player-new/puresource-btprobe
    /root/bt-player-new/puresource-playlist/.venv/bin/uvicorn \\
        puresource_btprobe.main:app --host 127.0.0.1 --port 8091

环境变量：
    QBT_BASE_URL    qBittorrent Web UI 地址（默认 http://127.0.0.1:8080）
    QBT_USER        qBittorrent 用户名
    QBT_PASS        qBittorrent 密码
    QBT_MOCK        若为 1，跳过真实 qBittorrent 调用，返回固定假数据
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import FastAPI

from .models import (
    BTPROBE_FILES_MAX,
    BtProbeResultPayload,
    ProbeAck,
    ProbeRequest,
)
from .qbt import ProbeResult, run_probe

LOG = logging.getLogger("puresource_btprobe")

# callback HTTP 超时；不应让主服务慢拖死 bt-probe worker。
CALLBACK_TIMEOUT_S = 10.0

app = FastAPI(
    title="puresource-btprobe",
    description="独立 BT metadata 探测子服务（fire-and-forget + callback）",
    version="0.3.0",
)


@app.on_event("startup")
async def _on_startup() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    LOG.info("puresource-btprobe startup")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "puresource-btprobe"}


@app.post("/probe", response_model=ProbeAck)
async def probe(body: ProbeRequest) -> ProbeAck:
    """接受探测请求；立即返回 ack，后台执行 metadata 拉取与 callback。"""
    asyncio.create_task(_probe_and_callback(body))
    return ProbeAck(task_id=body.task_id, note="queued; result will arrive via callback")


async def _probe_and_callback(req: ProbeRequest) -> None:
    """后台任务：跑 qBittorrent 探测 → 把结果 callback 主服务。

    qBittorrent 调用本身是同步阻塞的（httpx 同步客户端 + time.sleep 轮询），
    所以放到 asyncio executor 里跑，避免阻塞 event loop。
    """
    LOG.info("probe start task_id=%s magnet[:60]=%s", req.task_id, req.magnet[:60])
    loop = asyncio.get_running_loop()
    try:
        result: ProbeResult = await loop.run_in_executor(None, run_probe, req.magnet)
    except Exception as e:  # noqa: BLE001
        LOG.exception("run_probe unexpected")
        await _post_callback(
            req,
            payload={
                "status": "failed",
                "files": [],
                "peer_count": None,
                "seed_count": None,
                "probed_at": None,
                "main_file_index": None,
                "error": f"unexpected: {type(e).__name__}: {str(e)[:120]}",
                "log": [],
            },
        )
        return

    payload: dict[str, Any] = {
        "status": result.status,
        "files": result.files[:BTPROBE_FILES_MAX],
        "peer_count": result.peer_count,
        "seed_count": result.seed_count,
        "probed_at": result.probed_at,
        "main_file_index": result.main_file_index,
        "error": result.error,
        "log": result.log,
    }
    # 防御性：用模型 round-trip 一次，杜绝字段拼写错误悄悄漏到主服务。
    BtProbeResultPayload.model_validate(payload)
    await _post_callback(req, payload=payload)


async def _post_callback(req: ProbeRequest, *, payload: dict[str, Any]) -> None:
    LOG.info(
        "callback task_id=%s status=%s files=%d url=%s",
        req.task_id,
        payload.get("status"),
        len(payload.get("files") or []),
        req.callback_url,
    )
    try:
        async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT_S) as client:
            r = await client.post(req.callback_url, json=payload)
            r.raise_for_status()
    except httpx.HTTPError as e:
        LOG.error("callback failed task_id=%s: %s", req.task_id, e)
