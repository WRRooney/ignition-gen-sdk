"""ign session-props — Perspective session-props CLI subcommand.

`session-props declare` merges custom SESSION property declarations (name ->
default) into a project's session-props resource. Custom session props are
cross-view shared state accessed via self.session.custom.<path> in component
scripts — they must be DECLARED here (not created at runtime; the old
system.perspective.setSessionProperty does not exist in 8.3).

Sanctioned ign path; never hand-write session-props (disk-write ban).
Incremental: existing custom props are preserved (read -> merge -> write).
Mirrors cmd_page.py.
"""
from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..backends.api_client import AuthMissingError
from ..backends.project_disk import ProjectDiskBackend, ProjectNotFoundError
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ._errors import render_error

session_props_app = typer.Typer(
    help="Perspective session-props: declare, undeclare, or delete custom session properties.")


def _deep_merge(base: dict, incoming: dict) -> dict:
    """Merge ``incoming`` into ``base`` RECURSIVELY, returning a new dict.

    Session custom props are a TREE (`session.custom.nav.rootPath`), so a
    shallow ``dict.update`` silently destroys siblings: declaring
    ``{"nav": {"layout": "auto"}}`` used to replace the whole ``nav`` object
    and take ``rootPath``/``title``/``kpis`` with it. Declaring is additive by
    contract, so a nested declaration must add a LEAF, not swap a branch.
    A non-dict on either side is a leaf: ``incoming`` wins, which is how a
    default is re-declared.
    """
    out = dict(base)
    for key, value in incoming.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = _deep_merge(current, value)
        else:
            out[key] = value
    return out


@session_props_app.command("declare")
def declare_cmd(
    project: Annotated[
        str, typer.Option("--project", help="Project name (REQUIRED — must already exist).")
    ],
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file",
            help="JSON object of custom session props to declare (name -> default), "
            "e.g. {\"nav\": {\"selectedView\": \"\"}}. Merged into existing custom props.",
        ),
    ] = None,
    prop_config: Annotated[
        Optional[Path],
        typer.Option(
            "--prop-config",
            help="JSON object of propConfig entries (prop path -> entry), e.g. "
            "{\"props.theme\": {\"binding\": {...}}, \"custom.user.id\": "
            "{\"onChange\": {\"enabled\": true, \"script\": \"...\"}}}. Merged by "
            "prop path. This is the only way to put a BINDING or an onChange on a "
            "session property, built-in ones (props.theme) included.",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print payload + target; no write.")
    ] = False,
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="After write, POST /scan/projects (best-effort). Default: scan."),
    ] = True,
) -> None:
    """Declare custom session properties (merged) in <project>'s session-props resource.

    Writes projects/<project>/com.inductiveautomation.perspective/session-props/.
    """
    if file is None and prop_config is None:
        render_error(
            ValueError("pass --file, --prop-config, or both; nothing to declare."),
            no_color=False,
        )
        raise typer.Exit(code=1)

    def _read(option: str, path: Path) -> dict:
        try:
            payload = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            render_error(ValueError(f"{option} could not be read as JSON: {e}"), no_color=False)
            raise typer.Exit(code=1) from None
        if not isinstance(payload, dict):
            render_error(ValueError(f"{option} must be a JSON object."), no_color=False)
            raise typer.Exit(code=1)
        return payload

    custom = _read("--file", file) if file is not None else {}
    configs = _read("--prop-config", prop_config) if prop_config is not None else {}

    if dry_run:
        from ..models.session_props import SessionProps

        sp = SessionProps(custom=custom, propConfig=configs)
        from ..serializers.resource_metadata import session_props_resource_json

        typer.echo("=== session-props/props.json (NEW custom only; existing merged on real run) ===")
        typer.echo(_json.dumps(sp.props_json(), indent=2))
        # A real write emits BOTH props.json + resource.json, so a faithful
        # dry-run preview must show the resource.json sidecar too.
        typer.echo("=== session-props/resource.json ===")
        typer.echo(_json.dumps(session_props_resource_json(), indent=2))
        typer.echo("=== target ===")
        typer.echo(f"projects/{project}/com.inductiveautomation.perspective/session-props/")
        return

    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError("check that IGNITION_API_TOKEN is set"), no_color=False)
        raise typer.Exit(code=1) from None

    # Project resources register on a project scan (no reload gate).
    try:
        backend = ProjectDiskBackend(settings)
        sp = backend.read_session_props(project)
        sp.custom = _deep_merge(sp.custom, custom)
        mergedConfig = dict(sp.propConfig)
        mergedConfig.update(configs)
        sp.propConfig = mergedConfig
        dest = backend.write_session_props(project, sp)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"session-props write failed - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if custom:
        typer.echo(f"Declared custom session props in {project}: {sorted(custom)}")
    if configs:
        typer.echo(f"Declared session propConfig in {project}: {sorted(configs)}")
    typer.echo(f"Written: {dest}/props.json")
    typer.echo(f"Written: {dest}/resource.json")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed; change is on disk. Reason: {e}", err=True)
        return


@session_props_app.command("undeclare")
def undeclare_cmd(
    project: Annotated[
        str, typer.Option("--project", help="Project name (REQUIRED — must already exist).")
    ],
    name: Annotated[
        list[str],
        typer.Option("--name", help="Top-level custom session prop to remove. Repeatable."),
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print what would go; no write.")
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After write, POST /scan/projects."),
    ] = True,
) -> None:
    """Remove custom session properties AND their bindings from <project>.

    The propConfig entries under each removed prop go with it. That is the
    point of the verb: a custom session prop can carry a BINDING, and a session
    binding polls in every open session for as long as the project exists,
    whether or not anything is looking at the value. Dropping the prop without
    its propConfig would leave the binding declared and running.
    """
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError("check that IGNITION_API_TOKEN is set"), no_color=False)
        raise typer.Exit(code=1) from None

    try:
        backend = ProjectDiskBackend(settings)
        sp = backend.read_session_props(project)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    missing = [n for n in name if n not in sp.custom]
    if missing:
        render_error(
            ValueError(
                f"{project!r} declares no custom session prop(s) {sorted(missing)!r}; "
                f"it has {sorted(sp.custom)!r}."
            ),
            no_color=False,
        )
        raise typer.Exit(code=1)

    dropped_config = sorted(
        key for key in sp.propConfig
        if any(key == f"custom.{n}" or key.startswith(f"custom.{n}.") for n in name)
    )
    if dry_run:
        typer.echo(f"Would remove custom prop(s): {sorted(name)}")
        typer.echo(f"Would remove propConfig entries: {dropped_config or 'none'}")
        typer.echo(f"Would keep custom prop(s): {sorted(set(sp.custom) - set(name))}")
        return

    sp.custom = {k: v for k, v in sp.custom.items() if k not in name}
    sp.propConfig = {k: v for k, v in sp.propConfig.items() if k not in dropped_config}
    try:
        dest = backend.write_session_props(project, sp)
    except ValueError as e:
        render_error(ValueError(f"session-props write failed - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Removed custom session props from {project}: {sorted(name)}")
    if dropped_config:
        typer.echo(f"Removed propConfig entries: {dropped_config}")
    typer.echo(f"Written: {dest}/props.json")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed; change is on disk. Reason: {e}", err=True)


@session_props_app.command("delete")
def delete_cmd(
    project: Annotated[
        str, typer.Option("--project", help="Project name (REQUIRED).")
    ],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Required: removes the WHOLE session-props resource."),
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After write, POST /scan/projects."),
    ] = True,
) -> None:
    """Delete <project>'s ENTIRE session-props so it INHERITS its parent's.

    Session-props inherit per RESOURCE, not per property: a child holding any
    session-props of its own overrides the parent's completely, so a prop
    declared only on the parent never reaches the child. Removing the child's
    resource is the only way back to inheriting.
    """
    if not confirm:
        render_error(
            ValueError(
                "--confirm is required: this removes the project's whole "
                "session-props resource, not one property. Use "
                "'session-props undeclare --name X' to drop a single prop."
            ),
            no_color=False,
        )
        raise typer.Exit(code=1)
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError("check that IGNITION_API_TOKEN is set"), no_color=False)
        raise typer.Exit(code=1) from None

    try:
        backend = ProjectDiskBackend(settings)
        dest = backend.delete_session_props(project)
    except (ProjectNotFoundError, FileNotFoundError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Deleted session-props from {project}; it now inherits its parent's.")
    typer.echo(f"Removed: {dest}")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed; change is on disk. Reason: {e}", err=True)
