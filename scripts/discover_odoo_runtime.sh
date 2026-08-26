#!/usr/bin/env bash
# Read-only discovery for a Docker-based Odoo installation.
set -Eeuo pipefail

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed or not in PATH"
docker info >/dev/null 2>&1 || fail "cannot access the Docker daemon"

odoo_container_id="$(
  docker ps \
    --filter 'label=com.docker.compose.service=odoo' \
    --format '{{.ID}}' | head -n 1
)"

if [[ -z "$odoo_container_id" ]]; then
  odoo_container_id="$(
    docker ps --format '{{.ID}}\t{{.Names}}\t{{.Image}}' |
      awk 'tolower($0) ~ /odoo/ && tolower($0) !~ /postgres|database|backup/ {print $1; exit}'
  )"
fi

[[ -n "$odoo_container_id" ]] || fail "running Odoo application container was not found"

printf 'ODOO_CONTAINER_ID=%s\n' "$odoo_container_id"
docker inspect "$odoo_container_id" --format 'ODOO_CONTAINER_NAME={{trimPrefix "/" .Name}}'
docker inspect "$odoo_container_id" --format 'ODOO_IMAGE={{.Config.Image}}'
docker inspect "$odoo_container_id" --format 'COMPOSE_PROJECT={{index .Config.Labels "com.docker.compose.project"}}'
docker inspect "$odoo_container_id" --format 'COMPOSE_SERVICE={{index .Config.Labels "com.docker.compose.service"}}'
docker inspect "$odoo_container_id" --format 'COMPOSE_WORKING_DIR={{index .Config.Labels "com.docker.compose.project.working_dir"}}'
docker inspect "$odoo_container_id" --format 'COMPOSE_CONFIG_FILES={{index .Config.Labels "com.docker.compose.project.config_files"}}'

printf '\nODOO_VERSION\n'
docker exec "$odoo_container_id" sh -lc \
  'odoo --version 2>/dev/null || odoo-bin --version 2>/dev/null || true'

printf '\nODOO_MOUNTS\n'
docker inspect "$odoo_container_id" --format \
  '{{range .Mounts}}{{printf "%s\t%s -> %s\tRW=%t\n" .Type .Source .Destination .RW}}{{end}}'

printf '\nODOO_CONFIG_NON_SECRET_FIELDS\n'
docker exec "$odoo_container_id" sh -lc '
  found=0
  for file in /etc/odoo/odoo.conf /etc/odoo.conf; do
    if [ -f "$file" ]; then
      found=1
      printf "CONFIG_FILE=%s\n" "$file"
      grep -E "^[[:space:]]*(addons_path|data_dir|db_host|db_port|db_user|db_name|proxy_mode|workers|max_cron_threads)[[:space:]]*=" "$file" || true
    fi
  done
  [ "$found" -eq 1 ] || printf "CONFIG_FILE=NOT_FOUND_IN_STANDARD_LOCATIONS\n"
'

printf '\nCOMPOSE_PROJECTS\n'
docker compose ls 2>/dev/null || true

printf '\nRUNNING_ODOO_RELATED_CONTAINERS\n'
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' |
  awk 'NR == 1 || tolower($0) ~ /odoo|postgres/'

printf '\nDiscovery completed without changing containers, files, databases, or networks.\n'
