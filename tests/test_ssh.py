"""Tests covering SSH session management helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from management_agent import ssh


def _read_directive_tokens(path: Path, directive: str) -> List[str]:
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        parts = stripped.split()
        if parts and parts[0].lower() == directive.lower():
            return parts[1:]

    return []


def test_configure_sshd_sets_directives_for_non_root_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure non-root users have root logins disabled and AllowUsers updated."""

    config_path = tmp_path / "sshd_config"
    config_path.write_text("PermitRootLogin yes\n")
    monkeypatch.setattr(ssh, "SSHD_CONFIG_PATH", config_path)

    ssh.configure_sshd("hvdeploy")

    backup_path = config_path.with_suffix(".pre_hvdeploy")
    assert backup_path.exists()

    assert _read_directive_tokens(config_path, "PermitRootLogin") == ["no"]
    assert "hvdeploy" in _read_directive_tokens(config_path, "AllowUsers")


def test_configure_sshd_allows_root_key_logins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the management user is root, retain key-based root access."""

    config_path = tmp_path / "sshd_config"
    config_path.write_text("PermitRootLogin yes\n")
    monkeypatch.setattr(ssh, "SSHD_CONFIG_PATH", config_path)

    ssh.configure_sshd("root")

    assert _read_directive_tokens(config_path, "PermitRootLogin") == [
        "prohibit-password"
    ]
    assert _read_directive_tokens(config_path, "AllowUsers") == ["root"]


def test_detect_current_tty_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``SSH_TTY`` is used when ``ttyname`` is unavailable."""

    def raise_oserror(_fd: int) -> str:  # pragma: no cover - defensive
        raise OSError

    monkeypatch.setattr(ssh.os, "ttyname", raise_oserror)
    monkeypatch.setenv("SSH_TTY", "/dev/pts/42")

    assert ssh._detect_current_tty() == "pts/42"


def test_close_other_sessions_without_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the current TTY is unknown no sessions should be terminated."""

    monkeypatch.setattr(ssh, "_detect_current_tty", lambda: None)

    commands: List[List[str]] = []

    def fake_run_command(command: List[str], **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        raise AssertionError("run_command should not be called without a TTY")

    monkeypatch.setattr(ssh, "run_command", fake_run_command)

    ssh.close_other_ssh_sessions()

    assert commands == []


def test_close_other_sessions_terminates_non_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure only sessions on a different TTY are terminated."""

    monkeypatch.setattr(ssh, "_detect_current_tty", lambda: "pts/1")

    pkill_commands: List[List[str]] = []

    def fake_run_command(command: List[str], **kwargs: object) -> SimpleNamespace:
        if command == ["who"]:
            return SimpleNamespace(
                returncode=0,
                stdout="user pts/1 (1.2.3.4)\nuser pts/2 (5.6.7.8)\n",
            )

        if command[:3] == ["pkill", "-15", "-t"]:
            pkill_commands.append(command)
            return SimpleNamespace(returncode=0, stdout="")

        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(ssh, "run_command", fake_run_command)

    ssh.close_other_ssh_sessions()

    assert pkill_commands == [["pkill", "-15", "-t", "pts/2"]]
