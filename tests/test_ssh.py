"""Tests covering SSH session management helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

from management_agent import ssh


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
