"""tests/test_magnet.py — magnet URI 解析单测（stdlib unittest，零依赖）。

边界：仅验证字符串解析逻辑；不访问网络。
跑法：
    cd /root/bt-player-new/puresource-playlist
    python -m unittest tests.test_magnet -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 允许 `python -m unittest` 与 `python tests/test_magnet.py` 两种入口
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.magnet import parse_magnet  # noqa: E402


SAMPLE_V1 = (
    "magnet:?xt=urn:btih:2CBB4A34738EEFC45A677E4848A303ABA9412798"
)
SAMPLE_V1_LOWER = "2cbb4a34738eefc45a677e4848a303aba9412798"


class ParseMagnetTests(unittest.TestCase):
    def test_v1_hex40_lowercased(self) -> None:
        r = parse_magnet(SAMPLE_V1)
        self.assertEqual(r.info_hash, SAMPLE_V1_LOWER)
        self.assertEqual(r.info_hash_kind, "v1")
        self.assertIsNone(r.info_hash_v2)
        self.assertIsNone(r.display_name)
        self.assertEqual(r.trackers, [])
        self.assertTrue(r.parsed_at)

    def test_v1_full_with_dn_and_trackers(self) -> None:
        uri = (
            "magnet:?xt=urn:btih:2CBB4A34738EEFC45A677E4848A303ABA9412798"
            "&dn=Big%20Buck%20Bunny%20%282008%29"
            "&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
            "&tr=udp%3A%2F%2Ftracker.openbittorrent.com%3A6969%2Fannounce"
        )
        r = parse_magnet(uri)
        self.assertEqual(r.info_hash, SAMPLE_V1_LOWER)
        self.assertEqual(r.display_name, "Big Buck Bunny (2008)")
        self.assertEqual(
            r.trackers,
            [
                "udp://tracker.opentrackr.org:1337/announce",
                "udp://tracker.openbittorrent.com:6969/announce",
            ],
        )

    def test_v1_base32(self) -> None:
        # 同一 info_hash 的 base32 形式：必须解码出同样的 40 位 hex。
        # 用 stdlib 自己生成 base32 副本，避免硬编码出错。
        import base64

        raw = bytes.fromhex(SAMPLE_V1_LOWER)
        b32 = base64.b32encode(raw).decode("ascii")  # 32 字符
        uri = f"magnet:?xt=urn:btih:{b32}"
        r = parse_magnet(uri)
        self.assertEqual(r.info_hash, SAMPLE_V1_LOWER)
        self.assertEqual(r.info_hash_kind, "v1")

    def test_v2_btmh_sha256(self) -> None:
        # v2 multihash：sha-256(0x12) + len(0x20) + 32 字节摘要 → 共 68 hex
        digest = "ab" * 32  # 64 hex
        uri = f"magnet:?xt=urn:btmh:1220{digest}"
        r = parse_magnet(uri)
        self.assertIsNone(r.info_hash)
        self.assertEqual(r.info_hash_v2, digest)
        self.assertEqual(r.info_hash_kind, "v2")

    def test_v1_and_v2_combined(self) -> None:
        digest = "cd" * 32
        uri = (
            f"magnet:?xt=urn:btih:{SAMPLE_V1_LOWER.upper()}"
            f"&xt=urn:btmh:1220{digest}"
        )
        r = parse_magnet(uri)
        self.assertEqual(r.info_hash, SAMPLE_V1_LOWER)
        self.assertEqual(r.info_hash_v2, digest)
        self.assertEqual(r.info_hash_kind, "v1+v2")

    def test_reject_non_magnet(self) -> None:
        with self.assertRaises(ValueError):
            parse_magnet("https://example.com/foo.mp4")

    def test_reject_missing_xt(self) -> None:
        with self.assertRaises(ValueError):
            parse_magnet("magnet:?dn=bad")

    def test_reject_garbage_xt(self) -> None:
        with self.assertRaises(ValueError):
            parse_magnet("magnet:?xt=urn:btih:NOT_A_VALID_HASH")

    def test_trackers_dedup_and_strip(self) -> None:
        same = "udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
        uri = (
            "magnet:?xt=urn:btih:2CBB4A34738EEFC45A677E4848A303ABA9412798"
            f"&tr={same}&tr={same}"
        )
        r = parse_magnet(uri)
        self.assertEqual(len(r.trackers), 1)

    def test_extra_xt_skipped_does_not_break(self) -> None:
        uri = (
            "magnet:?xt=urn:btih:2CBB4A34738EEFC45A677E4848A303ABA9412798"
            "&xt=urn:custom:foobar"
        )
        r = parse_magnet(uri)
        self.assertEqual(r.info_hash, SAMPLE_V1_LOWER)
        self.assertEqual(r.info_hash_kind, "v1")
        self.assertTrue(any("xt skipped" in line for line in r.enrich_log))


if __name__ == "__main__":
    unittest.main()
