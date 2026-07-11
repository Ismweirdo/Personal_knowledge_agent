#!/usr/bin/env sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/knowledge_agent_$timestamp.dump"

docker compose -f "$(dirname "$0")/docker-compose.yml" exec -T postgres \
  pg_dump -U postgres -d knowledge_agent -Fc > "$target"
find "$BACKUP_DIR" -type f -name 'knowledge_agent_*.dump' -mtime "+$RETENTION_DAYS" -delete
echo "Backup created: $target"
