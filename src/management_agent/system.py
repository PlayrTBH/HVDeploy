"""System level utilities for preparing a host for remote management."""
from __future__ import annotations

import logging
import os
import pwd
import subprocess
from pathlib import Path
from typing import Iterable, List, Sequence

LOGGER = logging.getLogger(__name__)


class CommandError(RuntimeError):
    """Raised when a system command fails."""


def run_command(
    command: Sequence[str],
    *,
    check: bool = True,
    capture_output: bool = False,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Execute *command* and optionally capture its output.

    Parameters
    ----------
    command:
        Iterable of command tokens to execute.
    check:
        Raise :class:`CommandError` when the command exits with a non-zero
        status code.  If *check* is ``False`` the caller is responsible for
        validating the exit status.
    capture_output:
        When ``True`` the standard output of the command is captured and
        returned as part of the :class:`~subprocess.CompletedProcess` object.
    text:
        When ``True`` the command output is decoded as text.
    """

    LOGGER.debug("Running command: %s", " ".join(command))
    try:
        return subprocess.run(
            list(command),
            check=check,
            capture_output=capture_output,
            text=text,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - thin wrapper
        raise CommandError("Command failed: %s" % (" ".join(command),)) from exc


APT_PACKAGES = [
    "qemu-system",
    "qemu-system-x86",
    "qemu-utils",
    "qemu-kvm",
    "libvirt-daemon-system",
    "libvirt-clients",
    "bridge-utils",
    "virtinst",
    "cloud-image-utils",
    "ovmf",
]


def install_qemu_stack() -> None:
    """Install QEMU, libvirt and related tooling using ``apt``."""
    LOGGER.info("Updating apt cache before package installation")
    run_command(["apt-get", "update"])

    LOGGER.info("Installing virtualization packages: %s", ", ".join(APT_PACKAGES))
    run_command(["apt-get", "install", "-y", *APT_PACKAGES])

    LOGGER.info("Enabling libvirtd services")
    # ``libvirtd`` is the primary service; virtlogd handles logging.  Not all
    # distributions split the services the same way so failures are logged
    # rather than fatal.
    for service in ("libvirtd", "virtlogd"):
        result = run_command(
            ["systemctl", "enable", "--now", service],
            check=False,
        )
        if result.returncode != 0:
            LOGGER.warning("Service %s could not be enabled (exit code %s)", service, result.returncode)


def ensure_user_exists(username: str) -> None:
    """Create *username* when it does not already exist."""
    try:
        pwd.getpwnam(username)
        LOGGER.debug("User %s already exists", username)
        return
    except KeyError:
        LOGGER.info("Creating management user %s", username)
        run_command([
            "useradd",
            "--create-home",
            "--shell",
            "/bin/bash",
            username,
        ])


def ensure_user_groups(username: str, groups: Iterable[str]) -> None:
    """Ensure *username* is a member of *groups*."""
    if not groups:
        return

    group_names = list(groups)
    for group in group_names:
        result = run_command(["getent", "group", group], check=False)
        if result.returncode != 0:
            LOGGER.info("Creating missing group %s", group)
            run_command(["groupadd", group])

    LOGGER.info("Adding user %s to groups: %s", username, ", ".join(group_names))
    run_command([
        "usermod",
        "-aG",
        ",".join(group_names),
        username,
    ])


def lock_user_password(username: str) -> None:
    """Ensure the password for *username* is locked for SSH hardening."""

    status = run_command(
        ["passwd", "-S", username],
        capture_output=True,
        check=False,
    )

    if status.returncode == 0:
        parts = status.stdout.split()
        if len(parts) >= 2 and parts[1] == "L":
            LOGGER.debug("Password for %s already locked", username)
            return

    LOGGER.info("Locking password for %s to enforce key-based authentication", username)
    run_command(["passwd", "-l", username])


def ensure_authorized_keys(username: str, keys: Sequence[str]) -> Path:
    """Write *keys* to the user's ``authorized_keys`` file.

    Returns
    -------
    pathlib.Path
        Path to the ``authorized_keys`` file for convenience.
    """

    if not keys:
        raise ValueError("At least one public key must be provided")

    user_info = pwd.getpwnam(username)
    ssh_dir = Path(user_info.pw_dir) / ".ssh"
    ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)
    os.chown(ssh_dir, user_info.pw_uid, user_info.pw_gid)

    authorized_keys = ssh_dir / "authorized_keys"
    contents = "".join(f"{key.strip()}\n" for key in keys if key.strip())
    authorized_keys.write_text(contents)
    os.chmod(authorized_keys, 0o600)
    os.chown(authorized_keys, user_info.pw_uid, user_info.pw_gid)
    LOGGER.info("Wrote %d authorized key(s) for %s", len(keys), username)
    return authorized_keys


def ensure_passwordless_sudo(username: str, sudoers_path: Path | None = None) -> Path:
    """Grant passwordless sudo access to *username*."""

    if sudoers_path is None:
        sudoers_path = Path("/etc/sudoers.d/hvdeploy")

    content = f"{username} ALL=(ALL) NOPASSWD:ALL\n"
    sudoers_path.write_text(content)
    os.chmod(sudoers_path, 0o440)
    LOGGER.info("Ensured passwordless sudo for %s at %s", username, sudoers_path)
    return sudoers_path


def run_command_as_user(
    username: str,
    command: str,
    *,
    check: bool = True,
    capture_output: bool = False,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Execute *command* as *username* using ``sudo``."""

    if not command or not command.strip():
        raise ValueError("Command must be a non-empty string")

    sudo_command = ["sudo", "-u", username, "bash", "-lc", command]
    LOGGER.debug("Running command as %s: %s", username, command)
    return run_command(
        sudo_command,
        check=check,
        capture_output=capture_output,
        text=text,
    )
