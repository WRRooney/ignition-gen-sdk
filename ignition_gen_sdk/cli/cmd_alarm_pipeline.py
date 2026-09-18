"""ign alarm-pipeline — inspect and surgically edit alarm pipelines.

An alarm pipeline is the one gateway resource with no write API and no text
form. That is tolerable for the block graph, which is genuinely a wiring
diagram, but not for the Jython inside it: inline pipeline scripts are
unversioned, unreviewable and only editable through the Designer.

So this verb deliberately does not author pipelines. `show` decodes one, and
`replace-text` swaps whole entries in the file's string pool without touching
the block graph — enough to lift every inline script out into a project library
call, after which the pipeline is wired once and the behaviour lives in git.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from ..backends._fs_utils import _atomic_write_bytes
from ..backends.api_client import AuthMissingError
from ..backends.project_disk import ProjectDiskBackend, ProjectNotFoundError
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ..serializers.alarm_pipeline import AlarmPipeline, AlarmPipelineFormatError
from ._errors import render_error

alarm_pipeline_app = typer.Typer(
    help="Alarm pipelines: show, replace-text (no authoring — see the module docstring).")

_RESOURCE_DIR = "com.inductiveautomation.alarm-notification/alarm-pipelines"


def _now_stamp() -> str:
    """UTC timestamp in the shape every other ign resource.json uses."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False)
        raise typer.Exit(code=1) from None


def _pipeline_dir(project: str) -> Path:
    settings = _settings()
    backend = ProjectDiskBackend(settings)
    try:
        backend._project_views_root(project)  # project-exists guard
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    return settings.ignition_data_root / "projects" / project / _RESOURCE_DIR, settings


def _load(project: str, name: str):
    directory, settings = _pipeline_dir(project)
    path = directory / name / "data.bin"
    if not path.is_file():
        render_error(
            FileNotFoundError(
                "No alarm pipeline %r in %r (looked for %s)." % (name, project, path)),
            no_color=False)
        raise typer.Exit(code=1)
    try:
        return AlarmPipeline.parse(path.read_bytes()), path, settings
    except AlarmPipelineFormatError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None


@alarm_pipeline_app.command("list")
def list_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
) -> None:
    """List the alarm pipelines in ``--project`` (read-only)."""
    directory, _ = _pipeline_dir(project)
    if not directory.is_dir():
        typer.echo("No alarm pipelines in %r." % project)
        return
    names = sorted(p.parent.name for p in directory.glob("*/data.bin"))
    typer.echo("%d alarm pipeline(s) in %r:" % (len(names), project))
    for name in names:
        typer.echo("  %s" % name)


@alarm_pipeline_app.command("show")
def show_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
    name: Annotated[str, typer.Option("--name", help="Pipeline name.")],
    scripts_only: Annotated[
        bool,
        typer.Option("--scripts/--all", help="Show only the Jython bodies, or every "
                     "pooled string."),
    ] = True,
) -> None:
    """Decode a pipeline and print the text it carries.

    Prints the string pool, which is where scripts, expressions and property
    names live. The block graph is not decoded: this verb exists to find and
    verify the TEXT that replace-text can change.
    """
    pipeline, path, _ = _load(project, name)
    typer.echo("%s  (%d pooled strings)" % (path, len(pipeline.strings)))
    if scripts_only:
        found = pipeline.scripts()
        typer.echo("%d script-shaped entr(y/ies):" % len(found))
        for index, text in found:
            typer.echo("\n--- pool[%d] (%d lines) ---" % (index, len(text.splitlines())))
            typer.echo(text)
        return
    for index, text in enumerate(pipeline.strings):
        typer.echo("[%4d] %r" % (index, text))


@alarm_pipeline_app.command("replace-text")
def replace_text_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
    name: Annotated[str, typer.Option("--name", help="Pipeline name.")],
    old_file: Annotated[
        Optional[Path],
        typer.Option("--old-file", help="File holding the EXACT existing entry. Use "
                     "this for multi-line scripts."),
    ] = None,
    new_file: Annotated[
        Optional[Path],
        typer.Option("--new-file", help="File holding the replacement text."),
    ] = None,
    old: Annotated[
        Optional[str], typer.Option("--old", help="Exact existing entry (single line).")
    ] = None,
    new: Annotated[
        Optional[str], typer.Option("--new", help="Replacement text (single line).")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Report the match; no write.")
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After write, POST /scan/projects.")
    ] = True,
) -> None:
    """Replace whole entries in a pipeline's string pool.

    Matching is on the COMPLETE entry, never a substring: a pooled string is
    one whole value, and a substring edit could corrupt an unrelated entry that
    happens to share a prefix. The block graph is never touched — the node
    stream refers to strings by id, so changing their bytes cannot move an edge.

    A trailing newline in --old-file/--new-file is stripped, because pipeline
    script bodies are stored without one.
    """
    def _read(path: Optional[Path], inline: Optional[str], label: str) -> str:
        if path is not None and inline is not None:
            render_error(ValueError("give --%s or --%s-file, not both." % (label, label)),
                         no_color=False)
            raise typer.Exit(code=1)
        if path is not None:
            try:
                # Pipeline scripts carry no trailing newline; an editor's
                # newline would make an otherwise exact match fail.
                return path.read_text(encoding="utf-8").rstrip("\n")
            except OSError as e:
                render_error(ValueError("--%s-file could not be read: %s" % (label, e)),
                             no_color=False)
                raise typer.Exit(code=1) from None
        if inline is None:
            render_error(ValueError("--%s or --%s-file is required." % (label, label)),
                         no_color=False)
            raise typer.Exit(code=1)
        return inline

    old_text = _read(old_file, old, "old")
    new_text = _read(new_file, new, "new")

    if not old_text:
        # Pool index 0 is the empty string in every pipeline on this gateway,
        # so an empty --old matches, reports "Matched 1 pool entry", and
        # rewrites the file with the replacement wedged into that slot.
        render_error(
            ValueError("--old is empty. Every pipeline has an empty string in "
                       "its pool, so this would match and rewrite it."),
            no_color=False)
        raise typer.Exit(code=1)

    pipeline, path, settings = _load(project, name)
    hits = pipeline.find(old_text)
    if not hits:
        near = [i for i, s in enumerate(pipeline.strings)
                if old_text.strip() and old_text.strip()[:40] in s]
        render_error(
            ValueError(
                "No pool entry exactly equals the given text.%s Run "
                "'alarm-pipeline show --all' to see the entries verbatim."
                % ("" if not near else
                   " Entries containing its first 40 characters: %s." % near)),
            no_color=False)
        raise typer.Exit(code=1)

    typer.echo("Matched %d pool entr(y/ies): %s" % (len(hits), hits))
    if dry_run:
        typer.echo("--- would become ---")
        typer.echo(new_text)
        return

    pipeline.replace(old_text, new_text)
    try:
        _atomic_write_bytes(path, pipeline.emit())
    except AlarmPipelineFormatError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo("Written: %s" % path)

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo("WARNING: gateway scan failed; change is on disk. Reason: %s" % e,
                   err=True)


@alarm_pipeline_app.command("copy")
def copy_cmd(
    from_project: Annotated[
        str, typer.Option("--from-project", help="Project to copy from.")],
    to_project: Annotated[
        str, typer.Option("--to-project", help="Project to copy into.")],
    name: Annotated[
        Optional[list[str]],
        typer.Option("--name", help="Pipeline to copy. Repeatable; omit for all."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite/--no-overwrite",
                     help="Replace a pipeline that already exists in the target."),
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After write, POST /scan/projects.")
    ] = True,
) -> None:
    """Copy alarm pipelines between projects, verifying each one parses.

    Both the data.bin and its resource.json move. Each file is parsed before it
    is written: a pipeline that does not decode is a pipeline the gateway will
    not load either, and finding that out here beats finding out when an alarm
    fails to notify.
    """
    source_dir, settings = _pipeline_dir(from_project)
    target_dir, _ = _pipeline_dir(to_project)
    if not source_dir.is_dir():
        render_error(FileNotFoundError("No alarm pipelines in %r." % from_project),
                     no_color=False)
        raise typer.Exit(code=1)

    available = sorted(p.parent.name for p in source_dir.glob("*/data.bin"))
    wanted = list(name) if name else available
    missing = [n for n in wanted if n not in available]
    if missing:
        render_error(
            ValueError("%r has no pipeline(s) %s; it has %s."
                       % (from_project, sorted(missing), available)),
            no_color=False)
        raise typer.Exit(code=1)

    written = []
    for pipeline_name in wanted:
        source = source_dir / pipeline_name
        target = target_dir / pipeline_name
        if target.exists() and not overwrite:
            render_error(
                ValueError("%r already has pipeline %r; pass --overwrite to replace it."
                           % (to_project, pipeline_name)),
                no_color=False)
            raise typer.Exit(code=1)
        raw = (source / "data.bin").read_bytes()
        try:
            AlarmPipeline.parse(raw)
        except AlarmPipelineFormatError as e:
            render_error(ValueError("%s does not decode: %s" % (pipeline_name, e)),
                         no_color=False)
            raise typer.Exit(code=1) from None
        target.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(target / "data.bin", raw)
        resource = source / "resource.json"
        if resource.is_file():
            # Re-stamp rather than copying byte-for-byte: the source carries a
            # lastModificationSignature computed over the ORIGINAL data.bin and
            # an actor who never touched this copy. Every other ign writer
            # omits the signature and lets the gateway recompute it on scan.
            import json as _json

            meta = _json.loads(resource.read_text(encoding="utf-8"))
            meta.setdefault("attributes", {})
            meta["attributes"].pop("lastModificationSignature", None)
            meta["attributes"]["lastModification"] = {
                "actor": "ign",
                "timestamp": _now_stamp(),
            }
            _atomic_write_bytes(
                target / "resource.json",
                _json.dumps(meta, indent=2).encode("utf-8"))
        written.append(target)

    for target in written:
        typer.echo("Written: %s" % target)

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo("WARNING: gateway scan failed; change is on disk. Reason: %s" % e,
                   err=True)
