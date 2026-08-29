#!/usr/bin/env bash
# Prepare and deploy an immutable, reviewed Odoo release. Never runs implicitly.
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: sudo deploy_odoo_release.sh --execute --sha SHA --environment staging|production \
  --repository PATH --compose-directory PATH --service NAME --database NAME \
  --modules CSV --db-backup-id ID --db-backup-path PATH \
  --filestore-backup-id ID --filestore-backup-path PATH \
  --ci-evidence PATH --release-manifest PATH [--staging-certification PATH]

The script refuses production unless staging certification is supplied. It does
not create backups; it verifies explicit matching backup artifacts prepared by
the approved backup system.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
require_file() { [[ -f "$2" && -s "$2" ]] || fail "$1 missing or empty: $2"; }

execute=NO
sha=''
environment=''
repository=''
compose_directory=''
service=''
database=''
modules=''
db_backup_id=''
db_backup_path=''
filestore_backup_id=''
filestore_backup_path=''
ci_evidence=''
release_manifest=''
staging_certification=''

while (($#)); do
  case "$1" in
    --execute) execute=YES; shift ;;
    --sha|--environment|--repository|--compose-directory|--service|--database|--modules|--db-backup-id|--db-backup-path|--filestore-backup-id|--filestore-backup-path|--ci-evidence|--release-manifest|--staging-certification)
      (($# >= 2)) || fail "missing value for $1"
      key="${1#--}"; key="${key//-/_}"; printf -v "$key" '%s' "$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

[[ "$execute" == YES ]] || fail "explicit --execute is required"
[[ "${EUID}" -eq 0 ]] || fail "must run as root through the allowlisted deployment command"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || fail "SHA must be a full lowercase 40-character commit"
[[ "$environment" == staging || "$environment" == production ]] || fail "invalid environment"
for value_name in repository compose_directory service database modules db_backup_id db_backup_path filestore_backup_id filestore_backup_path ci_evidence release_manifest; do
  [[ -n "${!value_name}" ]] || fail "required value is empty: $value_name"
done
[[ -d "$repository/.git" ]] || fail "repository is not a Git worktree: $repository"
[[ -d "$compose_directory" ]] || fail "Compose directory not found: $compose_directory"
require_file "database backup" "$db_backup_path"
require_file "filestore backup" "$filestore_backup_path"
require_file "CI evidence" "$ci_evidence"
require_file "release manifest" "$release_manifest"
if [[ "$environment" == production ]]; then
  [[ -n "$staging_certification" ]] || fail "production requires staging certification"
  require_file "staging certification" "$staging_certification"
fi

command -v git >/dev/null || fail "git unavailable"
command -v docker >/dev/null || fail "docker unavailable"
command -v flock >/dev/null || fail "flock unavailable"
command -v sha256sum >/dev/null || fail "sha256sum unavailable"

exec 9>/run/lock/codestra-odoo-deploy.lock
flock -n 9 || fail "another deployment holds the Odoo deployment lock"

git -C "$repository" diff --quiet || fail "repository has unstaged changes"
git -C "$repository" diff --cached --quiet || fail "repository has staged changes"
[[ -z "$(git -C "$repository" status --porcelain)" ]] || fail "repository contains untracked files"
git -C "$repository" fetch --prune origin main
git -C "$repository" cat-file -e "${sha}^{commit}" || fail "unknown commit SHA"
git -C "$repository" merge-base --is-ancestor "$sha" origin/main || fail "SHA is not on protected origin/main"

grep -Fq "SOURCE_SHA=$sha" "$ci_evidence" || fail "CI evidence does not certify requested SHA"
grep -Fq "SOURCE_SHA=$sha" "$release_manifest" || fail "release manifest does not identify requested SHA"
grep -Fq "DATABASE_BACKUP_ID=$db_backup_id" "$release_manifest" || fail "database backup ID mismatch"
grep -Fq "FILESTORE_BACKUP_ID=$filestore_backup_id" "$release_manifest" || fail "filestore backup ID mismatch"
if [[ "$environment" == production ]]; then
  grep -Fq "STAGING_SHA=$sha" "$staging_certification" || fail "staging certification SHA mismatch"
  grep -Fq "STAGING_CERTIFICATION=PASS" "$staging_certification" || fail "staging is not certified"
fi

release_root=/opt/codestra/odoo/releases
release_dir="$release_root/$sha"
current_link=/opt/codestra/odoo/current
install -d -m 0750 -o root -g root "$release_root"
[[ ! -e "$release_dir" ]] || fail "immutable release already exists: $release_dir"
temporary_release="${release_dir}.preparing.$$"
install -d -m 0750 -o root -g root "$temporary_release"
cleanup() { [[ -d "$temporary_release" ]] && rm -rf --one-file-system "$temporary_release"; }
trap cleanup EXIT
git -C "$repository" archive "$sha" | tar -x -C "$temporary_release"
printf '%s\n' "$sha" >"$temporary_release/SOURCE_SHA"
find "$temporary_release" -type d -exec chmod 0750 {} +
find "$temporary_release" -type f -exec chmod 0640 {} +
mv "$temporary_release" "$release_dir"
temporary_release=

previous_target="$(readlink -f "$current_link" 2>/dev/null || true)"
ln -sfn "$release_dir" "${current_link}.next"

# Compose must mount /opt/codestra/odoo/current/custom-addons read-only. The
# pointer is switched only while the affected service is stopped.
cd "$compose_directory"
docker compose config --quiet
docker compose stop "$service"
mv -Tf "${current_link}.next" "$current_link"

rollback_pointer() {
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "${current_link}.rollback"
    mv -Tf "${current_link}.rollback" "$current_link"
  fi
}
trap 'rollback_pointer; docker compose up -d "$service" || true' ERR

docker compose run --rm --no-deps "$service" \
  odoo -d "$database" -u "$modules" --stop-after-init --no-http
docker compose up -d "$service"

container_id="$(docker compose ps -q "$service")"
[[ -n "$container_id" ]] || fail "Odoo service container was not created"
for _ in $(seq 1 60); do
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
  [[ "$state" == healthy || "$state" == running ]] && break
  [[ "$state" == unhealthy || "$state" == exited || "$state" == dead ]] && fail "Odoo failed readiness: $state"
  sleep 2
done

actual_mount="$(docker inspect "$container_id" --format '{{range .Mounts}}{{if eq .Destination "/mnt/extra-addons"}}{{.Source}}|{{.RW}}{{end}}{{end}}')"
[[ "$actual_mount" == "$release_dir/custom-addons|false" ]] || fail "container is not using the exact read-only release: $actual_mount"

record_dir=/var/lib/codestra-odoo/releases
install -d -m 0750 -o root -g root "$record_dir"
record="$record_dir/${environment}-${sha}.record"
{
  printf 'SOURCE_SHA=%s\n' "$sha"
  printf 'ENVIRONMENT=%s\n' "$environment"
  printf 'DATABASE=%s\n' "$database"
  printf 'MODULES=%s\n' "$modules"
  printf 'DATABASE_BACKUP_ID=%s\n' "$db_backup_id"
  printf 'DATABASE_BACKUP_SHA256=%s\n' "$(sha256sum "$db_backup_path" | awk '{print $1}')"
  printf 'FILESTORE_BACKUP_ID=%s\n' "$filestore_backup_id"
  printf 'FILESTORE_BACKUP_SHA256=%s\n' "$(sha256sum "$filestore_backup_path" | awk '{print $1}')"
  printf 'RELEASE_MANIFEST_SHA256=%s\n' "$(sha256sum "$release_manifest" | awk '{print $1}')"
  printf 'DEPLOYED_AT=%s\n' "$(date -u +%FT%TZ)"
} >"$record"
chmod 0640 "$record"
trap - ERR
printf 'DEPLOYMENT=PASS\nSOURCE_SHA=%s\nRELEASE_DIR=%s\nRECORD=%s\n' "$sha" "$release_dir" "$record"
