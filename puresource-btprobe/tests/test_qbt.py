"""tests/test_qbt.py — qBittorrent 封装与 magnet 解析单测（v0.3 T-2-02）。

边界：
- 仅验证纯函数 / mock 路径；不联网，不调真实 qBittorrent。
- 真实 qBittorrent 路径（_QbtClient）属集成测试，不在 unit test 覆盖范围。

跑法：
    cd /root/bt-player-new/puresource-btprobe
    /root/bt-player-new/puresource-playlist/.venv/bin/python -m unittest tests.test_qbt -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puresource_btprobe.models import (  # noqa: E402
    BtProbeResultPayload,
    ProbeRequest,
)
from puresource_btprobe.qbt import (  # noqa: E402
    _extract_info_hash,
    _is_mock,
    _normalize_files,
    _pick_main_file,
    run_probe,
)


# === info_hash 提取 ===


class InfoHashTests(unittest.TestCase):
    def test_v1_hex40_lower(self) -> None:
        magnet = "magnet:?xt=urn:btih:2cbb4a8f1d3e5e8c1234567890abcdef12345678&dn=Foo"
        self.assertEqual(
            _extract_info_hash(magnet), "2cbb4a8f1d3e5e8c1234567890abcdef12345678"
        )

    def test_v1_hex40_upper_normalized(self) -> None:
        magnet = "magnet:?xt=urn:btih:DEADBEEF1234567890ABCDEF1234567890ABCDEF"
        out = _extract_info_hash(magnet)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out, out.lower())
        self.assertEqual(len(out), 40)

    def test_no_btih_returns_none(self) -> None:
        self.assertIsNone(_extract_info_hash("magnet:?xt=urn:other:xxxxxx&dn=NoHash"))

    def test_btih_base32_returns_none(self) -> None:
        # 我们只支持 hex40；base32 (32 char) 不命中
        magnet = "magnet:?xt=urn:btih:NLRZ7HCROHGAUPVHQYHSAOAVPVPDM7HU&dn=Bar"
        self.assertIsNone(_extract_info_hash(magnet))

    def test_invalid_magnet_returns_none(self) -> None:
        self.assertIsNone(_extract_info_hash("not a magnet"))


# === 正片选择 ===


class PickMainFileTests(unittest.TestCase):
    def test_picks_largest_video(self) -> None:
        files = [
            {"path": "Sample/sample.mp4", "size_bytes": 15 * 1024 * 1024},
            {"path": "Movie.mp4", "size_bytes": 4_300_000_000},
            {"path": "Cover.jpg", "size_bytes": 200 * 1024},
        ]
        self.assertEqual(_pick_main_file(files), 1)

    def test_no_video_returns_none(self) -> None:
        files = [
            {"path": "readme.txt", "size_bytes": 1024},
            {"path": "cover.jpg", "size_bytes": 1024},
        ]
        self.assertIsNone(_pick_main_file(files))

    def test_multiple_video_extensions(self) -> None:
        files = [
            {"path": "a.mkv", "size_bytes": 1_000_000_000},
            {"path": "b.mp4", "size_bytes": 800_000_000},
            {"path": "c.ts", "size_bytes": 500_000_000},
        ]
        self.assertEqual(_pick_main_file(files), 0)

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(_pick_main_file([]))


# === 文件归一化 ===


class NormalizeFilesTests(unittest.TestCase):
    def test_qbt_shape_to_internal(self) -> None:
        raw = [
            {"name": "Foo/bar.mp4", "size": 12345, "priority": 0},
            {"name": "baz.srt", "size": 1024},
        ]
        out = _normalize_files(raw)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["path"], "Foo/bar.mp4")
        self.assertEqual(out[0]["size_bytes"], 12345)
        self.assertFalse(out[0]["is_recommended_main"])

    def test_skips_non_dict(self) -> None:
        raw = [{"name": "ok.mp4", "size": 1}, "garbage", None]  # type: ignore[list-item]
        out = _normalize_files(raw)  # type: ignore[arg-type]
        self.assertEqual(len(out), 1)

    def test_path_truncated_to_512(self) -> None:
        raw = [{"name": "a" * 1024, "size": 1}]
        out = _normalize_files(raw)
        self.assertEqual(len(out[0]["path"]), 512)


# === mock 模式：run_probe ===


class MockRunProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("QBT_MOCK")
        os.environ["QBT_MOCK"] = "1"
        self.assertTrue(_is_mock())

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("QBT_MOCK", None)
        else:
            os.environ["QBT_MOCK"] = self._old

    def test_returns_ok_with_files(self) -> None:
        result = run_probe("magnet:?xt=urn:btih:" + "0" * 40)
        self.assertEqual(result.status, "ok")
        self.assertGreater(len(result.files), 0)
        self.assertIsNotNone(result.main_file_index)
        self.assertIsNotNone(result.peer_count)
        self.assertIsNotNone(result.seed_count)
        self.assertIsNotNone(result.probed_at)
        self.assertIsNone(result.error)

    def test_main_file_marked(self) -> None:
        result = run_probe("magnet:?xt=urn:btih:" + "1" * 40)
        idx = result.main_file_index
        self.assertIsNotNone(idx)
        assert idx is not None
        self.assertTrue(result.files[idx]["is_recommended_main"])
        # other files should not be marked
        others = [f for i, f in enumerate(result.files) if i != idx]
        self.assertTrue(all(not f["is_recommended_main"] for f in others))


# === ProbeRequest 契约 ===


class ProbeRequestTests(unittest.TestCase):
    def test_accepts_magnet(self) -> None:
        req = ProbeRequest(
            task_id="abc",
            magnet="magnet:?xt=urn:btih:" + "0" * 40,
            callback_url="http://127.0.0.1:8090/internal/tasks/abc/bt-probe-result",
        )
        self.assertEqual(req.task_id, "abc")

    def test_rejects_non_magnet(self) -> None:
        with self.assertRaises(Exception):
            ProbeRequest(
                task_id="abc",
                magnet="https://example.com/foo.torrent",
                callback_url="http://127.0.0.1/cb",
            )

    def test_rejects_non_http_callback(self) -> None:
        with self.assertRaises(Exception):
            ProbeRequest(
                task_id="abc",
                magnet="magnet:?xt=urn:btih:" + "0" * 40,
                callback_url="file:///etc/passwd",
            )


# === BtProbeResultPayload 契约 ===


class ResultPayloadTests(unittest.TestCase):
    def test_status_ok(self) -> None:
        p = BtProbeResultPayload(status="ok")
        self.assertEqual(p.status, "ok")

    def test_status_failed(self) -> None:
        p = BtProbeResultPayload(status="failed", error="metadata timeout")
        self.assertEqual(p.status, "failed")

    def test_status_invalid_rejected(self) -> None:
        with self.assertRaises(Exception):
            BtProbeResultPayload(status="partial")

    def test_files_default_empty(self) -> None:
        p = BtProbeResultPayload(status="ok")
        self.assertEqual(p.files, [])


if __name__ == "__main__":
    unittest.main()
