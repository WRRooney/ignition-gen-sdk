"""ign event — gateway and Perspective session event scripts.

Kinds are ``gateway.<folder>`` or ``session.<folder>`` (``ign event kinds``).
Each event is ``<function>.py`` + resource.json on disk; settings such as a
timer's delay or a tag-change's paths are resource.json attributes, set with
``--attr key=JSON`` (repeatable) or ``--attrs-file``. A rewrite keeps the
event's existing settings unless overridden. Writes and deletes scan projects.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from ..backends.api_client import AuthMissingError
from ..backends.event_scripts import (
    KINDS,
    EventNotFoundError,
    EventScriptBackend,
    EventScriptError,
)
from ..backends.project_disk import ProjectNotFoundError, ScriptTabError
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ._errors import render_error

event_app = typer.Typer(help="Gateway and session event scripts: kinds, list, write, replace-text, delete.")

Project = Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")]
Kind = Annotated[str, typer.Option("--kind", help="Event kind, e.g. gateway.timer or session.startup (see `ign event kinds`).")]
Name = Annotated[str | None, typer.Option("--name", help="Event name, for named kinds (timer, tag-change, message, ...).")]
DryRun = Annotated[bool, typer.Option("--dry-run/--no-dry-run", help="Validate and print; no filesystem write.")]
Scan = Annotated[bool, typer.Option("--scan/--no-scan", help="POST /data/api/v1/scan/projects afterwards. Default: scan.")]


def _fail(e: Exception) -> None:
    render_error(e, no_color=False)
    raise typer.Exit(code=1) from None


def _settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        _fail(AuthMissingError("check that IGNITION_API_TOKEN is set"))


def _scan(settings: Settings, what: str) -> None:
    try:
        with ScanClient(settings) as client:
            client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed after {what}; the change is on disk. Reason: {e}", err=True)


def _parse_attrs(attr: list[str], attrs_file: Path | None) -> dict:
    out: dict = {}
    if attrs_file:
        out.update(json.loads(attrs_file.read_text(encoding="utf-8")))
    for item in attr:
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise EventScriptError(f"--attr {item!r}: expected key=JSON")
        try:
            out[key] = json.loads(raw)
        except json.JSONDecodeError:
            out[key] = raw  # bare word: a plain string (e.g. cronExpression=0 0 * * *)
    return out


@event_app.command("kinds")
def kinds_cmd() -> None:
    """Print every event kind: folder, function signature, named, settings."""
    for key, k in KINDS.items():
        settings = sorted(set(k.defaults) | set(k.required))
        typer.echo(f"{key:26} {k.function}({', '.join(k.params)})"
                   f"{'  [named]' if k.named else ''}"
                   f"{'  attrs: ' + ', '.join(settings) if settings else ''}")


@event_app.command("list")
def list_cmd(project: Project, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """List the event scripts a project holds on disk (not inherited ones)."""
    try:
        rows = EventScriptBackend(_settings()).list(project)
    except ProjectNotFoundError as e:
        _fail(e)
    if as_json:
        typer.echo(json.dumps([{"kind": k, "name": n, "attributes": a} for k, n, a in rows], indent=2))
        return
    for key, name, attrs in rows:
        typer.echo(f"{key:26} {name or '-':20} {json.dumps(attrs)}")


@event_app.command("write")
def write_cmd(
    project: Project,
    kind: Kind,
    file: Annotated[Path, typer.Option("--file", help="The .py file: must define the kind's function.")],
    name: Name = None,
    attr: Annotated[list[str], typer.Option("--attr", help="Setting key=JSON, repeatable.")] = [],  # noqa: B006
    attrs_file: Annotated[Path | None, typer.Option("--attrs-file", help="JSON object of settings.")] = None,
    enabled: Annotated[bool | None, typer.Option("--enabled/--disabled", help="Default: keep, or enabled.")] = None,
    dry_run: DryRun = False,
    scan: Scan = True,
) -> None:
    """Write <function>.py + resource.json for one event script."""
    try:
        code = file.read_text(encoding="utf-8")
        attrs = _parse_attrs(attr, attrs_file)
        settings = _settings()
        backend = EventScriptBackend(settings)
        if dry_run:
            dest, resource = backend.plan(project, kind, name, code, attrs, enabled)
            typer.echo(f"=== {KINDS[kind].function}.py ===\n{code}\n=== resource.json ===")
            typer.echo(json.dumps(resource, indent=2))
            typer.echo(f"=== target ===\n{dest}")
            return
        dest = backend.write(project, kind, name, code, attrs, enabled)
    except SyntaxError as e:
        _fail(ValueError(f"syntax error in --file: {e}"))
    except (OSError, ValueError, ScriptTabError) as e:  # EventScriptError/ProjectNotFoundError are ValueErrors
        _fail(e)
    typer.echo(f"Written: {dest}")
    if scan:
        _scan(settings, f"writing {kind}")


@event_app.command("replace-text")
def replace_text_cmd(
    project: Project,
    kind: Kind,
    old: Annotated[str, typer.Option("--old", help="Exact literal text (not a regex).")],
    new: Annotated[str, typer.Option("--new", help="Replacement text.")],
    name: Name = None,
    expect: Annotated[int | None, typer.Option("--expect", help="Require exactly this many matches.")] = None,
    dry_run: DryRun = False,
    scan: Scan = True,
) -> None:
    """Replace exact text in an existing event script; settings are kept."""
    try:
        settings = _settings()
        backend = EventScriptBackend(settings)
        path = backend.code_path(project, kind, name)
        code = path.read_text(encoding="utf-8")
        found = code.count(old) if old else 0
        if found == 0 or (expect is not None and found != expect):
            raise EventScriptError(f"--old occurs {found} time(s) in {path.name}"
                                   + (f", --expect said {expect}" if expect is not None else ""))
        if dry_run:
            backend.plan(project, kind, name, code.replace(old, new))
            typer.echo(f"Would replace {found} occurrence(s) in {path}")
            return
        backend.write(project, kind, name, code.replace(old, new))
    except SyntaxError as e:
        _fail(ValueError(f"replacement produced a syntax error: {e}"))
    except (EventNotFoundError, ValueError, ScriptTabError) as e:
        _fail(e)
    typer.echo(f"Replaced {found} occurrence(s): {path}")
    if scan:
        _scan(settings, f"editing {kind}")


@event_app.command("delete")
def delete_cmd(project: Project, kind: Kind, name: Name = None, dry_run: DryRun = False, scan: Scan = True) -> None:
    """Delete one event script directory."""
    try:
        settings = _settings()
        backend = EventScriptBackend(settings)
        if dry_run:
            typer.echo(f"Would delete: {backend.code_path(project, kind, name).parent}")
            return
        dest = backend.delete(project, kind, name)
    except (EventNotFoundError, ValueError) as e:
        _fail(e)
    typer.echo(f"Deleted: {dest}")
    if scan:
        _scan(settings, f"deleting {kind}")
