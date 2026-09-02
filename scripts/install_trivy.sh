#!/usr/bin/env bash
set -Eeuo pipefail

TRIVY_VERSION="0.74.0"
TRIVY_ARCHIVE_SHA256="2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a"
TEMP_ROOT="${RUNNER_TEMP:-/tmp}"
ARCHIVE="$TEMP_ROOT/trivy-${TRIVY_VERSION}.tar.gz"
INSTALL_DIR="${TRIVY_INSTALL_DIR:-$TEMP_ROOT/trivy-bin}"

curl \
  --fail \
  --location \
  --retry 3 \
  --show-error \
  --silent \
  --output "$ARCHIVE" \
  "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"

actual_sha256="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
printf 'TRIVY_ARCHIVE_ACTUAL_SHA256=%s\n' "$actual_sha256"
test "$actual_sha256" = "$TRIVY_ARCHIVE_SHA256"

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
tar -xzf "$ARCHIVE" -C "$INSTALL_DIR" trivy
chmod 0755 "$INSTALL_DIR/trivy"

if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$INSTALL_DIR" >> "$GITHUB_PATH"
fi

"$INSTALL_DIR/trivy" --version
printf 'TRIVY_VERSION_PIN=%s\n' "$TRIVY_VERSION"
printf 'TRIVY_ARCHIVE_SHA256_PIN=%s\n' "$TRIVY_ARCHIVE_SHA256"
printf 'TRIVY_INSTALLATION=PASS\n'
