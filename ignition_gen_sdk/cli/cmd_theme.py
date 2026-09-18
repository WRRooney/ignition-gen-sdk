"""ign theme — Perspective theme CRUD.

Themes were the last Perspective resource with no sanctioned writer: they live
in ``config/resources/core/com.inductiveautomation.perspective/themes/<name>/``
and hand-writing under ``config/resources/**`` is banned, so a new theme could
not be created at all.

A theme is thin by convention — ``index.css`` ``@import``s a base theme's
stylesheets and ``variables.css`` overrides the handful of custom properties it
actually means to change — so this verb does no CSS validation. It enforces the
two things that silently break a theme instead:

- the ``entrypoint`` file must exist among the supplied files, otherwise the
  gateway serves a theme that renders nothing;
- ``light`` / ``dark`` cannot be written. ``copy-base`` materializes them into
  ``core`` so their real token names and values can be READ, but the gateway
  ignores every edit to a copied base theme — a write would be a silent no-op.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from ..backends.api_client import (
    AuthMissingError,
    GatewayError,
    IgnitionAPIClient,
    NetworkError,
    PayloadError,
)
from ..backends.disk_backend import DiskBackend
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ._errors import render_error

theme_app = typer.Typer(help="Perspective themes: list, write, copy-base + delete.")

#: Endpoint that materializes the module's base themes into core so they can
#: be read. Documented caveat: edits to the copies are ignored by the gateway.
_COPY_BASE_PATH = "/data/perspective/api/v1/themes/copy-base-themes"


def _backend() -> tuple[Settings, DiskBackend]:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError) as e:
        render_error(
            AuthMissingError(f"check IGNITION_API_TOKEN (env or .env) ({e})"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None
    return settings, DiskBackend(settings)


def _scan(settings: Settings, scan: bool) -> None:
    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_config()
    except ScanWarning as e:
        typer.echo(
            "WARNING: gateway scan failed; the theme is on disk but may not be "
            f"picked up. Reason: {e}",
            err=True,
        )


@theme_app.command("list")
def list_cmd() -> None:
    """List the Perspective themes present in the ``core`` config layer."""
    _settings, backend = _backend()
    names = backend.list_themes()
    if not names:
        typer.echo("No themes in config/resources/core.")
        return
    typer.echo(f"{len(names)} theme(s):")
    for n in names:
        base = " (base copy — edits ignored by the gateway)" if n in DiskBackend.BASE_THEME_NAMES else ""
        typer.echo(f"  {n}{base}")


@theme_app.command("write")
def write_cmd(
    name: Annotated[str, typer.Option("--name", help="Theme name (REQUIRED).")],
    dir: Annotated[
        Path,
        typer.Option(
            "--dir",
            help="Directory holding the theme's CSS files. Every file in it is "
            "written into the theme; config.json and resource.json are generated.",
        ),
    ],
    entrypoint: Annotated[
        str, typer.Option("--entrypoint", help="Theme entrypoint file.")
    ] = "index.css",
    description: Annotated[
        Optional[str], typer.Option("--description", help="resource.json description.")
    ] = None,
    private: Annotated[
        bool, typer.Option("--private/--no-private", help="config.json isPrivate.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print targets; no write.")
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After write, POST /scan/config.")
    ] = True,
) -> None:
    """Write theme ``--name`` from the CSS files in ``--dir``."""
    if not dir.is_dir():
        render_error(ValueError(f"--dir is not a directory: {dir}"), no_color=False)
        raise typer.Exit(code=1)
    try:
        files = {
            p.name: p.read_text(encoding="utf-8")
            for p in sorted(dir.iterdir())
            if p.is_file() and p.name not in ("config.json", "resource.json")
        }
    except OSError as e:
        render_error(ValueError(f"--dir could not be read: {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if not files:
        render_error(ValueError(f"--dir holds no theme files: {dir}"), no_color=False)
        raise typer.Exit(code=1)

    settings, backend = _backend()
    if dry_run:
        typer.echo(f"Theme {name!r} ({len(files)} file(s), entrypoint {entrypoint!r}):")
        for fname in sorted(files):
            typer.echo(f"  {fname}")
        typer.echo(f"--> {backend._theme_path(name)}")
        return

    try:
        dest = backend.write_theme(
            name,
            files,
            entrypoint=entrypoint,
            description=description or "",
            is_private=private,
        )
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Written: {dest}")
    _scan(settings, scan)


@theme_app.command("delete")
def delete_cmd(
    name: Annotated[str, typer.Option("--name", help="Theme to remove.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print the target; no write.")
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After delete, POST /scan/config.")
    ] = True,
) -> None:
    """Delete theme ``--name`` from the ``core`` config layer."""
    settings, backend = _backend()
    try:
        target = backend._theme_path(name)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    if dry_run:
        typer.echo(f"Would remove: {target}")
        return
    try:
        dest = backend.delete_theme(name)
    except (FileNotFoundError, ValueError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo(f"Removed: {dest}")
    _scan(settings, scan)


@theme_app.command("copy-base")
def copy_base_cmd() -> None:
    """Copy the module's base ``light``/``dark`` themes into ``core`` so they
    can be READ.

    The gateway IGNORES every modification to the copies — they are reference
    only. Read them to learn the real token names and values, then put the
    overrides in a theme of your own that ``@import``s them.
    """
    settings, _backend_ = _backend()
    client = IgnitionAPIClient(settings)
    try:
        client.request("POST", _COPY_BASE_PATH)
    except (AuthMissingError, PayloadError, GatewayError, NetworkError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    finally:
        client.close()
    typer.echo(
        "Copied base themes into config/resources/core/"
        "com.inductiveautomation.perspective/themes/{light,dark}."
    )
    typer.echo("READ-ONLY reference: the gateway ignores edits to these copies.")
