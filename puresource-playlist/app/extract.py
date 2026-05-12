"""yt-dlp subprocess 封装 + cookies 白名单（v0.3 T-1-02 / T-1-03）。

边界（刻意保留）：
- 仅承载 yt-dlp `--dump-json` 调用与 cookies 路径白名单解析；不调度任务。
- 不直接读写 ResourceRecord / resources.json；产出 ExtractCandidate 列表
  交由 worker 通过 callback 回写主服务。
- subprocess 硬超时；失败 0 次重试（v0.3 §8 #9 裁决）。
- 不接 yt-dlp Python 包；用 subprocess 隔离失败域，避免 yt-dlp 崩溃拖垮 worker。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import ExtractCandidate

# 与 §6 Q3 推荐一致；调用方可以传更小值，不应传更大。
DEFAULT_TIMEOUT_S = 45
DEFAULT_YT_DLP_BIN = "yt-dlp"
COOKIES_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}\.txt$")
DEFAULT_COOKIES_DIR = "/var/lib/puresource/cookies"


class ExtractError(RuntimeError):
    """yt-dlp 调用失败（超时、非零退出、解析失败）。worker 用它分流。"""


class CookiesError(ValueError):
    """cookies_name 不合法或文件不存在/不可读。主服务返回 400。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cookies_dir() -> Path:
    """cookies 白名单目录。开发/测试通过 PURESOURCE_COOKIES_DIR 隔离。"""
    return Path(
        os.environ.get("PURESOURCE_COOKIES_DIR", DEFAULT_COOKIES_DIR)
    ).expanduser().resolve()


def resolve_cookies(cookies_name: Optional[str]) -> Optional[Path]:
    """把用户给的 cookies_name 解析为绝对路径。

    规则（§2 D7 + §6 Q3 安全要求）：
    - 必须匹配 `^[a-zA-Z0-9_-]{1,64}\\.txt$`
    - 拼接固定目录前缀；resolve 后必须仍在 cookies_dir 之下（防 ../ 越界）
    - 文件必须存在
    - POSIX 平台：owner 必须等于当前进程 euid（防越权读他人 cookies）
    """
    if cookies_name is None:
        return None
    if not COOKIES_NAME_RE.match(cookies_name):
        raise CookiesError(
            f"cookies_name 必须匹配 [a-zA-Z0-9_-]{{1,64}}.txt，得到: {cookies_name[:32]!r}"
        )
    base = _cookies_dir()
    if not base.is_dir():
        raise CookiesError(f"cookies 目录不存在: {base}")
    candidate = (base / cookies_name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise CookiesError("cookies_name 解析后越界") from None
    if not candidate.is_file():
        raise CookiesError(f"cookies 文件不存在: {cookies_name}")
    if hasattr(os, "geteuid"):
        st = candidate.stat()
        euid = os.geteuid()
        if st.st_uid != euid:
            raise CookiesError(
                f"cookies 文件 owner 不匹配（uid={st.st_uid} vs euid={euid}）"
            )
    return candidate


def _yt_dlp_bin() -> str:
    """yt-dlp 二进制路径。测试时可用 PURESOURCE_YT_DLP_BIN 注入 stub。"""
    return os.environ.get("PURESOURCE_YT_DLP_BIN", DEFAULT_YT_DLP_BIN)


def _format_res(w: object, h: object) -> Optional[str]:
    if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
        return f"{w}x{h}"
    return None


def _info_to_candidate(
    info: dict, extracted_at: str, base_title: Optional[str] = None
) -> Optional[ExtractCandidate]:
    """把 yt-dlp 单个 info_dict 或 format dict 转成 ExtractCandidate。

    跳过没有 url 的占位条目（yt-dlp 在 manifest 阶段会先吐空 url）。
    """
    url = info.get("url") or info.get("manifest_url")
    if not url or not isinstance(url, str):
        return None
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    title = info.get("title") or base_title or url[:80]
    container = info.get("ext")
    res = info.get("resolution") or _format_res(info.get("width"), info.get("height"))
    tbr = info.get("tbr") or info.get("vbr")
    bitrate_kbps = int(tbr) if isinstance(tbr, (int, float)) and tbr > 0 else None
    format_id = info.get("format_id")
    try:
        return ExtractCandidate(
            title=str(title)[:512],
            stream_url=url[:4096],
            container=str(container)[:32] if container else None,
            resolution=str(res)[:32] if res else None,
            bitrate_kbps=bitrate_kbps,
            format_id=str(format_id)[:64] if format_id else None,
            extracted_at=extracted_at,
        )
    except Exception:
        # pydantic 校验失败（例如非 http 的 url 在边界外被换成了 ftp://）→ 当作不可用候选丢弃。
        return None


def parse_dump_json(stdout: str) -> list[ExtractCandidate]:
    """解析 yt-dlp `--dump-json` 输出。

    yt-dlp 默认每行一个 JSON 对象（playlist 多行、单视频一行）。
    每个对象自身可作为一个候选；其 `formats` 子数组每条也作为候选。
    最后按 stream_url 去重，保持解析顺序。
    """
    candidates: list[ExtractCandidate] = []
    now = _now_iso()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(info, dict):
            continue
        cand = _info_to_candidate(info, now)
        if cand:
            candidates.append(cand)
        formats = info.get("formats") or []
        if isinstance(formats, list):
            base_title = info.get("title")
            for fmt in formats:
                if not isinstance(fmt, dict):
                    continue
                cand = _info_to_candidate(fmt, now, base_title=base_title)
                if cand:
                    candidates.append(cand)
    seen: set[str] = set()
    deduped: list[ExtractCandidate] = []
    for c in candidates:
        if c.stream_url in seen:
            continue
        seen.add(c.stream_url)
        deduped.append(c)
    return deduped


def run_yt_dlp(
    source_url: str,
    *,
    cookies_path: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> tuple[str, list[ExtractCandidate], list[str]]:
    """同步调用 yt-dlp --dump-json，返回 (status, candidates, log)。

    status: "ok" | "failed"
    candidates: 解析后的候选列表（至少 1 条才返回 "ok"）
    log: 简短诊断信息，回写到 ResourceRecord.probe_log
    """
    binary = _yt_dlp_bin()
    cmd = [
        binary,
        "--dump-json",
        "--no-playlist",
        "--ignore-errors",
        "--no-warnings",
        source_url,
    ]
    if cookies_path:
        cmd.extend(["--cookies", str(cookies_path)])
    log: list[str] = [f"{_now_iso()} cmd={shlex.join(cmd)[:200]}"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.append(f"{_now_iso()} timeout after {timeout}s")
        return "failed", [], log
    except FileNotFoundError:
        log.append(f"{_now_iso()} yt-dlp binary not found: {binary}")
        return "failed", [], log
    log.append(
        f"{_now_iso()} exit={result.returncode} stdout_bytes={len(result.stdout)}"
    )
    if result.returncode != 0:
        first = (result.stderr or "").splitlines()[:1]
        if first:
            log.append(f"{_now_iso()} stderr0={first[0][:200]}")
        return "failed", [], log
    candidates = parse_dump_json(result.stdout)
    if not candidates:
        log.append(f"{_now_iso()} no candidates parsed")
        return "failed", [], log
    log.append(f"{_now_iso()} parsed {len(candidates)} candidates")
    return "ok", candidates, log
