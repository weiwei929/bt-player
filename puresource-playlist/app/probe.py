"""无副作用 HTTP probe：判断链接是否疑似可播。

边界（刻意保留）：
- 仅做 HEAD / Range GET，**不下载**完整内容；读取上限 1 KiB。
- magnet / webpage / other / 非 http(s) 链接：probe 时一律 skip，保持 **pending**（第一版网页只登记不探测；绝不接入 BT/DHT/peer）。
- 网页 URL 不抓正文与 og:video。

输出：返回更新后的 ResourceRecord 副本（stage / probe_log / last_probed_at）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .models import (
    HTTP_SCHEMES,
    PROBE_LOG_MAX_LINE,
    ResourceRecord,
    ResourceStage,
)

PROBE_TIMEOUT_S = 5.0
PROBE_READ_LIMIT = 1024  # 1 KiB；用于 m3u8 magic / 头部嗅探

_VIDEO_CT_PREFIX = "video/"
_OCTET_CT = "application/octet-stream"
_M3U8_MAGIC = b"#EXTM3U"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trunc(s: str) -> str:
    return s[:PROBE_LOG_MAX_LINE]


def _settle(
    rec: ResourceRecord, stage: ResourceStage, log: list[str]
) -> ResourceRecord:
    return rec.model_copy(
        update={
            "stage": stage,
            "last_probed_at": _now_iso(),
            "probe_log": log,
        }
    )


def probe_record(rec: ResourceRecord) -> ResourceRecord:
    """对一条资源执行一次无副作用 probe。"""
    url = (rec.source_url or rec.stream_url or "").strip()
    log: list[str] = list(rec.probe_log)
    log.append(_trunc(f"{_now_iso()} probe start kind={rec.source_kind} url={url[:160]}"))

    if not url.lower().startswith(HTTP_SCHEMES):
        log.append(_trunc(f"{_now_iso()} skip: non-http url"))
        return _settle(rec, ResourceStage.pending, log)

    if rec.source_kind in ("magnet", "webpage", "other"):
        log.append(
            _trunc(
                f"{_now_iso()} skip: source_kind={rec.source_kind} "
                f"(第一版仅登记，不自动 HTTP probe)"
            )
        )
        return _settle(rec, ResourceStage.pending, log)

    try:
        with httpx.Client(timeout=PROBE_TIMEOUT_S, follow_redirects=True) as client:
            # 1) 先发 HEAD
            try:
                resp = client.head(url)
            except httpx.HTTPError as e:
                log.append(_trunc(f"{_now_iso()} HEAD error: {type(e).__name__}"))
                resp = None

            # 2) HEAD 不被支持或 4xx → 用 GET + Range 兜底
            need_fallback = resp is None or resp.status_code in (405, 501) or (
                resp.status_code >= 400 and resp.status_code < 500
            )
            if need_fallback:
                log.append(
                    _trunc(
                        f"{_now_iso()} HEAD "
                        f"{resp.status_code if resp is not None else 'err'} → fallback GET Range"
                    )
                )
                resp = client.get(url, headers={"Range": "bytes=0-1023"})

            sc = resp.status_code
            ct = resp.headers.get("content-type", "").lower()
            ar = resp.headers.get("accept-ranges", "").lower()
            cr = resp.headers.get("content-range", "")
            log.append(_trunc(f"{_now_iso()} resp {sc} ct={ct} ar={ar} cr={cr}"))

            if sc >= 400:
                log.append(_trunc(f"{_now_iso()} → failed (status>=400)"))
                return _settle(rec, ResourceStage.failed, log)

            # 3) m3u8：需要看 magic
            if rec.source_kind == "m3u8":
                if resp.request.method.upper() == "HEAD":
                    sniff = client.get(url, headers={"Range": "bytes=0-1023"})
                    body = sniff.content[:PROBE_READ_LIMIT]
                    log.append(_trunc(f"{_now_iso()} m3u8 sniff {sniff.status_code} bytes={len(body)}"))
                else:
                    body = resp.content[:PROBE_READ_LIMIT]
                if body.lstrip().startswith(_M3U8_MAGIC):
                    log.append(_trunc(f"{_now_iso()} → playable (#EXTM3U magic)"))
                    return _settle(rec, ResourceStage.playable, log)
                log.append(_trunc(f"{_now_iso()} → failed (no #EXTM3U magic)"))
                return _settle(rec, ResourceStage.failed, log)

            # 4) mp4：按 Content-Type + Accept-Ranges 判定（webpage 已在上方 skip）
            is_video_ct = ct.startswith(_VIDEO_CT_PREFIX)
            is_octet_with_ranges = ct.startswith(_OCTET_CT) and ar == "bytes"
            if is_video_ct or is_octet_with_ranges:
                log.append(_trunc(f"{_now_iso()} → playable (ct/ar ok)"))
                return _settle(rec, ResourceStage.playable, log)

            log.append(_trunc(f"{_now_iso()} → failed (ct={ct} not video; ar={ar})"))
            return _settle(rec, ResourceStage.failed, log)

    except httpx.HTTPError as e:
        log.append(_trunc(f"{_now_iso()} → failed (http error: {type(e).__name__}: {str(e)[:80]})"))
        return _settle(rec, ResourceStage.failed, log)
