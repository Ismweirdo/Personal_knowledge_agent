#!/usr/bin/env sh
set -eu

backup="${1:-}"
if [ -z "$backup" ] || [ ! -f "$backup" ]; then
  echo "Usage: $0 path/to/knowledge_agent.dump" >&2
  exit 2
fi
printf 'Restore will replace database contents. Type RESTORE to continue: '
read -r confirmation
[ "$confirmation" = "RESTORE" ] || exit 1

compose="$(dirname "$0")/docker-compose.yml"
docker compose -f "$compose" exec -T postgres dropdb -U postgres --if-exists knowledge_agent
docker compose -f "$compose" exec -T postgres createdb -U postgres knowledge_agent
docker compose -f "$compose" exec -T postgres pg_restore -U postgres -d knowledge_agent --clean --if-exists < "$backup"
echo "Restore completed"
