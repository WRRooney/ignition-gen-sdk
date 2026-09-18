"""ign driver — JDBC driver introspection subcommand group.

Two read-only subcommands wrapping ApiBackend's database-driver methods:

- list      — list all installed JDBC drivers (name + enabled flag)
- describe  — describe a single driver (type, classname, defaultTranslator,
              defaultValidationQuery, urlFormat, urlInstructions)

Use case: when authoring a database-connection config, the translator name
(e.g. SQLite -> ``SQLITE``) lives in the driver config. Previously you had
to grep ``config/resources/core/ignition/database-driver/<name>/config.json``
to discover it. This subcommand surfaces the metadata via the CLI.

Patterns mirrored from cmd_provider.py:

- Error taxonomy follows the five-clause order
  (AuthMissingError, AuthScopeError, PayloadError, GatewayError,
  NetworkError, ValueError).
- 404/not-found yields ``Error: driver '<name>' not found.`` not a raw
  httpx traceback.
- ``_get_api()`` helper constructs Settings + ApiBackend with the same
  AuthMissingError fallback as the provider subgroup.

Out of scope: create-driver, delete-driver, jar upload,
datafile management. Read-only only.
"""
from __future__ import annotations

import json
from typing import Annotated

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
from ..config import Settings
from ._errors import render_error

# Driver commands always use the API backend.
# --backend flag is not applicable here -- driver resources are
# introspected via the gateway, not authored on disk.

driver_app = typer.Typer(
    name="driver",
    help="Database driver introspection: list, describe.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Module-level helpers (mirror cmd_provider.py)
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


def _is_not_found(exc: PayloadError) -> bool:
    """Return True if the PayloadError looks like a 404 / not-found."""
    msg = str(exc).lower()
    return "not found" in msg or "404" in msg


# ---------------------------------------------------------------------------
# Read-only commands
# ---------------------------------------------------------------------------

@driver_app.command("list")
def list_cmd() -> None:
    """List all installed JDBC drivers (name + enabled)."""
    _settings, api = _get_api()
    try:
        result = api.list_drivers()
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


@driver_app.command("describe")
def describe_cmd(
    name: Annotated[str, typer.Argument(help="Driver name (e.g. SQLite, MySQL, 'Oracle Database').")],
) -> None:
    """Describe a single JDBC driver (translator, urlFormat, classname...)."""
    _settings, api = _get_api()
    try:
        result = api.get_driver(name)
        typer.echo(json.dumps(result, indent=2))
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        if _is_not_found(e):
            render_error(PayloadError(f"driver '{name}' not found."), no_color=False)
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
