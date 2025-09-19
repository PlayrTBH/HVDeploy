"""Integration tests for the CLI workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from management_agent import api, cli


def test_cli_fetches_profile_before_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)

    call_sequence: List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]] = []

    def record(action: str, *args: Any, **kwargs: Any) -> None:
        call_sequence.append((action, args, kwargs))

    def fake_fetch_account_profile(base_url: str, api_key: str) -> api.AccountProfile:
        record("fetch_account_profile", base_url, api_key)
        return api.AccountProfile(username="hvdeploy", authorized_keys=["ssh-rsa AAA"])

    def fake_register_server(
        base_url: str,
        api_key: str,
        *,
        endpoint: str,
        metadata: Dict[str, Any] | None,
        username: str,
        authorized_keys: List[str],
    ) -> api.RegistrationResult:
        record(
            "register_server",
            base_url,
            api_key,
            endpoint=endpoint,
            metadata=metadata,
            username=username,
            authorized_keys=authorized_keys,
        )
        assert authorized_keys == ["ssh-rsa AAA"]
        return api.RegistrationResult(
            username=username,
            authorized_keys=list(authorized_keys),
            close_other_sessions=True,
        )

    monkeypatch.setattr(api, "fetch_account_profile", fake_fetch_account_profile)
    monkeypatch.setattr(api, "register_server", fake_register_server)

    monkeypatch.setattr(
        cli.system,
        "install_qemu_stack",
        lambda: record("install_qemu_stack"),
    )
    monkeypatch.setattr(
        cli.system,
        "ensure_user_exists",
        lambda username: record("ensure_user_exists", username),
    )
    monkeypatch.setattr(
        cli.system,
        "ensure_user_groups",
        lambda username, groups: record("ensure_user_groups", username, tuple(groups)),
    )
    monkeypatch.setattr(
        cli.system,
        "ensure_authorized_keys",
        lambda username, keys: record("ensure_authorized_keys", username, tuple(keys)) or Path("/tmp/authorized_keys"),
    )
    monkeypatch.setattr(
        cli.system,
        "ensure_passwordless_sudo",
        lambda username: record("ensure_passwordless_sudo", username) or Path("/tmp/sudoers"),
    )
    monkeypatch.setattr(
        cli.system,
        "lock_user_password",
        lambda username: record("lock_user_password", username),
    )

    monkeypatch.setattr(
        cli.ssh,
        "configure_sshd",
        lambda username: record("configure_sshd", username),
    )
    monkeypatch.setattr(
        cli.ssh,
        "close_other_ssh_sessions",
        lambda: record("close_other_ssh_sessions"),
    )
    monkeypatch.setattr(
        cli.ssh,
        "restart_ssh_service",
        lambda: record("restart_ssh_service") or "ssh",
    )

    exit_code = cli.main(["--api-key", "secret"])

    assert exit_code == 0

    actions = [entry[0] for entry in call_sequence]
    assert actions.index("fetch_account_profile") < actions.index("register_server")

    # Ensure provisioning used the resolved username and keys.
    assert ("ensure_user_exists" in actions) and ("ensure_authorized_keys" in actions)
    ensure_keys_calls = [
        entry for entry in call_sequence if entry[0] == "ensure_authorized_keys"
    ]
    assert ensure_keys_calls[0][1][0] == "hvdeploy"
    assert list(ensure_keys_calls[0][1][1]) == ["ssh-rsa AAA"]

    # Verify SSH session closure was requested when allowed.
    assert "close_other_ssh_sessions" in actions
