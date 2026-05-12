// PureSource 资源提纯工作台 — zero-build 前端
// 设计原则：
//   1) 仅调本服务公开/私有 API；不存任何 Basic Auth 凭据。
//   2) 状态机分层：stage（提纯进度）由后端给；status（列表准入）只在 promote 后才会有值。
//   3) /tasks*、/intake、/resources 在生产受 Basic Auth 保护；浏览器靠 401 弹窗或 OS 钥匙串。
//   4) UI 不调用 /playlists/movies.m3u8 / debug.m3u8 等"未实现端点"，避免被 Caddy 403 防护命中。

const STAGE_ORDER = ["pending", "probing", "playable", "external_ready", "failed"];
const PROMOTABLE = new Set(["playable", "external_ready"]);

const state = {
  filterStage: "",
  tasks: [],
  promoteId: null,
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
    </div>
  `;
}

function renderTask(r) {
  const stage = r.stage || "pending";
  const status = r.status || "—";
  // magnet 用 enrich 替换 probe 槽位；mp4/m3u8 用 probe；webpage/other 不渲染按钮（不挂禁用按钮）。
  let actionBtn = "";
  if (r.source_kind === "magnet") {
    actionBtn = `<button data-act="enrich" data-id="${r.id}" title="纯字符串解析 info_hash / dn / trackers，零网络">enrich</button>`;
  } else if (r.source_kind === "mp4" || r.source_kind === "m3u8") {
    actionBtn = `<button data-act="probe" data-id="${r.id}">probe</button>`;
  }
  const promoteBtn = PROMOTABLE.has(stage)
    ? `<button class="primary" data-act="promote" data-id="${r.id}">promote</button>`
    : `<button disabled title="仅 playable / external_ready 可 promote">promote</button>`;

  const probeLog = (r.probe_log || []).map((l) => esc(l)).join("\n");

  return `
    <div class="task" data-id="${r.id}">
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
        ${actionBtn}
        ${promoteBtn}
      </div>
      ${renderMagnetInfo(r.magnet)}
      ${
        probeLog
          ? `<details><summary>probe_log（最近 ≤20 条）</summary><pre>${probeLog}</pre></details>`
          : ""
      }
    </div>
  `;
}

function render() {
  const tasks = state.tasks.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const filtered = state.filterStage
    ? tasks.filter((t) => t.stage === state.filterStage)
    : tasks;
  els.list.innerHTML = filtered.length
    ? filtered.map(renderTask).join("")
    : `<div class="muted small">空。${state.filterStage ? `当前过滤 stage=${state.filterStage}` : "提交一个新链接试试。"}</div>`;
  $$("#stage-tabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.stage === state.filterStage);
  });
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
    } else if (act === "promote") {
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
  els.pStream.value = t && t.stream_url ? t.stream_url : t && t.source_url ? t.source_url : "";
  els.pTitle.value = "";
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
