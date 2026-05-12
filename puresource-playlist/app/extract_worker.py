"""yt-dlp 异步执行 worker（v0.3 T-1-01 / T-1-02）。

边界（刻意保留）：
- 与主服务（puresource-playlist）通过文件队列 + HTTP callback 解耦：
  主服务在 POST /tasks/{id}/extract 写 `<id>.json` 入 jobs_dir；worker
  原子 rename 为 `<id>.processing.json` 抢占；处理完后调
  POST /internal/tasks/{id}/extract-result 回写并 unlink claim 文件。
- 不直接读写 resources.json；只通过 callback 改主服务状态。
- 单实例进程；多 worker 由 rename 抢锁实现互斥。
- 启动时清理 stale claim（mtime 老于 STALE_PROCESSING_S 视为崩溃任务）。
- 失败 0 次重试（v0.3 §8 #9 裁决）。

启动：
    .venv/bin/python -m app.extract_worker

环境变量：
    PURESOURCE_DATA_DIR        与主服务同根（决定 jobs_dir 位置）
    PURESOURCE_MAIN_BASE       回写 callback 的主服务地址（默认 http://127.0.0.1:8090）
    PURESOURCE_YT_DLP_BIN      yt-dlp 二进制路径（默认 yt-dlp）
    PURESOURCE_COOKIES_DIR     cookies 白名单目录（与主服务一致即可）
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from .extract import run_yt_dlp
from .models import ExtractCandidate
from .store import jobs_dir

LOG = logging.getLogger("extract_worker")

POLL_INTERVAL_S = 2.0
HARD_TIMEOUT_S = 45  # 与 §6 Q3 推荐一致；一刀切，不做 per-job 自定义。
# 启动时若发现 *.processing.json 文件 mtime 大于此值，视为崩溃任务。
STALE_PROCESSING_S = HARD_TIMEOUT_S + 30
# callback HTTP 调用超时；不应因为主服务慢导致 worker 阻塞太久。
CALLBACK_TIMEOUT_S = 10.0

_stopping = False


def _main_service_base() -> str:
    return os.environ.get("PURESOURCE_MAIN_BASE", "http://127.0.0.1:8090")


def _scan_pending(d: Path) -> list[Path]:
    """列出待处理 job 文件（排除已被抢占的 *.processing.json）。"""
    out: list[Path] = []
    for p in d.glob("*.json"):
        if p.name.endswith(".processing.json"):
            continue
        out.append(p)
    return sorted(out)


def _claim(job_path: Path) -> Optional[Path]:
    """原子抢占：rename 失败说明被另一个 worker 抢走或文件已消失。"""
    new_path = job_path.with_suffix(".processing.json")
    try:
        job_path.rename(new_path)
    except FileNotFoundError:
        return None
    return new_path


def _read_job(p: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        LOG.error("invalid job file %s: %s", p, e)
        return None


def _post_result(
    task_id: str,
    *,
    status: str,
    candidates: Optional[list[ExtractCandidate]] = None,
    error: Optional[str] = None,
    log: Optional[list[str]] = None,
) -> bool:
    payload = {
        "status": status,
        "candidates": [c.model_dump(mode="json") for c in (candidates or [])],
        "error": error,
        "log": log or [],
    }
    url = f"{_main_service_base()}/internal/tasks/{task_id}/extract-result"
    try:
        with httpx.Client(timeout=CALLBACK_TIMEOUT_S) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
        return True
    except httpx.HTTPError as e:
        LOG.error("callback failed task_id=%s: %s", task_id, e)
        return False


def _cleanup_stale(d: Path) -> None:
    now = time.time()
    for p in d.glob("*.processing.json"):
        try:
            age = now - p.stat().st_mtime
        except FileNotFoundError:
            continue
        if age <= STALE_PROCESSING_S:
            continue
        LOG.warning("stale claim %s (age=%.0fs); marking failed", p.name, age)
        job = _read_job(p)
        if job and "task_id" in job:
            _post_result(
                job["task_id"],
                status="failed",
                error=f"worker_crashed_or_stale (age={int(age)}s)",
            )
        p.unlink(missing_ok=True)


def _process(claimed_path: Path) -> None:
    job = _read_job(claimed_path)
    if not job:
        claimed_path.unlink(missing_ok=True)
        return
    task_id = job.get("task_id")
    source_url = job.get("source_url")
    cookies_path = job.get("cookies_path")
    if not task_id or not source_url:
        LOG.error("job missing task_id/source_url: %s", claimed_path)
        claimed_path.unlink(missing_ok=True)
        return
    LOG.info("process task_id=%s url=%s", task_id, source_url[:80])
    try:
        status, candidates, log = run_yt_dlp(
            source_url, cookies_path=cookies_path, timeout=HARD_TIMEOUT_S
        )
    except Exception as e:
        LOG.exception("unexpected error")
        _post_result(
            task_id, status="failed", error=f"unexpected: {type(e).__name__}: {str(e)[:120]}"
        )
    else:
        _post_result(task_id, status=status, candidates=candidates, log=log)
    finally:
        claimed_path.unlink(missing_ok=True)


def _install_signals() -> None:
    def _stop(*_args: object) -> None:
        global _stopping
        _stopping = True
        LOG.info("stop signal received; will exit after current iteration")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    d = jobs_dir()
    LOG.info(
        "extract worker start; polling %s every %.1fs (hard_timeout=%ds)",
        d,
        POLL_INTERVAL_S,
        HARD_TIMEOUT_S,
    )
    _install_signals()
    _cleanup_stale(d)
    while not _stopping:
        pending = _scan_pending(d)
        for p in pending:
            if _stopping:
                break
            claimed = _claim(p)
            if claimed:
                _process(claimed)
        time.sleep(POLL_INTERVAL_S)
    LOG.info("extract worker exit (graceful)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
