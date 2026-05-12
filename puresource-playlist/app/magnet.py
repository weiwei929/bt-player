"""magnet URI 解析（v0.3 PoC 1a）。

边界（刻意保留）：
- 纯字符串解析，**零网络、零 BT 协议**。
- 不接 DHT / tracker announce / peer，不调 libtorrent / rqbit / qBittorrent。
- 仅产出 info_hash / info_hash_v2 / display_name / trackers / kind。

供 `POST /tasks/{id}/enrich` 使用：把 magnet 资源从"黑盒 pending"
变成"可读 pending"，但 stage / status / 列表准入逻辑完全不变。
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlsplit

# v1 (BitTorrent v1, SHA-1)：40 hex 或 32 char base32
# v2 (BitTorrent v2, SHA-256 multihash)：64 hex，multihash 前缀 1220（前 4 字符）
_RE_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
_RE_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_RE_B32_32 = re.compile(r"^[A-Z2-7]{32}$")
_BTMH_V2_PREFIX = "1220"  # multihash: sha-256 (0x12) + length 32 (0x20)


@dataclass
class ParsedMagnet:
    """magnet 解析结果；上层包成 MagnetInfo（pydantic）入库。"""

    info_hash: Optional[str] = None       # 归一化 40 位小写 hex（v1）
    info_hash_v2: Optional[str] = None    # 64 位小写 hex（v2）
    info_hash_kind: str = "unknown"       # "v1" | "v2" | "v1+v2" | "unknown"
    display_name: Optional[str] = None
    trackers: list[str] = field(default_factory=list)
    parsed_at: str = ""
    enrich_log: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_btih(value: str) -> Optional[str]:
    """从 xt 中的 `urn:btih:XXX` 抽 v1 info_hash，归一化为 40 位小写 hex。"""
    v = value.strip()
    if _RE_HEX40.match(v):
        return v.lower()
    up = v.upper()
    if _RE_B32_32.match(up):
        try:
            raw = base64.b32decode(up)
        except binascii.Error:
            return None
        if len(raw) != 20:
            return None
        return raw.hex()
    return None


def _parse_btmh(value: str) -> Optional[str]:
    """从 xt 中的 `urn:btmh:XXX` 抽 v2 multihash，要求 sha-256 (前缀 1220)。

    返回 64 位小写 hex（不含前缀），方便人类对照。
    """
    v = value.strip().lower()
    if not _RE_HEX64.match(v.upper().lower()):
        # 可能是 1220 前缀 + 64 hex；按 multihash 规范处理
        if v.startswith(_BTMH_V2_PREFIX) and len(v) == 68:
            tail = v[4:]
            if _RE_HEX64.match(tail.upper().lower()):
                return tail
        return None
    return v


def parse_magnet(uri: str) -> ParsedMagnet:
    """解析 magnet URI；任何异常都包成 ValueError 抛出。

    成功路径：返回 ParsedMagnet。
    失败路径（非 magnet / xt 缺失 / 编码异常）：raise ValueError。
    """
    raw = (uri or "").strip()
    if not raw.lower().startswith("magnet:"):
        raise ValueError("not a magnet URI")

    # urllib 把 magnet:?xt=... 看作 scheme=magnet, path='', query='xt=...'。
    split = urlsplit(raw)
    qs = split.query or ""
    if not qs:
        # magnet: 后没有 ? 直接是参数（少见）：手工兼容 magnet:xt=...
        if raw.lower().startswith("magnet:?"):
            qs = raw.split("?", 1)[1]
        elif raw.lower().startswith("magnet:"):
            qs = raw.split(":", 1)[1]
        else:
            raise ValueError("magnet URI 缺少查询串")

    items = parse_qsl(qs, keep_blank_values=False, strict_parsing=False)

    result = ParsedMagnet()
    result.parsed_at = _now_iso()
    result.enrich_log.append(f"{result.parsed_at} parse start uri[:120]={raw[:120]}")

    xt_values: list[str] = []
    seen_trackers: set[str] = set()
    for key, value in items:
        k = key.lower()
        if k == "xt":
            xt_values.append(value)
        elif k == "dn" and result.display_name is None:
            result.display_name = value
        elif k == "tr":
            t = (value or "").strip()
            if t and t not in seen_trackers:
                seen_trackers.add(t)
                result.trackers.append(t)

    if not xt_values:
        raise ValueError("magnet URI 缺少 xt 字段")

    for xt in xt_values:
        low = xt.lower()
        if low.startswith("urn:btih:"):
            ih = _parse_btih(xt.split(":", 2)[-1])
            if ih and result.info_hash is None:
                result.info_hash = ih
                result.enrich_log.append(f"{_now_iso()} xt=v1 info_hash={ih}")
        elif low.startswith("urn:btmh:"):
            mh = _parse_btmh(xt.split(":", 2)[-1])
            if mh and result.info_hash_v2 is None:
                result.info_hash_v2 = mh
                result.enrich_log.append(f"{_now_iso()} xt=v2 info_hash_v2={mh}")
        else:
            result.enrich_log.append(f"{_now_iso()} xt skipped: {low[:60]}")

    if result.info_hash and result.info_hash_v2:
        result.info_hash_kind = "v1+v2"
    elif result.info_hash:
        result.info_hash_kind = "v1"
    elif result.info_hash_v2:
        result.info_hash_kind = "v2"
    else:
        raise ValueError("magnet URI 的 xt 字段均无法解析为 v1/v2 info_hash")

    result.enrich_log.append(
        f"{_now_iso()} ok kind={result.info_hash_kind} dn={'yes' if result.display_name else 'no'} trackers={len(result.trackers)}"
    )
    return result
