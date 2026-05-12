# Cursor 任务 01：yt-dlp 集成 → puresource-playlist

> 架构师：本地 Codex
> 执行者：VPS Cursor
> 日期：2026-05-12
> 分支：`task/v0.3-ytdlp-extract`

---

## 前置：初始化 puresource-playlist 的 git 仓库

当前 `/opt/puresource-playlist/` 不是 git 仓库，必须先初始化才能建任务分支。

```bash
cd /opt/puresource-playlist
git init
git config user.name "VPS Cursor"
git config user.email "cursor@bt-player.vps"
git add -A
git commit -m "chore: initial commit of puresource-playlist v0.2 baseline"
```

---

## 任务目标

在 puresource-playlist 中新增 `POST /tasks/{id}/extract` 端点，调用 yt-dlp 从网页 URL 提取候选播放链接。

---

## 步骤 1：安装 yt-dlp

```bash
/opt/puresource-playlist/.venv/bin/pip install yt-dlp
```

验证：
```bash
/opt/puresource-playlist/.venv/bin/yt-dlp --version
```

---

## 步骤 2：新建 `app/extract.py`

文件路径：`/opt/puresource-playlist/app/extract.py`

核心函数签名和逻辑：

```python
"""yt-dlp 集成：从网页/直链提取候选播放 URL。

边界：
- 仅做元数据提取（--dump-json），不下载媒体内容。
- subprocess 超时 30s，避免无限挂起。
- 所有候选写入 probe_log，结构化为 JSON 字符串便于前端解析。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from .models import PROBE_LOG_MAX_LINE, PROBE_LOG_MAX_ENTRIES

YTDLP_TIMEOUT_S = 30

# yt-dlp 二进制路径（venv 安装）
_YTDLP_BIN = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "yt-dlp"


def extract_from_url(
    url: str,
    cookies_file: Optional[str] = None,
) -> tuple[list[dict], list[str]]:
    """对单个 URL 执行 yt-dlp --dump-json，返回 (候选列表, log 行列表)。

    Args:
        url: 要提取的网页 URL（http/https）。
        cookies_file: 可选，Netscape 格式 cookies 文件路径。

    Returns:
        (candidates, log_lines)
        candidates: 候选列表，每个 dict 含 title/url/format/resolution/fps/ext/filesize
        log_lines: 人类可读的 probe_log 条目
    """
    log: list[str] = []
    candidates: list[dict] = []

    ytdlp = str(_YTDLP_BIN)

    cmd = [
        ytdlp,
        "--dump-json",
        "--no-download",
        "--no-playlist",
        "--ignore-config",
        "--no-warnings",
        "--socket-timeout", "15",
    ]
    if cookies_file:
        cmd.extend(["--cookies", cookies_file])
    cmd.append(url)

    log.append(f"yt-dlp start url={url[:160]}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=YTDLP_TIMEOUT_S,
            cwd="/tmp",
        )
    except subprocess.TimeoutExpired:
        log.append("yt-dlp timeout (>30s)")
        return [], log
    except FileNotFoundError:
        log.append("yt-dlp binary not found — run: pip install yt-dlp")
        return [], log
    except Exception as exc:
        log.append(f"yt-dlp subprocess error: {type(exc).__name__}: {exc}")
        return [], log

    if proc.returncode != 0:
        stderr = (proc.stderr or "")[:200]
        log.append(f"yt-dlp exit={proc.returncode} stderr={stderr}")
        return [], log

    # yt-dlp 可能输出多行 JSON（多格式/多码率）
    for line in proc.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue

        cand = {
            "title": str(info.get("title") or info.get("fulltitle") or "")[:200],
            "url": str(info.get("url") or ""),
            "format": str(info.get("format") or ""),
            "resolution": str(info.get("resolution") or ""),
            "fps": info.get("fps"),
            "ext": str(info.get("ext") or ""),
            "filesize": info.get("filesize"),
            "filesize_approx": info.get("filesize_approx"),
            "format_note": str(info.get("format_note") or ""),
        }
        if cand["url"] and cand["url"].startswith(("http://", "https://")):
            candidates.append(cand)
            log.append(
                f"candidate: {cand['format_note'] or cand['format']} "
                f"{cand['resolution']} ext={cand['ext']} "
                f"url={cand['url'][:120]}"
            )
        else:
            log.append(f"skipped non-http candidate: {cand['title'][:80]}")

    if not candidates:
        log.append("yt-dlp produced 0 http candidates")

    return candidates, log
```

**设计要求**：
- 超时 30s，不能因为某个慢站点把整个 worker 挂住
- 输出只取 http/https URL，过滤掉 rtmp/rtsp/magnet 等
- `--no-playlist` 避免对播放列表页递归提取
- 候选结果同时以人类可读行存入 probe_log

---

## 步骤 3：在 `app/main.py` 中新增 `/tasks/{id}/extract` 端点

在 `main.py` 末尾（`# === PotPlayer 订阅入口 ===` 之前）插入：

```python
# === yt-dlp 提取 ===


@app.post("/tasks/{rec_id}/extract")
def extract_task(rec_id: str) -> dict:
    """对网页/直链任务调用 yt-dlp 提取候选 stream_url。"""
    items = load_resources()
    cur = next((r for r in items if r.id == rec_id), None)
    if cur is None:
        raise HTTPException(status_code=404, detail="task not found")

    if cur.source_kind not in ("webpage", "mp4", "m3u8"):
        raise HTTPException(
            status_code=409,
            detail=f"extract only applies to webpage/mp4/m3u8, got source_kind={cur.source_kind}",
        )
    if not cur.source_url:
        raise HTTPException(status_code=409, detail="task has no source_url")

    from .extract import extract_from_url

    candidates, log = extract_from_url(cur.source_url)

    merged_log = (list(cur.probe_log) + log)[-PROBE_LOG_MAX_ENTRIES:]

    new_stage = ResourceStage.playable if candidates else ResourceStage.failed

    updated = cur.model_copy(
        update={
            "stage": new_stage,
            "last_probed_at": datetime.now(timezone.utc).isoformat(),
            "probe_log": merged_log,
        }
    )
    saved = update_resource(rec_id, lambda _r: updated)
    if saved is None:
        raise HTTPException(status_code=404, detail="task vanished mid-extract")

    return {
        "task": saved.model_dump(),
        "candidates": candidates,
    }
```

需要在 `main.py` 顶部增加 import：
```python
from datetime import datetime, timezone
```
（如果尚不存在的话——检查现有 import，datetime 可能已在）

---

## 步骤 4：更新前端 `app/static/app.js`

### 4.1 修改 renderTask 函数中的 actionBtn

将 webpage 类型加入 extract 按钮：

```javascript
// 替换现有的 actionBtn 逻辑（约 L111-117）
let actionBtn = "";
if (r.source_kind === "magnet") {
  actionBtn = `<button data-act="enrich" data-id="${r.id}" title="纯字符串解析 info_hash / dn / trackers，零网络">enrich</button>`;
} else if (r.source_kind === "webpage" || r.source_kind === "mp4" || r.source_kind === "m3u8") {
  actionBtn = `
    <button data-act="probe" data-id="${r.id}">probe</button>
    <button data-act="extract" data-id="${r.id}" title="yt-dlp 提取候选播放链接">extract</button>
  `;
}
```

### 4.2 在 onTaskAction 中处理 extract

```javascript
// 在 onTaskAction 函数中，promote 分支之后增加：
} else if (act === "extract") {
  const result = await api(`/tasks/${encodeURIComponent(id)}/extract`, { method: "POST" });
  if (result.candidates && result.candidates.length > 0) {
    const list = result.candidates.map((c, i) =>
      `[${i+1}] ${c.format_note || c.format} ${c.resolution} .${c.ext}  ${c.url ? c.url.substring(0, 80) + '...' : ''}`
    ).join("\n");
    alert(`yt-dlp 找到 ${result.candidates.length} 个候选：\n\n${list}\n\n选择一个 stream_url 填入 promote 对话框。`);
  } else {
    alert("yt-dlp 未找到可播放候选。查看 probe_log 了解详情。");
  }
  await reload();
}
```

### 4.3（可选）候选结果展示优化

如果候选数量 > 0，在 task 卡片中展示候选列表区域。当前 MVP 先用 alert 展示。

---

## 步骤 5：验证

```bash
# 1. 重启服务
systemctl restart puresource-playlist

# 2. 健康检查
curl -s http://127.0.0.1:8090/health

# 3. 创建一个网页任务
curl -sS -X POST http://127.0.0.1:8090/tasks \
  -H "Content-Type: application/json" \
  -d '{"source_url":"https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4","title":"yt-dlp 测试 - Cosmos Laundromat"}'

# 记录返回的 id，假设为 <rec_id>

# 4. 调用 extract
curl -sS -X POST http://127.0.0.1:8090/tasks/<rec_id>/extract | python3 -m json.tool

# 5. 验证前端
# 访问 https://bt.mgtv.dev/static/index.html
# 点击 extract 按钮，确认弹窗显示候选
```

---

## 回报格式

完成后回报：

```
分支名：task/v0.3-ytdlp-extract
commit hash：
修改文件列表：
构建/重启结果：
curl 验证结果（/extract 端点输出）：
前端验证截图或描述：
已知问题：
```
