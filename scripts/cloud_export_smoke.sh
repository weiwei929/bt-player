#!/usr/bin/env bash
set -euo pipefail

# 云导出占位链路 smoke test：
# 1) 创建任务（queued）
# 2) 查询任务列表
# 3) 手动更新状态（failed）
#
# 说明：
# - 不依赖 jq，使用 python3 解析 JSON。
# - 仅验证“任务接口与状态流”，不涉及任何实时播放链路。

API_BASE="${API_BASE:-http://127.0.0.1:9528}"
API_TOKEN="${API_TOKEN:-}"

auth_args=()
if [[ -n "$API_TOKEN" ]]; then
  auth_args+=(-H "x-api-key: ${API_TOKEN}")
fi

echo "[1/3] create cloud export task..."
create_resp="$(
  curl -fsS "${auth_args[@]}" \
    -H "Content-Type: application/json" \
    -X POST "${API_BASE}/api/cloud-exports" \
    --data '{
      "provider":"pikpak",
      "resource_id":"smoke-btih-001",
      "source_type":"magnet",
      "source_locator":"magnet:?xt=urn:btih:SMOKE_TEST_EXAMPLE"
    }'
)"
echo "$create_resp"

task_id="$(
  python3 - <<'PY' "$create_resp"
import json, sys
obj = json.loads(sys.argv[1])
print(obj.get("id", ""))
PY
)"
if [[ -z "$task_id" ]]; then
  echo "failed: cannot parse task id from response"
  exit 1
fi
echo "created task_id=${task_id}"

echo "[2/3] list cloud export tasks..."
list_resp="$(curl -fsS "${auth_args[@]}" "${API_BASE}/api/cloud-exports")"
echo "$list_resp"

echo "[3/3] update task status to failed (manual transition test)..."
update_resp="$(
  curl -fsS "${auth_args[@]}" \
    -H "Content-Type: application/json" \
    -X POST "${API_BASE}/api/cloud-exports/status" \
    --data "{\"id\":${task_id},\"status\":\"failed\",\"error_message\":\"smoke-check\"}"
)"
echo "$update_resp"

echo "done: smoke test finished"
