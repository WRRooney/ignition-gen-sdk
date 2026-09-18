"""ign stylesheet — project Perspective stylesheet CLI subcommand.

Style CLASSES (``ProjectDiskBackend.write_style_class``) cover component-level
styling, but some Perspective chrome renders in a PORTAL outside the component
subtree — dropdown option overlays (``.ia_dropdown__optionsModal``), popup
frames, scrollbars. Those are only reachable from the project stylesheet, so
this verb exists; without it the only route was hand-editing stylesheet.css,
which the disk-write ban forbids.

Writes are BLOCK-SCOPED: each upsert owns a ``/* >>> ign:<marker> */`` …
``/* <<< ign:<marker> */`` region and rewrites only that region, so
hand-authored CSS (the Designer stylesheet is user territory) survives
untouched. Re-running the same marker is idempotent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..backends.api_client import AuthMissingError
from ..backends.project_disk import ProjectDiskBackend, ProjectNotFoundError
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ._errors import render_error

stylesheet_app = typer.Typer(help="Perspective project stylesheet: upsert/show ign CSS blocks.")


def _settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None


@stylesheet_app.command("show")
def show_cmd(
    project: Annotated[
        str, typer.Option("--project", help="Project name (REQUIRED — must already exist).")
    ],
) -> None:
    """Print ``--project``'s stylesheet.css (read-only)."""
    settings = _settings()
    try:
        css = ProjectDiskBackend(settings).read_stylesheet(project)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    if not css:
        typer.echo(f"No stylesheet in {project!r} yet.")
        return
    typer.echo(css)


@stylesheet_app.command("upsert")
def upsert_cmd(
    project: Annotated[
        str, typer.Option("--project", help="Project name (REQUIRED — must already exist).")
    ],
    marker: Annotated[
        str,
        typer.Option(
            "--marker",
            help="Block name this write owns, e.g. 'nav-menu'. Re-running the same "
            "marker replaces ONLY that block; other CSS is preserved.",
        ),
    ],
    file: Annotated[
        Path, typer.Option("--file", help="Path to a .css file holding the block's rules.")
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print the block + target; no write.")
    ] = False,
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="After write, POST /scan/projects (best-effort)."),
    ] = True,
) -> None:
    """Upsert an ign-owned CSS block into ``--project``'s stylesheet.

    Writes projects/<project>/com.inductiveautomation.perspective/stylesheet/.
    """
    try:
        css = file.read_text(encoding="utf-8")
    except OSError as e:
        render_error(ValueError(f"--file could not be read: {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    if not css.strip():
        render_error(ValueError("--file is empty; nothing to upsert."), no_color=False)
        raise typer.Exit(code=1)

    if dry_run:
        typer.echo(f"=== stylesheet block 'ign:{marker}' ===")
        typer.echo(f"/* >>> ign:{marker} */\n{css.strip()}\n/* <<< ign:{marker} */")
        typer.echo("=== target ===")
        typer.echo(f"projects/{project}/com.inductiveautomation.perspective/stylesheet/")
        return

    settings = _settings()
    try:
        dest = ProjectDiskBackend(settings).write_stylesheet_block(project, marker, css)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"stylesheet write failed - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Upserted block 'ign:{marker}' in {project}")
    typer.echo(f"Written: {dest}/stylesheet.css")
    typer.echo(f"Written: {dest}/resource.json")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed; the change is on disk but the gateway "
            f"may not see it until the next scan tick. Reason: {e}",
            err=True,
        )


@stylesheet_app.command("remove")
def remove_cmd(
    project: Annotated[
        str, typer.Option("--project", help="Project name (REQUIRED — must already exist).")
    ],
    marker: Annotated[
        str, typer.Option("--marker", help="Block name to delete, e.g. 'nav'.")
    ],
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="After write, POST /scan/projects (best-effort)."),
    ] = True,
) -> None:
    """Delete one ign-owned CSS block from ``--project``'s stylesheet.

    The inverse of ``upsert``, and how a marker gets RENAMED: upsert the block
    under its new name, then remove the old one. An upsert cannot do it — empty
    content is refused, and would leave an empty block behind regardless.
    Hand-authored CSS around the block is preserved.
    """
    settings = _settings()
    try:
        removed = ProjectDiskBackend(settings).remove_stylesheet_block(project, marker)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"stylesheet remove failed - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if not removed:
        typer.echo(f"No block 'ign:{marker}' in {project}; nothing to remove.")
        return
    typer.echo(f"Removed block 'ign:{marker}' from {project}")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed; the change is on disk but the gateway "
            f"may not see it until the next scan tick. Reason: {e}",
            err=True,
        )
