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

    profile = api.fetch_account_profile("https://example.com", "secret")

    assert called["url"] == "https://example.com/v1/account/profile"
    assert called["headers"] == {"Authorization": "Bearer secret"}
    assert called["timeout"] == 30
    assert profile.username == "hvdeploy"
    assert profile.authorized_keys == ["ssh-rsa AAA", "ssh-ed25519 BBB"]


def test_register_server_prefers_provided_profile_data(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_payload: Dict[str, Any] = {}

    def fake_post(url: str, *, headers: Dict[str, str], data: str, timeout: int) -> _DummyResponse:  # type: ignore[override]
        captured_payload.update(json.loads(data))
        response_payload = {"close_other_sessions": False}
        return _DummyResponse(200, response_payload)

    monkeypatch.setattr(api.requests, "post", fake_post)

    result = api.register_server(
        "https://example.com",
        "secret",
        username="hvdeploy",
        authorized_keys=["ssh-rsa AAA", " ssh-rsa AAA ", "ssh-ed25519 BBB"],
    )

    assert captured_payload["username"] == "hvdeploy"
    assert captured_payload["authorized_keys"] == ["ssh-rsa AAA", "ssh-ed25519 BBB"]
    assert result.username == "hvdeploy"
    assert result.authorized_keys == ["ssh-rsa AAA", "ssh-ed25519 BBB"]
    assert result.close_other_sessions is False


def test_register_server_requires_authorized_keys_when_profile_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*_: Any, **__: Any) -> None:
        raise AssertionError("POST should not be invoked when keys are missing")

    monkeypatch.setattr(api.requests, "post", fail_post)

    with pytest.raises(api.APIClientError):
        api.register_server(
            "https://example.com",
            "secret",
            username="hvdeploy",
            authorized_keys=[],
        )
