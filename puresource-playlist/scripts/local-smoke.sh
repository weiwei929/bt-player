#!/usr/bin/env bash
# 本地 smoke：在独立端口（默认 8190）起一个 uvicorn，验证
#   create / probe / promote / list 端到端 + PotPlayer 列表准入隔离。
# 不动 systemd 服务（puresource-playlist.service 仍跑在 8090）。
# 通过 PURESOURCE_DATA_DIR 把数据存到临时目录，避免污染生产 data/resources.json。
#
# 用法：
#   scripts/local-smoke.sh
# 选项（环境变量）：
#   PORT            uvicorn 端口（默认 8190）
#   KEEP_DATA       1 表示保留 smoke 数据目录，便于事后检查
#   MP4_OK          一条 HEAD 可达、Content-Type=video/* 的 mp4 URL
#   MP4_BAD         一条以 .mp4 结尾且响应 4xx 的 URL（须为 mp4 kind，否则会被判为 webpage 而跳过 probe）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8190}"
SMOKE_DIR="$(mktemp -d -t puresource-smoke.XXXXXX)"
export PURESOURCE_DATA_DIR="$SMOKE_DIR"

# 默认样本：Big Buck Bunny 公网托管的 mp4；如需更稳定可通过 MP4_OK 覆盖。
MP4_OK="${MP4_OK:-https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4}"
MP4_BAD="${MP4_BAD:-https://download.blender.org/peach/bigbuckbunny_movies/__no_such_file__.mp4}"
MAGNET="magnet:?xt=urn:btih:2CBB4A34738EEFC45A677E4848A303ABA9412798&dn=Big+Buck+Bunny&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
MAGNET_EXPECT_IH="2cbb4a34738eefc45a677e4848a303aba9412798"

BASE="http://127.0.0.1:${PORT}"
LOG="$SMOKE_DIR/uvicorn.log"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*"; }
hr() { printf '\n--- %s ---\n' "$*"; }

cleanup() {
  if [[ -n "${UVI_PID:-}" ]] && kill -0 "$UVI_PID" 2>/dev/null; then
    kill "$UVI_PID" 2>/dev/null || true
    wait "$UVI_PID" 2>/dev/null || true
  fi
  if [[ "${KEEP_DATA:-0}" != "1" ]]; then
    rm -rf "$SMOKE_DIR"
  else
    echo "保留 smoke 数据：$SMOKE_DIR"
  fi
}
trap cleanup EXIT

require_cmd() { command -v "$1" >/dev/null || { red "缺少命令：$1"; exit 2; }; }
require_cmd curl
require_cmd jq
require_cmd python3

hr "启动 uvicorn @ ${PORT}（独立端口，不动 systemd 8090 服务）"
python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  >"$LOG" 2>&1 &
UVI_PID=$!

# 等待 /health
for i in $(seq 1 30); do
  if curl -fsS "$BASE/health" >/dev/null 2>&1; then break; fi
  sleep 0.3
done
if ! curl -fsS "$BASE/health" >/dev/null; then
  red "uvicorn 未就绪，日志："
  cat "$LOG"
  exit 1
fi
green "health ok"

hr "1) 创建 mp4 任务（应得 stage=pending, status=null）"
T_MP4=$(curl -fsS -X POST "$BASE/tasks" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "$MP4_OK" '{source_url:$u, title:"smoke-mp4"}')")
ID_MP4=$(jq -r .id <<<"$T_MP4")
STAGE_MP4=$(jq -r .stage <<<"$T_MP4")
STATUS_MP4=$(jq -r .status <<<"$T_MP4")
echo "id=$ID_MP4 stage=$STAGE_MP4 status=$STATUS_MP4"
[[ "$STAGE_MP4" == "pending" ]] || { red "expect pending"; exit 1; }
[[ "$STATUS_MP4" == "null" ]] || { red "expect status=null on create"; exit 1; }
green "OK"

hr "2) 创建 magnet 任务（应得 stage=pending, source_kind=magnet）"
T_MAG=$(curl -fsS -X POST "$BASE/tasks" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "$MAGNET" '{source_url:$u, title:"smoke-magnet"}')")
ID_MAG=$(jq -r .id <<<"$T_MAG")
KIND_MAG=$(jq -r .source_kind <<<"$T_MAG")
echo "id=$ID_MAG kind=$KIND_MAG"
[[ "$KIND_MAG" == "magnet" ]] || { red "expect kind=magnet"; exit 1; }
green "OK"

hr "3) 创建 4xx 任务（mp4 后缀但响应 404，应在 probe 后 failed）"
T_BAD=$(curl -fsS -X POST "$BASE/tasks" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "$MP4_BAD" '{source_url:$u, title:"smoke-bad"}')")
ID_BAD=$(jq -r .id <<<"$T_BAD")
echo "id=$ID_BAD"
green "OK"

hr "4) probe magnet（应保持 pending，不接 BT 引擎）"
P_MAG=$(curl -fsS -X POST "$BASE/tasks/$ID_MAG/probe")
STAGE_MAG=$(jq -r .stage <<<"$P_MAG")
echo "magnet after probe: stage=$STAGE_MAG"
[[ "$STAGE_MAG" == "pending" ]] || { red "magnet 不应被 probe 改状态"; exit 1; }
green "OK"

hr "4a) enrich magnet（纯 URI 解析，stage 必须保持 pending；零网络）"
E_MAG=$(curl -fsS -X POST "$BASE/tasks/$ID_MAG/enrich")
STAGE_E_MAG=$(jq -r .stage <<<"$E_MAG")
STATUS_E_MAG=$(jq -r .status <<<"$E_MAG")
IH=$(jq -r '.magnet.info_hash // empty' <<<"$E_MAG")
IH_KIND=$(jq -r '.magnet.info_hash_kind // empty' <<<"$E_MAG")
DN=$(jq -r '.magnet.display_name // empty' <<<"$E_MAG")
TR_COUNT=$(jq -r '.magnet.trackers | length' <<<"$E_MAG")
echo "enrich: stage=$STAGE_E_MAG status=$STATUS_E_MAG ih=$IH kind=$IH_KIND dn=$DN trackers=$TR_COUNT"
[[ "$STAGE_E_MAG" == "pending" ]] || { red "enrich 不应改 stage"; exit 1; }
[[ "$STATUS_E_MAG" == "null" ]] || { red "enrich 不应写 status"; exit 1; }
[[ "$IH" == "$MAGNET_EXPECT_IH" ]] || { red "info_hash 不匹配，期望 $MAGNET_EXPECT_IH 实际 $IH"; exit 1; }
[[ "$IH_KIND" == "v1" ]] || { red "expect kind=v1"; exit 1; }
[[ "$DN" == "Big Buck Bunny" ]] || { red "display_name 解析错"; exit 1; }
[[ "$TR_COUNT" == "1" ]] || { red "trackers 计数错，期望 1 实际 $TR_COUNT"; exit 1; }
green "OK"

hr "4a-bis) enrich 在非 magnet 任务上应得 409"
HTTP_ENR_MP4=$(curl -sS -o /tmp/.enr-mp4.json -w '%{http_code}' \
  -X POST "$BASE/tasks/$ID_MP4/enrich")
echo "enrich on mp4 → HTTP $HTTP_ENR_MP4"
[[ "$HTTP_ENR_MP4" == "409" ]] || { red "expect 409, got $HTTP_ENR_MP4"; cat /tmp/.enr-mp4.json; exit 1; }
green "OK"

hr "4b) POST /tasks 空白 source_url → 422"
HTTP_EMPTY=$(curl -sS -o /tmp/.empty-task.json -w '%{http_code}' \
  -X POST "$BASE/tasks" \
  -H 'Content-Type: application/json' \
  -d '{"source_url":"   ","title":"x"}')
echo "HTTP $HTTP_EMPTY"
[[ "$HTTP_EMPTY" == "422" ]] || { red "expect 422 for blank source_url"; cat /tmp/.empty-task.json; exit 1; }
green "OK"

hr "4c) 网页链接 probe 后仍为 pending（第一版仅登记）"
T_WEB=$(curl -fsS -X POST "$BASE/tasks" \
  -H 'Content-Type: application/json' \
  -d '{"source_url":"https://example.com/foo/bar","title":"smoke-web"}')
ID_WEB=$(jq -r .id <<<"$T_WEB")
KIND_WEB=$(jq -r .source_kind <<<"$T_WEB")
echo "id=$ID_WEB kind=$KIND_WEB"
[[ "$KIND_WEB" == "webpage" ]] || { red "expect kind=webpage"; exit 1; }
P_WEB=$(curl -fsS -X POST "$BASE/tasks/$ID_WEB/probe")
STAGE_WEB=$(jq -r .stage <<<"$P_WEB")
echo "webpage after probe: stage=$STAGE_WEB"
[[ "$STAGE_WEB" == "pending" ]] || { red "webpage probe 应保持 pending"; exit 1; }
green "OK"

hr "5) probe 4xx 链接（应得 stage=failed）"
P_BAD=$(curl -fsS -X POST "$BASE/tasks/$ID_BAD/probe")
STAGE_BAD=$(jq -r .stage <<<"$P_BAD")
echo "bad after probe: stage=$STAGE_BAD"
[[ "$STAGE_BAD" == "failed" ]] || { red "expect failed, got $STAGE_BAD"; jq -r .probe_log[] <<<"$P_BAD"; exit 1; }
green "OK"

hr "6) probe mp4 链接（期望 playable；网络问题时跳过但不算失败）"
P_MP4=$(curl -fsS -X POST "$BASE/tasks/$ID_MP4/probe" || true)
STAGE_AFTER_MP4=$(jq -r .stage <<<"$P_MP4" 2>/dev/null || echo "?")
echo "mp4 after probe: stage=$STAGE_AFTER_MP4"
echo "probe_log:"
jq -r '.probe_log[]?' <<<"$P_MP4" | sed 's/^/  /'
case "$STAGE_AFTER_MP4" in
  playable) green "OK (playable)";;
  failed)  printf '\033[33m注意：mp4 probe 落到 failed，可能是网络/上游问题；不阻断 smoke。\033[0m\n';;
  *) red "意外 stage=$STAGE_AFTER_MP4"; exit 1;;
esac

hr "7) 列表准入隔离：default.m3u8 此时应只有 #EXTM3U 头，没有任何条目"
PL_BEFORE=$(curl -fsS "$BASE/playlists/potplayer/default.m3u8")
echo "$PL_BEFORE"
COUNT_URL_BEFORE=$(echo "$PL_BEFORE" | grep -cE '^https?://' || true)
[[ "$COUNT_URL_BEFORE" -eq 0 ]] || { red "未 promote 时列表不应有任何 http URL"; exit 1; }
green "OK（pending/probing/failed/playable 均不入列）"

hr "8) promote magnet（应被 409 拒绝，因为 stage=pending）"
HTTP_CODE=$(curl -sS -o /tmp/.promote-mag.json -w '%{http_code}' \
  -X POST "$BASE/tasks/$ID_MAG/promote" \
  -H 'Content-Type: application/json' \
  -d '{"stream_url":"https://example.com/x.mp4","target_status":"external_ready"}')
echo "promote magnet → HTTP $HTTP_CODE"
cat /tmp/.promote-mag.json; echo
[[ "$HTTP_CODE" == "409" ]] || { red "expect 409, got $HTTP_CODE"; exit 1; }
green "OK"

hr "9) 手工 promote mp4 任务（直接以原 URL 当 stream_url；stage 必须先是 playable/external_ready）"
# 如果第 6 步 probe 未达 playable，则用 update_resource 兜底——这里改为只在 playable 时跑。
if [[ "$STAGE_AFTER_MP4" == "playable" ]]; then
  PROM=$(curl -fsS -X POST "$BASE/tasks/$ID_MP4/promote" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$MP4_OK" '{stream_url:$u, target_status:"external_ready"}')")
  STAGE_PROM=$(jq -r .stage <<<"$PROM")
  STATUS_PROM=$(jq -r .status <<<"$PROM")
  echo "promoted: stage=$STAGE_PROM status=$STATUS_PROM"
  [[ "$STAGE_PROM" == "external_ready" && "$STATUS_PROM" == "external_ready" ]] || {
    red "promote 未生效"; exit 1; }
  green "OK"

  hr "10) default.m3u8 现在应包含被 promote 的那一条"
  PL_AFTER=$(curl -fsS "$BASE/playlists/potplayer/default.m3u8")
  echo "$PL_AFTER"
  if grep -qF "$MP4_OK" <<<"$PL_AFTER"; then
    green "OK（promote 后入列）"
  else
    red "promote 后未出现在 default.m3u8"
    exit 1
  fi
else
  printf '\033[33m步骤 6 未达 playable，跳过 promote/入列验证（但已验证未 promote 时绝对不入列）。\033[0m\n'
fi

hr "11) GET /tasks?stage=failed 过滤验证"
F_FAIL=$(curl -fsS "$BASE/tasks?stage=failed" | jq '.tasks | length')
echo "failed count=$F_FAIL（至少含 1：bad 链接）"
[[ "$F_FAIL" -ge 1 ]] || { red "expect >=1 failed task"; exit 1; }
green "OK"

hr "12) 终态再验：magnet enrich 后 default.m3u8 仍不应出现 magnet/info_hash 字样"
PL_FINAL=$(curl -fsS "$BASE/playlists/potplayer/default.m3u8")
if grep -qi 'magnet:' <<<"$PL_FINAL" || grep -qi "$MAGNET_EXPECT_IH" <<<"$PL_FINAL"; then
  red "default.m3u8 不应包含 magnet 或 info_hash 字面"
  echo "$PL_FINAL"
  exit 1
fi
green "OK（magnet 永不出现在 PotPlayer 列表）"

hr "smoke 结束"
green "ALL CORE CHECKS PASSED"
echo "data dir: $SMOKE_DIR  uvicorn log: $LOG"
