"""ign logs — query the gateway log (the runtime-debugging verb).

Wraps GET /data/api/v1/logs. The first-class way to read gateway Jython
tracebacks + errors — e.g. a Perspective onStartup failure or a project-library
module that "Could not initialize". Read-only.

WHY: without an easy log-read verb, a wrong "needs reload" theory can run
for a long time while the real cause sits in the gateway log ("Could not
initialize project script module 'plant.nav'" + stack). After a scan, if a
view/script/tag misbehaves, check here BEFORE assuming structure.

Examples:
    ign logs --min-level ERROR --limit 20
    ign logs --search buildNavTree --stack
    ign logs --logger plant.nav --since-min 15
"""
from __future__ import annotations

import json
import time
from typing import Annotated, Optional
from urllib.parse import urlencode

import typer

from ..backends.api_client import (
    AuthMissingError,
    AuthScopeError,
    GatewayError,
    IgnitionAPIClient,
    NetworkError,
    PayloadError,
)
from ..config import Settings
from ._errors import render_error


def logs_cmd(
    search: Annotated[Optional[str], typer.Option("--search", help="Substring to match in the log message.")] = None,
    min_level: Annotated[Optional[str], typer.Option("--min-level", help="Minimum level: TRACE/DEBUG/INFO/WARN/ERROR.")] = None,
    logger: Annotated[Optional[str], typer.Option("--logger", help="Exact logger name (e.g. plant.nav).")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max entries.")] = 25,
    since_min: Annotated[Optional[int], typer.Option("--since-min", help="Only entries from the last N minutes.")] = None,
    stack: Annotated[bool, typer.Option("--stack/--no-stack", help="Print stack trace lines for ERROR entries.")] = False,
    as_json: Annotated[bool, typer.Option("--json/--no-json", help="Emit raw JSON instead of formatted lines.")] = False,
) -> None:
    """Query the gateway log (GET /data/api/v1/logs). Read-only runtime debugging."""
    params: dict = {"limit": limit, "sortBy": "timestamp"}
    if search:
        params["search"] = search
    if min_level:
        params["minLevel"] = min_level.upper()
    if logger:
        params["logger"] = logger
    if since_min:
        params["startTime"] = int(time.time() * 1000) - int(since_min) * 60000

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as e:  # noqa: BLE001
        render_error(AuthMissingError(f"check IGNITION_API_TOKEN (env or .env) ({e})"), no_color=False)
        raise typer.Exit(code=1) from None

    client = IgnitionAPIClient(settings)
    try:
        resp = client.request("GET", "/data/api/v1/logs?" + urlencode(params))
        data = resp.json() if resp.text else {}
    except (AuthMissingError, AuthScopeError, PayloadError, GatewayError, NetworkError, ValueError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    finally:
        try:
            client.close()
        except Exception:
            pass

    items = data.get("items", data if isinstance(data, list) else [])
    if as_json:
        typer.echo(json.dumps(items, indent=2))
        return
    if not items:
        typer.echo("(no matching log entries)")
        return
    now_ms = max((it.get("timestamp", 0) for it in items), default=0)
    for it in items:
        age = (now_ms - it.get("timestamp", 0)) / 60000.0
        lvl = it.get("level", "?")
        lg = (it.get("loggerName", "") or "")[-44:]
        msg = (it.get("message", "") or "").replace("\n", " ")
        typer.echo(f"[{age:5.0f}m] {lvl:5} {lg} :: {msg[:200]}")
        if stack and lvl == "ERROR":
            for line in (it.get("stack") or [])[:8]:
                typer.echo(f"        {line}")
