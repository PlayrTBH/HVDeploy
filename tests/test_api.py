"""Tests for the management API client helpers."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from management_agent import api


class _DummyResponse:
    def __init__(self, status_code: int, payload: Dict[str, Any] | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self) -> Dict[str, Any]:
        return self._payload


def test_fetch_account_profile_returns_username_and_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    def fake_get(url: str, *, headers: Dict[str, str], timeout: int) -> _DummyResponse:  # type: ignore[override]
        called["url"] = url
        called["headers"] = headers
        called["timeout"] = timeout
        payload = {
            "username": "hvdeploy",
            "authorized_keys": ["ssh-rsa AAA", "ssh-ed25519 BBB"],
        }
        return _DummyResponse(200, payload)

    monkeypatch.setattr(api.requests, "get", fake_get)

    profile = api.fetch_account_profile("https://api.playrservers.com/api", "secret")

    assert called["url"] == "https://api.playrservers.com/api/v1/account/profile"
    assert called["headers"] == {"Authorization": "Bearer secret"}
    assert called["timeout"] == 30
    assert profile.username == "hvdeploy"
    assert profile.authorized_keys == ["ssh-rsa AAA", "ssh-ed25519 BBB"]


def test_resolve_account_profile_retries_with_api_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    responses = [
        _DummyResponse(404),
        _DummyResponse(200, {"authorized_keys": ["ssh-ed25519 BBB"]}),
    ]

    def fake_get(url: str, *, headers: Dict[str, str], timeout: int) -> _DummyResponse:  # type: ignore[override]
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(api.requests, "get", fake_get)

    profile, resolved_base_url = api.resolve_account_profile(
        "https://api.playrservers.com", "secret"
    )

    assert calls == [
        "https://api.playrservers.com/v1/account/profile",
        "https://api.playrservers.com/api/v1/account/profile",
    ]
    assert resolved_base_url == "https://api.playrservers.com/api"
    assert profile.authorized_keys == ["ssh-ed25519 BBB"]


def test_resolve_account_profile_retries_without_api_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    responses = [
        _DummyResponse(404),
        _DummyResponse(200, {"authorized_keys": ["ssh-ed25519 BBB"]}),
    ]

    def fake_get(url: str, *, headers: Dict[str, str], timeout: int) -> _DummyResponse:  # type: ignore[override]
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(api.requests, "get", fake_get)

    profile, resolved_base_url = api.resolve_account_profile(
        "https://api.playrservers.com/api", "secret"
    )

    assert calls == [
        "https://api.playrservers.com/api/v1/account/profile",
        "https://api.playrservers.com/v1/account/profile",
    ]
    assert resolved_base_url == "https://api.playrservers.com"
    assert profile.authorized_keys == ["ssh-ed25519 BBB"]


def test_register_server_prefers_provided_profile_data(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_payload: Dict[str, Any] = {}

    def fake_post(url: str, *, headers: Dict[str, str], data: str, timeout: int) -> _DummyResponse:  # type: ignore[override]
        captured_payload.update(json.loads(data))
        response_payload = {"close_other_sessions": False}
        return _DummyResponse(200, response_payload)

    monkeypatch.setattr(api.requests, "post", fake_post)

    result = api.register_server(
        "https://api.playrservers.com",
        "secret",
        username="hvdeploy",
        authorized_keys=["ssh-rsa AAA", " ssh-rsa AAA ", "ssh-ed25519 BBB"],
    )

    assert captured_payload["username"] == "hvdeploy"
    assert captured_payload["authorized_keys"] == ["ssh-rsa AAA", "ssh-ed25519 BBB"]
    assert result.username == "hvdeploy"
    assert result.authorized_keys == ["ssh-rsa AAA", "ssh-ed25519 BBB"]
    assert result.close_other_sessions is False


def test_register_server_includes_public_ip_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_payload: Dict[str, Any] = {}

    def fake_post(url: str, *, headers: Dict[str, str], data: str, timeout: int) -> _DummyResponse:  # type: ignore[override]
        captured_payload.update(json.loads(data))
        return _DummyResponse(200, {"authorized_keys": ["ssh-ed25519 BBB"]})

    monkeypatch.setattr(api.requests, "post", fake_post)
    monkeypatch.setattr(api, "_determine_public_ip", lambda: "203.0.113.42")

    api.register_server(
        "https://api.playrservers.com",
        "secret",
        authorized_keys=["ssh-ed25519 BBB"],
    )

    assert captured_payload["ip_address"] == "203.0.113.42"
    assert captured_payload["ssh_port"] == 22


def test_register_server_requires_authorized_keys_when_profile_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*_: Any, **__: Any) -> None:
        raise AssertionError("POST should not be invoked when keys are missing")

    monkeypatch.setattr(api.requests, "post", fail_post)

    with pytest.raises(api.APIClientError):
        api.register_server(
            "https://api.playrservers.com",
            "secret",
            username="hvdeploy",
            authorized_keys=[],
        )


def test_fetch_pending_commands_returns_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: Dict[str, Any] = {}

    def fake_get(url: str, *, headers: Dict[str, str], timeout: int) -> _DummyResponse:  # type: ignore[override]
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        payload = {
            "commands": [
                {"id": "cmd-1", "command": "uptime"},
                {"command": " echo hello "},
                {"id": "skip", "command": "   "},
            ]
        }
        return _DummyResponse(200, payload)

    monkeypatch.setattr(api.requests, "get", fake_get)

    commands = api.fetch_pending_commands("https://api.playrservers.com/api", "secret")

    assert captured["url"] == "https://api.playrservers.com/api/v1/servers/commands"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["timeout"] == 30
    assert [command.identifier for command in commands] == ["cmd-1", None]
    assert [command.command for command in commands] == ["uptime", "echo hello"]


def test_fetch_pending_commands_rejects_non_default_host() -> None:
    with pytest.raises(api.APIClientError):
        api.fetch_pending_commands("https://example.com", "secret")
