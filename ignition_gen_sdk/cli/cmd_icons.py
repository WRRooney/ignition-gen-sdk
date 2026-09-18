"""``ign icons`` — the glyph names ``ia.display.icon`` can actually render.

In 8.3 the sprites live inside the Perspective module jar, not on disk. A name
missing from the sprite renders nothing and logs a React error, so validate
icon paths against this list.
"""
from __future__ import annotations

import json
from typing import Annotated, Optional

import typer

icons_app = typer.Typer(no_args_is_help=True, help="Perspective icon sprites: list.")


@icons_app.command("list")
def list_cmd(
    modl: Annotated[Optional[str], typer.Option("--modl", help="Path to Perspective-module.modl.")] = None,
    container: Annotated[Optional[str], typer.Option("--container", help="Docker container to `docker cp` the module from.")] = None,
    icon_set: Annotated[str, typer.Option("--set", help="Sprite set to print, or 'all' for a count per set.")] = "material",
    as_json: Annotated[bool, typer.Option("--json/--no-json", help="Emit a JSON array instead of one name per line.")] = False,
) -> None:
    """List glyph names in a sprite set (material, ignition, symbol_*)."""
    from ..validation.extract_icons import icon_sets, read_module  # noqa: PLC0415

    try:
        sets = icon_sets(read_module(modl, container))
    except (ValueError, OSError, SystemExit) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    if icon_set == "all":
        for name in sorted(sets):
            typer.echo(f"{name:<16} {len(sets[name]):4d}")
        return
    if icon_set not in sets:
        typer.echo(f"Error: no set {icon_set!r}; have {sorted(sets)}", err=True)
        raise typer.Exit(code=1)
    names = sets[icon_set]
    typer.echo(json.dumps(names, indent=1) if as_json else "\n".join(names))
