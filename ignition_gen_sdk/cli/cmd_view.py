"""ign view — Perspective view CLI subcommand.

Verbs: build/validate (emit a view's disk JSON — ``--file`` or a demo), write
(author to a project), delete, validate (headless render). All 6
container roots + helper components are supported via ViewBuilder.

--project is REQUIRED — no default, no Settings.default_project.
ProjectDiskBackend raises ProjectNotFoundError ONLY when project.json is
missing; missing perspective subdirs are auto-created under an existing
project.
After a successful write, POST /data/api/v1/scan/projects so the gateway
re-scans projects/** without waiting for the next tick. Best-effort: any
scan failure becomes a stderr WARNING and exit 0. Suppress with --no-scan
for offline / dev-without-gateway flows.

Mirrors cmd_tag.py: Typer subcommand group, Annotated[...] options for
every flag, error→stderr+typer.Exit pattern.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..backends._fs_utils import _encode_segment
from ..backends.api_client import AuthMissingError, AuthScopeError, GatewayError, NetworkError, PayloadError
from ..backends.project_disk import ProjectDiskBackend, ProjectNotFoundError, ViewNotFoundError
from ..backends.scan_client import ScanClient, ScanWarning
from ..builders.view import ViewBuilder
from ..config import DEFAULT_STATE_DIR, Settings
from ..models.views.component import Component
from ..models.views.meta import Meta
from ..models.views.positions import FlexChildPosition
from ..models.views.view import View
from ..serializers.resource_metadata import view_resource_json
from ..serializers.view_disk import view_to_disk
from ._errors import render_error

view_app = typer.Typer(help="Perspective view operations: build, write.")


def _demo_view() -> View:
    """Canonical demo view — Flex root + one Label. Used by build + write."""
    return (ViewBuilder()
            .flex_root(direction="column")
            .add_to_flex(
                Component(
                    type="ia.display.label",
                    meta=Meta(name="Hello"),
                    props={"text": "Hello, Perspective"},
                ),
                position=FlexChildPosition(basis="56px", shrink=0),
            )
            .build())


def _load_view_file(file: Path) -> View:
    """Load + validate a disk-shape view.json into a :class:`View` model.

    The accepted JSON is the same shape ``view build``/``view write`` emit
    (and that a Designer export produces). Validation round-trips through the
    Pydantic model so a malformed view fails here, not on the gateway.
    """
    try:
        data = json.loads(file.read_text())
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"--file could not be read as JSON - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    try:
        return View.model_validate(data)
    except ValueError as e:
        render_error(PayloadError(f"--file is not a valid view - {e}"), no_color=False)
        raise typer.Exit(code=1) from None


@view_app.command("build")
def build_cmd(
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file",
            help="Path to a view.json (disk shape) to validate + emit. Omit for the built-in demo view.",
        ),
    ] = None,
) -> None:
    """Print a view's JSON to stdout (no project required, no I/O).

    With ``--file`` validates and re-emits that view; without it prints the
    built-in demo view.
    """
    view = _load_view_file(file) if file is not None else _demo_view()
    typer.echo(json.dumps(view_to_disk(view), indent=2))


@view_app.command("write")
def write_cmd(
    project: Annotated[
        str,
        typer.Option(
            "--project",
            help="Project name (REQUIRED — no default; the project is never auto-scaffolded).",
        ),
    ],
    view_path: Annotated[
        str,
        typer.Option(
            "--view-path",
            help="View path under project, e.g. Main/Overview (slash-separated).",
        ),
    ],
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file",
            help="Path to a view.json (disk shape) to write. Omit to write the built-in demo view.",
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
    doc_file: Annotated[
        Optional[Path],
        typer.Option(
            "--doc-file",
            help=(
                "Text file whose contents become resource.json `documentation` "
                "(Designer view docs, e.g. a license notice on derived artwork). "
                "Omit to keep an existing view's documentation."
            ),
        ),
    ] = None,
) -> None:
    """Write a view to disk under projects/<name>/com.inductiveautomation.perspective/views/<path>/.

    With ``--file`` writes that (validated) view; without it writes the built-in demo view.
    """
    # Validate --view-path
    # BEFORE the dry-run branch so the error message is clean and
    # consistent regardless of dry-run mode. Dry-run must NOT silently
    # accept invalid paths (traversal markers, empty/whitespace segments,
    # or wholly-empty input).
    if not view_path or not view_path.strip():
        render_error(ValueError("--view-path must not be empty or whitespace-only."), no_color=False)
        raise typer.Exit(code=1)
    encoded_segments: list[str] = []
    for seg in view_path.split("/"):
        if not seg:
            continue
        try:
            encoded_segments.append(_encode_segment(seg))
        except ValueError as e:
            render_error(ValueError(f"invalid --view-path - {e}"), no_color=False)
            raise typer.Exit(code=1) from None
    if not encoded_segments:
        render_error(ValueError(
            "--view-path has no non-empty segments; "
            "a view must live under a named subdirectory of views/."
        ), no_color=False)
        raise typer.Exit(code=1)
    encoded_view_path = "/".join(encoded_segments)
    view = _load_view_file(file) if file is not None else _demo_view()
    view_payload = view_to_disk(view)
    documentation = doc_file.read_text(encoding="utf-8") if doc_file is not None else None
    resource_payload = view_resource_json(documentation)

    if dry_run:
        typer.echo("=== view.json ===")
        typer.echo(json.dumps(view_payload, indent=2))
        typer.echo("=== resource.json ===")
        typer.echo(json.dumps(resource_payload, indent=2))
        typer.echo("=== target path ===")
        typer.echo(
            f"projects/{project}/com.inductiveautomation.perspective/views/{encoded_view_path}/"
        )
        return

    # Narrow the catch and DO NOT interpolate the
    # exception body. pydantic-settings' ValidationError can include
    # the offending input_value in str(e) -- if a future Pydantic echoes
    # IGNITION_API_TOKEN=<actual-value> in that field, the token would
    # land in stderr. Defense-in-depth: never format credential-loading
    # exceptions into user output.
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError) as _e:
        # ValueError covers pydantic ValidationError (which subclasses ValueError).
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None

    # A project SCAN DOES register newly-added VIEWS (proven by rendering a
    # brand-new view live after scan), so there is NO view-registration NOTE
    # here. The reload caveat applies
    # only to project-LIBRARY code.py modules (see `ign script write`) — a view
    # that CALLS a newly-added library renders, but that library call stays stale
    # until a gateway reload.
    try:
        backend = ProjectDiskBackend(settings)
        dest = backend.write_view(project, view_path, view, documentation=documentation)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except PayloadError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Written: {dest}/view.json")
    typer.echo(f"Written: {dest}/resource.json")

    # Record successful write to manifest (never on dry-run path)
    from ..manifest.manifest import record as _manifest_record
    _manifest_record(
        resource_type="views",
        resource_id=f"{project}/{view_path}",
        payload=view_payload,
        backend="disk",
    )

    # Notify the gateway of the disk change so Designer
    # picks it up without waiting for the next scan tick. Best-effort: any
    # scan failure becomes a stderr WARNING and exit 0 — the disk write has
    # already succeeded. --no-scan suppresses entirely (offline / dev flows).
    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed for {dest}; "
            f"the change is on disk but Designer may not see it "
            f"until the next scan tick. Reason: {e}",
            err=True,
        )
        # Disk write succeeded; exit 0 — scan is best-effort.
        return


@view_app.command("validate")
def validate_cmd(
    project: Annotated[
        Optional[str],
        typer.Option(
            "--project",
            help="Project whose Perspective client to load (→ /data/perspective/client/<project>). "
            "Combine with --page for a mounted page. One of --project/--client-path/--url required.",
        ),
    ] = None,
    page: Annotated[
        Optional[str],
        typer.Option(
            "--page",
            help="Page path under the project's client (e.g. 'pid'). Requires --project.",
        ),
    ] = None,
    client_path: Annotated[
        Optional[str],
        typer.Option(
            "--client-path",
            help="Explicit client path under the base URL (e.g. /data/perspective/client/Demo/pid).",
        ),
    ] = None,
    url: Annotated[
        Optional[str],
        typer.Option("--url", help="Absolute URL to render (overrides --project/--client-path)."),
    ] = None,
    base: Annotated[
        Optional[str],
        typer.Option("--base", help="Gateway base URL (default: IGNITION_URL from env/.env)."),
    ] = None,
    out: Annotated[
        Path,
        typer.Option("--out", help="Screenshot output path."),
    ] = DEFAULT_STATE_DIR / "validate.png",
) -> None:
    """Render a Perspective view in headless Chrome and report RUNTIME health.

    Drives a real browser against the gateway's Perspective client (read-only,
    no token needed). Reports component crashes (error boundaries = real bugs →
    exit 1) vs data-quality overlays (a data signal → warning, exit 0), plus a
    screenshot. A `page list` URL maps to `--page` by dropping the leading
    slash (`/pid` → `--page pid`); the ROOT page `/` is just `--project P`
    with no `--page`. `--project P --page pid` is shorthand for
    `--client-path /data/perspective/client/P/pid`. Requires the optional
    'runtime' extra: `pip install -e '.\\[runtime]' && playwright install chrome`.
    """
    # NOTE: the docstring escapes '[' as '\\[' so Rich markup (Typer --help)
    # renders the literal '[runtime]' instead of silently eating the bracketed
    # token and printing `pip install -e '.'`.
    from ..validation.runtime import RuntimeValidationError, client_url, validate, verdict, warnings

    try:
        target = client_url(base, project=project, page=page, client_path=client_path, url=url)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = validate(target, str(out))
    except RuntimeValidationError as e:
        # Missing optional dep — exit 2 distinguishes "couldn't run" from "view failed".
        render_error(e, no_color=False)
        raise typer.Exit(code=2) from None

    printable = {k: v for k, v in result.items() if k != "visible_text_sample"}
    typer.echo(json.dumps(printable, indent=2))

    for w in warnings(result):
        typer.echo(f"WARNING: {w}", err=True)

    ok, reasons = verdict(result)
    if not ok:
        typer.echo(f"FAIL: {'; '.join(reasons)}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"OK: rendered {target} (screenshot: {result.get('screenshot')})")


@view_app.command("delete")
def delete_cmd(
    project: Annotated[
        str,
        typer.Option(
            "--project",
            help="Project name (REQUIRED — no default; the project is never auto-scaffolded).",
        ),
    ],
    view_path: Annotated[
        str,
        typer.Option(
            "--view-path",
            help="View path under project to delete, e.g. Components/PumpFaceplate (slash-separated).",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print target path; no filesystem change.",
        ),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help=(
                "After a successful delete, POST /data/api/v1/scan/projects "
                "to notify the gateway of the disk change. Pass --no-scan "
                "during local dev when the gateway is unreachable. Default: scan."
            ),
        ),
    ] = True,
) -> None:
    """Delete a view directory from disk under projects/<name>/com.inductiveautomation.perspective/views/<path>/.

    The gateway picks up the removal on the next project scan (or immediately
    if --scan is active). Use --dry-run to preview the target path without
    removing anything.
    """
    # Validate --view-path early (same as write_cmd)
    if not view_path or not view_path.strip():
        render_error(ValueError("--view-path must not be empty or whitespace-only."), no_color=False)
        raise typer.Exit(code=1)

    if dry_run:
        # Encode path for display (mirrors write_cmd dry-run pattern)
        encoded_segments: list[str] = []
        for seg in view_path.split("/"):
            if not seg:
                continue
            try:
                encoded_segments.append(_encode_segment(seg))
            except ValueError as e:
                render_error(ValueError(f"invalid --view-path - {e}"), no_color=False)
                raise typer.Exit(code=1) from None
        if not encoded_segments:
            render_error(ValueError(
                "--view-path has no non-empty segments; "
                "a view must live under a named subdirectory of views/."
            ), no_color=False)
            raise typer.Exit(code=1)
        encoded_view_path = "/".join(encoded_segments)
        typer.echo(
            f"Would delete: projects/{project}/com.inductiveautomation.perspective/views/{encoded_view_path}/"
        )
        return

    # Narrow credential-loading exception to avoid leaking token value
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError) as _e:
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None

    try:
        backend = ProjectDiskBackend(settings)
        backend.delete_view(project, view_path)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ViewNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Deleted: {view_path}")

    # Notify gateway of disk change; best-effort
    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed after deleting {view_path}; "
            f"the change is on disk but Designer may not see it "
            f"until the next scan tick. Reason: {e}",
            err=True,
        )


@view_app.command("replace-text")
def view_replace_text_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project name containing the view (e.g. Demo)."),
    ],
    view_path: Annotated[
        str,
        typer.Option("--view-path", help="View path under project, e.g. Navigation/Menu (slash-separated)."),
    ],
    old: Annotated[
        str,
        typer.Option(
            "--old",
            help=(
                "Exact literal text to replace in view.json (not a regex). Matched "
                "against the RAW FILE, so it must be written the way the serializer "
                "stores it: inner quotes escaped, and `=` written \\u003d. Prefer a "
                "token with neither (a messageType, a style class) and let --expect "
                "catch a miss."
            ),
        ),
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
                "Require exactly this many occurrences of --old. Refuses the write on a "
                "mismatch, so a typo in --old fails loudly instead of changing nothing. "
                "Default: at least one."
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
    """Replace exact literal text inside an existing view's view.json.

    The view-side counterpart to ``script replace-text``, and the surgical
    alternative to ``view write --file`` when a change is a few tokens deep in a
    place the typed surface does not reach — an event-script body, a message
    handler's ``messageType``, a style class named in many components. Renaming
    such a token across several views otherwise means hand-patching JSON.

    The result is re-validated through the View model before any disk write, so a
    replacement that corrupts the view is refused.
    """
    if not view_path or not view_path.strip():
        render_error(ValueError("--view-path must not be empty or whitespace-only."), no_color=False)
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
        / "com.inductiveautomation.perspective" / "views" / view_path / "view.json"
    )
    if not source.is_file():
        render_error(FileNotFoundError(
            f"view.json not found at {source}; check --project and --view-path are correct."
        ), no_color=False)
        raise typer.Exit(code=1) from None
    try:
        raw_text = source.read_text(encoding="utf-8")
    except OSError as e:
        render_error(ValueError(f"could not read {source}: {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    found = raw_text.count(old)
    if expect is not None and found != expect:
        render_error(ValueError(
            f"--old occurs {found} time(s) in {view_path}/view.json, --expect said {expect}."
        ), no_color=False)
        raise typer.Exit(code=1)
    if found == 0:
        render_error(ValueError(
            f"--old not found in {view_path}/view.json; nothing replaced."
        ), no_color=False)
        raise typer.Exit(code=1)

    try:
        view = View.model_validate(json.loads(raw_text.replace(old, new)))
    except json.JSONDecodeError as e:
        render_error(ValueError(f"replacement produced invalid JSON: {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(PayloadError(f"view is not valid after the change - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if dry_run:
        typer.echo(f"Would replace {found} occurrence(s) in {source}")
        return

    try:
        dest = ProjectDiskBackend(settings).write_view(project, view_path, view)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo(f"Replaced {found} occurrence(s): {dest}/view.json")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed for {dest}; "
            f"the change is on disk but Designer may not see it "
            f"until the next scan tick. Reason: {e}",
            err=True,
        )


def _parse_prop_value(text: str):
    """JSON when it parses (``""``, ``0``, ``false``, ``{...}``), else the raw string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


#: Prop roots addressable on a nested component (view level allows only the first two).
_COMPONENT_PROP_HEADS = ("props", "custom", "position", "meta")


def _resolve_component(raw: dict, component: str) -> dict:
    """Walk ``root/Child/Grandchild`` (``meta.name`` segments) in a raw view dict.

    The first segment names the root component itself — conventionally ``root``,
    but any name matching the root's ``meta.name`` is accepted so a view whose
    root is called something else is still addressable.
    """
    segments = [s for s in component.split("/") if s]
    if not segments:
        raise ValueError("--component must name at least the root, e.g. 'root'.")

    node = raw.get("root")
    if not isinstance(node, dict):
        raise ValueError("view has no root component.")
    root_name = (node.get("meta") or {}).get("name")
    if segments[0] not in ("root", root_name):
        raise ValueError(
            f"--component must start at the root ({root_name!r} or 'root'), "
            f"got {segments[0]!r}."
        )

    walked = [segments[0]]
    for seg in segments[1:]:
        children = node.get("children")
        if not isinstance(children, list):
            raise ValueError(f"{'/'.join(walked)} has no children; cannot reach {seg!r}.")
        for child in children:
            if isinstance(child, dict) and (child.get("meta") or {}).get("name") == seg:
                node = child
                break
        else:
            names = [
                (c.get("meta") or {}).get("name")
                for c in children
                if isinstance(c, dict)
            ]
            raise ValueError(
                f"no child named {seg!r} under {'/'.join(walked)}; available: {names}."
            )
        walked.append(seg)
    return node


@view_app.command("set-prop")
def set_prop_cmd(
    project: Annotated[
        str,
        typer.Option("--project", help="Project name containing the view (e.g. Demo)."),
    ],
    view_path: Annotated[
        str,
        typer.Option("--view-path", help="View path under project, e.g. Navigation/Menu (slash-separated)."),
    ],
    prop: Annotated[
        str,
        typer.Option(
            "--prop",
            help=(
                "Property to change (dots nest). View level: custom.<name> or "
                "params.<name>. With --component: props.*, custom.*, position.* "
                "or meta.* on that component."
            ),
        ),
    ],
    component: Annotated[
        Optional[str],
        typer.Option(
            "--component",
            help=(
                "Target a nested component instead of the view level: a slash path "
                "of meta.name segments starting at the root, e.g. 'root' or "
                "'root/Body/Label'."
            ),
        ),
    ] = None,
    unset_binding: Annotated[
        bool,
        typer.Option(
            "--unset-binding",
            help=(
                "Remove the propConfig BINDING for --prop, leaving any static value "
                "in place. Use to retire a binding whose source no longer exists."
            ),
        ),
    ] = False,
    binding_file: Annotated[
        Optional[Path],
        typer.Option(
            "--binding-file",
            help=(
                "JSON file holding the propConfig `binding` object to SET on --prop "
                '(e.g. {"type": "tag", "config": {...}}). Replaces any existing '
                "binding; validated through the View model like every other write."
            ),
        ),
    ] = None,
    value: Annotated[
        Optional[str],
        typer.Option(
            "--value",
            help='New seed value. Parsed as JSON when it parses ("", 0, false, {...}); otherwise a plain string.',
        ),
    ] = None,
    unset: Annotated[
        bool,
        typer.Option("--unset", help="Drop the stored seed value (propConfig flags stay)."),
    ] = False,
    persistent: Annotated[
        Optional[bool],
        typer.Option(
            "--persistent/--no-persistent",
            help=(
                "Set the propConfig `persistent` flag. --no-persistent ALSO drops the "
                "stored seed: the Designer saves none for a non-persistent prop, so the "
                "view ships in the shape it would save."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print the resulting view.json; no disk write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help="After a successful write, POST /data/api/v1/scan/projects. Default: scan.",
        ),
    ] = True,
) -> None:
    """Set/unset ONE prop (seed value, persistent flag, or binding) on an existing view.

    Reads the on-disk view.json, applies the change, validates through the
    View model, writes back (resource.json documentation kept), then scans.
    Without --component the target is view level (custom/params); with it, the
    named component's own props/custom/position/meta.

    Typical uses: a Designer preview session persisted transient state into an
    unbound `persistent: true` prop (`--no-persistent` stops it recurring); a
    binding whose source custom no longer exists (`--unset-binding`); adding or
    replacing one binding without rewriting the whole view (`--binding-file`).
    """
    if (
        value is None and not unset and persistent is None
        and not unset_binding and binding_file is None
    ):
        render_error(ValueError(
            "nothing to do - pass --value, --unset, --unset-binding, --binding-file "
            "and/or --persistent/--no-persistent."
        ), no_color=False)
        raise typer.Exit(code=1)
    if value is not None and unset:
        render_error(ValueError("--value and --unset are mutually exclusive."), no_color=False)
        raise typer.Exit(code=1)
    if unset_binding and binding_file is not None:
        render_error(ValueError(
            "--unset-binding and --binding-file are mutually exclusive."
        ), no_color=False)
        raise typer.Exit(code=1)
    binding: dict | None = None
    if binding_file is not None:
        try:
            binding = json.loads(binding_file.read_text())
        except (OSError, ValueError) as e:
            render_error(ValueError(f"could not read --binding-file {binding_file}: {e}"), no_color=False)
            raise typer.Exit(code=1) from None
        if not isinstance(binding, dict) or "type" not in binding:
            render_error(ValueError(
                "--binding-file must hold a JSON object with a 'type' key "
                '(e.g. {"type": "expr", "config": {"expression": "..."}}).'
            ), no_color=False)
            raise typer.Exit(code=1)
    head, _, rest = prop.partition(".")
    if component is None:
        if head not in ("custom", "params") or not rest:
            render_error(ValueError(
                f"--prop must be custom.<name> or params.<name> at view level, got {prop!r}. "
                f"Pass --component to address a component's props.*/position.*/meta.*."
            ), no_color=False)
            raise typer.Exit(code=1)
    elif head not in _COMPONENT_PROP_HEADS or not rest:
        render_error(ValueError(
            f"--prop must start with one of {', '.join(_COMPONENT_PROP_HEADS)} "
            f"when --component is given, got {prop!r}."
        ), no_color=False)
        raise typer.Exit(code=1)

    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None

    source_path = (
        settings.ignition_data_root / "projects" / project
        / "com.inductiveautomation.perspective" / "views" / view_path / "view.json"
    )
    if not source_path.is_file():
        render_error(FileNotFoundError(
            f"view.json not found at {source_path}; check --project and --view-path are correct."
        ), no_color=False)
        raise typer.Exit(code=1) from None
    try:
        raw = json.loads(source_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"could not read {source_path}: {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if component is None:
        target = raw
    else:
        try:
            target = _resolve_component(raw, component)
        except ValueError as e:
            render_error(ValueError(f"--component {component!r}: {e}"), no_color=False)
            raise typer.Exit(code=1) from None

    keys = rest.split(".")
    leaf = keys[-1]
    # Only a value operation may materialize the value tree. A propConfig-only
    # call (--binding-file, --unset-binding, --persistent) must not leave an
    # empty `props: {}` behind — that is a Perspective default, i.e. churn the
    # user strips on the next Designer save.
    if value is not None or unset or persistent is False:
        head_existed = head in target
        parent = target.setdefault(head, {})
        for k in keys[:-1]:
            parent = parent.setdefault(k, {})
            if not isinstance(parent, dict):
                render_error(ValueError(f"{prop!r}: {k!r} is not an object."), no_color=False)
                raise typer.Exit(code=1)
        if value is not None:
            parent[leaf] = _parse_prop_value(value)
        if unset or persistent is False:
            parent.pop(leaf, None)
        # An unset that emptied a container we just created leaves nothing useful.
        if not head_existed and not target.get(head):
            target.pop(head, None)
    if persistent is not None:
        target.setdefault("propConfig", {}).setdefault(prop, {})["persistent"] = persistent
    if binding is not None:
        target.setdefault("propConfig", {}).setdefault(prop, {})["binding"] = binding
    if unset_binding:
        entry = (target.get("propConfig") or {}).get(prop)
        if not isinstance(entry, dict) or "binding" not in entry:
            render_error(ValueError(
                f"--unset-binding: no binding on {prop!r}"
                + (f" of component {component!r}" if component else "")
                + "."
            ), no_color=False)
            raise typer.Exit(code=1)
        entry.pop("binding", None)
        # An entry that carried nothing but the binding is now noise.
        if not entry:
            target["propConfig"].pop(prop, None)
        if not target.get("propConfig"):
            target.pop("propConfig", None)

    try:
        view = View.model_validate(raw)
    except ValueError as e:
        render_error(PayloadError(f"view is not valid after the change - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    if dry_run:
        typer.echo(json.dumps(view_to_disk(view), indent=2))
        return

    try:
        dest = ProjectDiskBackend(settings).write_view(project, view_path, view)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo(f"Written: {dest}/view.json")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed for {dest}; "
            f"the change is on disk but Designer may not see it "
            f"until the next scan tick. Reason: {e}",
            err=True,
        )
