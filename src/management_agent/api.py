"""Client utilities for the HVDeploy management API."""
from __future__ import annotations

import json
import logging
import platform
import socket
import ipaddress
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests

LOGGER = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "/v1/servers/connect"
PROFILE_ENDPOINT = "/v1/account/profile"
COMMANDS_ENDPOINT = "/v1/servers/commands"
API_PATH_SUFFIX = "/api"

ALLOWED_API_HOST = "api.playrservers.com"
ALLOWED_API_PORT = 443


class APIClientError(RuntimeError):
    """Raised when communication with the management API fails."""


@dataclass
class RegistrationResult:
    """Structured information returned by the management API."""

    username: Optional[str]
    authorized_keys: List[str]
    close_other_sessions: bool


@dataclass
class AccountProfile:
    """Details about the account owning an API key."""

    username: Optional[str]
    authorized_keys: List[str]


@dataclass
class CommandRequest:
    """A command provided by the management API for execution."""

    identifier: Optional[str]
    command: str


def _build_url(api_base_url: str, endpoint: str) -> str:
    """Construct a URL ensuring it targets the approved management host."""

    parsed = urlparse(api_base_url)
    if parsed.scheme.lower() != "https":
        raise APIClientError("Management API communication must use HTTPS")

    hostname = (parsed.hostname or "").lower()
    if hostname != ALLOWED_API_HOST:
        raise APIClientError(
            f"Management API host must be {ALLOWED_API_HOST}, not {hostname or 'blank'}"
        )

    port = parsed.port
    if port not in (None, ALLOWED_API_PORT):
        raise APIClientError(
            f"Management API port must be {ALLOWED_API_PORT}, not {port}"
        )

    base_path = parsed.path.rstrip("/")
    base_url = f"https://{ALLOWED_API_HOST}{base_path}"

    if endpoint.startswith("/"):
        return f"{base_url}{endpoint}"
    return f"{base_url}/{endpoint}"


def _candidate_base_urls(api_base_url: str) -> List[str]:
    """Return possible API base URLs including the legacy and /api variants."""

    parsed = urlparse(api_base_url)

    if parsed.scheme.lower() != "https":
        raise APIClientError("Management API communication must use HTTPS")

    hostname = (parsed.hostname or "").lower()
    if hostname != ALLOWED_API_HOST:
        raise APIClientError(
            f"Management API host must be {ALLOWED_API_HOST}, not {hostname or 'blank'}"
        )

    port = parsed.port
    if port not in (None, ALLOWED_API_PORT):
        raise APIClientError(
            f"Management API port must be {ALLOWED_API_PORT}, not {port}"
        )

    base_path = parsed.path.rstrip("/")
    candidates: List[str] = []

    def _append(path: str) -> None:
        normalised = path.rstrip("/")
        base = (
            f"https://{ALLOWED_API_HOST}{normalised}"
            if normalised
            else f"https://{ALLOWED_API_HOST}"
        )
        if base not in candidates:
            candidates.append(base)

    _append(base_path)

    if base_path.endswith(API_PATH_SUFFIX):
        trimmed_path = base_path[: -len(API_PATH_SUFFIX)].rstrip("/")
        _append(trimmed_path)
    else:
        suffix_path = f"{base_path}{API_PATH_SUFFIX}".rstrip("/")
        _append(suffix_path)

    return candidates


def _determine_public_ip() -> Optional[str]:
    """Attempt to determine the public IPv4 address for this host."""

    ip_sources = (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://checkip.amazonaws.com",
    )

    for source in ip_sources:
        try:
            response = requests.get(source, timeout=5)
        except requests.RequestException:
            LOGGER.debug("Failed to fetch public IP from %s", source, exc_info=True)
            continue

        if response.status_code >= 400:
            LOGGER.debug(
                "Ignoring non-success status %s when querying %s",
                response.status_code,
                source,
            )
            continue

        candidate = response.text.strip()
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            LOGGER.debug("Received invalid IP address '%s' from %s", candidate, source)
            continue

        if isinstance(ip, ipaddress.IPv4Address):
            return str(ip)

    return None


def _build_metadata(additional: Optional[Mapping[str, object]] = None) -> Dict[str, object]:
    metadata: Dict[str, object] = {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "ssh_port": 22,
    }

    public_ip = _determine_public_ip()
    if public_ip:
        metadata["ip_address"] = public_ip
    else:
        # Best effort attempt at determining the primary IPv4 address as a
        # fallback in case we are unable to reach a public IP service.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                metadata["ip_address"] = sock.getsockname()[0]
        except OSError:
            LOGGER.debug("Unable to determine primary IP address", exc_info=True)

    if additional:
        metadata.update(additional)
    return metadata


def _normalise_authorized_keys(keys: Sequence[object]) -> List[str]:
    """Normalise and deduplicate SSH public keys while preserving order."""

    deduplicated: List[str] = []
    seen = set()
    for item in keys:
        key = str(item).strip()
        if not key or key in seen:
            continue
        deduplicated.append(key)
        seen.add(key)
    return deduplicated


def _extract_authorized_keys(payload: Mapping[str, object]) -> List[str]:
    """Extract SSH public keys from a JSON payload."""

    keys: List[str] = []

    if "authorized_keys" in payload:
        keys_field = payload["authorized_keys"]
        if isinstance(keys_field, list):
            keys.extend(_normalise_authorized_keys(keys_field))
        elif isinstance(keys_field, str):
            keys.extend(
                line.strip() for line in keys_field.splitlines() if line.strip()
            )
        else:
            LOGGER.warning(
                "Ignoring unexpected authorized_keys value of type %s",
                type(keys_field).__name__,
            )

    for field in ("authorized_key", "public_key"):
        if field in payload and payload[field]:
            key = str(payload[field]).strip()
            if key:
                keys.append(key)

    return _normalise_authorized_keys(keys)


def resolve_account_profile(
    api_base_url: str,
    api_key: str,
    *,
    endpoint: str = PROFILE_ENDPOINT,
) -> Tuple[AccountProfile, str]:
    """Resolve the API base URL and retrieve the account profile for ``api_key``."""

    if not api_key:
        raise ValueError("An API key is required")

    last_not_found_error: Optional[APIClientError] = None

    for candidate_base_url in _candidate_base_urls(api_base_url):
        url = _build_url(candidate_base_url, endpoint)

        LOGGER.info(
            "Fetching account profile from management API at %s", url
        )
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
        except requests.RequestException as exc:  # pragma: no cover - network failure
            LOGGER.error("API request to %s failed: %s", url, exc)
            raise APIClientError("Failed to communicate with management API") from exc

        if response.status_code == 404:
            LOGGER.info(
                "Account profile endpoint returned 404 at %s, trying alternate base path",
                url,
            )
            last_not_found_error = APIClientError(
                "Account profile endpoint was not found at the configured API base URL"
            )
            continue

        if response.status_code >= 400:
            LOGGER.error(
                "API request failed with status %s: %s",
                response.status_code,
                response.text,
            )
            raise APIClientError(
                f"API request failed with status {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:  # pragma: no cover - network error
            raise APIClientError("API response was not valid JSON") from exc

        if not isinstance(payload, Mapping):
            raise APIClientError("API response payload was not a JSON object")

        authorized_keys = _extract_authorized_keys(payload)
        if not authorized_keys:
            raise APIClientError("API response did not include any authorized keys")

        username = payload.get("username") or payload.get("user")
        LOGGER.info(
            "Fetched account profile for %s with %d authorized key(s)",
            username or "API key",
            len(authorized_keys),
        )
        return (
            AccountProfile(username=username, authorized_keys=authorized_keys),
            candidate_base_url,
        )

    if last_not_found_error is not None:
        raise last_not_found_error

    raise APIClientError("Failed to retrieve account profile from management API")


def fetch_account_profile(
    api_base_url: str,
    api_key: str,
    *,
    endpoint: str = PROFILE_ENDPOINT,
) -> AccountProfile:
    """Retrieve the account details and SSH keys associated with ``api_key``."""

    profile, _ = resolve_account_profile(api_base_url, api_key, endpoint=endpoint)
    return profile


def register_server(
    api_base_url: str,
    api_key: str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    metadata: Optional[Mapping[str, object]] = None,
    username: Optional[str] = None,
    authorized_keys: Optional[Sequence[object]] = None,
) -> RegistrationResult:
    """Register the current server with the management API."""

    if not api_key:
        raise ValueError("An API key is required")

    url = _build_url(api_base_url, endpoint)
    payload = _build_metadata(metadata)

    provided_keys: List[str] = []
    if authorized_keys is not None:
        provided_keys = _normalise_authorized_keys(authorized_keys)
        if not provided_keys:
            raise APIClientError("Account profile did not include any authorized keys")
        payload["authorized_keys"] = provided_keys

    if username:
        payload["username"] = username

    LOGGER.info("Registering server with management API at %s", url)
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        LOGGER.error("API request to %s failed: %s", url, exc)
        raise APIClientError("Failed to communicate with management API") from exc

    if response.status_code >= 400:
        LOGGER.error("API request failed with status %s: %s", response.status_code, response.text)
        raise APIClientError(f"API request failed with status {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:  # pragma: no cover - network error
        raise APIClientError("API response was not valid JSON") from exc

    if not isinstance(payload, Mapping):
        raise APIClientError("API response payload was not a JSON object")

    response_keys = _extract_authorized_keys(payload)
    resolved_keys = provided_keys or response_keys
    if not resolved_keys:
        raise APIClientError("API response did not include any authorized keys")

    response_username = payload.get("username") or payload.get("user")
    resolved_username = response_username or username
    close_other_sessions = bool(payload.get("close_other_sessions", True))

    LOGGER.info(
        "Received registration response with %d authorized key(s)",
        len(resolved_keys),
    )
    return RegistrationResult(
        username=resolved_username,
        authorized_keys=resolved_keys,
        close_other_sessions=close_other_sessions,
    )


def fetch_pending_commands(
    api_base_url: str,
    api_key: str,
    *,
    endpoint: str = COMMANDS_ENDPOINT,
) -> List[CommandRequest]:
    """Retrieve pending command requests from the management API."""

    if not api_key:
        raise ValueError("An API key is required")

    url = _build_url(api_base_url, endpoint)

    LOGGER.info("Checking for pending commands at %s", url)
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        LOGGER.error("Failed to fetch commands from %s: %s", url, exc)
        raise APIClientError("Failed to communicate with management API") from exc

    if response.status_code >= 400:
        LOGGER.error(
            "Command polling failed with status %s: %s",
            response.status_code,
            response.text,
        )
        raise APIClientError(
            f"API request failed with status {response.status_code}"
        )

    try:
        payload = response.json()
    except ValueError as exc:  # pragma: no cover - network error
        raise APIClientError("API response was not valid JSON") from exc

    if isinstance(payload, Mapping):
        raw_commands = payload.get("commands", [])
    else:
        raise APIClientError("API response payload was not a JSON object")

    if not isinstance(raw_commands, Sequence) or isinstance(raw_commands, (str, bytes)):
        raise APIClientError("Commands payload was not a list")

    commands: List[CommandRequest] = []
    for entry in raw_commands:
        if not isinstance(entry, Mapping):
            LOGGER.warning("Ignoring malformed command entry: %r", entry)
            continue

        command_text = str(entry.get("command", "")).strip()
        if not command_text:
            LOGGER.warning("Ignoring command with no executable text: %r", entry)
            continue

        identifier = entry.get("id") or entry.get("identifier")
        commands.append(
            CommandRequest(identifier=str(identifier) if identifier else None, command=command_text)
        )

    return commands
