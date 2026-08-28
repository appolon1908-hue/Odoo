#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Multi-architecture index digests for reviewed official images.
ODOO_IMAGE="${ODOO_CI_IMAGE:-docker.io/library/odoo:19.0-20260817@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd}"
POSTGRES_IMAGE="${POSTGRES_CI_IMAGE:-docker.io/library/postgres:15-bookworm@sha256:b0c5bab0fbba8e0c221f73b1dc6359ec35f8650074377e727299df248fc8ad51}"

DATABASE="odoo_ci"
DB_USER="odoo_ci"
SAFE_RUN_ID="$(
  printf '%s' "${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$$" \
    | tr -cd 'A-Za-z0-9_.-'
)"
NETWORK="codestra-odoo-ci-${SAFE_RUN_ID}"
DB_CONTAINER="codestra-postgres-ci-${SAFE_RUN_ID}"
ODOO_DATA_VOLUME="codestra-odoo-data-${SAFE_RUN_ID}"
SECRET_DIR=""
TEST_LOG=""

cleanup() {
  docker rm -f "$DB_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  docker volume rm "$ODOO_DATA_VOLUME" >/dev/null 2>&1 || true
  if [[ -n "$SECRET_DIR" && -d "$SECRET_DIR" ]]; then
    sudo rm -rf "$SECRET_DIR" >/dev/null 2>&1 || true
  fi
  if [[ -n "$TEST_LOG" && -f "$TEST_LOG" ]]; then
    rm -f "$TEST_LOG" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || {
  printf 'ERROR=DOCKER_NOT_AVAILABLE\n' >&2
  exit 1
}

for image in "$ODOO_IMAGE" "$POSTGRES_IMAGE"; do
  [[ "$image" == *@sha256:* ]] || {
    printf 'ERROR=CI_IMAGE_NOT_DIGEST_PINNED:%s\n' "$image" >&2
    exit 1
  }
done

DB_PASSWORD="$(
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(36))
PY
)"
ADMIN_PASSWORD="$(
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(40))
PY
)"

printf '==> Pulling immutable Odoo and PostgreSQL images\n'
docker pull "$ODOO_IMAGE"
docker pull "$POSTGRES_IMAGE"

printf 'ODOO_IMAGE=%s\n' "$ODOO_IMAGE"
printf 'POSTGRES_IMAGE=%s\n' "$POSTGRES_IMAGE"
docker image inspect \
  --format 'ODOO_IMAGE_ID={{.Id}}' \
  "$ODOO_IMAGE"
docker image inspect \
  --format 'POSTGRES_IMAGE_ID={{.Id}}' \
  "$POSTGRES_IMAGE"

docker network create "$NETWORK" >/dev/null
docker volume create "$ODOO_DATA_VOLUME" >/dev/null

printf '==> Starting isolated PostgreSQL\n'
docker run -d \
  --name "$DB_CONTAINER" \
  --network "$NETWORK" \
  --network-alias db \
  -e POSTGRES_USER="$DB_USER" \
  -e POSTGRES_PASSWORD="$DB_PASSWORD" \
  -e POSTGRES_DB="$DATABASE" \
  --health-cmd="pg_isready -U $DB_USER -d $DATABASE" \
  --health-interval=2s \
  --health-timeout=3s \
  --health-retries=45 \
  "$POSTGRES_IMAGE" \
  >/dev/null

for _ in $(seq 1 60); do
  db_health="$(
    docker inspect \
      --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$DB_CONTAINER"
  )"
  if [[ "$db_health" == "healthy" ]]; then
    break
  fi
  if [[ "$db_health" == "unhealthy" || "$db_health" == "exited" ]]; then
    docker logs "$DB_CONTAINER" >&2 || true
    printf 'ERROR=POSTGRESQL_CI_STARTUP_FAILED:%s\n' "$db_health" >&2
    exit 1
  fi
  sleep 2
done

if [[ "$(docker inspect --format '{{.State.Health.Status}}' "$DB_CONTAINER")" != "healthy" ]]; then
  docker logs "$DB_CONTAINER" >&2 || true
  printf 'ERROR=POSTGRESQL_CI_READINESS_TIMEOUT\n' >&2
  exit 1
fi

printf 'POSTGRESQL_CONTAINER_HEALTH=PASS\n'
docker exec "$DB_CONTAINER" postgres --version

printf '==> Installing and testing every reviewed custom module on Odoo 19\n'
mapfile -t module_names < <(
  find custom-addons \
    -mindepth 2 \
    -maxdepth 2 \
    -type f \
    -name '__manifest__.py' \
    -printf '%h\n' \
    | xargs -r -n1 basename \
    | sort -u
)
if ((${#module_names[@]} == 0)); then
  printf 'ERROR=NO_CUSTOM_MODULES_FOR_RUNTIME_TEST\n' >&2
  exit 1
fi
module_csv="$(IFS=,; printf '%s' "${module_names[*]}")"
test_tags=""
for module_name in "${module_names[@]}"; do
  if [[ -n "$test_tags" ]]; then
    test_tags+=","
  fi
  test_tags+="/${module_name}"
done

TEST_LOG="$(mktemp)"
if ! docker run --rm \
  --network "$NETWORK" \
  -e HOST=db \
  -e PORT=5432 \
  -e USER="$DB_USER" \
  -e PASSWORD="$DB_PASSWORD" \
  -v "$ROOT_DIR/custom-addons:/mnt/extra-addons:ro" \
  -v "$ODOO_DATA_VOLUME:/var/lib/odoo" \
  "$ODOO_IMAGE" \
  -- \
  -d "$DATABASE" \
  --db-filter="^${DATABASE}$" \
  --init="$module_csv" \
  --without-demo \
  --test-enable \
  --test-tags="$test_tags" \
  --stop-after-init \
  --workers=0 \
  --http-interface=127.0.0.1 \
  --log-level=test \
  2>&1 | tee "$TEST_LOG"; then
  printf 'ERROR=ODOO_MODULE_INSTALL_OR_TEST_FAILED\n' >&2
  exit 1
fi

if grep -Fq "Internal Error:" "$TEST_LOG"; then
  printf 'ERROR=ODOO_ASSET_COMPILATION_INTERNAL_ERROR\n' >&2
  exit 1
fi
if grep -Fq "invalid boolean value" "$TEST_LOG"; then
  printf 'ERROR=ODOO_INVALID_CLI_BOOLEAN\n' >&2
  exit 1
fi
if ! grep -Eq "0 failed, 0 error\(s\)" "$TEST_LOG"; then
  printf 'ERROR=ODOO_TEST_SUCCESS_MARKER_MISSING\n' >&2
  exit 1
fi

printf 'ODOO_ASSET_COMPILATION=PASS\n'
printf 'ODOO_MODULE_INSTALL_AND_TEST=PASS\n'
printf 'CUSTOM_MODULES_TESTED=%s\n' "${#module_names[@]}"

printf '==> Exercising fail-closed administrator provisioning\n'
SECRET_DIR="$(mktemp -d)"
ADMIN_SECRET="$SECRET_DIR/codestra_odoo_admin_password"
umask 077
printf '%s' "$ADMIN_PASSWORD" > "$ADMIN_SECRET"
chmod 0400 "$ADMIN_SECRET"

mapfile -t odoo_ids < <(
  docker run --rm \
    --entrypoint sh \
    "$ODOO_IMAGE" \
    -c 'id -u; id -g'
)
if ((${#odoo_ids[@]} != 2)); then
  printf 'ERROR=UNABLE_TO_RESOLVE_ODOO_CONTAINER_IDENTITY\n' >&2
  exit 1
fi
sudo chown "${odoo_ids[0]}:${odoo_ids[1]}" "$ADMIN_SECRET"

docker run --rm \
  --network "$NETWORK" \
  -e HOST=db \
  -e PORT=5432 \
  -e USER="$DB_USER" \
  -e PASSWORD="$DB_PASSWORD" \
  -e ODOO_ADMIN_LOGIN=appolon1908@gmail.com \
  -e ODOO_ADMIN_BOOTSTRAP_APPLY=YES \
  -e ODOO_ADMIN_PASSWORD_FILE=/run/secrets/codestra_odoo_admin_password \
  -v "$ROOT_DIR/custom-addons:/mnt/extra-addons:ro" \
  -v "$ROOT_DIR/scripts/ensure_codestra_admin.py:/opt/codestra/ensure_codestra_admin.py:ro" \
  -v "$ADMIN_SECRET:/run/secrets/codestra_odoo_admin_password:ro" \
  -v "$ODOO_DATA_VOLUME:/var/lib/odoo" \
  "$ODOO_IMAGE" \
  -- \
  shell -d "$DATABASE" --no-http \
  < "$ROOT_DIR/scripts/ensure_codestra_admin.py"

printf 'ADMINISTRATOR_PROVISIONING_RUNTIME_TEST=PASS\n'

printf '==> Auditing database, administrator, and installed module state\n'
docker run --rm \
  --network "$NETWORK" \
  -e HOST=db \
  -e PORT=5432 \
  -e USER="$DB_USER" \
  -e PASSWORD="$DB_PASSWORD" \
  -e EXPECTED_ADMIN_LOGIN=appolon1908@gmail.com \
  -e EXPECTED_ODOO_MODULES="$module_csv" \
  -v "$ROOT_DIR/custom-addons:/mnt/extra-addons:ro" \
  -v "$ODOO_DATA_VOLUME:/var/lib/odoo" \
  "$ODOO_IMAGE" \
  -- \
  shell -d "$DATABASE" --no-http \
  < "$ROOT_DIR/scripts/audit_odoo_state.py"

schema_ok="$(
  docker exec \
    -e PGPASSWORD="$DB_PASSWORD" \
    "$DB_CONTAINER" \
    psql -X -v ON_ERROR_STOP=1 \
      -U "$DB_USER" \
      -d "$DATABASE" \
      -Atqc "
        SELECT CASE
          WHEN to_regclass('public.ir_module_module') IS NOT NULL
           AND to_regclass('public.res_users') IS NOT NULL
           AND to_regclass('public.ir_ui_view') IS NOT NULL
          THEN 1 ELSE 0
        END
      "
)"
if [[ "$schema_ok" != "1" ]]; then
  printf 'ERROR=ODOO_CI_SCHEMA_AUDIT_FAILED\n' >&2
  exit 1
fi

printf 'POSTGRESQL_SCHEMA_AUDIT=PASS\n'
printf 'ADMINISTRATOR_STATE_AUDIT=PASS\n'
printf 'MODULE_STATE_AUDIT=PASS\n'
printf 'ODOO_POSTGRESQL_RUNTIME_CI=PASS\n'
