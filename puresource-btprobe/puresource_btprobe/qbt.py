"""qBittorrent Web API 封装（v0.3 T-2-02）。

边界（刻意保留）：
- 仅承载 add / files / info / setFilePrio / delete 五个调用；不接管 magnet 解析、
  不接管文件树呈现、不直接 callback 主服务（那是 prober 的事）。
- 凭据走环境变量（QBT_BASE_URL / QBT_USER / QBT_PASS），永不读 puresource-playlist
  的 resources.json。
- 所有 HTTP 调用都有超时；失败抛 QbtError，由 prober 决定是否回写 failed。
- mock 模式（QBT_MOCK=1）：返回固定的"假 metadata"，让端到端测试不依赖真实 qBittorrent。

关键原则：**add 后立即 setFilePrio=0，不让 piece 真的下载到磁盘**——这是
"探测器，不是缓存执行器"边界的代码体现。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
QBT_REQUEST_TIMEOUT_S = 10.0
# magnet metadata 拉取的最长等待。冷门种子超过此值直接放弃，避免 worker 占用。
DEFAULT_METADATA_WAIT_S = 90
METADATA_POLL_INTERVAL_S = 1.5

# magnet URI 中 info_hash 的快速提取（用于 qBittorrent /files?hash=）
# 与 puresource-playlist app/magnet.py 同口径，但只取 v1 hex40。
_RE_BTIH_HEX40 = re.compile(r"urn:btih:([0-9a-fA-F]{40})", re.IGNORECASE)


class QbtError(RuntimeError):
    """qBittorrent 调用失败（认证、超时、metadata 拉不到、删除失败等）。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_mock() -> bool:
    return os.environ.get("QBT_MOCK", "").strip() in ("1", "true", "yes")


def _base_url() -> str:
    return os.environ.get("QBT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _credentials() -> tuple[Optional[str], Optional[str]]:
    return os.environ.get("QBT_USER"), os.environ.get("QBT_PASS")


def _extract_info_hash(magnet: str) -> Optional[str]:
    """从 magnet URI 提取 v1 info_hash（40 hex 小写）；其它形式返回 None。"""
    m = _RE_BTIH_HEX40.search(magnet)
    if m:
        return m.group(1).lower()
    return None


@dataclass
class ProbeResult:
    """qbt.run_probe 的返回值；prober 据此构造 callback payload。"""

    status: str  # "ok" | "failed"
    files: list[dict[str, Any]]
    peer_count: Optional[int]
    seed_count: Optional[int]
    probed_at: Optional[str]
    main_file_index: Optional[int]
    error: Optional[str]
    log: list[str]


# === 真·qBittorrent 路径 ===


class _QbtClient:
    """同步 qBittorrent Web API 客户端（仅在非 mock 路径使用）。

    复用一个 httpx.Client 维持 cookie 会话；使用 with 语句保证关闭。
    """

    def __init__(self, base_url: str, user: Optional[str], password: Optional[str]) -> None:
        self.base_url = base_url
        self.user = user
        self.password = password
        self._client = httpx.Client(timeout=QBT_REQUEST_TIMEOUT_S)

    def __enter__(self) -> "_QbtClient":
        if self.user and self.password:
            self._login()
        return self

    def __exit__(self, *_args: object) -> None:
        self._client.close()

    def _login(self) -> None:
        r = self._client.post(
            f"{self.base_url}/api/v2/auth/login",
            data={"username": self.user, "password": self.password},
            headers={"Referer": self.base_url},
        )
        if r.status_code != 200 or r.text.strip().lower() != "ok.":
            raise QbtError(f"qBittorrent login failed: status={r.status_code} body={r.text[:80]!r}")

    def add_paused(self, magnet: str) -> None:
        """添加 magnet 仅探测 metadata。

        qBittorrent 4.5+ 必须 paused=false 才会主动连 DHT/tracker 拉 metadata；
        stopCondition=MetadataReceived 保证拿到 metadata 后立即自动 paused，
        组合起来等价于"只探测、不下载内容"。
        函数名保留以维持向后兼容（含义已迁移）。
        """
        r = self._client.post(
            f"{self.base_url}/api/v2/torrents/add",
            data={
                "urls": magnet,
                "paused": "false",
                "skip_checking": "true",
                "stopCondition": "MetadataReceived",  # qBittorrent 4.5+
            },
        )
        if r.status_code >= 400:
            raise QbtError(f"add failed: status={r.status_code} body={r.text[:80]!r}")

    def info(self, info_hash: str) -> Optional[dict[str, Any]]:
        r = self._client.get(
            f"{self.base_url}/api/v2/torrents/info",
            params={"hashes": info_hash},
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            return None
        return rows[0]

    def files(self, info_hash: str) -> list[dict[str, Any]]:
        r = self._client.get(
            f"{self.base_url}/api/v2/torrents/files",
            params={"hash": info_hash},
        )
        r.raise_for_status()
        out = r.json()
        return out if isinstance(out, list) else []

    def set_all_files_zero_prio(self, info_hash: str, file_count: int) -> None:
        if file_count <= 0:
            return
        r = self._client.post(
            f"{self.base_url}/api/v2/torrents/filePrio",
            data={
                "hash": info_hash,
                "id": "|".join(str(i) for i in range(file_count)),
                "priority": "0",
            },
        )
        if r.status_code >= 400:
            raise QbtError(f"filePrio failed: status={r.status_code}")

    def delete(self, info_hash: str) -> None:
        # deleteFiles=true：把任何已写入磁盘的 piece 一并清掉
        r = self._client.post(
            f"{self.base_url}/api/v2/torrents/delete",
            data={"hashes": info_hash, "deleteFiles": "true"},
        )
        if r.status_code >= 400:
            raise QbtError(f"delete failed: status={r.status_code}")


def _pick_main_file(files: list[dict[str, Any]]) -> Optional[int]:
    """正片推荐：在文件列表里找最大的视频文件。

    极简启发式：扩展名落在 video_exts 内 → 取 size_bytes 最大者。
    无视频文件则返回 None。
    """
    video_exts = (".mp4", ".mkv", ".ts", ".m4v", ".mov", ".avi", ".webm", ".flv", ".wmv")
    best_idx: Optional[int] = None
    best_size = -1
    for i, f in enumerate(files):
        path = (f.get("path") or "").lower()
        size = int(f.get("size_bytes") or 0)
        if not path.endswith(video_exts):
            continue
        if size > best_size:
            best_size = size
            best_idx = i
    return best_idx


def _normalize_files(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """qBittorrent /files 返回的 dict 转成主服务 MagnetFile 字段。"""
    out: list[dict[str, Any]] = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        out.append(
            {
                "path": str(f.get("name") or "")[:512],
                "size_bytes": int(f.get("size") or 0),
                "is_recommended_main": False,
            }
        )
    return out


def _mock_probe(magnet: str) -> ProbeResult:
    """mock 模式产物：固定文件树，便于端到端测试不依赖真实 qBittorrent。"""
    log: list[str] = [f"{_now_iso()} mock=1 magnet[:60]={magnet[:60]}"]
    files = [
        {"path": "Sample/sample.mp4", "size_bytes": 15 * 1024 * 1024, "is_recommended_main": False},
        {"path": "Movie.mp4", "size_bytes": 4_300_000_000, "is_recommended_main": False},
        {"path": "Cover.jpg", "size_bytes": 200 * 1024, "is_recommended_main": False},
        {"path": "Subtitles/eng.srt", "size_bytes": 50_000, "is_recommended_main": False},
    ]
    main_idx = _pick_main_file(files)
    if main_idx is not None:
        files[main_idx]["is_recommended_main"] = True
    return ProbeResult(
        status="ok",
        files=files,
        peer_count=12,
        seed_count=5,
        probed_at=_now_iso(),
        main_file_index=main_idx,
        error=None,
        log=log,
    )


def run_probe(magnet: str, *, wait_s: int = DEFAULT_METADATA_WAIT_S) -> ProbeResult:
    """同步执行一次 metadata 探测。

    流程：
    1. 提取 info_hash。
    2. add_paused(magnet)，立即 setFilePrio=0（双保险，metadata 拉到后再调一次）。
    3. 轮询 info 直到 metadata 到位（state ∈ pausedDL/uploading/...，size > 0）。
    4. 拉文件列表，标记正片。
    5. 删除任务（清掉任何残留 piece）。
    """
    log: list[str] = []
    if _is_mock():
        return _mock_probe(magnet)

    info_hash = _extract_info_hash(magnet)
    if not info_hash:
        return ProbeResult(
            status="failed",
            files=[],
            peer_count=None,
            seed_count=None,
            probed_at=_now_iso(),
            main_file_index=None,
            error="cannot extract v1 info_hash from magnet",
            log=[f"{_now_iso()} no btih hex40 in magnet"],
        )

    base_url = _base_url()
    user, password = _credentials()
    log.append(f"{_now_iso()} qbt={base_url} hash={info_hash}")

    try:
        with _QbtClient(base_url, user, password) as client:
            client.add_paused(magnet)
            log.append(f"{_now_iso()} add_paused ok")
            # 轮询 metadata
            deadline = time.monotonic() + wait_s
            torrent_info: Optional[dict[str, Any]] = None
            while time.monotonic() < deadline:
                torrent_info = client.info(info_hash)
                if torrent_info and (torrent_info.get("size") or 0) > 0:
                    break
                time.sleep(METADATA_POLL_INTERVAL_S)
            if not torrent_info or (torrent_info.get("size") or 0) == 0:
                log.append(f"{_now_iso()} metadata timeout after {wait_s}s")
                _safe_delete(client, info_hash, log)
                return ProbeResult(
                    status="failed",
                    files=[],
                    peer_count=None,
                    seed_count=None,
                    probed_at=_now_iso(),
                    main_file_index=None,
                    error=f"metadata not received in {wait_s}s",
                    log=log,
                )

            raw_files = client.files(info_hash)
            files = _normalize_files(raw_files)
            client.set_all_files_zero_prio(info_hash, len(files))
            main_idx = _pick_main_file(files)
            if main_idx is not None:
                files[main_idx]["is_recommended_main"] = True
            peer_count = int(torrent_info.get("num_leechs") or 0)
            seed_count = int(torrent_info.get("num_seeds") or 0)
            log.append(
                f"{_now_iso()} metadata ok files={len(files)} peers={peer_count} seeds={seed_count}"
            )
            _safe_delete(client, info_hash, log)
            return ProbeResult(
                status="ok",
                files=files,
                peer_count=peer_count,
                seed_count=seed_count,
                probed_at=_now_iso(),
                main_file_index=main_idx,
                error=None,
                log=log,
            )
    except QbtError as e:
        log.append(f"{_now_iso()} QbtError: {e}")
        return ProbeResult(
            status="failed",
            files=[],
            peer_count=None,
            seed_count=None,
            probed_at=_now_iso(),
            main_file_index=None,
            error=str(e)[:200],
            log=log,
        )
    except httpx.HTTPError as e:
        log.append(f"{_now_iso()} HTTPError: {type(e).__name__}: {str(e)[:120]}")
        return ProbeResult(
            status="failed",
            files=[],
            peer_count=None,
            seed_count=None,
            probed_at=_now_iso(),
            main_file_index=None,
            error=f"{type(e).__name__}: {str(e)[:200]}",
            log=log,
        )


def _safe_delete(client: _QbtClient, info_hash: str, log: list[str]) -> None:
    """删除时不抛异常；删除失败仅留痕，不影响返回结果。"""
    try:
        client.delete(info_hash)
        log.append(f"{_now_iso()} delete ok")
    except Exception as e:  # noqa: BLE001
        log.append(f"{_now_iso()} delete failed (ignored): {type(e).__name__}: {str(e)[:80]}")
