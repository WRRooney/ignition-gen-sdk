"""ign style-class — Perspective style-class CLI subcommand.

Style classes are written by the committed generators
(ProjectDiskBackend.write_style_class); what was missing was a way to LIST and
REMOVE them. A generated class goes stale as soon as the generator stops
emitting it, and a stale class keeps applying to anything that still names it,
so pruning needs a sanctioned path rather than a hand-deletion.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..backends.api_client import AuthMissingError
from ..backends.project_disk import ProjectDiskBackend, ProjectNotFoundError
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ._errors import render_error

style_class_app = typer.Typer(help="Perspective style classes: write, list + delete.")


def _settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None


def _root(project: str):
    settings = _settings()
    backend = ProjectDiskBackend(settings)
    try:
        views_root = backend._project_views_root(project)  # project-exists guard
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    return settings, backend, views_root.parent / "style-classes"


@style_class_app.command("list")
def list_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
) -> None:
    """List the style classes defined in ``--project`` (read-only)."""
    _settings_, _backend, root = _root(project)
    if not root.is_dir():
        typer.echo(f"No style classes in {project!r}.")
        return
    names = sorted(p.name for p in root.iterdir() if (p / "style.json").is_file())
    typer.echo(f"{len(names)} style class(es) in {project!r}:")
    for n in names:
        typer.echo(f"  {n}")


@style_class_app.command("write")
def write_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
    file: Annotated[
        Path,
        typer.Option(
            "--file",
            help="JSON file: either ONE style-class payload {base, variants} (used "
            "with --name) or an OBJECT mapping class name -> payload (bulk write, "
            "--name omitted).",
        ),
    ],
    name: Annotated[
        Optional[str],
        typer.Option(
            "--name",
            help="Style class name for a single-payload --file. Omit when --file "
            "is a name -> payload mapping.",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print targets; no write.")
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After write, POST /scan/projects.")
    ] = True,
) -> None:
    """Write style-classes/<name>/{style.json, resource.json} into ``--project``.

    ``style.json`` carries only ``base`` and ``variants``; any other top-level
    key is a typo and fails loud. Bulk mode exists because a UI family is
    written as a set — one call keeps them consistent and triggers one scan.
    """
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except OSError as e:
        render_error(ValueError(f"--file could not be read: {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"--file is not valid JSON: {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if not isinstance(payload, dict):
        render_error(ValueError("--file must contain a JSON object."), no_color=False)
        raise typer.Exit(code=1)

    if name:
        classes = {name: payload}
    else:
        # Bulk mode. Distinguish it from a single payload written without
        # --name, which would otherwise be silently treated as N classes
        # called "base" and "variants".
        if {"base", "variants"} & set(payload):
            render_error(
                ValueError(
                    "--file looks like a SINGLE style-class payload (it has "
                    "'base'/'variants' at the top level) but --name was not given."
                ),
                no_color=False,
            )
            raise typer.Exit(code=1)
        classes = payload

    if not classes:
        render_error(ValueError("--file declares no style classes."), no_color=False)
        raise typer.Exit(code=1)

    settings, backend, root = _root(project)
    if dry_run:
        for cls_name, style in sorted(classes.items()):
            typer.echo(f"=== {cls_name} ===")
            typer.echo(json.dumps(style, indent=2))
            typer.echo(f"--> {root / cls_name}/style.json")
        return

    written = []
    for cls_name, style in sorted(classes.items()):
        try:
            written.append(backend.write_style_class(project, cls_name, style))
        except ValueError as e:
            render_error(ValueError(f"style class {cls_name!r}: {e}"), no_color=False)
            raise typer.Exit(code=1) from None
    for dest in written:
        typer.echo(f"Written: {dest}/style.json")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed ({e})", err=True)


@style_class_app.command("delete")
def delete_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
    name: Annotated[str, typer.Option("--name", help="Style class to remove.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print the target; no write.")
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After write, POST /scan/projects.")
    ] = True,
) -> None:
    """Delete style class ``--name`` from ``--project``."""
    settings, backend, root = _root(project)
    if dry_run:
        typer.echo(f"Would remove: {root / name}")
        return
    try:
        dest = backend.delete_style_class(project, name)
    except (FileNotFoundError, ValueError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Deleted style class {name!r} from {project}")
    typer.echo(f"Removed: {dest}")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed ({e})", err=True)
