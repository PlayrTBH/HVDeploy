"""Helpers for hardening SSH access for the management agent."""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import List

from .system import CommandError, run_command

LOGGER = logging.getLogger(__name__)

SSHD_CONFIG_PATH = Path("/etc/ssh/sshd_config")


class SSHConfigurationError(RuntimeError):
    """Raised when updating the SSH server configuration fails."""


def _normalise_directive(directive: str) -> str:
    return directive.strip().lower()


def _parse_directive_line(line: str) -> tuple[str, list[str], str]:
    """Split a configuration *line* into indentation, tokens and comment."""

    leading_whitespace = line[: len(line) - len(line.lstrip())]
    remainder = line[len(leading_whitespace) :]
    comment = ""

    if "#" in remainder:
        hash_index = remainder.find("#")
        comment = remainder[hash_index:]
        remainder = remainder[:hash_index]

    tokens = remainder.split()
    return leading_whitespace, tokens, comment.strip()


def _set_directive(path: Path, directive: str, value: str) -> bool:
    """Ensure *directive* in *path* is set to *value*.

    Returns ``True`` if the file was modified.
    """

    directive_key = _normalise_directive(directive)
    updated = False
    lines: List[str] = []

    if path.exists():
        lines = path.read_text().splitlines()

    new_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            new_lines.append(line)
            continue

        parts = stripped.split(maxsplit=1)
        if _normalise_directive(parts[0]) == directive_key:
            if parts[-1].strip() != value:
                new_lines.append(f"{directive} {value}")
                updated = True
            else:
                new_lines.append(line)
            continue
        new_lines.append(line)

    if not any(
        _normalise_directive(line.split(maxsplit=1)[0]) == directive_key
        for line in lines
        if line.split()
    ):
        new_lines.append(f"{directive} {value}")
        updated = True

    if updated:
        path.write_text("\n".join(new_lines) + "\n")
    return updated


def _ensure_allow_users(path: Path, username: str) -> bool:
    """Ensure *username* is present on the ``AllowUsers`` line."""

    directive_key = "allowusers"
    modified = False
    lines: List[str] = []

    if path.exists():
        lines = path.read_text().splitlines()

    new_lines: List[str] = []
    directive_found = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            new_lines.append(line)
            continue

        leading_ws, tokens, comment = _parse_directive_line(line)
        if not tokens:
            new_lines.append(line)
            continue

        if _normalise_directive(tokens[0]) == directive_key:
            directive_found = True
            users = tokens[1:]
            if username in users:
                new_lines.append(line)
                continue

            users.append(username)
            modified = True
            comment_suffix = f" {comment}" if comment else ""
            new_lines.append(
                f"{leading_ws}AllowUsers {' '.join(users)}{comment_suffix}"
            )
            continue
        new_lines.append(line)

    if not directive_found:
        new_lines.append(f"AllowUsers {username}")
        modified = True

    if modified:
        path.write_text("\n".join(new_lines) + "\n")
    return modified


def configure_sshd(username: str) -> None:
    """Harden the SSH daemon for key-based authentication."""

    if not SSHD_CONFIG_PATH.exists():
        raise SSHConfigurationError("Could not locate sshd_config")

    backup_path = SSHD_CONFIG_PATH.with_suffix(".pre_hvdeploy")
    if not backup_path.exists():
        shutil.copy2(SSHD_CONFIG_PATH, backup_path)
        LOGGER.info("Backed up SSH configuration to %s", backup_path)

    changes = [
        _set_directive(SSHD_CONFIG_PATH, "PasswordAuthentication", "no"),
        _set_directive(SSHD_CONFIG_PATH, "ChallengeResponseAuthentication", "no"),
        _set_directive(SSHD_CONFIG_PATH, "KbdInteractiveAuthentication", "no"),
        _set_directive(SSHD_CONFIG_PATH, "PubkeyAuthentication", "yes"),
        _set_directive(SSHD_CONFIG_PATH, "PermitRootLogin", "no"),
        _set_directive(SSHD_CONFIG_PATH, "AuthenticationMethods", "publickey"),
        _ensure_allow_users(SSHD_CONFIG_PATH, username),
    ]

    if any(changes):
        LOGGER.info("Updated SSH configuration to enforce key-based access")
    else:
        LOGGER.info("SSH configuration already enforced key-based access")


def restart_ssh_service() -> str:
    """Restart the SSH service to apply configuration updates."""

    last_error: CommandError | None = None
    for service in ("ssh", "sshd"):
        try:
            run_command(["systemctl", "restart", service])
            LOGGER.info("Restarted %s service", service)
            return service
        except CommandError as exc:
            last_error = exc
            LOGGER.debug("Service %s restart failed: %s", service, exc)

    if last_error is not None:
        raise last_error
    raise SSHConfigurationError("Unable to restart SSH service")


def _detect_current_tty() -> str | None:
    """Return the TTY for the running process or ``None`` when unavailable."""

    try:
        tty = os.ttyname(sys.stdin.fileno())
    except (OSError, AttributeError, ValueError):
        tty = os.environ.get("SSH_TTY")

    if not tty:
        return None

    if tty.startswith("/dev/"):
        tty = tty[5:]

    return tty or None


def close_other_ssh_sessions() -> None:
    """Terminate any SSH sessions other than the one running the agent."""

    current_tty = _detect_current_tty()

    if current_tty is None:
        LOGGER.warning(
            "Cannot determine controlling TTY; skipping termination of other SSH sessions",
        )
        return

    result = run_command(["who"], capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        LOGGER.warning("Could not enumerate active SSH sessions")
        return

    terminated = 0
    for line in result.stdout.splitlines():
        if "(" not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        tty = parts[1]
        if current_tty and tty == current_tty:
            continue
        LOGGER.info("Terminating SSH session attached to %s", tty)
        run_command(["pkill", "-15", "-t", tty], check=False)
        terminated += 1

    if terminated:
        LOGGER.info("Terminated %d other SSH session(s)", terminated)
    else:
        LOGGER.info("No other SSH sessions found to terminate")
