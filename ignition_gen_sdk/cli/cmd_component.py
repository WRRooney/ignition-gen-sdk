"""ign component — component palette listing.

Source-of-truth is _KNOWN_TYPES from the discriminated union. No
separate registry — single source prevents ia.* string drift between models
and CLI output.

Output modes:
- default  — palette-grouped with Rich-colored "# palette" headers on tty
- --flat   — one type per line, no headers (greppable)
- --json   — {palette: [type,...]} JSON (machine-readable)
- --palette N — filter to single palette group

Rich color gated via _should_color() from cli/_errors.py.
"""
from __future__ import annotations

import json
from typing import Annotated, Optional

import typer

from ..models.views.components import _KNOWN_TYPES
from ._errors import _should_color

component_app = typer.Typer(help="Component palette: list.")


def _group_by_palette(types: frozenset[str]) -> dict[str, list[str]]:
    """Group ia.<palette>.<name> strings by palette.

    Splits each type string on '.' and uses index 1 as the palette name.
    Strings with fewer than 3 parts are placed under 'unknown'.
    Returns a dict sorted by palette key; each value list is sorted.
    """
    grouped: dict[str, list[str]] = {}
    for t in types:
        parts = t.split(".")
        palette = parts[1] if len(parts) >= 3 else "unknown"
        grouped.setdefault(palette, []).append(t)
    return {k: sorted(v) for k, v in sorted(grouped.items())}


@component_app.command("list")
def list_cmd(
    flat: Annotated[
        bool,
        typer.Option("--flat", help="One type per line, no headers (greppable)."),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit {palette: [type,...]} JSON."),
    ] = False,
    palette: Annotated[
        Optional[str],
        typer.Option("--palette", help="Filter to a single palette (e.g. display)."),
    ] = None,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Suppress Rich color output."),
    ] = False,
) -> None:
    """List all known ia.* component type strings.

    Default output is grouped by palette with Rich-colored headers on tty.
    Use --flat for grep-friendly one-per-line output (no headers).
    Use --json for machine-readable {palette: [types]} dict.
    Use --palette display to filter to a single palette.
    """
    grouped = _group_by_palette(_KNOWN_TYPES)

    if palette is not None:
        if palette not in grouped:
            typer.echo(
                f"Error: palette '{palette}' not found. "
                f"Available: {', '.join(sorted(grouped.keys()))}",
                err=True,
            )
            raise typer.Exit(code=1)
        grouped = {palette: grouped[palette]}

    if as_json:
        typer.echo(json.dumps(grouped))
        return

    if flat:
        for types in grouped.values():
            for t in types:
                typer.echo(t)
        return

    # Default: palette-grouped with colored headers on tty
    use_color = _should_color(no_color)
    if use_color:
        try:
            from rich.console import Console

            console = Console(highlight=False)
            for pal_name, types in grouped.items():
                console.print(f"[bold cyan]# {pal_name}[/bold cyan]")
                for t in types:
                    console.print(f"  {t}")
            return
        except ImportError:
            pass  # fall through to plain output

    # Plain output (no color or Rich unavailable)
    for pal_name, types in grouped.items():
        typer.echo(f"# {pal_name}")
        for t in types:
            typer.echo(f"  {t}")
