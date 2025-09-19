"""Client utilities for the HVDeploy management API."""
from __future__ import annotations

import json
import logging
import platform
import socket
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

import requests

LOGGER = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "/v1/servers/connect"


class APIClientError(RuntimeError):
    """Raised when communication with the management API fails."""


@dataclass
class RegistrationResult:
    """Structured information returned by the management API."""

    username: Optional[str]
    authorized_keys: List[str]
    close_other_sessions: bool


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


def register_server(
    api_base_url: str,
    api_key: str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    metadata: Optional[Mapping[str, object]] = None,
) -> RegistrationResult:
    """Register the current server with the management API."""

    if not api_key:
        raise ValueError("An API key is required")

    url = f"{api_base_url.rstrip('/')}{endpoint}" if endpoint.startswith("/") else f"{api_base_url.rstrip('/')}/{endpoint}"
    payload = _build_metadata(metadata)

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

    authorized_keys: List[str] = []
    if "authorized_keys" in payload:
        keys_field = payload["authorized_keys"]
        if isinstance(keys_field, list):
            authorized_keys.extend(
                key for key in (str(item).strip() for item in keys_field) if key
            )
        elif isinstance(keys_field, str):
            authorized_keys.extend(
                key for key in (line.strip() for line in keys_field.splitlines()) if key
            )
        else:
            LOGGER.warning(
                "Ignoring unexpected authorized_keys value of type %s", type(keys_field).__name__
            )
    if "authorized_key" in payload and payload["authorized_key"]:
        key = str(payload["authorized_key"]).strip()
        if key:
            authorized_keys.append(key)
    if "public_key" in payload and payload["public_key"]:
        key = str(payload["public_key"]).strip()
        if key:
            authorized_keys.append(key)

    # Remove duplicates while preserving order.
    deduplicated_keys: List[str] = []
    seen = set()
    for key in authorized_keys:
        if key not in seen:
            deduplicated_keys.append(key)
            seen.add(key)
    authorized_keys = deduplicated_keys

    username = payload.get("username") or payload.get("user")
    close_other_sessions = bool(payload.get("close_other_sessions", True))

    if not authorized_keys:
        raise APIClientError("API response did not include any authorized keys")

    LOGGER.info("Received %d authorized key(s) from management API", len(authorized_keys))
    return RegistrationResult(
        username=username,
        authorized_keys=authorized_keys,
        close_other_sessions=close_other_sessions,
    )
