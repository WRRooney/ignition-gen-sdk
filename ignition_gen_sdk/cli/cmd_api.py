"""ign api -- generic Ignition HTTP API call (curl-like positional surface).

Single Typer command that wraps IgnitionAPIClient.request() behind a
curl-like `METHOD PATH` interface so scripts and agent skills can call any
`/data/api/v1/*` endpoint WITHOUT shelling `curl` (which would leak the
X-Ignition-API-Token via process args, curl -v header echo, and the agent's
tool-output context).

Order of operations inside the command callback (top-to-bottom, ALL
BEFORE the network call):

1. Uppercase ``method``.
2. Resolve body via ``_read_body(json, file)`` -- ValueError if both passed.
3. Call ``_refuse_jwe_in_body(body)`` -- recursive dict walk; raises
   PayloadError with the JWE refusal message if {ciphertext,
   encrypted_key, iv, protected, tag} is a subset of any nested dict's
   keys.
4. ``_get_api()`` -- constructs Settings + IgnitionAPIClient (this
   surfaces missing-creds via AuthMissingError + render_error before
   any other step).
5. ``resolve_path_against_spec(settings, method, path)`` -- light
   always-on validation. Raises UnknownPathError /
   MethodNotAllowedError.
6. If ``--strict``: lazy-import ``openapi_core`` and call
   ``_validate_body_strict(...)`` -- surface failing JSON pointer
   via ``PayloadError(...)``.
7. Confirmation gate -- non-GET/HEAD/OPTIONS in a tty without
   ``--confirm`` prompts via ``typer.confirm(..., abort=True)``.
8. ``--dry-run`` -- print the planned request as indented JSON; exit 0.
9. Otherwise -- ``client.request(method, path, json=body)``; on success
   print ``response.json() if response.text else {}`` as indented JSON.

The error block matches the canonical five-clause order from
``cmd_provider.py`` (do not reorder; log scanners assert this). Every echo
of variable content is wrapped in ``scrub_token()``
so a hypothetical future ``--verbose`` flag (or a response body that
happens to echo the token) cannot leak it to stdout/stderr
(defense in depth).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from ..backends.api_client import (
    AuthMissingError,
    AuthScopeError,
    GatewayError,
    IgnitionAPIClient,
    MethodNotAllowedError,
    NetworkError,
    PayloadError,
    UnknownPathError,
)
from ..config import Settings
from ..models.databases import JWE_KEYS_REQUIRED
from ._errors import render_error
from ._openapi_resolver import load_spec, resolve_path_against_spec
from ._redact import scrub_token

# Single-verb Typer command (no subgroup) -- skill bodies become
# `Bash(ign api METHOD /path)`.
api_app = typer.Typer(
    name="api",
    help="Generic Ignition HTTP API call (curl-like positional METHOD + PATH).",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _get_api() -> tuple[Settings, IgnitionAPIClient]:
    """Construct Settings + IgnitionAPIClient; surface missing-creds cleanly.

    Mirrors ``cmd_provider._get_api`` but returns the bare client rather
    than wrapping in ApiBackend -- ``cmd_api`` consumes ``client.request()``
    directly.
    """
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as e:  # noqa: BLE001
        render_error(
            AuthMissingError(
                f"check IGNITION_API_TOKEN (env or .env) ({e})"
            ),
            no_color=False,
        )
        raise typer.Exit(code=1) from None
    client = IgnitionAPIClient(settings)
    return settings, client


def _read_body(
    json_arg: str | None,
    file_arg: str | None,
) -> dict[str, Any] | list[Any] | None:
    """Resolve request body from --json '...' OR --file body.json.

    Returns None for no body (GET/HEAD/DELETE without payload). Mutually
    exclusive -- raises ValueError with a clear message if BOTH ``--json``
    and ``--file`` are passed (clearer mistake signal).
    """
    if json_arg is not None and file_arg is not None:
        raise ValueError("--json and --file are mutually exclusive")
    if json_arg is not None:
        return json.loads(json_arg)
    if file_arg is not None:
        text = sys.stdin.read() if file_arg == "-" else Path(file_arg).read_text(encoding="utf-8")
        return json.loads(text)
    return None


def _refuse_jwe_in_body(body: Any) -> None:
    """Refuse any request body containing the canonical JWE key signature.

    Walks the body recursively (dicts + lists); raises PayloadError with
    the JWE refusal message if ``JWE_KEYS_REQUIRED`` is a subset of
    any nested dict's keys. Mirrors the ConnectionConfig password field-validator
    but generalized to arbitrary request shapes.
    """
    if body is None:
        return

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if JWE_KEYS_REQUIRED.issubset(node.keys()):
                raise PayloadError(
                    "JWE credential payload refused: request body contains an AES-256-GCM "
                    "JWE credential payload. Set encrypted values via the "
                    "Gateway UI."
                )
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(body)


def _validate_body_strict(
    settings: Settings,
    method: str,
    path: str,
    body: Any,
) -> None:
    """Deep schema validation via openapi-core (lazy import).

    Only imported / instantiated when ``--strict`` is passed (see
    api_cmd step 6). Construct an OpenAPI app from the cached spec dict
    (``load_spec`` reuses the resolver cache), build a
    ``MockRequest`` with the body serialized as JSON bytes, and surface
    the first iter_request_errors failure as a ``PayloadError`` whose
    message carries the failing JSON pointer (e.g. ``$.name``).

    The lazy import means the lean install (no [strict] extras) still
    imports cmd_api at module-level cleanly. Users who pass ``--strict``
    accept the openapi-core cold-start cost.

    Raises:
        PayloadError: validation failed; the message includes the JSON
            pointer of the failing field plus the underlying message.
    """
    # Lazy import -- only when --strict is on the command line.
    try:
        from openapi_core import Config, OpenAPI
        from openapi_core.testing import MockRequest
    except ImportError as e:
        raise PayloadError(
            "strict validation requires the [strict] extras -- run "
            "`pip install -e tools/ignition_gen_sdk[strict]` to install openapi-core"
        ) from e

    spec_dict = load_spec(settings)
    # spec_validator_cls=None: the Ignition openapi.json uses x-* style
    # extension fields (e.g. `internal: False` on path-items) that the
    # strict openapi-spec-validator schema rejects. Skip the spec-shape
    # validator and trust the path/method validation that
    # already performed (resolve_path_against_spec ran in step 5).
    oa = OpenAPI.from_dict(spec_dict, config=Config(spec_validator_cls=None))

    # MockRequest carries the body as bytes + content-type so openapi-core
    # deserializes it through the same media-type pipeline as a real
    # request. base_url is a stub; openapi-core only uses it for
    # server-base resolution which we are not asserting on here.
    data_bytes = json.dumps(body).encode("utf-8") if body is not None else b""
    mock = MockRequest(
        host_url="http://localhost",
        method=method.lower(),
        path=path,
        data=data_bytes,
        content_type="application/json",
    )

    for err in oa.iter_request_errors(mock):
        # Walk the cause chain to find the underlying jsonschema
        # ValidationError (which has json_path / message). openapi-core
        # wraps it inside InvalidRequestBody -> InvalidSchemaValue ->
        # ValidationError-tuple. If we cannot dig out a json_path we
        # still surface the top error message.
        cause = err.__cause__
        pointer: str | None = None
        sub_msg: str | None = None
        while cause is not None:
            if hasattr(cause, "schema_errors"):
                for se in cause.schema_errors:
                    pointer = getattr(se, "json_path", None) or pointer
                    sub_msg = getattr(se, "message", None) or sub_msg
                    break
            cause = cause.__cause__

        if pointer or sub_msg:
            raise PayloadError(
                f"strict validation failed: {pointer or '$'}: {sub_msg or err}"
            )
        raise PayloadError(f"strict validation failed: {err}")


# ---------------------------------------------------------------------------
# Single command (positional METHOD + PATH; curl-like surface)
#
# Exported BOTH as a standalone function (registered on the outer Typer
# app via `app.command("api")(api_cmd)` -- mirrors cmd_diff.py since
# this is a single-verb command, not a subgroup) AND as a callback on
# the local `api_app` (preserves the artifact contract; some test
# patterns instantiate api_app directly).
# ---------------------------------------------------------------------------

def api_cmd(
    method: Annotated[
        str,
        typer.Argument(help="HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)."),
    ],
    path: Annotated[
        str,
        typer.Argument(help="API path starting with /, e.g. /data/api/v1/gateway-info."),
    ],
    json_body: Annotated[
        str | None,
        typer.Option("--json", help="JSON request body as a literal string."),
    ] = None,
    file_body: Annotated[
        str | None,
        typer.Option("--file", help="Path to JSON request body file, or '-' for stdin."),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Deep schema validation via openapi-core (body + query + path params).",
        ),
    ] = False,
    confirm: Annotated[
        bool,
        typer.Option(
            "--confirm",
            help="Skip confirmation prompt for non-GET/HEAD/OPTIONS methods.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print the planned request to stdout; do not send.",
        ),
    ] = False,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Suppress Rich color output."),
    ] = False,
) -> None:
    """Generic Ignition HTTP API call. Curl-like positional METHOD + PATH.

    The X-Ignition-API-Token NEVER appears in argv -- it is read once
    from .env via Settings and lives only inside the
    long-lived httpx Client's header dict. This closes the curl-in-skills
    leak surface.
    """
    method = method.upper()

    # 1. Body resolution.
    try:
        body = _read_body(json_body, file_body)
    except ValueError as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1) from None
    except (OSError, json.JSONDecodeError) as e:
        render_error(
            ValueError(f"could not parse request body: {e}"),
            no_color=no_color,
        )
        raise typer.Exit(code=1) from None

    # 2. JWE refusal (before any HTTP call).
    try:
        _refuse_jwe_in_body(body)
    except PayloadError as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1)

    # 3. Settings + client construction (surfaces missing-creds cleanly).
    settings, client = _get_api()

    # 4. Light validation (always-on).
    try:
        resolve_path_against_spec(settings, method, path)
    except (UnknownPathError, MethodNotAllowedError) as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1)

    # 5. Strict validation (opt-in, lazy openapi-core import).
    if strict:
        try:
            _validate_body_strict(settings, method, path, body)
        except PayloadError as e:
            render_error(e, no_color=no_color)
            raise typer.Exit(code=1)

    # 6. Confirmation gate for non-GET/HEAD/OPTIONS in a tty.
    if method not in ("GET", "HEAD", "OPTIONS") and not confirm and sys.stdin.isatty():
        typer.confirm(f"{method} {path} -- proceed?", abort=True)

    # 7. Dry-run short-circuit -- print planned request as JSON, no HTTP.
    if dry_run:
        typer.echo(scrub_token(json.dumps({"method": method, "path": path, "body": body}, indent=2)))
        return

    # 8. The actual call. Five-clause error block matches cmd_provider.py
    #    canonical order verbatim (log scanners assert this ordering).
    try:
        response = client.request(method, path, json=body)
        typer.echo(scrub_token(json.dumps(response.json() if response.text else {}, indent=2)))
    except AuthMissingError as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1)
    except AuthScopeError as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1)
    except PayloadError as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1)
    except GatewayError as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1)
    except NetworkError as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1)
    except ValueError as e:
        render_error(e, no_color=no_color)
        raise typer.Exit(code=1)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


# Register api_cmd on the local api_app so callers who invoke api_app
# directly (e.g. some test patterns) also get a working command. The
# outer ign app routes via `app.command("api")(api_cmd)` in
# cli/__init__.py -- single-verb apps cannot be added via add_typer()
# without Typer demanding a (non-existent) sub-subcommand placeholder.
api_app.command(name="run", hidden=True)(api_cmd)
