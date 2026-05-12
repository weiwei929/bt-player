from __future__ import annotations

from .models import ResourceRecord
from .store import eligible_for_playlist


def _escape_extinf_title(title: str) -> str:
    return title.replace("\n", " ").replace("\r", " ").replace(",", " ")


def build_m3u8(entries: list[ResourceRecord], header_comment: str) -> str:
    """PotPlayer 外部播放列表（M3U），非 HLS 分片。"""
    lines: list[str] = [
        "#EXTM3U",
        "# PureSource playlist router — not HLS segments",
        f"# {header_comment}",
    ]
    for r in entries:
        # eligible_for_playlist 已经校验 stream_url 与 status；此处再做防御性检查
        if not r.stream_url or r.status is None:
            continue
        title = _escape_extinf_title(f"{r.title} [{r.status.value}]")
        lines.append(f"#EXTINF:-1,{title}")
        lines.append(r.stream_url)
    return "\n".join(lines) + "\n"


def default_playlist(resources: list[ResourceRecord]) -> str:
    eligible = [r for r in resources if eligible_for_playlist(r)]
    eligible.sort(key=lambda x: x.created_at)
    return build_m3u8(eligible, "default: all eligible resources")


def recent_playlist(resources: list[ResourceRecord], limit: int = 20) -> str:
    eligible = [r for r in resources if eligible_for_playlist(r)]
    eligible.sort(key=lambda x: x.created_at, reverse=True)
    return build_m3u8(eligible[:limit], f"recent: last {limit} eligible by created_at")
