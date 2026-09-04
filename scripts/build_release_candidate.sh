#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SOURCE_SHA="$(git rev-parse HEAD)"
EXPECTED_SOURCE_SHA="${EXPECTED_SOURCE_SHA:-$SOURCE_SHA}"
SOURCE_COMMIT_VERIFIED="${SOURCE_COMMIT_VERIFIED:-false}"
SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
export SOURCE_COMMIT_VERIFIED SOURCE_DATE_EPOCH

test "$SOURCE_SHA" = "$EXPECTED_SOURCE_SHA"
test -z "$(git status --porcelain --untracked-files=no)"

rm -rf dist
mkdir -p dist

PREFIX="codestra-odoo-contact-center-${SOURCE_SHA}"
ARCHIVE="dist/${PREFIX}.tar.gz"
SBOM="dist/${PREFIX}.source-sbom.spdx.json"
REPORT="dist/${PREFIX}.final-report.txt"
MANIFEST="dist/${PREFIX}.release-manifest.json"

python3 scripts/generate_source_sbom.py --output "$SBOM"
python3 scripts/generate_release_report.py --output "$REPORT"

git archive \
  --format=tar \
  --prefix="${PREFIX}/" \
  HEAD \
  .dockerignore \
  .github \
  .gitleaks.toml \
  README.md \
  SERVER-VS-GITHUB-DRIFT.md \
  api \
  config \
  custom-addons \
  deploy \
  docs \
  release \
  scripts \
  tests \
  | gzip -n > "$ARCHIVE"

python3 scripts/generate_release_manifest.py \
  --source-archive "$ARCHIVE" \
  --sbom "$SBOM" \
  --report "$REPORT" \
  --output "$MANIFEST"

(
  cd dist
  sha256sum \
    "$(basename "$ARCHIVE")" \
    "$(basename "$SBOM")" \
    "$(basename "$REPORT")" \
    "$(basename "$MANIFEST")" \
    > SHA256SUMS
  sha256sum --check SHA256SUMS
)

find dist -type f -exec chmod 0644 {} +
printf 'SOURCE_CANDIDATE_SHA=%s\n' "$SOURCE_SHA"
printf 'SOURCE_CANDIDATE_ARCHIVE=%s\n' "$ARCHIVE"
printf 'SOURCE_CANDIDATE_PUBLISHED=NO\n'
printf 'SOURCE_CANDIDATE_DEPLOYED=NO\n'
if [[ "$SOURCE_COMMIT_VERIFIED" == "true" ]]; then
  printf 'SOURCE_CANDIDATE_SIGNED=YES\n'
else
  printf 'SOURCE_CANDIDATE_SIGNED=NO\n'
fi
printf 'SOURCE_CANDIDATE_PRODUCTION_READY=NO\n'
cat dist/SHA256SUMS
