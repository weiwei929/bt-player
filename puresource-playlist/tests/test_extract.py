"""tests/test_extract.py — yt-dlp 封装与 cookies 白名单单测（v0.3 T-1-02 / T-1-03）。

边界：仅验证字符串解析与白名单逻辑；不调真实 yt-dlp，不联网。
跑法：
    cd /root/bt-player-new/puresource-playlist
    .venv/bin/python -m unittest tests.test_extract -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.extract import (  # noqa: E402
    CookiesError,
    parse_dump_json,
    resolve_cookies,
)


# === cookies 白名单 ===


class CookiesWhitelistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cookies_dir = Path(self.tmp.name)
        self._old = os.environ.get("PURESOURCE_COOKIES_DIR")
        os.environ["PURESOURCE_COOKIES_DIR"] = str(self.cookies_dir)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("PURESOURCE_COOKIES_DIR", None)
        else:
            os.environ["PURESOURCE_COOKIES_DIR"] = self._old
        self.tmp.cleanup()

    def _put(self, name: str, body: str = "# netscape cookies\n") -> Path:
        p = self.cookies_dir / name
        p.write_text(body, encoding="utf-8")
        return p

    def test_none_returns_none(self) -> None:
        self.assertIsNone(resolve_cookies(None))

    def test_legal_name_resolves(self) -> None:
        self._put("mysite.txt")
        out = resolve_cookies("mysite.txt")
        self.assertIsNotNone(out)
        self.assertTrue(out.is_file())
        self.assertTrue(str(out).endswith("mysite.txt"))

    def test_reject_path_traversal(self) -> None:
        with self.assertRaises(CookiesError) as cm:
            resolve_cookies("../etc/passwd")
        self.assertIn("必须匹配", str(cm.exception))

    def test_reject_absolute_path(self) -> None:
        with self.assertRaises(CookiesError):
            resolve_cookies("/etc/passwd")

    def test_reject_wrong_extension(self) -> None:
        self._put("foo.json")
        with self.assertRaises(CookiesError):
            resolve_cookies("foo.json")

    def test_reject_too_long(self) -> None:
        too_long = ("a" * 65) + ".txt"
        with self.assertRaises(CookiesError):
            resolve_cookies(too_long)

    def test_reject_special_chars(self) -> None:
        self._put("ok.txt")
        for bad in ("a b.txt", "中文.txt", "a;b.txt", "a$b.txt"):
            with self.assertRaises(CookiesError):
                resolve_cookies(bad)

    def test_reject_missing_file(self) -> None:
        with self.assertRaises(CookiesError) as cm:
            resolve_cookies("never-created.txt")
        self.assertIn("不存在", str(cm.exception))

    def test_reject_missing_dir(self) -> None:
        os.environ["PURESOURCE_COOKIES_DIR"] = str(self.cookies_dir / "nope")
        with self.assertRaises(CookiesError) as cm:
            resolve_cookies("a.txt")
        self.assertIn("目录不存在", str(cm.exception))


# === yt-dlp dump-json 解析 ===


class ParseDumpJsonTests(unittest.TestCase):
    def test_empty_string(self) -> None:
        self.assertEqual(parse_dump_json(""), [])

    def test_single_video_with_url(self) -> None:
        info = {
            "title": "Test Video",
            "url": "https://cdn.example.com/v.mp4",
            "ext": "mp4",
            "width": 1920,
            "height": 1080,
            "tbr": 2400,
            "format_id": "best",
        }
        out = parse_dump_json(json.dumps(info))
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual(c.title, "Test Video")
        self.assertEqual(c.stream_url, "https://cdn.example.com/v.mp4")
        self.assertEqual(c.container, "mp4")
        self.assertEqual(c.resolution, "1920x1080")
        self.assertEqual(c.bitrate_kbps, 2400)
        self.assertEqual(c.format_id, "best")

    def test_resolution_field_passthrough(self) -> None:
        # 当 yt-dlp 直接给 resolution 字符串时，原样保留。
        info = {
            "title": "T",
            "url": "https://e/v.mp4",
            "resolution": "1080p",
        }
        out = parse_dump_json(json.dumps(info))
        self.assertEqual(out[0].resolution, "1080p")

    def test_multi_format_dedup(self) -> None:
        # 顶层 url + formats[0].url 相同 → 应去重保留一条。
        info = {
            "title": "Movie",
            "url": "https://e/v.mp4",
            "ext": "mp4",
            "formats": [
                {"url": "https://e/v.mp4", "format_id": "alt", "ext": "mp4"},
                {"url": "https://e/v_720.mp4", "format_id": "720p", "ext": "mp4"},
            ],
        }
        out = parse_dump_json(json.dumps(info))
        urls = [c.stream_url for c in out]
        self.assertEqual(urls, ["https://e/v.mp4", "https://e/v_720.mp4"])

    def test_skip_no_url(self) -> None:
        # yt-dlp 在某些 manifest 阶段会吐没有 url 的占位条目，必须丢弃。
        info = {"title": "x", "formats": [{"format_id": "stub"}]}
        out = parse_dump_json(json.dumps(info))
        self.assertEqual(out, [])

    def test_skip_non_http_url(self) -> None:
        info = {"title": "x", "url": "ftp://e/v"}
        out = parse_dump_json(json.dumps(info))
        self.assertEqual(out, [])

    def test_invalid_json_lines_ignored(self) -> None:
        good = json.dumps({"title": "g", "url": "https://e/v.mp4"})
        out = parse_dump_json("garbage\n" + good + "\nnot json either")
        self.assertEqual(len(out), 1)

    def test_playlist_multiple_entries(self) -> None:
        a = json.dumps({"title": "A", "url": "https://e/a.mp4"})
        b = json.dumps({"title": "B", "url": "https://e/b.mp4"})
        out = parse_dump_json(a + "\n" + b)
        self.assertEqual(len(out), 2)
        self.assertEqual({c.title for c in out}, {"A", "B"})


if __name__ == "__main__":
    unittest.main()
