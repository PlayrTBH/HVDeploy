#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[hvdeploy-installer] %s\n' "$*"
}

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    log "This installer must be run as root. Try re-running with sudo."
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    log "apt-get was not found; this installer supports Ubuntu 24.04 or newer."
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
APT_PACKAGES=(python3 python3-pip python3-venv git ca-certificates)

log "Updating apt package index..."
apt-get update

log "Installing dependencies: ${APT_PACKAGES[*]}"
apt-get install -y --no-install-recommends "${APT_PACKAGES[@]}"

if ! python3 -m pip --version >/dev/null 2>&1; then
    log "Python pip could not be located after installation."
    exit 1
fi

if ! python3 - <<'PY'
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
then
    log "Python 3.10 or newer is required."
    exit 1
fi

PACKAGE_BRANCH=${HVDEPLOY_BRANCH:-main}
PACKAGE_URL=${HVDEPLOY_PACKAGE_URL:-https://github.com/HVDeploy/HVDeploy/archive/refs/heads/${PACKAGE_BRANCH}.tar.gz}
PACKAGE_SPEC="hvdeploy-management-agent @ ${PACKAGE_URL}"

PIP_INSTALL=(python3 -m pip install --upgrade)
if python3 -m pip help install 2>&1 | grep -q -- '--break-system-packages'; then
    PIP_INSTALL+=(--break-system-packages)
fi

log "Installing hvdeploy-management-agent from ${PACKAGE_URL}"
"${PIP_INSTALL[@]}" "${PACKAGE_SPEC}"

log "Installation complete. Run 'hvdeploy-agent --api-key YOUR_API_KEY' to configure this host."
