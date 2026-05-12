"""tests/test_qbt_stub.py — _QbtClient 对 qBittorrent Web API 的真实 HTTP 集成测试。

为什么单独一组：
- mock 路径（QBT_MOCK=1）走 `_mock_probe`，永不触达 `_QbtClient`，无法捕获 add 时的字段（如 paused=true 这种 silent bug）。
- 本组测试启一个 stdlib http.server 当 qBittorrent stub，断言 _QbtClient 对每个端点的请求字段。
- 不联网，不依赖真实 qBittorrent，但覆盖到 _QbtClient → httpx → HTTP 这条真实路径。

边界：
- 不依赖外部测试 lib（无 respx / pytest-httpx）。
- stub 仅实现本测试断言所需的端点，行为足够让 _QbtClient 跑通一次完整 probe 即可。

回归这条路径的初衷：v0.3 实测发现 `paused=true` 让 qbt 不主动连 DHT/tracker，
metadata 永远拉不到——此 bug 单测全绿但生产 100% 失败。
该测试组建立后，未来重构若误把 paused 改回 true 会立即被这里捕获。

跑法：
    cd /root/bt-player-new/puresource-btprobe
    /root/bt-player-new/puresource-playlist/.venv/bin/python -m unittest tests.test_qbt_stub -v
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puresource_btprobe.qbt import run_probe  # noqa: E402


# === qBittorrent Web API stub ===


class _QbtStubHandler(BaseHTTPRequestHandler):
    """模拟 qBittorrent Web API 关键端点；把每次入站请求落到 server.recorded 上。

    支持的端点（v4.5.x 形态）：
    - POST /api/v2/auth/login              → 200 "Ok."
    - POST /api/v2/torrents/add            → 200 "Ok."
    - GET  /api/v2/torrents/info?hashes=…  → 200 [<torrent>]（含 size>0，模拟 metadata 已到）
    - GET  /api/v2/torrents/files?hash=…   → 200 [<file>...]
    - POST /api/v2/torrents/filePrio       → 200 ""
    - POST /api/v2/torrents/delete         → 200 ""
    """

    server: "_RecordingServer"  # type: ignore[assignment]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # 静音 stdlib 默认 stderr 日志
        return

    def _read_body(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        # qBittorrent 接受 form-urlencoded
        parsed = parse_qs(raw, keep_blank_values=True)
        return {k: v[0] if v else "" for k, v in parsed.items()}

    def _record(self, method: str, path: str, body: dict[str, str], query: dict[str, str]) -> None:
        self.server.recorded.append(
            {"method": method, "path": path, "body": body, "query": query}
        )

    def _respond(self, code: int, body: str | bytes, ctype: str = "text/plain") -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(u.query).items()}
        self._record("GET", u.path, {}, query)

        if u.path == "/api/v2/torrents/info":
            torrent = {
                "hash": query.get("hashes", "0" * 40),
                "size": 4_300_000_000,
                "num_seeds": 5,
                "num_leechs": 12,
                "state": "pausedDL",
                "name": "Stub.Torrent",
            }
            self._respond(200, json.dumps([torrent]), ctype="application/json")
            return

        if u.path == "/api/v2/torrents/files":
            files = [
                {"name": "Stub/sample.mp4", "size": 15 * 1024 * 1024, "priority": 1},
                {"name": "Stub/main.mp4", "size": 4_200_000_000, "priority": 1},
                {"name": "Stub/cover.jpg", "size": 200_000, "priority": 1},
            ]
            self._respond(200, json.dumps(files), ctype="application/json")
            return

        if u.path == "/api/v2/app/version":
            self._respond(200, "v4.5.2-stub")
            return

        self._respond(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        body = self._read_body()
        self._record("POST", u.path, body, {})

        if u.path == "/api/v2/auth/login":
            self._respond(200, "Ok.")
            return
        if u.path == "/api/v2/torrents/add":
            self._respond(200, "Ok.")
            return
        if u.path == "/api/v2/torrents/filePrio":
            self._respond(200, "")
            return
        if u.path == "/api/v2/torrents/delete":
            self._respond(200, "")
            return

        self._respond(404, "not found")


class _RecordingServer(ThreadingHTTPServer):
    """ThreadingHTTPServer 子类，挂一个 list 收集每次请求。"""

    def __init__(self, *a: object, **kw: object) -> None:
        super().__init__(*a, **kw)  # type: ignore[arg-type]
        self.recorded: list[dict[str, object]] = []


# === fixture ===


class _StubLifecycle(unittest.TestCase):
    """启 stub server + 在 setUp 注入 QBT_* 环境变量，tearDown 关闭。"""

    server: _RecordingServer
    thread: threading.Thread
    _saved_env: dict[str, str | None]

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = _RecordingServer(("127.0.0.1", 0), _QbtStubHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self) -> None:
        host, port = self.server.server_address
        self._saved_env = {
            "QBT_MOCK": os.environ.pop("QBT_MOCK", None),
            "QBT_BASE_URL": os.environ.pop("QBT_BASE_URL", None),
            "QBT_USER": os.environ.pop("QBT_USER", None),
            "QBT_PASS": os.environ.pop("QBT_PASS", None),
            "BT_PROBE_METADATA_WAIT_S": os.environ.pop("BT_PROBE_METADATA_WAIT_S", None),
            "BT_PROBE_METADATA_POLL_INTERVAL_S": os.environ.pop(
                "BT_PROBE_METADATA_POLL_INTERVAL_S", None
            ),
        }
        os.environ["QBT_MOCK"] = "0"
        os.environ["QBT_BASE_URL"] = f"http://{host}:{port}"
        # user/pass 留空 → 跳过 login，更贴近本机 LocalHostAuth=false 部署
        # 缩短轮询以加快单测
        self.server.recorded.clear()

    def tearDown(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# === 实际测试 ===


class AddTorrentFieldsTests(_StubLifecycle):
    """关键回归测试：add 时 paused 必须为 false。"""

    def test_add_uses_paused_false(self) -> None:
        """v0.3 silent bug 防御：paused=true 会让 qbt 不连 DHT/tracker。"""
        magnet = "magnet:?xt=urn:btih:" + "a" * 40
        result = run_probe(magnet, wait_s=5)
        adds = [r for r in self.server.recorded if r["path"] == "/api/v2/torrents/add"]
        self.assertEqual(len(adds), 1, f"add must be called exactly once; got {len(adds)}")
        body = adds[0]["body"]
        self.assertEqual(
            body.get("paused"),
            "false",
            "qBittorrent 4.5+ 不在 paused 状态拉 metadata；paused 必须 false",
        )
        # 同时 stopCondition 保证拿到 metadata 后自动停，等价"只探测不下载"
        self.assertEqual(body.get("stopCondition"), "MetadataReceived")
        self.assertEqual(body.get("skip_checking"), "true")
        self.assertIn("urls", body)
        self.assertTrue(body["urls"].startswith("magnet:?"))
        # 完整 run_probe 还应该是 ok
        self.assertEqual(result.status, "ok")

    def test_add_called_before_info(self) -> None:
        """生命周期顺序：先 add，再轮询 info。"""
        run_probe("magnet:?xt=urn:btih:" + "b" * 40, wait_s=5)
        seq = [(r["method"], r["path"]) for r in self.server.recorded]
        idx_add = seq.index(("POST", "/api/v2/torrents/add"))
        idx_first_info = next(
            i for i, x in enumerate(seq) if x == ("GET", "/api/v2/torrents/info")
        )
        self.assertLess(idx_add, idx_first_info)


class FilePrioAndDeleteTests(_StubLifecycle):
    """metadata 拿到后必须 setFilePrio=0 + delete，磁盘零残留。"""

    def test_set_all_files_zero_prio(self) -> None:
        run_probe("magnet:?xt=urn:btih:" + "c" * 40, wait_s=5)
        prios = [r for r in self.server.recorded if r["path"] == "/api/v2/torrents/filePrio"]
        self.assertGreaterEqual(len(prios), 1)
        body = prios[0]["body"]
        self.assertEqual(body.get("priority"), "0", "priority 必须为 0（不下载）")
        # stub 返 3 个文件，所以 id="0|1|2"
        self.assertEqual(body.get("id"), "0|1|2")

    def test_delete_with_files(self) -> None:
        run_probe("magnet:?xt=urn:btih:" + "d" * 40, wait_s=5)
        dels = [r for r in self.server.recorded if r["path"] == "/api/v2/torrents/delete"]
        self.assertEqual(len(dels), 1, "delete 必须调用且仅调用一次")
        body = dels[0]["body"]
        self.assertEqual(body.get("deleteFiles"), "true", "deleteFiles 必须 true 防残留")


class LoginSkippedWhenNoCredsTests(_StubLifecycle):
    """user/pass 为空时跳过 /auth/login；契合 LocalHostAuth=false 部署。"""

    def test_no_login_call_without_creds(self) -> None:
        run_probe("magnet:?xt=urn:btih:" + "e" * 40, wait_s=5)
        logins = [r for r in self.server.recorded if r["path"] == "/api/v2/auth/login"]
        self.assertEqual(len(logins), 0, "无凭据时不应调 /auth/login")


class LoginCalledWhenCredsPresentTests(_StubLifecycle):
    """user/pass 都有值时必须先 login。"""

    def setUp(self) -> None:
        super().setUp()
        os.environ["QBT_USER"] = "admin"
        os.environ["QBT_PASS"] = "secret"

    def test_login_called_first(self) -> None:
        run_probe("magnet:?xt=urn:btih:" + "f" * 40, wait_s=5)
        seq = [(r["method"], r["path"]) for r in self.server.recorded]
        self.assertIn(("POST", "/api/v2/auth/login"), seq)
        self.assertLess(
            seq.index(("POST", "/api/v2/auth/login")),
            seq.index(("POST", "/api/v2/torrents/add")),
            "login 必须先于 add",
        )


if __name__ == "__main__":
    unittest.main()
