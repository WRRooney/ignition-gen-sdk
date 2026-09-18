"""ign alarm-journal — alarm-journal profile CRUD subcommand group.

Encapsulates what the loop previously did with a raw ``ign api`` POST,
including the array-body gotcha: the resources API ``(multiple)`` pattern
requires the request body to be a JSON **ARRAY** ``[ {object} ]``. A bare
object returns HTTP 400 "Not a JSON Array".

3 subcommands:

- create   — POST /data/api/v1/resources/ignition/alarm-journal?allowInvalidReferences=true
             body is a one-element JSON array (--dry-run, --confirm, --scan/--no-scan).
- list     — GET /data/api/v1/resources/list/ignition/alarm-journal (read-only).
- get      — GET /data/api/v1/resources/find/ignition/alarm-journal/<name> (read-only).

Patterns (mirrored from cmd_db_conn.py / cmd_api.py):

- Settings() credential handling via _get_api() (token never enters argv).
- Uses IgnitionAPIClient.request() directly (the resources API has no typed
  ApiBackend verb), same client mechanism cmd_api.py uses.
- Five-clause error taxonomy in the canonical cmd_provider.py order
  (AuthMissing → AuthScope → Payload → Gateway → Network → ValueError); do
  not reorder (log scanners assert this).
- 404/not-found on `get` yields "Error: alarm journal '<name>' not found."
- --scan (default on) POSTs /data/api/v1/scan/config after a successful
  create; ScanWarning → stderr WARNING line, exit 0 (mirrors cmd_db_conn).
"""
from __future__ import annotations

import json
import sys
from typing import Annotated, Any

import typer

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
from ._errors import render_error

# CLI: alarm-journal commands always use the raw resources API via
# IgnitionAPIClient.request() -- there is no typed ApiBackend verb for the
# resources/(multiple) endpoint, and no on-disk codegen path for it.

alarm_journal_app = typer.Typer(
    name="alarm-journal",
    help="Alarm journal profile CRUD.",
    no_args_is_help=True,
)

# Resource API endpoints (verified working — the create endpoint is the
# resources "(multiple)" POST which requires a JSON ARRAY body).
_CREATE_PATH = "/data/api/v1/resources/ignition/alarm-journal?allowInvalidReferences=true"
_LIST_PATH = "/data/api/v1/resources/list/ignition/alarm-journal"
_FIND_PATH = "/data/api/v1/resources/find/ignition/alarm-journal"

# Allowed --min-priority values (Ignition alarm priority enum).
_MIN_PRIORITIES = ("Diagnostic", "Low", "Medium", "High", "Critical")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _get_api() -> tuple[Settings, IgnitionAPIClient]:
    """Construct Settings + IgnitionAPIClient; surface missing-creds cleanly.

    Mirrors cmd_api._get_api -- returns the bare client (this module consumes
    client.request() directly against the resources API).
    """
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as e:  # noqa: BLE001
        render_error(AuthMissingError(
            f"check IGNITION_API_TOKEN (env or .env) ({e})"
        ), no_color=False)
        raise typer.Exit(code=1) from None
    client = IgnitionAPIClient(settings)
    return settings, client


def _scan_after_mutation(settings: Settings, scan: bool) -> None:
    """POST scan/config after an alarm-journal mutation (mirrors cmd_db_conn.py).

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


def _build_resource_object(
    *,
    name: str,
    datasource: str,
    min_priority: str,
    description: str,
    prune_age: int,
    prune_units: str,
    table_name: str,
    data_table_name: str,
) -> dict[str, Any]:
    """Build the single alarm-journal resource object (verified shape).

    The CREATE endpoint wraps this in a one-element JSON array (the resources
    "(multiple)" pattern). A bare object returns 400 "Not a JSON Array".
    """
    return {
        "name": name,
        "collection": "core",
        "enabled": True,
        "description": description,
        "config": {
            "profile": {
                "type": "DATASOURCE",
                "queryOnly": False,
            },
            "settings": {
                "datasource": datasource,
                "events": {
                    "minPriority": min_priority,
                    "storeShelvedEvents": False,
                    "storeFromEnabledChange": False,
                },
                "eventData": {
                    "staticConfig": False,
                    "dynamicConfig": True,
                    "staticAssociatedData": True,
                    "dynamicAssociatedData": True,
                },
                "dataFilters": {},
                "pruning": {
                    "enabled": True,
                    "age": prune_age,
                    "ageUnits": prune_units,
                },
                "advanced": {
                    "tableName": table_name,
                    "dataTableName": data_table_name,
                    "useStoreAndForward": True,
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Read-only commands
# ---------------------------------------------------------------------------

@alarm_journal_app.command("list")
def list_cmd() -> None:
    """List all alarm-journal profiles."""
    settings, client = _get_api()
    try:
        response = client.request("GET", _LIST_PATH)
        typer.echo(json.dumps(response.json() if response.text else [], indent=2))
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
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


@alarm_journal_app.command("get")
def get_cmd(
    name: Annotated[str, typer.Option("--name", help="Alarm journal profile name.")],
) -> None:
    """Get a single alarm-journal profile by name."""
    settings, client = _get_api()
    try:
        response = client.request("GET", f"{_FIND_PATH}/{name}")
        typer.echo(json.dumps(response.json() if response.text else {}, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"alarm journal '{name}' not found."), no_color=False)
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
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Mutating command
# ---------------------------------------------------------------------------

@alarm_journal_app.command("create")
def create_cmd(
    name: Annotated[str, typer.Option("--name", help="Alarm journal profile name.")],
    datasource: Annotated[
        str,
        typer.Option("--datasource", help="Target database connection (datasource) name."),
    ],
    min_priority: Annotated[
        str,
        typer.Option(
            "--min-priority",
            help="Minimum alarm priority to store: Diagnostic/Low/Medium/High/Critical.",
        ),
    ] = "Diagnostic",
    description: Annotated[
        str,
        typer.Option("--description", help="Optional human-readable description."),
    ] = "",
    prune_age: Annotated[
        int,
        typer.Option("--prune-age", help="Prune events older than this many --prune-units."),
    ] = 90,
    prune_units: Annotated[
        str,
        typer.Option("--prune-units", help="Pruning age units (e.g. DAY, WEEK, MONTH)."),
    ] = "DAY",
    table_name: Annotated[
        str,
        typer.Option("--table-name", help="Alarm events table name."),
    ] = "alarm_events",
    data_table_name: Annotated[
        str,
        typer.Option("--data-table-name", help="Alarm event data (associated) table name."),
    ] = "alarm_event_data",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print the array-wrapped payload to stdout; no API call.",
        ),
    ] = False,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Skip the confirmation prompt for the POST."),
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
    """Create an alarm-journal profile (DATASOURCE type).

    The request body is a one-element JSON ARRAY (the resources "(multiple)"
    pattern); a bare object returns 400 "Not a JSON Array".
    """
    # Validate enum BEFORE any HTTP. ValueError → render_error → exit 1.
    if min_priority not in _MIN_PRIORITIES:
        render_error(
            ValueError(
                f"--min-priority must be one of {', '.join(_MIN_PRIORITIES)}; got '{min_priority}'."
            ),
            no_color=False,
        )
        raise typer.Exit(code=1)

    obj = _build_resource_object(
        name=name,
        datasource=datasource,
        min_priority=min_priority,
        description=description,
        prune_age=prune_age,
        prune_units=prune_units,
        table_name=table_name,
        data_table_name=data_table_name,
    )
    # CRITICAL: the resources "(multiple)" endpoint requires a JSON ARRAY.
    payload: list[dict[str, Any]] = [obj]

    if dry_run:
        typer.echo(json.dumps(payload, indent=2))
        return

    # Confirmation gate for the mutating POST in a tty.
    if not confirm and sys.stdin.isatty():
        typer.confirm(f"Create alarm journal '{name}'?", abort=True)

    settings, client = _get_api()
    try:
        response = client.request("POST", _CREATE_PATH, json=payload)
        typer.echo(json.dumps(response.json() if response.text else {}, indent=2))
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
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    _scan_after_mutation(settings, scan)
