import { useState, useEffect } from "react";

interface FileEntry {
  index: number;
  path: string;
  size_bytes: number;
  size_mb: number;
  stream_url: string;
  is_suspected_ad?: boolean;
}

interface PlayHistoryEntry {
  id: number;
  magnet: string;
  file_path: string;
  stream_url: string;
  played_at: string;
  progress_sec: number;
  is_suspected_ad: boolean;
}

const API_BASE = "";  // 同域下，Caddy 反向代理 /api/*
const API_TOKEN = (import.meta.env.VITE_API_TOKEN as string | undefined)?.trim();

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers ?? {});
  headers.set("Content-Type", "application/json");
  if (API_TOKEN) {
    headers.set("x-api-key", API_TOKEN);
  }

  const res = await fetch(`${API_BASE}${path}`, {
    headers,
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || "请求失败");
  }
  return res.json();
}

function App() {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [sourceType, setSourceType] = useState<"magnet" | "hls" | null>(null);
  const [history, setHistory] = useState<PlayHistoryEntry[]>([]);
  const [playingUrl, setPlayingUrl] = useState<string | null>(null);
  const [playingTitle, setPlayingTitle] = useState<string | null>(null);

  const loadHistory = async () => {
    try {
      const list = await api<PlayHistoryEntry[]>("/api/history");
      setHistory(list);
    } catch {
      setHistory([]);
    }
  };

  useEffect(() => { loadHistory(); }, []);

  const handleResolve = async () => {
    const url = input.trim();
    if (!url) return;
    setLoading(true);
    setError(null);
    setFiles([]);
    setStreamUrl(null);
    setPlayingUrl(null);
    try {
      const result = await api<{ stream_url: string; files: FileEntry[]; source_type: string }>(
        "/api/resolve",
        { method: "POST", body: JSON.stringify({ url }) }
      );
      setStreamUrl(result.stream_url);
      setFiles(result.files);
      setSourceType(result.source_type as "magnet" | "hls");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6 flex flex-col">
      <div className="max-w-4xl mx-auto w-full flex-1 flex flex-col">
        <h1 className="text-2xl font-bold text-cyan-400 mb-4">BT-Player</h1>

        {/* 视频播放区域 */}
        {playingUrl && (
          <div className="w-full aspect-video max-h-[54vh] mb-4 rounded-lg bg-black/80 border border-slate-600 overflow-hidden">
            <video
              src={playingUrl}
              controls
              autoPlay
              className="w-full h-full"
              onError={() => setError("播放失败：流地址不可达或编码不支持")}
            />
          </div>
        )}
        {!playingUrl && (
          <div className="w-full aspect-video max-h-[54vh] mb-4 rounded-lg bg-black/80 border border-slate-600 flex items-center justify-center">
            <span className="text-slate-500 text-sm">
              解析链接后点击文件即可播放
            </span>
          </div>
        )}

        {playingTitle && (
          <div className="flex items-center mb-4 px-2">
            <span className="text-emerald-400 text-sm truncate max-w-xs">
              ▶ {playingTitle}
            </span>
          </div>
        )}

        {/* 输入区域 */}
        <div className="space-y-4 mb-6">
          <label className="block text-sm font-medium text-slate-300">
            磁链或 m3u8 地址
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="magnet:?xt=urn:btih:... 或 https://xxx.m3u8"
              className="flex-1 px-4 py-2 rounded-lg bg-slate-800 border border-slate-600 focus:border-cyan-500 outline-none"
            />
            <button
              onClick={handleResolve}
              disabled={loading}
              className="px-6 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 font-medium"
            >
              {loading ? "解析中..." : "解析"}
            </button>
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/50 border border-red-700 text-red-200">
            {error}
          </div>
        )}

        {/* 流 URL 显示 */}
        {streamUrl && (
          <div className="mb-4 p-3 rounded-lg bg-slate-800 border border-slate-600">
            <span className="text-slate-400 text-sm">流 URL: </span>
            <code className="text-cyan-300 text-sm break-all">{streamUrl}</code>
          </div>
        )}

        {/* 文件列表 */}
        <div className="rounded-lg border border-slate-600 bg-slate-800/50 overflow-hidden">
          <div className="px-4 py-2 border-b border-slate-600 font-medium text-slate-300">
            {sourceType === "hls" ? "HLS 流" : `文件列表 (${files.length})`}
          </div>
          <ul className="divide-y divide-slate-600 max-h-96 overflow-y-auto">
            {files.length === 0 && !loading && (
              <li className="px-4 py-8 text-center text-slate-500">输入地址后点击「解析」</li>
            )}
            {files.map((f) => (
              <li
                key={f.index}
                className="px-4 py-2 hover:bg-slate-700/50 flex items-center justify-between gap-4 cursor-pointer"
                onClick={() => {
                  if (f.stream_url) {
                    setPlayingUrl(f.stream_url);
                    setPlayingTitle(f.path);
                    setError(null);
                    // 记录播放历史
                    api("/api/history", {
                      method: "POST",
                      body: JSON.stringify({
                        magnet: input.trim(),
                        file_path: f.path,
                        stream_url: f.stream_url,
                        is_suspected_ad: f.is_suspected_ad ?? false,
                      }),
                    }).catch(() => {});
                  }
                }}
              >
                <span className="text-cyan-300 truncate flex-1 font-mono text-sm">{f.path}</span>
                {f.is_suspected_ad && <span className="text-amber-400 text-xs shrink-0">广告</span>}
                <span className="text-slate-400 text-sm shrink-0">{f.size_mb.toFixed(2)} MB</span>
              </li>
            ))}
          </ul>
        </div>

        {/* 播放历史 */}
        {history.length > 0 && (
          <div className="mt-6 rounded-lg border border-slate-600 bg-slate-800/50 overflow-hidden">
            <div className="px-4 py-2 border-b border-slate-600 font-medium text-slate-300">
              播放历史 ({history.length})
            </div>
            <ul className="divide-y divide-slate-600 max-h-48 overflow-y-auto">
              {history.slice(0, 10).map((h) => (
                <li key={h.id} className="px-4 py-2 text-sm text-slate-400 truncate" title={h.file_path}>
                  {h.file_path} · {h.played_at}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
