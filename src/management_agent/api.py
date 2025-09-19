"""Client utilities for the HVDeploy management API."""
from __future__ import annotations

import json
import logging
import platform
import socket
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence

import requests

LOGGER = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "/v1/servers/connect"
PROFILE_ENDPOINT = "/v1/account/profile"


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


def _build_metadata(additional: Optional[Mapping[str, object]] = None) -> Dict[str, object]:
    metadata: Dict[str, object] = {
        "hostname": platform.node(),
        "platform": platform.platform(),
    }

    # Best effort attempt at determining the primary IPv4 address.
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


def fetch_account_profile(
    api_base_url: str,
    api_key: str,
    *,
    endpoint: str = PROFILE_ENDPOINT,
) -> AccountProfile:
    """Retrieve the account details and SSH keys associated with ``api_key``."""

    if not api_key:
        raise ValueError("An API key is required")

    url = (
        f"{api_base_url.rstrip('/')}{endpoint}"
        if endpoint.startswith("/")
        else f"{api_base_url.rstrip('/')}/{endpoint}"
    )

    LOGGER.info("Fetching account profile from management API at %s", url)
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        LOGGER.error("API request to %s failed: %s", url, exc)
        raise APIClientError("Failed to communicate with management API") from exc

    if response.status_code >= 400:
        LOGGER.error(
            "API request failed with status %s: %s", response.status_code, response.text
        )
        raise APIClientError(f"API request failed with status {response.status_code}")

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
    return AccountProfile(username=username, authorized_keys=authorized_keys)


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

    url = (
        f"{api_base_url.rstrip('/')}{endpoint}"
        if endpoint.startswith("/")
        else f"{api_base_url.rstrip('/')}/{endpoint}"
    )
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
