"""ign script — project library script CLI subcommand.

The write verb is the sanctioned ign path for writing project library
scripts (code.py) under projects/<name>/ignition/script-python/<path>/.

--project is REQUIRED — no default.
ProjectDiskBackend raises ProjectNotFoundError when project.json is
missing; the project must exist in the gateway.
TAB: Project library scripts must be TAB-indented (Jython 2.7 convention).
     Space-indented code is rejected (ScriptTabError). No auto-convert.
Syntax: Code is validated via CPython-3 ast.parse before any disk write.
        Note: Jython 2.7 grammar ≈ Python 2.7; this check may not catch
        all Jython-2.7-only constructs (e.g. print-as-statement).
Scan: After write, POST /data/api/v1/scan/projects (best-effort; any failure
      becomes a stderr WARNING and exit 0). Suppress with --no-scan.
Dry-run: --dry-run prints payload + target path without touching disk and
         without requiring Settings() / .env.

Mirrors cmd_view.py: option structure, error handling, Settings() placement,
narrow credential catch, ScanClient context manager usage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from ..backends._fs_utils import _encode_segment
from ..backends.api_client import AuthMissingError
from ..backends.project_disk import (
    ProjectDiskBackend,
    ProjectNotFoundError,
    ScriptNotFoundError,
    ScriptTabError,
    script_resource_json,
    validate_script_code,
)
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ._errors import render_error

script_app = typer.Typer(help="Project library script operations: write, delete.")


@script_app.command("write")
def write_cmd(
    project: Annotated[
        str,
        typer.Option(
            "--project",
            help="Project name (REQUIRED — no default; the project is never auto-scaffolded).",
        ),
    ],
    script_path: Annotated[
        str,
        typer.Option(
            "--script-path",
            help=(
                "Script package path, e.g. plant/nav (slash-separated). "
                "Final segment is the package directory containing code.py."
            ),
        ),
    ],
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file",
            help="Path to a .py file to write as code.py (REQUIRED for script write).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print payload + target path; no filesystem write.",
        ),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help=(
                "After a successful write, POST /data/api/v1/scan/projects "
                "to notify the gateway of the disk change. Pass --no-scan "
                "during local dev when the gateway is unreachable. Default: scan."
            ),
        ),
    ] = True,
) -> None:
    """Write code.py + resource.json for a project library script.

    Writes to projects/<name>/ignition/script-python/<path>/.

    Code must be TAB-indented (Jython 2.7 convention). Space-indented code
    is rejected before any disk write. Code is also validated via
    CPython-3 ast.parse (does not catch all Jython-2.7-only constructs).
    """
    # Validate --script-path early — before dry-run, before Settings(),
    # so the error is clean and consistent in all modes.
    if not script_path or not script_path.strip():
        render_error(ValueError("--script-path must not be empty or whitespace-only."), no_color=False)
        raise typer.Exit(code=1)
    encoded_segments: list[str] = []
    for seg in script_path.split("/"):
        if not seg:
            continue
        try:
            encoded_segments.append(_encode_segment(seg))
        except ValueError as e:
            render_error(ValueError(f"invalid --script-path - {e}"), no_color=False)
            raise typer.Exit(code=1) from None
    if not encoded_segments:
        render_error(ValueError(
            "--script-path has no non-empty segments; "
            "a script must live under a named subdirectory of script-python/."
        ), no_color=False)
        raise typer.Exit(code=1)

    # --file is required for script write (no built-in demo script)
    if file is None:
        render_error(ValueError("--file is required; provide a .py file to write as code.py."), no_color=False)
        raise typer.Exit(code=1)

    # Load code from --file
    try:
        code = file.read_text(encoding="utf-8")
    except OSError as e:
        render_error(ValueError(f"--file could not be read: {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if dry_run:
        # Dry-run: faithful preview. Run the SAME acceptance gate a real write
        # applies (previously skipped, so a dry-run "passed" on code a
        # real write rejects) and show BOTH files, including the resource.json
        # whose hintScope:2 is what makes the module load.
        import json

        try:
            validate_script_code(code)
        except ScriptTabError as e:
            render_error(e, no_color=False)
            raise typer.Exit(code=1) from None
        except SyntaxError as e:
            render_error(ValueError(f"syntax error in --file: {e}"), no_color=False)
            raise typer.Exit(code=1) from None
        except ValueError as e:  # incl. UnknownSystemCallError
            render_error(e, no_color=False)
            raise typer.Exit(code=1) from None
        encoded_path = "/".join(encoded_segments)
        typer.echo("=== code.py ===")
        typer.echo(code)
        typer.echo("=== resource.json ===")
        typer.echo(json.dumps(script_resource_json(), indent=2))
        typer.echo("=== target path ===")
        typer.echo(
            f"projects/{project}/ignition/script-python/{encoded_path}/"
        )
        return

    # Narrow the credential-loading catch — never format exception
    # body into user output (pydantic-settings ValidationError may contain
    # the offending input_value which could include the token value).
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError) as _e:
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None

    # Project-LIBRARY code.py modules ARE (re)loaded on a project scan, like
    # views (proven: a fresh ign script initialized clean on scan). There is
    # NO reload gate. If a module misbehaves after a
    # scan, it is a real init/runtime ERROR — check the gateway logs
    # (GET /data/api/v1/logs?search=<module>), not a reload.
    try:
        backend = ProjectDiskBackend(settings)
        dest = backend.write_script(project, script_path, code)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ScriptTabError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except SyntaxError as e:
        render_error(ValueError(f"syntax error in --file: {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Written: {dest}/code.py")
    typer.echo(f"Written: {dest}/resource.json")

    # Best-effort scan: notify the gateway of the disk change. Any failure
    # becomes a stderr WARNING and exit 0 — the disk write has already succeeded.
    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed for {dest}; "
            f"the change is on disk but the gateway may not see it "
            f"until the next scan tick. Reason: {e}",
            err=True,
        )
        # Disk write succeeded; exit 0 — scan is best-effort.
        return


@script_app.command("replace-text")
def replace_text_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project name (REQUIRED)."),
    ],
    script_path: Annotated[
        str,
        typer.Option(
            "--script-path",
            help="Script package path under script-python, e.g. library/navbuilder.",
        ),
    ],
    old: Annotated[
        str,
        typer.Option("--old", help="Exact literal text to replace (not a regex)."),
    ],
    new: Annotated[
        str,
        typer.Option("--new", help="Replacement text."),
    ],
    expect: Annotated[
        Optional[int],
        typer.Option(
            "--expect",
            help=(
                "Require exactly this many occurrences of --old. Refuses the write "
                "on a mismatch, so a typo in --old fails loudly instead of silently "
                "changing nothing. Default: at least one."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Report the match count; no filesystem write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help="After a successful write, POST /data/api/v1/scan/projects. Default: scan.",
        ),
    ] = True,
) -> None:
    """Replace exact literal text inside an existing library script's code.py.

    The surgical counterpart to `write`, which needs the whole file. Use it for
    a one-token correction (a misspelled dict key, a wrong constant) where
    round-tripping the entire module would be wasteful and risk unrelated drift.

    The result goes through the same acceptance gate as `write` (TAB indent +
    syntax), so a replacement that breaks the module is rejected before any
    disk write.
    """
    if not script_path or not script_path.strip():
        render_error(ValueError("--script-path must not be empty or whitespace-only."), no_color=False)
        raise typer.Exit(code=1)
    if not old:
        render_error(ValueError("--old must not be empty."), no_color=False)
        raise typer.Exit(code=1)
    if old == new:
        render_error(ValueError("--old and --new are identical; nothing to do."), no_color=False)
        raise typer.Exit(code=1)

    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None

    source = (
        settings.ignition_data_root / "projects" / project
        / "ignition" / "script-python" / script_path / "code.py"
    )
    if not source.is_file():
        render_error(FileNotFoundError(
            f"code.py not found at {source}; check --project and --script-path are correct."
        ), no_color=False)
        raise typer.Exit(code=1) from None
    try:
        code = source.read_text(encoding="utf-8")
    except OSError as e:
        render_error(ValueError(f"could not read {source}: {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    found = code.count(old)
    if expect is not None and found != expect:
        render_error(ValueError(
            f"--old occurs {found} time(s) in {script_path}/code.py, --expect said {expect}."
        ), no_color=False)
        raise typer.Exit(code=1)
    if found == 0:
        render_error(ValueError(
            f"--old not found in {script_path}/code.py; nothing replaced."
        ), no_color=False)
        raise typer.Exit(code=1)

    updated = code.replace(old, new)

    if dry_run:
        typer.echo(f"Would replace {found} occurrence(s) in {source}")
        return

    try:
        dest = ProjectDiskBackend(settings).write_script(project, script_path, updated)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ScriptTabError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except SyntaxError as e:
        render_error(ValueError(f"replacement produced a syntax error: {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Replaced {found} occurrence(s): {dest}/code.py")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed for {dest}; "
            f"the change is on disk but the gateway may not see it "
            f"until the next scan tick. Reason: {e}",
            err=True,
        )


@script_app.command("delete")
def delete_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project name (REQUIRED)."),
    ],
    script_path: Annotated[
        str,
        typer.Option(
            "--script-path",
            help="Script package path under script-python to delete, e.g. library/navbuilder.",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print target path; no filesystem change."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help="After a successful delete, POST /data/api/v1/scan/projects. Default: scan.",
        ),
    ] = True,
) -> None:
    """Delete a library script package dir from projects/<name>/ignition/script-python/<path>/."""
    if not script_path or not script_path.strip():
        render_error(ValueError("--script-path must not be empty or whitespace-only."), no_color=False)
        raise typer.Exit(code=1)

    if dry_run:
        typer.echo(
            f"Would delete: projects/{project}/ignition/script-python/{script_path}/"
        )
        return

    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None

    try:
        backend = ProjectDiskBackend(settings)
        backend.delete_script(project, script_path)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ScriptNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Deleted: {script_path}")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed after deleting {script_path}; "
            f"the change is on disk but Designer may not see it "
            f"until the next scan tick. Reason: {e}",
            err=True,
        )
