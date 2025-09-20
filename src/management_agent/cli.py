"""Command line interface for preparing a server for HVDeploy management."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Dict
from urllib.parse import urlparse

from . import api, system
from .api import APIClientError
from .system import CommandError

DEFAULT_BASE_URL = "https://api.playrservers.com"
DEFAULT_GROUPS = "sudo,libvirt,kvm"


def _parse_metadata(pairs: list[str]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise argparse.ArgumentTypeError(
                f"Invalid metadata entry '{pair}'. Use KEY=VALUE format."
            )
        key, value = pair.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def _configure_logging(level: str) -> None:
    log_level = getattr(logging, level.upper(), None)
    if log_level is None:
        raise argparse.ArgumentTypeError(f"Unknown log level: {level}")

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _validate_api_base_url(url: str) -> str:
    """Ensure *url* targets the approved management API endpoint."""

    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise argparse.ArgumentTypeError("Management API URL must use HTTPS")

    hostname = (parsed.hostname or "").lower()
    if hostname != api.ALLOWED_API_HOST:
        raise argparse.ArgumentTypeError(
            f"Management API host must be {api.ALLOWED_API_HOST}"
        )

    port = parsed.port
    if port not in (None, api.ALLOWED_API_PORT):
        raise argparse.ArgumentTypeError(
            f"Management API port must be {api.ALLOWED_API_PORT}"
        )

    base_path = parsed.path.rstrip("/")
    return f"https://{api.ALLOWED_API_HOST}{base_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure a server for HVDeploy remote management.",
    )

    parser.add_argument(
        "--api-key",
        help="API key used to authenticate with the management API. Defaults to the HVDEPLOY_API_KEY environment variable.",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_BASE_URL,
        help=f"Management API base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--api-endpoint",
        default=api.DEFAULT_ENDPOINT,
        help="Management API endpoint used for registration.",
    )
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional metadata to include when registering the server. Can be specified multiple times.",
    )
    parser.add_argument(
        "--management-user",
        default="hvdeploy",
        help="Username to configure for remote management (default: hvdeploy).",
    )
    parser.add_argument(
        "--management-groups",
        default=DEFAULT_GROUPS,
        help=f"Comma-separated list of groups to assign the management user to (default: {DEFAULT_GROUPS}).",
    )
    parser.add_argument(
        "--skip-close-sessions",
        action="store_true",
        help="Do not terminate other active SSH sessions after configuration.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        _configure_logging(args.log_level)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    try:
        api_base_url = _validate_api_base_url(args.api_base_url)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    if os.geteuid() != 0:
        parser.error("This utility must be run as root.")

    metadata: Dict[str, str] = {}
    try:
        metadata = _parse_metadata(args.metadata)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    api_key = args.api_key or os.environ.get("HVDEPLOY_API_KEY")
    if not api_key:
        parser.error("An API key must be provided via --api-key or HVDEPLOY_API_KEY.")

    logger = logging.getLogger(__name__)

    try:
        profile = api.fetch_account_profile(api_base_url, api_key)

        username_from_api = profile.username or args.management_user
        if not username_from_api:
            parser.error(
                "Unable to determine the management username from arguments or account profile."
            )

        system.install_qemu_stack()

        registration = api.register_server(
            api_base_url,
            api_key,
            endpoint=args.api_endpoint,
            metadata=metadata,
            username=username_from_api,
            authorized_keys=profile.authorized_keys,
        )

        username = registration.username or username_from_api

        groups = [group.strip() for group in args.management_groups.split(",") if group.strip()]
        system.ensure_user_exists(username)
        system.ensure_user_groups(username, groups)
        system.ensure_authorized_keys(username, registration.authorized_keys)
        system.ensure_passwordless_sudo(username)
        system.lock_user_password(username)

        command_requests = api.fetch_pending_commands(api_base_url, api_key)
        if command_requests:
            logger.info(
                "Executing %d command(s) provided by the management API",
                len(command_requests),
            )
        else:
            logger.info("No pending commands provided by the management API")

        for request in command_requests:
            descriptor = request.identifier or request.command
            logger.info("Running command '%s' as %s", descriptor, username)
            system.run_command_as_user(
                username,
                request.command,
                check=True,
                capture_output=False,
            )
    except APIClientError as exc:
        logger.error("API communication failed: %s", exc)
        return 1
    except (CommandError, ValueError) as exc:
        logger.error("Configuration failed: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover - defensive safety net
        logger.exception("Unexpected error during configuration: %s", exc)
        return 1

    logger.info("Management agent configuration complete for user %s", username)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
