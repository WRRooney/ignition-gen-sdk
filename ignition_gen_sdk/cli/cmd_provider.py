"""ign provider — tag-provider CRUD subcommand group.

9 subcommands wrapping ApiBackend's tag-provider methods:

- list      — list all providers (read-only)
- names     — list provider names (read-only)
- get       — get one provider by name (read-only)
- create    — create a new provider (--dry-run, --scan/--no-scan)
- update    — update an existing provider (two-call: get sig → update, --dry-run, --scan/--no-scan)
- delete    — delete a provider (two-call: get sig → delete, --yes, --scan/--no-scan)
- delete-bulk — bulk delete by entries file (no scan, no manifest)
- rename    — rename a provider (no scan, no manifest)
- describe  — describe the provider type (read-only)

Patterns:

- Error taxonomy mirrors cmd_tag.py exactly (five-clause order).
- Scan-after-mutation mirrors cmd_view.py (scan_config, ScanWarning → stderr WARNING, exit 0).
- manifest.record() called BEFORE _scan_after_mutation on create/update/delete.
- update + delete fetch signature via get_provider() first (two-call pattern).
- 404/not-found yields "Error: provider '<name>' not found." not a raw httpx traceback.
- delete requires --yes or interactive confirm.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from ..backends.api_backend import ApiBackend
from ..backends.api_client import (
    AuthMissingError,
    AuthScopeError,
    GatewayError,
    IgnitionAPIClient,
    NetworkError,
    PayloadError,
)
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ..manifest.manifest import record as _manifest_record
from ._errors import render_error

# Provider commands always use the API backend.
# --backend flag is not applicable here -- provider resources have no on-disk representation.

provider_app = typer.Typer(help="Tag provider CRUD.")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _get_api() -> tuple[Settings, ApiBackend]:
    """Construct Settings + ApiBackend; surface missing-creds error cleanly."""
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as e:  # noqa: BLE001
        render_error(AuthMissingError(
            f"check IGNITION_API_TOKEN (env or .env) ({e})"
        ), no_color=False)
        raise typer.Exit(code=1) from None
    client = IgnitionAPIClient(settings)
    api = ApiBackend(client)
    return settings, api


def _read_config(path: str) -> dict[str, Any]:
    """Read JSON config from a file path or '-' for stdin."""
    if path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def _scan_after_mutation(settings: Settings, scan: bool) -> None:
    """POST scan/config after a provider mutation (mirrors cmd_view.py).

    Best-effort: any failure becomes a stderr WARNING and exit 0.
    --no-scan suppresses entirely (offline / dev flows).
    """
    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_config()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed; the change is on disk but may not be picked up. Reason: {e}",
            err=True,
        )
        return


def _is_not_found(exc: PayloadError) -> bool:
    """Return True if the PayloadError looks like a 404 / not-found."""
    msg = str(exc).lower()
    return "not found" in msg or "404" in msg


# ---------------------------------------------------------------------------
# Read-only commands
# ---------------------------------------------------------------------------

@provider_app.command("list")
def list_cmd() -> None:
    """List all tag providers (full config)."""
    settings, api = _get_api()
    try:
        result = api.list_providers()
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)


@provider_app.command("names")
def names_cmd() -> None:
    """List names of all tag providers."""
    settings, api = _get_api()
    try:
        result = api.get_provider_names()
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)


@provider_app.command("get")
def get_cmd(
    name: Annotated[str, typer.Argument(help="Provider name.")],
) -> None:
    """Get full config for a single tag provider."""
    settings, api = _get_api()
    try:
        result = api.get_provider(name)
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"provider '{name}' not found."), no_color=False)
        else:
            render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)


@provider_app.command("describe")
def describe_cmd() -> None:
    """Describe the tag-provider resource type (extension points, defaults)."""
    settings, api = _get_api()
    try:
        result = api.describe_provider_type()
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Mutating commands
# ---------------------------------------------------------------------------

@provider_app.command("create")
def create_cmd(
    name: Annotated[str, typer.Option("--name", help="Provider name.")],
    config_file: Annotated[
        str,
        typer.Option(
            "--config-file",
            help="Path to provider config JSON file, or '-' for stdin.",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print payload to stdout; no API call.",
        ),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help=(
                "After a successful create, POST /data/api/v1/scan/config "
                "to notify the gateway. Pass --no-scan when the gateway is "
                "unreachable. Default: scan."
            ),
        ),
    ] = True,
) -> None:
    """Create a new tag provider from a JSON config file."""
    try:
        config_dict = _read_config(config_file)
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"could not read config file '{config_file}': {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if dry_run:
        payload = {"name": name, "config": config_dict}
        typer.echo(json.dumps(payload, indent=2))
        return

    settings, api = _get_api()
    try:
        result = api.create_provider(name, config=config_dict)
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)

    # manifest before scan (scan failure must not invalidate record)
    _manifest_record(
        resource_type="providers",
        resource_id=name,
        payload=config_dict,
        backend="api",
    )
    _scan_after_mutation(settings, scan)


@provider_app.command("update")
def update_cmd(
    name: Annotated[str, typer.Option("--name", help="Provider name.")],
    config_file: Annotated[
        str,
        typer.Option(
            "--config-file",
            help="Path to provider config JSON file, or '-' for stdin.",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print payload to stdout; no API call.",
        ),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help=(
                "After a successful update, POST /data/api/v1/scan/config "
                "to notify the gateway. Pass --no-scan when the gateway is "
                "unreachable. Default: scan."
            ),
        ),
    ] = True,
) -> None:
    """Update an existing tag provider (fetches signature first, then updates)."""
    try:
        config_dict = _read_config(config_file)
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"could not read config file '{config_file}': {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if dry_run:
        payload = {"name": name, "config": config_dict}
        typer.echo(json.dumps(payload, indent=2))
        return

    settings, api = _get_api()
    try:
        # Two-call pattern: fetch signature first
        existing = api.get_provider(name)
        sig = existing.get("signature", "")
        result = api.update_provider(name, sig, config=config_dict)
        typer.echo(json.dumps(result, indent=2))
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"provider '{name}' not found."), no_color=False)
        else:
            render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)

    # manifest before scan
    _manifest_record(
        resource_type="providers",
        resource_id=name,
        payload=config_dict,
        backend="api",
    )
    _scan_after_mutation(settings, scan)


@provider_app.command("delete")
def delete_cmd(
    name: Annotated[str, typer.Option("--name", help="Provider name.")],
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Skip confirmation prompt.",
        ),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help=(
                "After a successful delete, POST /data/api/v1/scan/config "
                "to notify the gateway. Pass --no-scan when the gateway is "
                "unreachable. Default: scan."
            ),
        ),
    ] = True,
) -> None:
    """Delete a tag provider (fetches signature first; prompts for confirmation)."""
    # Confirmation guard
    if not yes:
        typer.confirm(f"Delete provider '{name}'?", abort=True)

    settings, api = _get_api()
    try:
        # Two-call pattern: fetch signature first
        existing = api.get_provider(name)
        sig = existing.get("signature", "")
        result = api.delete_provider(name, sig)
        typer.echo(json.dumps(result, indent=2))
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"provider '{name}' not found."), no_color=False)
        else:
            render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)

    # manifest before scan; empty payload records the deletion
    _manifest_record(
        resource_type="providers",
        resource_id=name,
        payload={},
        backend="api",
    )
    _scan_after_mutation(settings, scan)


@provider_app.command("delete-bulk")
def delete_bulk_cmd(
    entries_file: Annotated[
        str,
        typer.Option(
            "--entries-file",
            help="Path to JSON file containing list of {name, signature} dicts.",
        ),
    ],
) -> None:
    """Bulk delete tag providers from a JSON entries file."""
    try:
        entries: list[dict[str, str]] = json.loads(
            Path(entries_file).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"could not read entries file '{entries_file}': {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    _settings, api = _get_api()
    try:
        result = api.delete_providers(entries)
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)


@provider_app.command("rename")
def rename_cmd(
    name: Annotated[str, typer.Option("--name", help="Current provider name.")],
    new_name: Annotated[str, typer.Option("--new-name", help="New provider name.")],
) -> None:
    """Rename a tag provider (updates cross-resource references)."""
    _settings, api = _get_api()
    try:
        result = api.rename_provider(name, new_name)
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"provider '{name}' not found."), no_color=False)
        else:
            render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
