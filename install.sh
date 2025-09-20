#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[hvdeploy-installer] %s\n' "$*"
}

DEFAULT_API_BASE_URL="https://api.playrservers.com"
INSTALL_API_BASE_URL="${HVDEPLOY_API_BASE_URL:-$DEFAULT_API_BASE_URL}"
HVDEPLOY_INSTALL_API_KEY="${HVDEPLOY_API_KEY:-}"

prompt_for_api_key() {
    if [[ -n "$HVDEPLOY_INSTALL_API_KEY" ]]; then
        return
    fi

    log "An HVDeploy API key is required to complete installation."

    local prompt_output=""
    local prompt_status=0
    prompt_output="$(
        python3 - <<'PY'
import sys

try:
    key = input("Enter HVDeploy API key: ")
except (EOFError, KeyboardInterrupt):
    sys.exit(1)

key = key.strip()
if not key:
    sys.exit(2)

print(key)
PY
    )" || prompt_status=$?

    if [[ $prompt_status -ne 0 ]]; then
        case "$prompt_status" in
            1)
                log "Installation cancelled before completion."
                ;;
            2)
                log "An API key must be provided to continue."
                ;;
            *)
                log "Failed to read an API key (exit code $prompt_status)."
                ;;
        esac
        log "Set HVDEPLOY_API_KEY in the environment to install non-interactively."
        exit 1
    fi

    HVDEPLOY_INSTALL_API_KEY="$prompt_output"
}

validate_api_key() {
    if [[ -z "$HVDEPLOY_INSTALL_API_KEY" ]]; then
        log "An API key must be provided to continue."
        exit 1
    fi

    log "Validating API key with HVDeploy management API..."

    export HVDEPLOY_INSTALL_API_KEY
    export INSTALL_API_BASE_URL

    if ! python3 - <<'PY'
import json
import os
import sys
from urllib import error, request
from urllib.parse import urlparse

ALLOWED_API_HOST = "api.playrservers.com"
ALLOWED_API_PORT = 443
PROFILE_ENDPOINT = "/v1/account/profile"
API_SUFFIX = "/api"

api_key = os.environ.get("HVDEPLOY_INSTALL_API_KEY", "").strip()
if not api_key:
    print("An API key is required to continue installation.", file=sys.stderr)
    sys.exit(2)

base_url = os.environ.get("INSTALL_API_BASE_URL", "https://api.playrservers.com")
parsed = urlparse(base_url)

if parsed.scheme.lower() != "https":
    print("Management API URL must use HTTPS.", file=sys.stderr)
    sys.exit(3)

hostname = (parsed.hostname or "").lower()
if hostname != ALLOWED_API_HOST:
    print(f"Management API host must be {ALLOWED_API_HOST}.", file=sys.stderr)
    sys.exit(3)

port = parsed.port
if port not in (None, ALLOWED_API_PORT):
    print(
        f"Management API port must be {ALLOWED_API_PORT}.",
        file=sys.stderr,
    )
    sys.exit(3)

base_path = parsed.path.rstrip("/")
candidate_paths = [base_path]
if not base_path.endswith(API_SUFFIX):
    candidate_paths.append(f"{base_path}{API_SUFFIX}".rstrip("/"))

candidate_base_urls = []
for path in candidate_paths:
    candidate = f"https://{ALLOWED_API_HOST}{path}" if path else f"https://{ALLOWED_API_HOST}"
    if candidate not in candidate_base_urls:
        candidate_base_urls.append(candidate)

payload_bytes = None
not_found = False

for candidate in candidate_base_urls:
    url = f"{candidate}{PROFILE_ENDPOINT}"
    request_obj = request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )

    try:
        with request.urlopen(request_obj, timeout=30) as response:
            payload_bytes = response.read()
            break
    except error.HTTPError as exc:
        if exc.code in (401, 403):
            print(
                "The provided API key was rejected by the management API.",
                file=sys.stderr,
            )
            sys.exit(4)
        if exc.code == 404:
            not_found = True
            continue
        print(
            f"Management API returned HTTP status {exc.code}.",
            file=sys.stderr,
        )
        sys.exit(4)
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        print(
            f"Failed to contact the management API: {reason}",
            file=sys.stderr,
        )
        sys.exit(5)
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"Unexpected error contacting the management API: {exc}",
            file=sys.stderr,
        )
        sys.exit(6)

if payload_bytes is None:
    if not_found:
        print(
            "Management API endpoint was not found. Verify the HVDEPLOY_API_BASE_URL setting.",
            file=sys.stderr,
        )
    else:
        print(
            "Failed to retrieve a response from the management API.",
            file=sys.stderr,
        )
    sys.exit(4)

try:
    payload = json.loads(payload_bytes.decode("utf-8"))
except Exception:  # pragma: no cover - defensive
    print("Management API response was not valid JSON.", file=sys.stderr)
    sys.exit(7)

if not isinstance(payload, dict):
    print("Management API response payload was not a JSON object.", file=sys.stderr)
    sys.exit(8)

def normalise_keys(values):
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result

keys = []
authorized_keys = payload.get("authorized_keys")

if isinstance(authorized_keys, list):
    keys.extend(normalise_keys(authorized_keys))
elif isinstance(authorized_keys, str):
    keys.extend(
        normalise_keys(
            line for line in authorized_keys.splitlines() if line.strip()
        )
    )

for field in ("authorized_key", "public_key"):
    value = payload.get(field)
    if value:
        keys.extend(normalise_keys([value]))

keys = normalise_keys(keys)

if not keys:
    print(
        "Management API response did not include any authorized keys.",
        file=sys.stderr,
    )
    sys.exit(9)
PY
    then
        log "API key validation failed. Please verify the key and try again."
        exit 1
    fi

    log "API key validation succeeded."
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

prompt_for_api_key
validate_api_key

PACKAGE_BRANCH=${HVDEPLOY_BRANCH:-main}
PACKAGE_URL=${HVDEPLOY_PACKAGE_URL:-https://github.com/PlayrTBH/HVDeploy/archive/refs/heads/${PACKAGE_BRANCH}.tar.gz}
PACKAGE_SPEC="hvdeploy-management-agent @ ${PACKAGE_URL}"

PIP_INSTALL=(python3 -m pip install --upgrade)
if python3 -m pip help install 2>&1 | grep -q -- '--break-system-packages'; then
    PIP_INSTALL+=(--break-system-packages)
fi

log "Installing hvdeploy-management-agent from ${PACKAGE_URL}"
"${PIP_INSTALL[@]}" "${PACKAGE_SPEC}"

log "Installation complete. Run 'hvdeploy-agent --api-key YOUR_API_KEY' to configure this host."
