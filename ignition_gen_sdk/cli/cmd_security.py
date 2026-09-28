"""``ign security`` — gateway security properties (who may access, read, write, design).

The resource is a singleton whose ``config`` carries five permission sets
(``accessPermissions``, ``readPermissions``, ``writePermissions``,
``designerPermissions``, ``createProjectPermissions``) and the auth settings.
``set-permissions`` does the get, patch, put cycle for one set; ``update`` PUTs a
whole config file. Both need the current signature, fetched for you.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from pydantic import ValidationError

from ..backends.api_client import IgnitionAPIError
from ..models.security import PermissionSet
from ..models.security_properties import PERMISSION_KEYS, SecurityProperties
from ._errors import render_error
from .cmd_provider import _get_api

security_app = typer.Typer(no_args_is_help=True, help="Gateway security properties: get, update, set-permissions.")


def _fetch(api) -> tuple[str, dict]:  # noqa: ANN001
    env = api.get_security_properties()
    return env.get("signature", ""), env.get("config", {})


@security_app.command("get")
def get_cmd(
    key: Annotated[Optional[str], typer.Option("--key", help="Print only this config key, e.g. writePermissions.")] = None,
    paths: Annotated[bool, typer.Option("--paths/--no-paths", help="Print permission sets as slash paths instead of trees.")] = False,
) -> None:
    """Print the gateway security properties config."""
    _, api = _get_api()
    try:
        _, config = _fetch(api)
    except IgnitionAPIError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    if paths:
        for k in PERMISSION_KEYS:
            if k in config:
                ps = PermissionSet.model_validate(config[k])
                config[k] = {"type": ps.type, "paths": ps.paths()}
    if key:
        if key not in config:
            typer.echo(f"Error: no config key {key!r}; have {sorted(config)}", err=True)
            raise typer.Exit(code=1)
        typer.echo(json.dumps(config[key], indent=2))
        return
    typer.echo(json.dumps(config, indent=2))


@security_app.command("set-permissions")
def set_permissions_cmd(
    key: Annotated[str, typer.Option("--key", help="One of: " + ", ".join(PERMISSION_KEYS))],
    any_of: Annotated[Optional[list[str]], typer.Option("--any-of", help="Security level path to grant (repeatable), e.g. Authenticated/Roles/Operator.")] = None,
    all_of: Annotated[Optional[list[str]], typer.Option("--all-of", help="Like --any-of but every path is required.")] = None,
    open_to_all: Annotated[bool, typer.Option("--open", help="Grant everyone (empty security levels).")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run", help="Print the new set; no PUT.")] = False,
) -> None:
    """Replace one permission set (get, patch, put)."""
    if key not in PERMISSION_KEYS:
        typer.echo(f"Error: --key must be one of {', '.join(PERMISSION_KEYS)}", err=True)
        raise typer.Exit(code=1)
    chosen = [bool(any_of), bool(all_of), open_to_all]
    if sum(chosen) != 1:
        typer.echo("Error: give exactly one of --any-of (repeatable), --all-of (repeatable), or --open.", err=True)
        raise typer.Exit(code=1)
    if open_to_all:
        new = PermissionSet.everyone()
    elif any_of:
        new = PermissionSet.any_of(*any_of)
    else:
        new = PermissionSet.all_of(*all_of)  # type: ignore[misc]
    _, api = _get_api()
    try:
        signature, config = _fetch(api)
        before = config.get(key)
        config[key] = new.emit()
        SecurityProperties.model_validate(config)
        if dry_run:
            typer.echo(json.dumps({key: config[key], "was": before}, indent=2))
            return
        api.update_security_properties(signature, config)
    except (IgnitionAPIError, ValueError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo(f"Updated {key}: {new.type} {new.paths() or '(everyone)'}")


@security_app.command("update")
def update_cmd(
    file: Annotated[Path, typer.Option("--file", help="JSON file with the full config object (as printed by `ign security get`).")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run", help="Validate and print; no PUT.")] = False,
) -> None:
    """PUT a whole security-properties config from a file."""
    try:
        config = json.loads(file.read_text(encoding="utf-8"))
        SecurityProperties.model_validate(config)
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"could not read {file}: {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    except ValidationError as e:
        render_error(ValueError(f"{file} is not a valid security-properties config: {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    if dry_run:
        typer.echo(json.dumps(config, indent=2))
        return
    _, api = _get_api()
    try:
        signature, _ = _fetch(api)
        api.update_security_properties(signature, config)
    except (IgnitionAPIError, ValueError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo("Updated security properties.")
