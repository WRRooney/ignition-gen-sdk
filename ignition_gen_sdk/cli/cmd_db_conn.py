"""ign db-conn — database-connection CRUD subcommand group.

9 subcommands wrapping ApiBackend's database-connection methods:

- list        — list all connections (read-only)
- names       — list connection names (read-only)
- get         — get one connection by name (read-only)
- create      — create a new connection (--dry-run, --scan/--no-scan, --password-stdin)
- update      — update an existing connection (two-call: get sig → update,
                --dry-run, --scan/--no-scan, --password-stdin)
- delete      — delete a connection (two-call: get sig → delete, --yes, --scan/--no-scan)
- delete-bulk — bulk delete by entries file (no scan, no manifest)
- rename      — rename a connection (no scan, no manifest)
- describe    — describe the connection resource type (read-only)

Patterns:

- Error taxonomy mirrors cmd_provider.py exactly (five-clause order).
- Scan-after-mutation mirrors cmd_view.py (scan_config, ScanWarning → stderr WARNING, exit 0).
- update + delete fetch signature via get_connection() first (two-call pattern).
- 404/not-found yields "Error: connection '<name>' not found." not a raw httpx traceback.
- delete requires --yes or interactive confirm.
- Password resolution (`_resolve_password`) matrix:
    1. config-dict already has dict-shaped password → pass through (the JWE guard fires at model layer).
    2. config-dict already has non-empty plaintext password string → pass through.
    3. --password-stdin → read one line; inject if non-empty.
    4. no flag AND sys.stdin.isatty() → typer.prompt(hide_input=True); inject if non-empty.
    5. no flag AND not a tty AND no password key → pass through unchanged (SQLite/H2/no-auth).
   NEVER errors. The gateway-side rejects if the driver actually requires auth.
- Envelope refusal: create_cmd / update_cmd extract `backupConfig` from the top of
  config_dict and route it to DatabaseConnection's envelope; the @model_validator emits
  the backupConfig Hint when it is non-None. Inner-nested backupConfig falls back to
  ConnectionConfig.extra="forbid" as a generic ValidationError.
- _validate_driver: client-side check that --config-file's driver name is in
  api.list_drivers() before issuing create/update.

Manifest hooks: create / update / delete each call
``_manifest_record(resource_type="database-connections", ...)`` AFTER the
successful API call but BEFORE ``_scan_after_mutation`` so a failed scan
does not invalidate the record. delete uses ``payload={}`` as a
deletion tombstone. The on-disk manifest lives at
``tools/ignition_gen_sdk/.manifest/database-connections.json`` (gitignored).
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
from ..models.databases import ConnectionConfig, DatabaseConnection
from ._errors import render_error

# db-conn commands always use the API backend.
# --backend flag is not applicable here -- database-connection resources have no
# on-disk codegen path (the gateway owns the encrypted password material;
# tooling never constructs that).

db_conn_app = typer.Typer(
    name="db-conn",
    help="Database connection CRUD.",
    no_args_is_help=True,
)


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
    """POST scan/config after a db-conn mutation (mirrors cmd_provider.py).

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


def _resolve_password(config_dict: dict[str, Any], password_stdin: bool) -> dict[str, Any]:
    """Resolve the connection password using a 5-branch decision matrix.

    NEVER errors -- a missing password
    is a legitimate case (SQLite, H2, no-auth dev DBs). The gateway rejects
    server-side if the driver actually requires auth.

    Matrix (first match wins):
      (1) config_dict.password is a dict      → pass through (the JWE guard fires later).
      (2) config_dict.password is a non-empty str → pass through (gateway encrypts).
      (3) password_stdin=True                 → read one line from stdin;
                                                inject if non-empty, skip if empty.
      (4) no flag AND sys.stdin.isatty()      → typer.prompt(hide_input=True);
                                                inject if non-empty, skip if empty.
      (5) no flag AND not a tty AND no key    → pass through unchanged.

    Returns config_dict in all branches.
    """
    existing = config_dict.get("password")

    # Branch (1): dict-shaped password — leave alone, the JWE guard catches it.
    if isinstance(existing, dict):
        return config_dict

    # Branch (2): non-empty plaintext string — caller supplied it.
    if isinstance(existing, str) and existing != "":
        return config_dict

    # Branch (3): --password-stdin pipe.
    if password_stdin:
        line = sys.stdin.readline()
        line = line.rstrip("\n").rstrip("\r")
        if line:
            config_dict["password"] = line
        return config_dict

    # Branch (4): interactive tty prompt (no flag AND no key AND no string AND tty).
    if sys.stdin.isatty():
        prompted = typer.prompt(
            "Database password (input hidden)",
            hide_input=True,
            confirmation_prompt=False,
            default="",
            show_default=False,
        )
        if prompted:
            config_dict["password"] = prompted
        return config_dict

    # Branch (5): non-tty subprocess + no password key — pass through (SQLite/H2 case).
    return config_dict


def _validate_driver(api: ApiBackend, driver: str | None) -> None:
    """Client-side check that ``driver`` is in the gateway's installed-driver list.

    Raises ``PayloadError`` with a Hint pointing at ``ign driver list`` when
    the driver is not installed. PayloadError is caught by the existing
    five-clause taxonomy in every create/update body, so this surfaces cleanly
    via render_error without a custom branch.

    A ``None`` or empty driver short-circuits (let the model/gateway complain).
    """
    if not driver:
        return
    drivers = api.list_drivers()
    names = {item["name"] for item in drivers if isinstance(item, dict) and "name" in item}
    if driver not in names:
        raise PayloadError(
            f"driver '{driver}' not installed. Hint: run `ign driver list` to "
            "see available drivers."
        )


# ---------------------------------------------------------------------------
# Read-only commands
# ---------------------------------------------------------------------------

@db_conn_app.command("list")
def list_cmd() -> None:
    """List all database connections (full config)."""
    settings, api = _get_api()
    try:
        result = api.list_connections()
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


@db_conn_app.command("names")
def names_cmd() -> None:
    """List names of all database connections."""
    settings, api = _get_api()
    try:
        result = api.get_connection_names()
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


@db_conn_app.command("get")
def get_cmd(
    name: Annotated[str, typer.Argument(help="Connection name.")],
) -> None:
    """Get full config for a single database connection."""
    settings, api = _get_api()
    try:
        result = api.get_connection(name)
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"connection '{name}' not found."), no_color=False)
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


@db_conn_app.command("describe")
def describe_cmd() -> None:
    """Describe the database-connection resource type (extension points, defaults)."""
    settings, api = _get_api()
    try:
        result = api.describe_connection_type()
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

@db_conn_app.command("create")
def create_cmd(
    name: Annotated[str, typer.Option("--name", help="Connection name.")],
    config_file: Annotated[
        str,
        typer.Option(
            "--config-file",
            help=(
                "Path to ConnectionConfig JSON file (the 25 inner fields, "
                "optionally with an outer backupConfig sibling), or '-' for stdin."
            ),
        ),
    ],
    description: Annotated[
        str,
        typer.Option("--description", help="Optional human-readable description."),
    ] = "",
    enabled: Annotated[
        bool,
        typer.Option(
            "--enabled/--disabled",
            help="Mark the new connection enabled (default) or disabled.",
        ),
    ] = True,
    password_stdin: Annotated[
        bool,
        typer.Option(
            "--password-stdin",
            help=(
                "Read the password from stdin (single line). Pipe-friendly; "
                "no tty prompt. Without this flag and without a password key in "
                "the config, no password is injected."
            ),
        ),
    ] = False,
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
    """Create a new database connection from a JSON config file."""
    try:
        config_dict = _read_config(config_file)
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"could not read config file '{config_file}': {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    # Resolve password BEFORE dry-run so the dry-run payload reflects what
    # would actually ship. Helper never errors -- pass-through when absent.
    config_dict = _resolve_password(config_dict, password_stdin)

    if dry_run:
        payload = {"name": name, "config": config_dict}
        typer.echo(json.dumps(payload, indent=2))
        return

    settings, api = _get_api()
    try:
        # Extract any outer-envelope backupConfig BEFORE building the
        # ConnectionConfig (which has extra="forbid"). Pass it to the
        # DatabaseConnection envelope so the @model_validator emits the backupConfig
        # Hint when it is non-None.
        backup_config = config_dict.pop("backupConfig", None)

        # Client-side driver name validation. PayloadError → render_error.
        _validate_driver(api, config_dict.get("driver"))

        # Validate the full envelope before any HTTP. Catches:
        #   - JWE-shaped password (ConnectionConfig field validator)
        #   - outer backupConfig (DatabaseConnection model_validator)
        #   - extra fields nested INSIDE the 25-key config (ConnectionConfig.extra="forbid")
        # pydantic.ValidationError is a ValueError subclass; caught by the
        # existing ValueError clause below.
        envelope_kwargs: dict[str, Any] = {
            "name": name,
            "description": description or "",
            "enabled": enabled,
            "config": ConnectionConfig(**config_dict),
        }
        if backup_config is not None:
            envelope_kwargs["backupConfig"] = backup_config
        DatabaseConnection(**envelope_kwargs)

        # Actual wire payload is the raw config_dict (already stripped of
        # backupConfig per the pop above). The model layer's job was
        # validation, not payload reshape.
        result = api.create_connection(name, config=config_dict)
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
        resource_type="database-connections",
        resource_id=name,
        payload=config_dict,
        backend="api",
    )
    _scan_after_mutation(settings, scan)


@db_conn_app.command("update")
def update_cmd(
    name: Annotated[str, typer.Option("--name", help="Connection name.")],
    config_file: Annotated[
        str,
        typer.Option(
            "--config-file",
            help=(
                "Path to ConnectionConfig JSON file (the 25 inner fields, "
                "optionally with an outer backupConfig sibling), or '-' for stdin."
            ),
        ),
    ],
    description: Annotated[
        str,
        typer.Option("--description", help="Optional human-readable description."),
    ] = "",
    enabled: Annotated[
        bool,
        typer.Option(
            "--enabled/--disabled",
            help="Mark the connection enabled (default) or disabled.",
        ),
    ] = True,
    password_stdin: Annotated[
        bool,
        typer.Option(
            "--password-stdin",
            help=(
                "Read the password from stdin (single line). Pipe-friendly; "
                "no tty prompt. Without this flag and without a password key in "
                "the config, no password is injected."
            ),
        ),
    ] = False,
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
    """Update an existing database connection (fetches signature first, then updates)."""
    try:
        config_dict = _read_config(config_file)
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"could not read config file '{config_file}': {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    config_dict = _resolve_password(config_dict, password_stdin)

    if dry_run:
        payload = {"name": name, "config": config_dict}
        typer.echo(json.dumps(payload, indent=2))
        return

    settings, api = _get_api()
    try:
        # Extract outer-envelope backupConfig before ConnectionConfig.
        backup_config = config_dict.pop("backupConfig", None)

        _validate_driver(api, config_dict.get("driver"))

        envelope_kwargs: dict[str, Any] = {
            "name": name,
            "description": description or "",
            "enabled": enabled,
            "config": ConnectionConfig(**config_dict),
        }
        if backup_config is not None:
            envelope_kwargs["backupConfig"] = backup_config
        DatabaseConnection(**envelope_kwargs)

        # Two-call pattern: fetch signature first.
        existing = api.get_connection(name)
        sig = existing.get("signature", "")
        result = api.update_connection(name, sig, config=config_dict)
        typer.echo(json.dumps(result, indent=2))
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"connection '{name}' not found."), no_color=False)
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
        resource_type="database-connections",
        resource_id=name,
        payload=config_dict,
        backend="api",
    )
    _scan_after_mutation(settings, scan)


@db_conn_app.command("delete")
def delete_cmd(
    name: Annotated[str, typer.Option("--name", help="Connection name.")],
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
    """Delete a database connection (fetches signature first; prompts for confirmation)."""
    # Confirmation guard.
    if not yes:
        typer.confirm(f"Delete connection '{name}'?", abort=True)

    settings, api = _get_api()
    try:
        # Two-call pattern: fetch signature first.
        existing = api.get_connection(name)
        sig = existing.get("signature", "")
        result = api.delete_connection(name, sig)
        typer.echo(json.dumps(result, indent=2))
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"connection '{name}' not found."), no_color=False)
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
        resource_type="database-connections",
        resource_id=name,
        payload={},
        backend="api",
    )
    _scan_after_mutation(settings, scan)


@db_conn_app.command("delete-bulk")
def delete_bulk_cmd(
    entries_file: Annotated[
        str,
        typer.Option(
            "--entries-file",
            help="Path to JSON file containing list of {name, signature} dicts.",
        ),
    ],
) -> None:
    """Bulk delete database connections from a JSON entries file."""
    try:
        entries: list[dict[str, str]] = json.loads(
            Path(entries_file).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"could not read entries file '{entries_file}': {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    _settings, api = _get_api()
    try:
        result = api.delete_connections(entries)
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


@db_conn_app.command("rename")
def rename_cmd(
    name: Annotated[str, typer.Option("--name", help="Current connection name.")],
    new_name: Annotated[str, typer.Option("--new-name", help="New connection name.")],
) -> None:
    """Rename a database connection (updates cross-resource references)."""
    _settings, api = _get_api()
    try:
        result = api.rename_connection(name, new_name)
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"connection '{name}' not found."), no_color=False)
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
