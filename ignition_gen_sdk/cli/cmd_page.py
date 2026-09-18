"""ign page — Perspective page-config CLI subcommand.

`page mount` maps a URL to a project view (the only way to give a Perspective
project a navigable entry URL — without a page-config the client shows "No view
configured for this page"). Sanctioned ign path; never hand-write page-config
(disk-write ban).

Mounting is incremental: existing pages are preserved (read -> add/replace ->
write). Mirrors cmd_script.py (Settings placement, error contract, best-effort
scan, dry-run).
"""
from __future__ import annotations

import json as _json
from typing import Annotated, Optional

import typer

from ..backends.api_client import AuthMissingError
from ..backends.project_disk import ProjectDiskBackend, ProjectNotFoundError
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ._errors import render_error

page_app = typer.Typer(help="Perspective page-config: mount + list pages.")


def _settings() -> Settings:
    """Settings, or a rendered auth error + exit (shared by the verbs below)."""
    try:
        return Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None

# Dock defaults per side, matching the shape Designer writes (verified against
# the IA quickstart page-config). Only viewPath/size vary in practice.
_DOCK_SIDES = ("top", "bottom", "left", "right")
_DOCK_DEFAULT_SIZE = {"top": 48, "bottom": 48, "left": 260, "right": 300}


def _parse_dock(spec: str) -> tuple[str, dict]:
    """Parse a ``side:viewPath[:size]`` dock spec into (side, dock entry).

    viewPath may contain '/' but not ':'. Raises ValueError on a bad spec.
    """
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(
            f"--dock {spec!r} must be 'side:viewPath' or 'side:viewPath:size' "
            f"(side one of {', '.join(_DOCK_SIDES)})."
        )
    side, view_path = parts[0].strip().lower(), parts[1].strip()
    if side not in _DOCK_SIDES:
        raise ValueError(f"--dock side {side!r} must be one of {', '.join(_DOCK_SIDES)}.")
    if not view_path:
        raise ValueError(f"--dock {spec!r} has an empty viewPath.")
    size = _DOCK_DEFAULT_SIZE[side]
    if len(parts) == 3:
        try:
            size = int(parts[2])
        except ValueError:
            raise ValueError(f"--dock {spec!r} size must be an integer.") from None
    return side, {
        "anchor": "fixed",
        "autoBreakpoint": 480,
        "content": "push",
        "handle": "hide",
        "iconUrl": "",
        "id": view_path.rsplit("/", 1)[-1].lower().replace(" ", "-"),
        "modal": False,
        "resizable": False,
        "show": "visible",
        "size": size,
        "viewParams": {},
        "viewPath": view_path,
    }


def _docks_from_specs(specs: list[str] | None) -> dict | None:
    """Build the page entry's ``docks`` map from repeated --dock specs."""
    if not specs:
        return None
    docks: dict[str, list] = {}
    for spec in specs:
        side, entry = _parse_dock(spec)
        docks.setdefault(side, []).append(entry)
    return docks


@page_app.command("list")
def list_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project name (REQUIRED — must already exist)."),
    ],
    as_json: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit the page map as JSON (url -> {viewPath,title})."),
    ] = False,
) -> None:
    """List the pages mounted in ``--project``'s Perspective page-config (read-only).

    Reads projects/<project>/com.inductiveautomation.perspective/page-config/.
    Use this to confirm a URL is mounted before rendering it (e.g. with
    ``ign view validate``). No view configured? The client shows "No view
    configured for this page" — mount one with ``ign page mount``.
    """
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None

    try:
        backend = ProjectDiskBackend(settings)
        cfg = backend.read_page_config(project)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    pages = cfg.pages
    if as_json:
        typer.echo(_json.dumps(
            {url: {"viewPath": e.viewPath, "title": e.title} for url, e in pages.items()},
            indent=2,
        ))
        return

    if not pages:
        typer.echo(
            f"No pages mounted in {project!r}. "
            f"Mount one with: ign page mount --project {project} --url / --view-path <viewPath>"
        )
        return

    typer.echo(f"{len(pages)} page(s) mounted in {project!r}:")
    for url in sorted(pages):
        entry = pages[url]
        title = f"  [{entry.title}]" if entry.title else ""
        typer.echo(f"  {url}  ->  {entry.viewPath}{title}")


@page_app.command("mount")
def mount_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project name (REQUIRED — must already exist)."),
    ],
    view_path: Annotated[
        str,
        typer.Option(
            "--view-path",
            help="Project-relative view path to mount, e.g. Pages/Overview.",
        ),
    ],
    url: Annotated[
        str,
        typer.Option("--url", help="Page URL to mount at (e.g. / or /pid)."),
    ] = "/",
    title: Annotated[
        Optional[str],
        typer.Option("--title", help="Optional page title."),
    ] = None,
    dock: Annotated[
        Optional[list[str]],
        typer.Option(
            "--dock",
            help="Docked view: 'side:viewPath[:size]' (side=top|bottom|left|right; "
            "size defaults 48 top/bottom, 260 left, 300 right). Repeatable. "
            "Omit to KEEP the page's existing docks; pass --no-docks to clear.",
        ),
    ] = None,
    no_docks: Annotated[
        bool,
        typer.Option("--no-docks", help="Remove all docks from this page."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print payload + target; no write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help="After write, POST /data/api/v1/scan/projects (best-effort). Default: scan.",
        ),
    ] = True,
) -> None:
    """Mount ``--view-path`` at ``--url`` in ``--project``'s Perspective page-config.

    Preserves any existing pages (incremental). Writes
    projects/<project>/com.inductiveautomation.perspective/page-config/.
    """
    if not url or not url.strip():
        render_error(ValueError("--url must not be empty."), no_color=False)
        raise typer.Exit(code=1)
    if not view_path or not view_path.strip():
        render_error(ValueError("--view-path must not be empty."), no_color=False)
        raise typer.Exit(code=1)
    if no_docks and dock:
        render_error(ValueError("--no-docks cannot be combined with --dock."), no_color=False)
        raise typer.Exit(code=1)
    try:
        docks = {} if no_docks else _docks_from_specs(dock)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    if dry_run:
        from ..models.page_config import PageConfig

        cfg = PageConfig().with_page(url, view_path, title, docks=docks)
        import json as _json

        from ..serializers.resource_metadata import page_config_resource_json

        typer.echo("=== page-config/config.json (NEW page only; existing preserved on real run) ===")
        typer.echo(_json.dumps(cfg.config_json(), indent=2))
        # A real write emits BOTH config.json + resource.json, so a faithful
        # dry-run preview must show the resource.json sidecar too.
        typer.echo("=== page-config/resource.json ===")
        typer.echo(_json.dumps(page_config_resource_json(), indent=2))
        typer.echo("=== target path ===")
        typer.echo(f"projects/{project}/com.inductiveautomation.perspective/page-config/")
        return

    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None

    # Project resources register on a project scan (no reload gate).
    try:
        backend = ProjectDiskBackend(settings)
        existing = backend.read_page_config(project)
        merged = existing.with_page(url, view_path, title, docks=docks)
        dest = backend.write_page_config(project, merged)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"page-config write failed - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Mounted {url!r} -> {view_path!r} in {project}")
    typer.echo(f"Written: {dest}/config.json")
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
        return


@page_app.command("shared-dock")
def shared_dock_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project name (REQUIRED — must already exist)."),
    ],
    dock: Annotated[
        Optional[list[str]],
        typer.Option(
            "--dock",
            help="Shared docked view: 'side:viewPath[:size]' (side=top|bottom|left|right). "
            "Repeatable; repeating a side stacks entries on it. Replaces only the "
            "sides named — the others survive.",
        ),
    ] = None,
    remove: Annotated[
        Optional[list[str]],
        typer.Option("--remove", help="Remove the shared dock on this side. Repeatable."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print the resulting sharedDocks; no write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="After write, POST /scan/projects (best-effort)."),
    ] = True,
) -> None:
    """Set or remove ``--project``'s SHARED docks (chrome every page inherits).

    Per-page docks come from ``page mount --dock``; this verb writes the
    ``sharedDocks`` map instead, which is where a project-wide header/footer
    lives. Pages and the sides you do not name are preserved.

    Only ONE dock per side is ever laid out by the client — a second entry on
    the same side mounts hidden — so stacked chrome belongs in ROWS inside one
    docked view, not in two docks.
    """
    if not dock and not remove:
        render_error(ValueError("pass --dock and/or --remove."), no_color=False)
        raise typer.Exit(code=1)
    for side in remove or []:
        if side.strip().lower() not in _DOCK_SIDES:
            render_error(
                ValueError(f"--remove {side!r} must be one of {', '.join(_DOCK_SIDES)}."),
                no_color=False,
            )
            raise typer.Exit(code=1)
    try:
        docks = _docks_from_specs(dock) or {}
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    settings = _settings()
    try:
        backend = ProjectDiskBackend(settings)
        cfg = backend.read_page_config(project)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    merged = cfg.with_shared_docks(docks)
    for side in remove or []:
        merged = merged.without_shared_dock(side.strip().lower())

    if dry_run:
        typer.echo("=== sharedDocks (result) ===")
        typer.echo(_json.dumps(merged.config_json()["sharedDocks"], indent=2))
        typer.echo("=== target path ===")
        typer.echo(f"projects/{project}/com.inductiveautomation.perspective/page-config/")
        return

    try:
        dest = backend.write_page_config(project, merged)
    except ValueError as e:
        render_error(ValueError(f"page-config write failed - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    sides = sorted(s for s in merged.sharedDocks if s in _DOCK_SIDES)
    typer.echo(f"Shared docks in {project}: {', '.join(sides) or '(none)'}")
    typer.echo(f"Written: {dest}/config.json")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed ({e})", err=True)


@page_app.command("delete")
def delete_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project whose page-config resource to remove."),
    ],
    confirm: Annotated[
        bool,
        typer.Option("--confirm/--no-confirm", help="Required: removes ALL of the project's pages."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print what would be removed; no write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="After write, POST /scan/projects (best-effort)."),
    ] = True,
) -> None:
    """Delete ``--project``'s ENTIRE page-config so it INHERITS its parent's.

    Perspective resolves page-config per RESOURCE, not per URL: a child project
    holding any page-config overrides the parent's completely. Removing the
    child's resource is how routes defined once in an inheritable template
    reach every child project.

    Requires --confirm; use ``page unmount`` to remove a single URL instead.
    """
    settings = _settings()
    backend = ProjectDiskBackend(settings)

    try:
        cfg = backend.read_page_config(project)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    if dry_run:
        typer.echo(
            f"Would remove the page-config of {project!r}, dropping {len(cfg.pages)} page(s):"
        )
        for url in sorted(cfg.pages):
            typer.echo(f"  {url}  ->  {cfg.pages[url].viewPath}")
        typer.echo(f"projects/{project}/com.inductiveautomation.perspective/page-config/")
        return

    if not confirm:
        render_error(
            ValueError(
                f"refusing to delete {len(cfg.pages)} page(s) from {project!r} without "
                f"--confirm (use --dry-run to preview, or 'page unmount' for one URL)."
            ),
            no_color=False,
        )
        raise typer.Exit(code=1)

    try:
        dest = backend.delete_page_config(project)
    except FileNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Deleted page-config of {project!r}; it now inherits its parent's routes.")
    typer.echo(f"Removed: {dest}")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed ({e})", err=True)


@page_app.command("unmount")
def unmount_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project name (REQUIRED — must already exist)."),
    ],
    url: Annotated[
        str,
        typer.Option("--url", help="Page URL to unmount (e.g. /pid)."),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print the page that would be removed; no write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help="After write, POST /data/api/v1/scan/projects (best-effort). Default: scan.",
        ),
    ] = True,
) -> None:
    """Remove the ``--url`` mapping from ``--project``'s page-config.

    Inverse of ``page mount`` (incremental: other pages preserved). Errors if
    the URL is not mounted.
    """
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None

    try:
        backend = ProjectDiskBackend(settings)
        existing = backend.read_page_config(project)
        entry = existing.pages.get(url)
        if entry is None:
            render_error(
                ValueError(
                    f"--url {url!r} is not mounted in {project!r}. "
                    f"Mounted: {sorted(existing.pages) or '(none)'}"
                ),
                no_color=False,
            )
            raise typer.Exit(code=1)
        if dry_run:
            typer.echo(f"Would unmount {url!r} -> {entry.viewPath!r} from {project}")
            return
        dest = backend.write_page_config(project, existing.without_page(url))
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Unmounted {url!r} (was -> {entry.viewPath!r}) from {project}")
    typer.echo(f"Written: {dest}/config.json")

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
        return
