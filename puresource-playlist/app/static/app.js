// PureSource 资源提纯工作台 — zero-build 前端 (v0.3 T-3)
//
// 设计原则：
//   1) 仅调本服务公开/私有 API；不存任何 Basic Auth 凭据。
//   2) 状态机分层：stage（提纯进度）由后端给；status（列表准入）只在 promote 后才会有值。
//   3) /tasks*、/intake、/resources 在生产受 Basic Auth 保护；浏览器靠 401 弹窗或 OS 钥匙串。
//   4) UI 不调用 /playlists/movies.m3u8 / debug.m3u8 等"未实现端点"，避免被 Caddy 403 防护命中。
//   5) v0.3 T-3：bt-probe / extract 按钮 + 文件树 / 候选展示 + 进行中任务自动轮询。

const STAGE_ORDER = [
  "pending",
  "extracting",
  "bt_probing",
  "probing",
  "metadata_ready",
  "playable",
  "external_ready",
  "failed",
];

// v0.3 T-1-06：promote 准入按 §2 D5 的 B 方案扩入 metadata_ready。
// 含义：bt-probe 完成、有文件树但无 stream_url 的 magnet 任务，用户从
// PikPak / 油猴等外部渠道拿到 stream_url 后可直接 promote 入列。
// extracting / bt_probing / pending / probing / failed 仍不在白名单内。
const PROMOTABLE = new Set(["playable", "external_ready", "metadata_ready"]);

// 进行中状态：自动轮询的对象。一旦列表里没有这些状态就停止轮询。
const IN_FLIGHT = new Set(["extracting", "bt_probing", "probing"]);

// 自动轮询节奏。轻量：5s 一次 GET /tasks，DOM diff 由浏览器自己抗。
const POLL_INTERVAL_MS = 5000;

const state = {
  filterStage: "",
  tasks: [],
  promoteId: null,
  pollTimer: null,
  // 候选行选中预填到 promote dialog 的临时态
  pendingPromotePrefill: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  form: $("#form-create"),
  fSource: $("#f-source"),
  fTitle: $("#f-title"),
  fNote: $("#f-note"),
  createMsg: $("#create-msg"),
  btnRefresh: $("#btn-refresh"),
  btnCopy: $("#btn-copy-playlist"),
  lnkPlaylist: $("#lnk-playlist"),
  tabs: $("#stage-tabs"),
  list: $("#task-list"),
  dlg: $("#dlg-promote"),
  pStream: $("#p-stream-url"),
  pTarget: $("#p-target-status"),
  pTitle: $("#p-title"),
  pConfirm: $("#p-confirm"),
};

function setMsg(el, text, kind) {
  el.textContent = text || "";
  el.className = "msg" + (kind ? " " + kind : "");
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtBytes(n) {
  if (n == null || isNaN(n)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = Number(n);
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return (i === 0 ? v.toFixed(0) : v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2)) + " " + units[i];
}

async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      if (j && j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (_) {}
    const err = new Error(`HTTP ${res.status} ${detail}`);
    err.status = res.status;
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

// === 渲染：magnet 文件树（bt-probe 完成后） ===
//
// 前置约定：
//   - m.files = null 表示尚未做过 bt-probe；空数组表示"做过，但种子里没有文件"。
//   - is_recommended_main / main_file_index 是 bt-probe 算出的"正片建议"，
//     不强制；前端只是把它高亮，不把它写进 promote 流程的"自动 stream_url"
//     —— magnet 仍然需要外部渠道（PikPak / 缓存）拿到可播 URL。
function renderMagnetFiles(m) {
  if (!m) return "";
  const files = m.files;
  if (files == null) return "";
  if (!Array.isArray(files) || files.length === 0) {
    return `<div class="bt-probe muted small">bt-probe 完成，但种子内文件列表为空</div>`;
  }
  const peers = m.peer_count == null ? "—" : m.peer_count;
  const seeds = m.seed_count == null ? "—" : m.seed_count;
  const probedAt = m.probed_at || "—";
  const mainIdx = m.main_file_index;
  const rows = files
    .map((f, i) => {
      const isMain = !!f.is_recommended_main || i === mainIdx;
      const path = esc(f.path || "");
      const size = fmtBytes(f.size_bytes);
      const tag = isMain ? `<span class="main-tag">正片</span>` : "";
      return `
        <tr class="${isMain ? "main" : ""}">
          <td class="path">${path}</td>
          <td class="size">${size}</td>
          <td class="tag">${tag}</td>
        </tr>`;
    })
    .join("");
  return `
    <div class="bt-probe">
      <div class="row1">
        <span class="label">bt-probe</span>
        <span class="meta">peers: ${esc(peers)}</span>
        <span class="meta">seeds: ${esc(seeds)}</span>
        <span class="meta">probed: ${esc(probedAt)}</span>
      </div>
      <details open>
        <summary>文件树（${files.length} 个文件${
    mainIdx != null ? `，正片 idx=${esc(mainIdx)}` : ""
  }）</summary>
        <table class="bt-files">
          <thead><tr><th>path</th><th>size</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <p class="muted small note">
          bt-probe 只给文件树和 peer 状态，不自动产出 stream_url。
          需要 PikPak 转存 / 油猴脚本 / qBittorrent 缓存等外部渠道拿到可播 URL，
          然后通过 promote 入列。
        </p>
      </details>
    </div>
  `;
}

// === 渲染：magnet 解析信息（enrich 字段） ===
function renderMagnetInfo(m) {
  if (!m) return "";
  const trackers = (m.trackers || []).map((t) => esc(t)).join("\n");
  const enrichLog = (m.enrich_log || []).map((l) => esc(l)).join("\n");
  const ih = m.info_hash || "—";
  const ih2 = m.info_hash_v2 || "—";
  const dn = m.display_name || "—";
  const kind = m.info_hash_kind || "unknown";
  return `
    <div class="magnet-info">
      <div class="row1">
        <span class="label">magnet</span>
        <span class="kind">${esc(kind)}</span>
        <span class="meta">parsed: ${esc(m.parsed_at || "—")}</span>
      </div>
      <div class="urls">
        <div><span class="label">info_hash (v1):</span> <code>${esc(ih)}</code></div>
        <div><span class="label">info_hash (v2):</span> <code>${esc(ih2)}</code></div>
        <div><span class="label">display_name:</span> ${esc(dn)}</div>
        <div><span class="label">trackers:</span> ${(m.trackers || []).length}</div>
      </div>
      ${
        trackers
          ? `<details><summary>trackers（去重，≤64）</summary><pre>${trackers}</pre></details>`
          : ""
      }
      ${
        enrichLog
          ? `<details><summary>enrich_log（最近 ≤20 条）</summary><pre>${enrichLog}</pre></details>`
          : ""
      }
      ${renderMagnetFiles(m)}
    </div>
  `;
}

// === 渲染：yt-dlp 候选 ===
//
// 前置约定：
//   - r.extract = null 表示尚未 extract；空数组表示"做过，但 yt-dlp 没产出候选"。
//   - 每个候选行带"用此候选 promote"按钮：弹 promote dialog 时预填 stream_url / title。
function renderExtractCandidates(r) {
  const cs = r.extract;
  if (cs == null) return "";
  if (!Array.isArray(cs) || cs.length === 0) {
    return `<div class="extract muted small">extract 完成，但 yt-dlp 未给出候选</div>`;
  }
  const rows = cs
    .map((c, i) => {
      const meta = [
        c.container,
        c.resolution,
        c.bitrate_kbps != null ? c.bitrate_kbps + " kbps" : null,
        c.format_id ? `format=${c.format_id}` : null,
      ]
        .filter(Boolean)
        .map((s) => esc(s))
        .join(" · ");
      return `
        <li class="cand" data-idx="${i}">
          <div class="row1">
            <span class="cand-title">${esc(c.title || "(无标题)")}</span>
            <span class="meta">${meta || "—"}</span>
          </div>
          <div class="urls">
            <div><span class="label">stream_url:</span> <code>${esc(c.stream_url)}</code></div>
            <div><span class="label">extracted:</span> ${esc(c.extracted_at || "—")}</div>
          </div>
          <div class="actions">
            <button class="primary" data-act="promote-cand" data-id="${r.id}" data-idx="${i}">
              用此候选 promote
            </button>
          </div>
        </li>`;
    })
    .join("");
  return `
    <div class="extract">
      <div class="row1">
        <span class="label">extract</span>
        <span class="meta">${cs.length} 个候选</span>
      </div>
      <ol class="cand-list">${rows}</ol>
    </div>
  `;
}

// === 渲染：单个任务 ===
function renderTask(r) {
  const stage = r.stage || "pending";
  const status = r.status || "—";
  const inFlight = IN_FLIGHT.has(stage);
  // 三种探针按钮按 source_kind 分发：
  //   magnet  → enrich（瞬时字符串解析）+ bt-probe（异步网络协商）
  //   webpage → extract（异步 yt-dlp）
  //   mp4/m3u8→ probe（同步 HTTP 探活）
  //   other   → 不挂按钮（避免误导）
  const probeBtns = [];
  if (r.source_kind === "magnet") {
    probeBtns.push(
      `<button data-act="enrich" data-id="${r.id}" title="纯字符串解析 info_hash / dn / trackers，零网络">enrich</button>`,
      `<button data-act="bt-probe" data-id="${r.id}" title="qBittorrent 拉 metadata + 文件树 + peer 数（异步）">bt-probe</button>`
    );
  } else if (r.source_kind === "webpage") {
    probeBtns.push(
      `<button data-act="extract" data-id="${r.id}" title="yt-dlp --dump-json 抽取候选 stream_url（异步，可选 cookies）">extract</button>`
    );
  } else if (r.source_kind === "mp4" || r.source_kind === "m3u8") {
    probeBtns.push(`<button data-act="probe" data-id="${r.id}">probe</button>`);
  }
  const promoteBtn = PROMOTABLE.has(stage)
    ? `<button class="primary" data-act="promote" data-id="${r.id}">promote</button>`
    : `<button disabled title="仅 playable / external_ready / metadata_ready 可 promote">promote</button>`;

  const probeLog = (r.probe_log || []).map((l) => esc(l)).join("\n");

  return `
    <div class="task ${inFlight ? "in-flight" : ""}" data-id="${r.id}">
      <div class="row1">
        <span class="title">${esc(r.title || "(无标题)")}</span>
        <span class="badge ${stage}">${stage}</span>
        <span class="kind">${esc(r.source_kind)}</span>
        <span class="meta">status: ${esc(status)}</span>
        <span class="meta">created: ${esc(r.created_at || "")}</span>
      </div>
      <div class="urls">
        <div><span class="label">source_url:</span> ${esc(r.source_url || "")}</div>
        <div><span class="label">stream_url:</span> ${esc(r.stream_url || "")}</div>
      </div>
      <div class="actions">
        ${probeBtns.join("\n")}
        ${promoteBtn}
      </div>
      ${renderMagnetInfo(r.magnet)}
      ${renderExtractCandidates(r)}
      ${
        probeLog
          ? `<details><summary>probe_log（最近 ≤20 条）</summary><pre>${probeLog}</pre></details>`
          : ""
      }
    </div>
  `;
}

// === 渲染：stage tabs 计数 ===
function renderTabs() {
  const counts = {};
  for (const t of state.tasks) {
    const s = t.stage || "pending";
    counts[s] = (counts[s] || 0) + 1;
  }
  $$("#stage-tabs button").forEach((b) => {
    const s = b.dataset.stage;
    const total = state.tasks.length;
    const n = s === "" ? total : counts[s] || 0;
    // 保留原文本（避免重复追加），用 dataset 记录原 label
    if (!b.dataset.label) b.dataset.label = b.textContent.trim();
    b.textContent = `${b.dataset.label}（${n}）`;
    b.classList.toggle("active", s === state.filterStage);
  });
}

// === 渲染：列表主体 ===
function render() {
  const tasks = state.tasks.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const filtered = state.filterStage
    ? tasks.filter((t) => t.stage === state.filterStage)
    : tasks;
  els.list.innerHTML = filtered.length
    ? filtered.map(renderTask).join("")
    : `<div class="muted small">空。${state.filterStage ? `当前过滤 stage=${state.filterStage}` : "提交一个新链接试试。"}</div>`;
  renderTabs();
  schedulePoll();
}

// === 自动轮询：进行中任务存在时启 5s 轮询；都终态则停 ===
function schedulePoll() {
  const hasInFlight = state.tasks.some((t) => IN_FLIGHT.has(t.stage));
  if (hasInFlight && !state.pollTimer) {
    state.pollTimer = setInterval(reload, POLL_INTERVAL_MS);
  } else if (!hasInFlight && state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function reload() {
  try {
    const data = await api("/tasks");
    state.tasks = data.tasks || [];
    render();
  } catch (e) {
    els.list.innerHTML = `<div class="msg err">加载失败：${esc(e.message)}</div>`;
  }
}

async function onCreate(ev) {
  ev.preventDefault();
  setMsg(els.createMsg, "");
  const source_url = els.fSource.value.trim();
  if (!source_url) return;
  const payload = { source_url };
  const title = els.fTitle.value.trim();
  const note = els.fNote.value.trim();
  if (title) payload.title = title;
  if (note) payload.note = note;
  try {
    await api("/tasks", { method: "POST", body: payload });
    setMsg(els.createMsg, "已创建", "ok");
    els.fSource.value = "";
    els.fTitle.value = "";
    els.fNote.value = "";
    await reload();
  } catch (e) {
    setMsg(els.createMsg, "失败：" + e.message, "err");
  }
}

// === 任务行操作分发 ===
async function onTaskAction(ev) {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.dataset.id;
  const act = btn.dataset.act;
  if (!id || !act) return;
  btn.disabled = true;
  try {
    if (act === "probe") {
      await api(`/tasks/${encodeURIComponent(id)}/probe`, { method: "POST" });
      await reload();
    } else if (act === "enrich") {
      await api(`/tasks/${encodeURIComponent(id)}/enrich`, { method: "POST" });
      await reload();
    } else if (act === "bt-probe") {
      await api(`/tasks/${encodeURIComponent(id)}/bt-probe`, { method: "POST" });
      // bt-probe 是异步的，立即收到 stage=bt_probing；轮询会接管刷新
      await reload();
    } else if (act === "extract") {
      // cookies_name 可选；prompt 留空表示无需 cookies。
      // pattern 校验放后端；前端只做"非法字符就别发"的减负检查。
      const cookiesName = window.prompt(
        "可选：cookies 文件名（仅文件名，形如 mysite.txt；留空跳过）",
        ""
      );
      if (cookiesName === null) return; // 用户按取消
      const body = {};
      const cn = cookiesName.trim();
      if (cn) body.cookies_name = cn;
      await api(`/tasks/${encodeURIComponent(id)}/extract`, { method: "POST", body });
      await reload();
    } else if (act === "promote") {
      openPromote(id);
    } else if (act === "promote-cand") {
      // 候选行的快捷 promote：从 r.extract[idx] 取 stream_url + title 预填
      const idx = Number(btn.dataset.idx);
      const r = state.tasks.find((x) => x.id === id);
      const c = r && Array.isArray(r.extract) ? r.extract[idx] : null;
      if (!c) {
        alert("候选已失效，请刷新");
        return;
      }
      state.pendingPromotePrefill = {
        stream_url: c.stream_url || "",
        title: c.title || "",
      };
      openPromote(id);
    }
  } catch (e) {
    alert("操作失败：" + e.message);
  } finally {
    btn.disabled = false;
  }
}

function openPromote(id) {
  const t = state.tasks.find((x) => x.id === id);
  state.promoteId = id;
  const prefill = state.pendingPromotePrefill;
  if (prefill) {
    els.pStream.value = prefill.stream_url;
    els.pTitle.value = prefill.title;
    state.pendingPromotePrefill = null;
  } else {
    els.pStream.value = t && t.stream_url ? t.stream_url : t && t.source_url ? t.source_url : "";
    els.pTitle.value = "";
  }
  els.pTarget.value = "external_ready";
  if (typeof els.dlg.showModal === "function") {
    els.dlg.showModal();
  } else {
    els.dlg.setAttribute("open", "");
  }
}

async function onPromoteConfirm(ev) {
  if (ev.submitter && ev.submitter.value !== "confirm") return;
  ev.preventDefault();
  const id = state.promoteId;
  if (!id) return;
  const body = {
    stream_url: els.pStream.value.trim(),
    target_status: els.pTarget.value,
  };
  const title = els.pTitle.value.trim();
  if (title) body.title = title;
  try {
    await api(`/tasks/${encodeURIComponent(id)}/promote`, { method: "POST", body });
    els.dlg.close();
    state.promoteId = null;
    await reload();
  } catch (e) {
    alert("Promote 失败：" + e.message);
  }
}

function onTabClick(ev) {
  const b = ev.target.closest("button[data-stage]");
  if (!b) return;
  state.filterStage = b.dataset.stage;
  render();
}

async function onCopyPlaylist() {
  const url = new URL(els.lnkPlaylist.getAttribute("href"), window.location.origin).toString();
  try {
    await navigator.clipboard.writeText(url);
    alert("已复制：" + url);
  } catch (_) {
    prompt("手动复制：", url);
  }
}

function init() {
  els.form.addEventListener("submit", onCreate);
  els.btnRefresh.addEventListener("click", reload);
  els.btnCopy.addEventListener("click", onCopyPlaylist);
  els.list.addEventListener("click", onTaskAction);
  els.tabs.addEventListener("click", onTabClick);
  $("#form-promote").addEventListener("submit", onPromoteConfirm);
  reload();
}

document.addEventListener("DOMContentLoaded", init);
