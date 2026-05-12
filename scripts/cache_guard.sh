#!/usr/bin/env bash
set -euo pipefail

# 最低磁盘保护：超阈值时按目录 mtime 删除最旧缓存目录。
# 这是 Phase 0 的兜底方案，后续可由应用内精细淘汰替代。

CACHE_DIR="${BT_PLAYER_CACHE_DIR:-/var/lib/btplayer/cache}"
MAX_GIB="${BT_PLAYER_CACHE_MAX_GIB:-5}"
FLOOR_PERCENT="${BT_PLAYER_CACHE_FLOOR_PERCENT:-80}"
PROTECT_NAME="${BT_PLAYER_CACHE_DB_NAME:-bt_player.db}"

if [[ ! -d "$CACHE_DIR" ]]; then
  exit 0
fi

max_bytes=$((MAX_GIB * 1024 * 1024 * 1024))
floor_bytes=$((max_bytes * FLOOR_PERCENT / 100))

dir_size_bytes() {
  du -sb "$1" | awk '{print $1}'
}

total_bytes="$(dir_size_bytes "$CACHE_DIR")"
if (( total_bytes <= max_bytes )); then
  exit 0
fi

echo "[cache_guard] cache over limit: ${total_bytes} > ${max_bytes}" >&2

# 只清理一级子目录，避免误删根目录文件。
mapfile -t candidates < <(
  ls -1dt "$CACHE_DIR"/*/ 2>/dev/null || true
)

for dir in "${candidates[@]}"; do
  base="$(basename "$dir")"
  # 跳过数据库文件同名目录（防御性判断）
  if [[ "$base" == "$PROTECT_NAME" ]]; then
    continue
  fi

  rm -rf -- "$dir"
  total_bytes="$(dir_size_bytes "$CACHE_DIR")"
  echo "[cache_guard] removed: $dir, now=${total_bytes}" >&2

  if (( total_bytes <= floor_bytes )); then
    break
  fi
done
