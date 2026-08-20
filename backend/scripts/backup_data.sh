#!/usr/bin/env bash
# Daily off-site backup of the application data directory (Doc M7 / plan 0.7).
#
#   backend/scripts/backup_data.sh [DATA_DIR] [DEST]
#
#   DATA_DIR  defaults to backend/data (must contain workspaces/)
#   DEST      local dir or rsync target, e.g. user@backup-host:/srv/petition-backups
#
# What it does
#   1. tar.gz DATA_DIR (excluding *.lock, llm_cache/) to /tmp/petition-data-<ts>.tar.gz
#   2. rsync it to DEST (or cp if DEST is a local dir)
#   3. keep the last 14 archives at DEST when DEST is local
#
# crontab example (03:15 every day):
#   15 3 * * * /srv/petition/backend/scripts/backup_data.sh /srv/petition/backend/data user@backup:/srv/petition-backups >> /var/log/petition-backup.log 2>&1
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${1:-$HERE/../data}"
DEST="${2:?usage: backup_data.sh [DATA_DIR] DEST}"
KEEP=14

TS="$(date -u +%Y%m%d_%H%M%S)"
ARCHIVE="/tmp/petition-data-${TS}.tar.gz"

if [ ! -d "$DATA_DIR" ]; then
  echo "[backup] data dir not found: $DATA_DIR" >&2
  exit 1
fi

echo "[backup] $(date -u +%FT%TZ) archiving $DATA_DIR"
tar --exclude='*.lock' --exclude='llm_cache' -czf "$ARCHIVE" -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")"
SIZE=$(du -h "$ARCHIVE" | cut -f1)
echo "[backup] archive $ARCHIVE ($SIZE)"

if [[ "$DEST" == *:* ]]; then
  rsync -az --partial "$ARCHIVE" "$DEST/"
  echo "[backup] rsync -> $DEST"
else
  mkdir -p "$DEST"
  cp "$ARCHIVE" "$DEST/"
  echo "[backup] copied -> $DEST"
  # prune
  ls -1t "$DEST"/petition-data-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
fi

rm -f "$ARCHIVE"
echo "[backup] done"
