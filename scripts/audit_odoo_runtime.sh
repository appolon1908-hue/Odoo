#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ODOO_CONTAINER=""
DB_CONTAINER=""
DATABASE=""
BASE_URL=""
ODOO_BIN="odoo"
ODOO_ENTRYPOINT=""
EXPECTED_ADMIN_LOGIN="appolon1908@gmail.com"

usage() {
  cat <<'USAGE'
Usage:
  audit_odoo_runtime.sh \
    --odoo-container <name> \
    --db-container <name> \
    --database <name> \
    [--base-url <https://odoo.example.com>] \
    [--odoo-bin <command>] \
    [--odoo-entrypoint <path>]

The audit auto-detects `/entrypoint.sh` in official Odoo images and invokes it
so HOST/PORT/USER/PASSWORD or their file-backed equivalents are translated to
Odoo database arguments. Use `--odoo-entrypoint` for an equivalent custom
entrypoint, or `--odoo-bin` when database settings are persisted safely in the
container's Odoo configuration.

This audit is read-only. It checks:
  - Odoo and PostgreSQL container state/health;
  - PostgreSQL readiness and the expected Odoo schema;
  - Odoo registry startup through the effective database connection path;
  - the designated human administrator login and email identity;
  - required and pending module states;
  - every custom module present in custom-addons/.
USAGE
}

while (($#)); do
  case "$1" in
    --odoo-container)
      ODOO_CONTAINER="${2:-}"
      shift 2
      ;;
    --db-container)
      DB_CONTAINER="${2:-}"
      shift 2
      ;;
    --database)
      DATABASE="${2:-}"
      shift 2
      ;;
    --base-url)
      BASE_URL="${2:-}"
      shift 2
      ;;
    --odoo-bin)
      ODOO_BIN="${2:-}"
      shift 2
      ;;
    --odoo-entrypoint)
      ODOO_ENTRYPOINT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'ERROR=UNKNOWN_ARGUMENT:%s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ODOO_CONTAINER" || -z "$DB_CONTAINER" || -z "$DATABASE" ]]; then
  usage >&2
  exit 2
fi

if [[ ! "$DATABASE" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  printf 'ERROR=UNSAFE_DATABASE_NAME\n' >&2
  exit 2
fi

command -v docker >/dev/null 2>&1 || {
  printf 'ERROR=DOCKER_NOT_AVAILABLE\n' >&2
  exit 1
}

check_container() {
  local label="$1"
  local container="$2"
  local status health

  status="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null)" || {
    printf 'ERROR=%s_CONTAINER_NOT_FOUND:%s\n' "$label" "$container" >&2
    return 1
  }
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "$container")"

  printf '%s_CONTAINER=%s\n' "$label" "$container"
  printf '%s_CONTAINER_STATE=%s\n' "$label" "$status"
  printf '%s_CONTAINER_HEALTH=%s\n' "$label" "$health"

  [[ "$status" == "running" ]] || {
    printf 'ERROR=%s_CONTAINER_NOT_RUNNING\n' "$label" >&2
    return 1
  }
  [[ "$health" != "unhealthy" ]] || {
    printf 'ERROR=%s_CONTAINER_UNHEALTHY\n' "$label" >&2
    return 1
  }
}

check_container ODOO "$ODOO_CONTAINER"
check_container POSTGRESQL "$DB_CONTAINER"

docker exec -i \
  -e TARGET_DB="$DATABASE" \
  "$DB_CONTAINER" \
  sh -s <<'DB_CHECK'
set -eu
db_user="${POSTGRES_USER:-odoo}"

if [ -n "${POSTGRES_PASSWORD_FILE:-}" ]; then
  if [ ! -r "$POSTGRES_PASSWORD_FILE" ]; then
    printf 'ERROR=POSTGRES_PASSWORD_FILE_NOT_READABLE\n' >&2
    exit 1
  fi
  export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
else
  export PGPASSWORD="${POSTGRES_PASSWORD:-}"
fi

pg_isready -q -U "$db_user" -d "$TARGET_DB" || {
  printf 'ERROR=POSTGRESQL_NOT_READY_FOR_TARGET_DATABASE\n' >&2
  exit 1
}

schema_ok="$(
  psql -X -v ON_ERROR_STOP=1 \
    -U "$db_user" \
    -d "$TARGET_DB" \
    -Atqc "
      SELECT CASE
        WHEN to_regclass('public.ir_module_module') IS NOT NULL
         AND to_regclass('public.res_users') IS NOT NULL
         AND to_regclass('public.ir_ui_view') IS NOT NULL
        THEN 1 ELSE 0
      END
    "
)"

if [ "$schema_ok" != "1" ]; then
  printf 'ERROR=ODOO_SCHEMA_NOT_PRESENT\n' >&2
  exit 1
fi

printf 'POSTGRESQL_READINESS=PASS\n'
printf 'ODOO_DATABASE_SCHEMA=PASS\n'
DB_CHECK

mapfile -t module_names < <(
  find "$ROOT_DIR/custom-addons" \
    -mindepth 2 \
    -maxdepth 2 \
    -type f \
    -name '__manifest__.py' \
    -printf '%h\n' \
    | xargs -r -n1 basename \
    | sort -u
)

expected_modules=""
if ((${#module_names[@]})); then
  expected_modules="$(IFS=,; printf '%s' "${module_names[*]}")"
fi

if [[ -z "$ODOO_ENTRYPOINT" ]] \
  && docker exec "$ODOO_CONTAINER" test -x /entrypoint.sh >/dev/null 2>&1; then
  ODOO_ENTRYPOINT="/entrypoint.sh"
fi

if [[ -n "$ODOO_ENTRYPOINT" ]]; then
  if ! docker exec "$ODOO_CONTAINER" test -x "$ODOO_ENTRYPOINT" >/dev/null 2>&1; then
    printf 'ERROR=ODOO_ENTRYPOINT_NOT_EXECUTABLE:%s\n' "$ODOO_ENTRYPOINT" >&2
    exit 1
  fi
  printf 'ODOO_SHELL_CONNECTION_MODE=ENTRYPOINT_ENV_TRANSLATION\n'
  docker exec -i \
    -e EXPECTED_ADMIN_LOGIN="$EXPECTED_ADMIN_LOGIN" \
    -e EXPECTED_ODOO_MODULES="$expected_modules" \
    "$ODOO_CONTAINER" \
    "$ODOO_ENTRYPOINT" -- shell -d "$DATABASE" --no-http \
    < "$ROOT_DIR/scripts/audit_odoo_state.py"
else
  printf 'ODOO_SHELL_CONNECTION_MODE=PERSISTED_ODOO_CONFIG\n'
  docker exec -i \
    -e EXPECTED_ADMIN_LOGIN="$EXPECTED_ADMIN_LOGIN" \
    -e EXPECTED_ODOO_MODULES="$expected_modules" \
    "$ODOO_CONTAINER" \
    "$ODOO_BIN" shell -d "$DATABASE" --no-http \
    < "$ROOT_DIR/scripts/audit_odoo_state.py"
fi

if [[ -n "$BASE_URL" ]]; then
  command -v curl >/dev/null 2>&1 || {
    printf 'ERROR=CURL_NOT_AVAILABLE_FOR_HTTP_CHECK\n' >&2
    exit 1
  }
  curl \
    --fail \
    --silent \
    --show-error \
    --max-time 15 \
    "${BASE_URL%/}/web/login?db=${DATABASE}" \
    >/dev/null
  printf 'ODOO_LOGIN_HTTP=PASS\n'
else
  printf 'ODOO_LOGIN_HTTP=NOT_CHECKED_NO_BASE_URL\n'
fi

printf 'RUNTIME_AUDIT=PASS\n'
