"""``ign tag`` subcommand group — build/validate, push, import, and manage tags.

Commands:

- ``build`` — validate + print tag JSON. Without ``--file`` prints a canonical
  demo Float8 OPC tag (sanity-checks the Pydantic emit path); with ``--file``
  validates the given tag(s) and re-emits the import body.
- ``push`` — push tag(s) to the gateway (or disk) via :class:`WriteRouter`
  (``--file`` or the demo tag; ``--dry-run``; ``--backend api|disk|auto``).
- ``import`` — POST a tags/import body (``--file``); ``--dry-run`` previews the
  request + validates UdtInstance typeIds offline.
- ``udt-type`` — author a UDT TYPE definition (disk; ``--dry-run``).
- ``set-udt-member-prop`` — patch ONE property on the matching members of an
  EXISTING UDT definition file, siblings untouched (disk; ``--dry-run``).
- ``set-udt-type-prop`` — patch ONE property on the TYPE NODE itself (the flat
  ``meta_*`` layer), siblings untouched (disk; ``--dry-run``).
- ``udt-instance`` — author UDT INSTANCES into a tag folder's ``udts.json``
  (disk; ``--dry-run``).
- ``delete`` — delete a tag/instance/folder.

Disk-write verbs (``udt-type``, ``udt-instance``, ``push --backend disk``)
take the gateway's config scan lock around write+scan when ``--scan`` is on
— see :func:`_acquire_config_lock`.

Error taxonomy (mapped 1:1 from
:class:`IgnitionAPIClient._raise_for_status`):

- :class:`AuthMissingError` (401) → ``Auth error: check IGNITION_API_TOKEN in
  .env`` (stderr; exit 1)
- :class:`AuthScopeError` (403) → ``Permission error: token lacks required
  scope — check Gateway UI`` (stderr; exit 1)
- :class:`PayloadError` (400) → ``Payload error: <server response body>``
  (stderr; exit 1)
- :class:`GatewayError` (5xx) → ``Gateway error: <message>`` (stderr; exit 1)
- :class:`ValueError` (e.g. invalid ``--backend``) → ``Error: <message>``
  (stderr; exit 1)

"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Optional
from urllib.parse import urlencode

import typer

from ..backends.api_backend import ApiBackend
from ..backends.api_client import (
    AuthMissingError,
    AuthScopeError,
    GatewayError,
    IgnitionAPIClient,
    NetworkError,
    PayloadError,
)
from ..backends.disk_backend import DiskBackend, TagNotFoundError
from ..backends.router import AutoFallbackToDisk, WriteRouter
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ..models.tags.alarm import Alarm
from ..models.tags.enums.tag_alarm_mode import TagAlarmMode
from ..models.tags.enums.tag_alarm_priority import TagAlarmPriority
from ..models.tags.enums.tag_datatype import TagDataType
from ..models.tags.enums.tag_type import TagType
from ..models.tags.enums.tag_value_source import TagValueSource
from ..models.tags.tag import Tag
from ..models.tags.udt import UdtInstance, UdtType
from ..serializers.tag_api import tags_to_import_body
from ..serializers.tag_disk import tags_to_disk
from ..serializers.udt_disk import udt_types_to_disk, udts_to_disk
from ._errors import render_error

tag_app = typer.Typer(help="Tag operations: build, push.")


def _demo_tag() -> Tag:
    """Canonical demo tag used by ``build`` and ``push`` commands.

    Float8 OPC tag pointing at the published OPC UA Sample Device sine
    waveform; carries one HIGH alarm and history enabled at the default
    provider. No sensitive data — paths and values are public sample
    fixtures.
    """
    return Tag(
        name="SmokeTestLevel",
        tagType=TagType.ATOMIC,
        dataType=TagDataType.DOUBLE,
        valueSource=TagValueSource.OPC,
        opcItemPath="ns=1;s=[Sample_Device]_Meta:Sine/Sine1",
        opcServer="Ignition OPC UA Server",
        alarms=[
            Alarm(
                name="Hi",
                mode=TagAlarmMode.ABOVE_SETPOINT,
                priority=TagAlarmPriority.HIGH,
                setpointA=90.0,
                displayPath="Smoke/Hi Alarm",
            )
        ],
        historyEnabled=True,
        historyProvider="default",
        historicalDeadband=0.1,
    )


def _make_router(settings: Settings) -> WriteRouter:
    """Compose ApiBackend + DiskBackend into a WriteRouter.

    Kept as a helper so tests can patch ``WriteRouter`` at the module
    namespace and intercept the construction without touching the
    underlying httpx client.
    """
    client = IgnitionAPIClient(settings)
    api = ApiBackend(client)
    disk = DiskBackend(settings)
    return WriteRouter(api, disk)


def _acquire_config_lock(settings: Settings) -> None:
    """Best-effort POST /data/api/v1/scan-lock/config before a disk write.

    While the lock is held the gateway queues other config changes, so the
    write + the following ``scan_config()`` (which releases the lock) land as
    one unit instead of the gateway noticing a half-written file and applying
    its internal abort collision policy.

    Only call this when the caller WILL scan afterwards — the scan is the
    release. Failure is a WARNING, never fatal: the write still happens, it
    is just no longer atomic from the gateway's point of view.
    """
    try:
        with ScanClient(settings) as scan_client:
            scan_client.acquire_config_lock()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: could not acquire the gateway config scan lock; "
            f"writing anyway (the gateway may apply its own collision policy "
            f"if it reads the file mid-write). Reason: {e}",
            err=True,
        )


def _print_diagnostics(result: Any) -> None:
    """Render a non-empty router result. Errors → stderr; rest → stdout.

    Live gateway 8.3.4 returns a dict ``{successCount, failureCount,
    failures}``; legacy docs describe a list of diagnostic dicts. We
    accept both: a dict short-circuits to a single success line if there
    were no failures, otherwise we print the dict as-is; a list of dicts
    is rendered line-by-line with stderr routing for ``Error`` levels.
    """
    if isinstance(result, dict):
        # 8.3.4 shape: ``{successCount, failureCount, failures}``. If no
        # failures recorded, print a tidy one-liner; otherwise surface the
        # full dict so failure details are visible. ``failureCount`` is
        # the canonical signal — ``failures`` may be omitted when zero.
        if result.get("failureCount", 0) == 0:
            typer.echo("Push successful.")
        else:
            typer.echo(json.dumps(result, indent=2))
        return

    if isinstance(result, list) and result:
        for diag in result:
            level = diag.get("level", "INFO") if isinstance(diag, dict) else "INFO"
            msg = diag.get("diagnosticMessage", str(diag)) if isinstance(diag, dict) else str(diag)
            typer.echo(f"[{level}] {msg}", err=(level == "Error"))
        return

    # Empty list (disk path) or any other empty/None result → success.
    typer.echo("Push successful.")


def _load_tags_file(file: Path) -> list[Tag]:
    """Load + validate tag(s) from a JSON file into a list of :class:`Tag`.

    Accepts any of: a ``tags/import`` body (``{name, tagType, tags:[...]}``),
    a bare JSON list of tag objects, or a single tag object. Each tag is
    validated through the Tag model so a malformed tag fails here, not on the
    gateway. The accepted per-tag shape is what ``tag build`` emits.
    """
    try:
        data = json.loads(file.read_text())
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"--file could not be read as JSON - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    # Only unwrap when it is genuinely a Provider import-body envelope
    # ({name, tagType:"Provider", tags:[...]}). A UdtType/Folder node ALSO
    # carries a "tags" key — unwrapping those would silently discard the
    # wrapper (silent-corruption trap). Anything else is treated as a
    # single tag node and fails Tag validation with a clear error.
    if isinstance(data, dict) and data.get("tagType") == "Provider" and "tags" in data:
        items = data["tags"]
    elif isinstance(data, list):
        items = data
    else:
        items = [data]
    try:
        # UdtInstance nodes are validated as UdtInstance. A fully-specified
        # instance used to slip through Tag validation and get MIS-FILED into
        # tags.json by the disk backend — with a sidecar listing only
        # tags.json, un-manifesting the folder's udts.json. push_cmd rejects
        # instances on the disk path and redirects to `tag udt-instance`
        # (the udts.json writer).
        return [
            UdtInstance.model_validate(it)
            if isinstance(it, dict) and it.get("tagType") == "UdtInstance"
            else Tag.model_validate(it)
            for it in items
        ]
    except ValueError as e:
        render_error(PayloadError(f"--file is not a valid tag set - {e}"), no_color=False)
        raise typer.Exit(code=1) from None


@tag_app.command("build")
def build_cmd(
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file",
            help="Path to a tag JSON (single tag, list, or import body) to validate + emit. Omit for the built-in demo tag.",
        ),
    ] = None,
) -> None:
    """Print tag JSON to stdout (no gateway required).

    Without ``--file`` prints the built-in demo tag. With ``--file`` validates
    the supplied tag(s) and prints the ``tags/import`` body that ``push`` sends.
    """
    if file is not None:
        typer.echo(json.dumps(tags_to_import_body(_load_tags_file(file)), indent=2))
        return
    tag = _demo_tag()
    typer.echo(json.dumps(tag.emit(), indent=2))


@tag_app.command("push")
def push_cmd(
    provider: Annotated[
        str, typer.Option("--provider", help="Tag provider name")
    ] = "default",
    path: Annotated[
        str, typer.Option("--path", help="Tag path under provider root")
    ] = "",
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file",
            help="Path to a tag JSON (single tag, list, or import body) to push. Omit to push the built-in demo tag.",
        ),
    ] = None,
    backend: Annotated[
        str,
        typer.Option(
            "--backend", help="Backend to use: 'api', 'disk', or 'auto'."
        ),
    ] = "auto",
    collision_policy: Annotated[
        str,
        typer.Option(
            "--collision-policy",
            help="API-backend collision policy: Abort, Overwrite, Rename, "
            "Ignore, or MergeOverwrite. Ignored by --backend disk.",
        ),
    ] = "Overwrite",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print Provider-root JSON only; no gateway/disk write.",
        ),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help=(
                "After a successful disk write (either "
                "--backend disk or the 'auto' 5xx-fallback path), POST "
                "/data/api/v1/scan/config so the gateway re-scans "
                "config/resources/** without waiting for the next tick. "
                "Pass --no-scan during offline / dev-without-gateway flows. "
                "Default: scan."
            ),
        ),
    ] = True,
) -> None:
    """Push the demo tag to the gateway (or disk).

    ``--dry-run`` previews the Provider-root JSON envelope that would be
    sent to ``POST /data/api/v1/tags/import`` without calling any backend.
    With ``--file`` pushes the supplied tag(s); without it pushes the demo tag.
    """
    tags = _load_tags_file(file) if file is not None else [_demo_tag()]

    # UdtInstance sets are only pushable via the API (merge-capable import).
    # The disk path (and auto's 5xx disk fallback) writes tags.json — the
    # WRONG file for instances; `tag udt-instance` is the udts.json writer.
    if backend != "api" and any(isinstance(t, UdtInstance) for t in tags):
        render_error(
            PayloadError(
                "--file contains UdtInstance node(s): `tag push` can only send "
                "those with --backend api (tags/import). For a disk write use "
                "`ign tag udt-instance` (writes udts.json; REPLACES the "
                "folder's instance list, so include every instance)."
            ),
            no_color=False,
        )
        raise typer.Exit(code=1)

    if collision_policy not in _COLLISION_POLICIES:
        render_error(
            ValueError(
                f"--collision-policy must be one of {', '.join(_COLLISION_POLICIES)} "
                f"(got {collision_policy!r})."
            ),
            no_color=False,
        )
        raise typer.Exit(code=1)

    # Settings instantiation reads IGNITION_API_TOKEN from .env.
    # Narrow the catch and DO NOT interpolate the
    # exception body into the error message. pydantic-settings'
    # ValidationError can include the offending input_value in str(e);
    # if a future version echoes IGNITION_API_TOKEN=<actual-value>, that
    # would land in stderr. Defense-in-depth: never format credential-
    # loading exception messages into user-visible output.
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError) as _e:
        # ValueError covers pydantic ValidationError (which subclasses ValueError).
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None

    router = _make_router(settings)

    try:
        if dry_run:
            payload = tags_to_import_body(tags)
            typer.echo(json.dumps(payload, indent=2))
            return

        # Hold the gateway's config scan lock across the disk write +
        # the scan that releases it, so the gateway never half-reads the file
        # and falls back to its internal (abort) collision policy. Only when
        # --scan is on: the releasing call IS scan_config().
        if backend == "disk" and scan:
            _acquire_config_lock(settings)

        result = router.push_tags(
            provider=provider,
            path=path,
            tags=tags,
            dry_run=False,
            backend=backend,  # type: ignore[arg-type]
            collision_policy=collision_policy,
        )

        if backend == "disk":
            # Disk backend returns [] from the router; we need the
            # destination directory for both the user message and the
            # scan trigger. Compute the path via
            # DiskBackend._tag_def_path so the displayed string is the
            # SAME path that was just written -- including the gateway-
            # observed encoding rule (':' -> '%3a'). The previous
            # f-string interpolation skipped DiskBackend's encoder and
            # could display a path different from the actual write
            # destination.
            disk_path = DiskBackend(settings)._tag_def_path(provider, path)
            typer.echo(f"Written to disk: {disk_path}")
            # Record successful push to manifest (never on dry-run path)
            # For disk backend, store the disk-shape
            # payload (tags_to_disk = the usr-wrapped flat list that lives
            # in tags.json on disk) NOT the api envelope. Previously stored
            # the api envelope, which caused ign diff to always report
            # drift because the on-disk shape (bare list) and the manifest
            # shape (envelope) differed. The manifest payload now matches
            # exactly what disk_backend.write_tags writes via json.dumps,
            # so cmd_diff's _sha256 short-circuit succeeds when the file
            # on disk is unchanged.
            from ..manifest.manifest import record as _manifest_record
            _manifest_record(
                resource_type="tags",
                resource_id=f"{provider}/{path}" if path else provider,
                payload=tags_to_disk(tags),
                backend="disk",
            )
            # Notify gateway of the config/resources/**
            # disk change. Without this, Designer/runtime keeps a stale
            # view until the next scheduled scan tick (MEMORY.md feedback).
            # Best-effort: ScanWarning -> stderr WARNING, exit 0. The disk
            # write has already succeeded by the time we reach this point.
            # --no-scan suppresses entirely for offline / dev flows.
            if scan:
                try:
                    with ScanClient(settings) as scan_client:
                        scan_client.scan_config()
                except ScanWarning as e:
                    typer.echo(
                        f"WARNING: gateway scan failed for {disk_path}; "
                        f"the tag is on disk but Designer may not see it "
                        f"until the next scan tick. Reason: {e}",
                        err=True,
                    )
            return

        _print_diagnostics(result)
        # Record successful push to manifest (never on dry-run path)
        from ..manifest.manifest import record as _manifest_record
        _manifest_record(
            resource_type="tags",
            resource_id=f"{provider}/{path}" if path else provider,
            payload=tags_to_import_body(tags),
            backend=backend if backend != "auto" else "api",
        )

    except AuthMissingError as e:
        # Fixed hint — does not interpolate any token value.
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        # PayloadError already wraps the server response body in its
        # message; the gateway never echoes the token in observed
        # responses, so forwarding the body verbatim is safe.
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AutoFallbackToDisk as e:
        # The auto backend hit a 5xx and fell back
        # to disk successfully. Treat as WARNING (not error) -- the
        # tags are on disk but the gateway is unaware. Trigger scan
        # so Designer picks them up; record disk manifest entry; exit 0.
        typer.echo(
            f"WARNING: gateway returned 5xx; wrote to disk at {e.disk_path}. "
            f"Underlying gateway error: {e.gateway_error}",
            err=True,
        )
        from ..manifest.manifest import record as _manifest_record
        _manifest_record(
            resource_type="tags",
            resource_id=f"{provider}/{path}" if path else provider,
            payload=tags_to_disk(tags),
            backend="disk",
        )
        if scan:
            try:
                with ScanClient(settings) as scan_client:
                    scan_client.scan_config()
            except ScanWarning as sw:
                typer.echo(
                    f"WARNING: post-fallback gateway scan also failed; "
                    f"the tag is on disk at {e.disk_path} but Designer may "
                    f"not see it until the next scan tick. Reason: {sw}",
                    err=True,
                )
        # Exit 0: disk write succeeded; the gateway just wasn't reachable.
        return
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        # Catches invalid --backend (raised by WriteRouter) and any other
        # programmer errors surfaced from the call chain.
        render_error(e, no_color=False)
        raise typer.Exit(code=1)


# Collision policies accepted by /data/api/v1/tags/import. Overwrite is the
# loop's de-facto default (replace the tag tree wholesale); the others mirror
# the gateway's TagImportCollisionPolicy enum so callers can choose merge /
# rename / abort behavior without dropping to a raw `ign api` call.
_COLLISION_POLICIES = ("Abort", "Overwrite", "Rename", "Ignore", "MergeOverwrite")


def _load_import_body(file: Path) -> dict | list:
    """Load a raw tags/import body from a JSON file.

    Unlike :func:`_load_tags_file` (which validates each tag through the Tag
    model and re-wraps in a Provider envelope), this reads the body verbatim
    and posts it; the gateway is the validator. Accepts either a
    ``{"tags": [...]}`` / Provider-root envelope (dict) or a bare JSON list of
    tag objects, which is wrapped as ``{"tags": [...]}`` because the gateway
    rejects a bare array. Any other top-level JSON shape is rejected here so
    the failure is a clean CLI error, not a 400 from the gateway.
    """
    try:
        data = json.loads(file.read_text())
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"--file could not be read as JSON - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    if not isinstance(data, (dict, list)):
        render_error(
            PayloadError(
                "--file must contain a JSON object (e.g. {\"tags\": [...]}) "
                "or a bare JSON list of tags."
            ),
            no_color=False,
        )
        raise typer.Exit(code=1) from None
    if isinstance(data, list):
        # The gateway rejects a bare array; it wants the {"tags": [...]} envelope.
        return {"tags": data}
    return data


@tag_app.command("import")
def import_cmd(
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file",
            help="Path to a JSON file containing a tags/import body "
            "({\"tags\": [...]}) or a bare JSON list of tags.",
        ),
    ] = None,
    provider: Annotated[
        str, typer.Option("--provider", help="Tag provider name.")
    ] = "default",
    path: Annotated[
        Optional[str],
        typer.Option("--path", help="Tag path under the provider root (optional)."),
    ] = None,
    collision_policy: Annotated[
        str,
        typer.Option(
            "--collision-policy",
            help="Collision policy: Abort, Overwrite, Rename, Ignore, or MergeOverwrite.",
        ),
    ] = "Overwrite",
    type_: Annotated[
        str,
        typer.Option("--type", help="Import body type (gateway 'type' param)."),
    ] = "json",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print the import URL + body summary; no gateway call.",
        ),
    ] = False,
    confirm: Annotated[
        bool,
        typer.Option(
            "--confirm",
            help="Skip the confirmation prompt before POSTing to the gateway.",
        ),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help=(
                "After a successful import, POST /data/api/v1/scan/config so "
                "the gateway re-scans config/resources/** without waiting for "
                "the next tick. Pass --no-scan during offline / dev flows. "
                "Default: scan."
            ),
        ),
    ] = True,
) -> None:
    """POST a tags/import body to the gateway via /data/api/v1/tags/import.

    First-class verb mirroring ``view write --file``: reads the file body
    (wrapping a bare list as {"tags": [...]}) and posts it through the SAME httpx client the rest of the CLI
    uses (IgnitionAPIClient.request) so the API token never enters argv.
    ``--dry-run`` prints the resolved URL + a body summary and makes no call.
    On success prints the gateway's successCount / failureCount.
    """
    # --file required via in-body check (Optional decl + exit 1) — matches the
    # cmd_script/cmd_view convention so a missing file exits 1, not Click's 2.
    if file is None:
        render_error(
            ValueError("--file is required; provide a JSON tags/import body file."),
            no_color=False,
        )
        raise typer.Exit(code=1)

    if collision_policy not in _COLLISION_POLICIES:
        render_error(
            ValueError(
                f"--collision-policy must be one of {', '.join(_COLLISION_POLICIES)} "
                f"(got {collision_policy!r})."
            ),
            no_color=False,
        )
        raise typer.Exit(code=1)

    body = _load_import_body(file)

    # Build the import URL the same way IgnitionAPIClient.import_tags assembles
    # its query string, so dry-run output matches the real call exactly.
    query: list[tuple[str, str]] = [("provider", provider)]
    if path:
        query.append(("path", path))
    query.append(("type", type_))
    query.append(("collisionPolicy", collision_policy))
    import_path = f"/data/api/v1/tags/import?{urlencode(query)}"

    # Body summary: tag count for the two accepted shapes; never echo values.
    if isinstance(body, list):
        tag_count = len(body)
    else:
        tags_field = body.get("tags")
        tag_count = len(tags_field) if isinstance(tags_field, list) else 0

    if dry_run:
        typer.echo("=== import URL ===")
        typer.echo(import_path)
        typer.echo("=== body summary ===")
        typer.echo(f"shape: {'list' if isinstance(body, list) else 'object'}, tags: {tag_count}")
        # Offline UDT-instance validation — catch a missing/typo'd typeId
        # before the live POST (the likeliest authoring mistake; `tag build`
        # can't validate instance bodies). typeId resolution degrades to a
        # structural-only check when the UDT defs aren't locatable (no creds).
        from ..validation.instance_body import (
            collect_udt_typeids,
            validate_instance_body,
        )

        valid_typeids: set[str] = set()
        try:
            valid_typeids = collect_udt_typeids(
                Path(Settings().ignition_data_root), provider  # type: ignore[call-arg]
            )
        except Exception:
            valid_typeids = set()
        count, types_used, issues = validate_instance_body(body, valid_typeids)
        if count:
            typer.echo("=== UDT instances ===")
            typer.echo(f"{count} instance(s); typeIds: {sorted(types_used)}")
            if valid_typeids:
                typer.echo(
                    f"(resolved against {len(valid_typeids)} on-disk UDT def(s) "
                    f"in provider {provider!r})"
                )
            else:
                typer.echo(
                    "(typeId resolution skipped — UDT defs not locatable; "
                    "structural check only)"
                )
            if issues:
                typer.echo("=== instance issues ===")
                for i in issues:
                    typer.echo(f"  ! {i}")
        return

    # Narrow the catch and DO NOT interpolate the
    # exception body into the error message — pydantic-settings'
    # ValidationError can echo the offending input_value (potentially the
    # token) in str(e). Defense-in-depth: never format credential-loading
    # exceptions into user-visible output.
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None

    # Confirmation gate for the live POST (mirrors cmd_api): a non-tty / piped
    # invocation proceeds without prompting; --confirm always proceeds.
    import sys as _sys
    if not confirm and _sys.stdin.isatty():
        typer.confirm(f"Import {tag_count} tag(s) to provider {provider!r} -- proceed?", abort=True)

    client = IgnitionAPIClient(settings)
    try:
        response = client.request("POST", import_path, json=body)
        result = response.json() if response.text else {}
    except AuthMissingError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except PayloadError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    # 8.3.4 returns {successCount, failureCount, failures}; surface the counts.
    if isinstance(result, dict):
        success = result.get("successCount", 0)
        failure = result.get("failureCount", 0)
        typer.echo(f"Import complete: successCount={success} failureCount={failure}")
        if failure:
            typer.echo(json.dumps(result, indent=2))
    else:
        typer.echo(json.dumps(result, indent=2))

    # Notify the gateway of the config/resources/** change
    # so Designer / runtime picks it up without waiting for the next scan tick.
    # Best-effort: ScanWarning -> stderr WARNING, exit 0; --no-scan suppresses.
    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_config()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed after import; the tags are "
            f"registered but Designer may not refresh until the next scan "
            f"tick. Reason: {e}",
            err=True,
        )


def _load_udt_types_file(file: Path) -> list[UdtType]:
    """Load + validate UDT *definition*(s) from a JSON file into UdtType list.

    Accepts a single UdtType object or a JSON list of them (the udts.json shape).
    """
    try:
        data = json.loads(file.read_text())
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"--file could not be read as JSON - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    items = data if isinstance(data, list) else [data]
    try:
        return [UdtType.model_validate(x) for x in items]
    except ValueError as e:
        render_error(PayloadError(f"--file is not a valid UDT type set - {e}"), no_color=False)
        raise typer.Exit(code=1) from None


@tag_app.command("udt-type")
def udt_type_cmd(
    file: Annotated[
        Path,
        typer.Option("--file", help="Path to UDT-definition JSON (single UdtType or a list)."),
    ],
    provider: Annotated[
        str, typer.Option("--provider", help="Tag provider name")
    ] = "default",
    path: Annotated[
        str, typer.Option("--path", help="Folder path under the provider (slash-separated)")
    ] = "",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print the udts.json payload; no disk write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="POST /scan/config after a successful write. Default: scan."),
    ] = True,
) -> None:
    """Write a UDT *definition* (UdtType) to ``tag-type-definition`` on disk.

    Disk-only (UDT defs have no API import path). Pairs with ``ign tag push``
    for atomic tags / UDT instances.
    """
    types = _load_udt_types_file(file)
    if dry_run:
        typer.echo(json.dumps(udt_types_to_disk(types), indent=2))
        return
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None
    if scan:
        _acquire_config_lock(settings)  # released by scan_config() below
    try:
        dest = DiskBackend(settings).write_udt_types(provider, path, types)
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo(f"Written to disk: {dest}")
    if scan:
        try:
            with ScanClient(settings) as scan_client:
                scan_client.scan_config()
        except ScanWarning as e:
            typer.echo(
                f"WARNING: gateway scan failed for {dest}; the UDT type is on "
                f"disk but Designer may not see it until the next scan tick. Reason: {e}",
                err=True,
            )


def _parse_json_ish(raw: str) -> Any:
    """JSON-decode ``raw``, falling back to the bare string.

    So ``--value opc`` needs no quoting while ``--value 3`` / ``--value true``
    stay typed.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _patch_members(
    node: dict, prop: str, value: Any, where: tuple[str, Any] | None
) -> int:
    """Set ``prop`` on every member of ``node`` matching ``where``; return the
    number of members actually changed.

    Members are the entries of a node's ``tags`` list at ANY depth — UDT
    members nest through Folder members — so the walk recurses.
    """
    changed = 0
    for member in node.get("tags") or []:
        if not isinstance(member, dict):
            continue
        matches = where is None or member.get(where[0]) == where[1]
        if matches and member.get(prop) != value:
            member[prop] = value
            changed += 1
        changed += _patch_members(member, prop, value, where)
    return changed


@tag_app.command("set-udt-member-prop")
def set_udt_member_prop_cmd(
    prop: Annotated[
        str, typer.Option("--prop", help="Member property to set, e.g. 'opcServer'.")
    ],
    value: Annotated[
        str,
        typer.Option("--value", help="New value — JSON if parseable, else a plain string."),
    ],
    provider: Annotated[str, typer.Option("--provider", help="Tag provider name")] = "default",
    path: Annotated[
        str, typer.Option("--path", help="Folder path under the provider (slash-separated)")
    ] = "",
    where: Annotated[
        Optional[str],
        typer.Option(
            "--where",
            help="Only members whose KEY equals VALUE (e.g. 'valueSource=opc'). "
                 "Omit to hit every member.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print the patched payload; no disk write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="POST /scan/config after a successful write. Default: scan."),
    ] = True,
) -> None:
    """Set ONE property on the matching members of an EXISTING UDT definition file.

    The surgical counterpart to ``udt-type``, which replaces a whole
    ``udts.json`` from a supplied file. Here the file is read, only matched
    members are patched, every type is re-validated through ``UdtType``, and
    the full sibling list is written back — so nothing outside ``--prop`` moves
    and no member is dropped.
    """
    new_value = _parse_json_ish(value)
    clause: tuple[str, Any] | None = None
    if where is not None:
        key, sep, raw = where.partition("=")
        if not sep or not key:
            render_error(
                ValueError("--where must look like KEY=VALUE (e.g. valueSource=opc)"),
                no_color=False,
            )
            raise typer.Exit(code=1)
        clause = (key, _parse_json_ish(raw))
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None
    backend = DiskBackend(settings)
    try:
        nodes = backend.read_udt_types(provider, path)
    except TagNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    changed = sum(_patch_members(n, prop, new_value, clause) for n in nodes)
    try:
        types = [UdtType.model_validate(n) for n in nodes]
    except ValueError as e:
        render_error(PayloadError(f"patched UDT set is not valid - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    if dry_run:
        typer.echo(json.dumps(udt_types_to_disk(types), indent=2))
        typer.echo(f"Would set {prop} on {changed} member(s).", err=True)
        return
    if changed == 0:
        typer.echo(f"No change: {prop} is already {new_value!r} on every match.")
        return
    if scan:
        _acquire_config_lock(settings)  # released by scan_config() below
    dest = backend.write_udt_types(provider, path, types)
    typer.echo(f"Set {prop} on {changed} member(s); written to disk: {dest}")
    if scan:
        try:
            with ScanClient(settings) as scan_client:
                scan_client.scan_config()
        except ScanWarning as e:
            typer.echo(
                f"WARNING: gateway scan failed for {dest}; the UDT type is on "
                f"disk but Designer may not see it until the next scan tick. Reason: {e}",
                err=True,
            )


@tag_app.command("set-udt-type-prop")
def set_udt_type_prop_cmd(
    type_name: Annotated[
        str,
        typer.Option("--type", help="Name of the UDT TYPE in the file, e.g. '_Field'."),
    ],
    prop: Annotated[
        str, typer.Option("--prop", help="Type-level property to set, e.g. 'meta_hideOnDisabled'.")
    ],
    value: Annotated[
        str,
        typer.Option("--value", help="New value — JSON if parseable, else a plain string."),
    ],
    provider: Annotated[str, typer.Option("--provider", help="Tag provider name")] = "default",
    path: Annotated[
        str, typer.Option("--path", help="Folder path under the provider (slash-separated)")
    ] = "",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print the patched payload; no disk write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="POST /scan/config after a successful write. Default: scan."),
    ] = True,
) -> None:
    """Set ONE property on the TYPE NODE itself in an EXISTING UDT definition file.

    The sibling of ``set-udt-member-prop``, which patches a type's *members*.
    This one patches the type node — where the flat ``meta_*`` custom props that
    drive UDT-driven field views live. Everything else in the file (sibling
    types, members, key order) is read back and written unchanged.
    """
    new_value = _parse_json_ish(value)
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None
    backend = DiskBackend(settings)
    try:
        nodes = backend.read_udt_types(provider, path)
    except TagNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    matches = [n for n in nodes if n.get("name") == type_name]
    if not matches:
        render_error(ValueError(
            f"no UDT type named {type_name!r} in {provider}/{path}; "
            f"available: {[n.get('name') for n in nodes]}."
        ), no_color=False)
        raise typer.Exit(code=1)
    changed = 0
    for node in matches:
        if node.get(prop) != new_value:
            node[prop] = new_value
            changed += 1

    try:
        types = [UdtType.model_validate(n) for n in nodes]
    except ValueError as e:
        render_error(PayloadError(f"patched UDT set is not valid - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    if dry_run:
        typer.echo(json.dumps(udt_types_to_disk(types), indent=2))
        typer.echo(f"Would set {prop} on {changed} type(s).", err=True)
        return
    if changed == 0:
        typer.echo(f"No change: {prop} is already {new_value!r} on {type_name!r}.")
        return
    if scan:
        _acquire_config_lock(settings)  # released by scan_config() below
    dest = backend.write_udt_types(provider, path, types)
    typer.echo(f"Set {prop} on {changed} type(s); written to disk: {dest}")
    if scan:
        try:
            with ScanClient(settings) as scan_client:
                scan_client.scan_config()
        except ScanWarning as e:
            typer.echo(
                f"WARNING: gateway scan failed for {dest}; the UDT type is on "
                f"disk but Designer may not see it until the next scan tick. Reason: {e}",
                err=True,
            )


def _load_udt_instances_file(file: Path) -> list[UdtInstance]:
    """Load + validate UDT *instance*(s) from a JSON file into a UdtInstance list.

    Accepts a single UdtInstance object or a JSON list of them (the udts.json
    shape that lives under tag-definition/).
    """
    try:
        data = json.loads(file.read_text())
    except (OSError, json.JSONDecodeError) as e:
        render_error(ValueError(f"--file could not be read as JSON - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    items = data if isinstance(data, list) else [data]
    try:
        return [UdtInstance.model_validate(x) for x in items]
    except ValueError as e:
        render_error(PayloadError(f"--file is not a valid UDT instance set - {e}"), no_color=False)
        raise typer.Exit(code=1) from None


@tag_app.command("udt-instance")
def udt_instance_cmd(
    file: Annotated[
        Path,
        typer.Option("--file", help="Path to UDT-instance JSON (single UdtInstance or a list)."),
    ],
    provider: Annotated[
        str, typer.Option("--provider", help="Tag provider name")
    ] = "default",
    path: Annotated[
        str, typer.Option("--path", help="Folder path under the provider (slash-separated)")
    ] = "",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Print the udts.json payload; no disk write."),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option("--scan/--no-scan", help="POST /scan/config after a successful write. Default: scan."),
    ] = True,
) -> None:
    """Write UDT *instances* to ``tag-definition`` on disk.

    Mirrors ``udt-type`` but writes ``config/resources/core/ignition/
    tag-definition/<provider>/<path>/{udts.json,unary-resource.json}`` — the
    folder-shaped on-disk convention where each tag FOLDER is a directory
    holding udts.json (instances) and/or tags.json (atomic tags).

    Note this REPLACES the folder's udts.json wholesale; include every
    instance the folder should end up with. ``ign tag push`` (API backend)
    is the merge-capable path.
    """
    udts = _load_udt_instances_file(file)
    if dry_run:
        typer.echo(json.dumps(udts_to_disk(udts), indent=2))
        return
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(AuthMissingError(
            "check that IGNITION_API_TOKEN is set"
        ), no_color=False)
        raise typer.Exit(code=1) from None
    if scan:
        _acquire_config_lock(settings)  # released by scan_config() below
    try:
        dest = DiskBackend(settings).write_udts(provider, path, udts)
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo(f"Written to disk: {dest}")
    if scan:
        try:
            with ScanClient(settings) as scan_client:
                scan_client.scan_config()
        except ScanWarning as e:
            typer.echo(
                f"WARNING: gateway scan failed for {dest}; the UDT instance(s) are "
                f"on disk but Designer may not see them until the next scan tick. Reason: {e}",
                err=True,
            )


@tag_app.command("delete")
def delete_cmd(
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="Tag provider name (e.g. 'default').",
        ),
    ],
    path: Annotated[
        str,
        typer.Option(
            "--path",
            help="Tag path under the provider (slash-separated, e.g. 'Tanks/T01').",
        ),
    ],
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help="'instance' (tag-definition, default) or 'type' (tag-type-definition)",
        ),
    ] = "instance",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print the target directory; no filesystem change.",
        ),
    ] = False,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan/--no-scan",
            help=(
                "After a successful delete, POST /data/api/v1/scan/config "
                "to notify the gateway of the disk change. Pass --no-scan "
                "during local dev when the gateway is unreachable. Default: scan."
            ),
        ),
    ] = True,
) -> None:
    """Delete a tag-definition (or tag-type-definition) directory from disk.

    Removes the entire directory (tags.json / udts.json + unary-resource.json)
    under config/resources/core/ignition/tag-definition/<provider>/<path>/
    (``--kind instance``, default) or .../tag-type-definition/<provider>/<path>/
    (``--kind type``). The gateway picks up the removal on the next config
    scan (or immediately if --scan is active). Use --dry-run to preview the
    target path without removing anything.
    """
    if kind not in ("instance", "type"):
        render_error(
            ValueError(f"--kind must be one of 'instance', 'type' (got {kind!r})."),
            no_color=False,
        )
        raise typer.Exit(code=1)

    if dry_run:
        # Encode path segments for accurate display — mirrors view delete dry-run.
        # No Settings/IO needed for dry-run.
        from ..backends._fs_utils import _encode_segment as _enc
        try:
            enc_provider = _enc(provider)
        except ValueError as e:
            render_error(ValueError(f"invalid --provider - {e}"), no_color=False)
            raise typer.Exit(code=1) from None
        encoded_segments: list[str] = []
        for seg in path.split("/"):
            if not seg:
                continue
            try:
                encoded_segments.append(_enc(seg))
            except ValueError as e:
                render_error(ValueError(f"invalid --path - {e}"), no_color=False)
                raise typer.Exit(code=1) from None
        encoded_path = "/".join(encoded_segments)
        resource_type = "tag-type-definition" if kind == "type" else "tag-definition"
        display = f"config/resources/core/ignition/{resource_type}/{enc_provider}"
        if encoded_path:
            display = f"{display}/{encoded_path}"
        typer.echo(f"Would delete: {display}/")
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
        if kind == "type":
            dest = DiskBackend(settings).delete_udt_type(provider, path)
        else:
            dest = DiskBackend(settings).delete_tag(provider, path)
    except TagNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except ValueError as e:
        render_error(ValueError(f"invalid path - {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Deleted: {dest}")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_config()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed after deleting {dest}; "
            f"the change is on disk but Designer may not see it "
            f"until the next scan tick. Reason: {e}",
            err=True,
        )
