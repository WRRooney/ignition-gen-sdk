"""Centralized error rendering for ign CLI commands.

Provides _should_color(no_color_flag) for the no-color.org precedence gate
and render_error(exc, *, no_color) to write Error: + Hint: to stderr.

Rich color + one-line Hint per error code. No --error-json mode is implemented.
Centralizes isatty() + NO_COLOR env + --no-color flag so every command except
block calls render_error() instead of duplicating the color/hint logic.

Precedence for color gating (https://no-color.org):
1. --no-color flag (explicit) -> suppress color
2. NO_COLOR env var set (any value) -> suppress color
3. sys.stdout.isatty() -> use its value
"""
from __future__ import annotations

import os
import sys

import typer

from ..backends.api_client import (
    AuthMissingError,
    AuthScopeError,
    GatewayError,
    MethodNotAllowedError,
    NetworkError,
    PayloadError,
    UnknownPathError,
)

# Hint strings — one line per error class.
_HINTS: dict[type, str] = {
    AuthMissingError: "Check IGNITION_API_TOKEN (env or .env) is the full name:secret; over http://, turn off 'Require secure connections' on the gateway API key",
    AuthScopeError: "The API key cannot write — give it a security level listed in Gateway Write Permissions (Platform > Security > General Settings)",
    PayloadError: "Server response body included above — paste into gateway logs for context",
    GatewayError: "Gateway error — retry after ensuring the gateway is up",
    NetworkError: "Network error — check IGNITION_URL is reachable from this host (use http://localhost:PORT if running outside docker network)",
    # Light-validation errors raised by cli._openapi_resolver.
    UnknownPathError: "Path not in openapi.json. Check <state-dir>/api_reference/INDEX.md for valid paths.",
    MethodNotAllowedError: (
        "Method not allowed on this path. "
        "See <state-dir>/api_reference/INDEX.md for the path's operations."
    ),
}

# Per-exception label prefix; classifies stderr for log scanning.
_LABELS: dict[type, str] = {
    AuthMissingError: "Auth error",
    AuthScopeError: "Permission error",
    PayloadError: "Payload error",
    GatewayError: "Gateway error",
    NetworkError: "Network error",
    UnknownPathError: "Path error",
    MethodNotAllowedError: "Method error",
}


def _should_color(no_color_flag: bool) -> bool:
    """Return True if Rich color output is appropriate.

    Precedence per https://no-color.org:
    1. no_color_flag True -> return False (explicit flag wins)
    2. NO_COLOR env var set to any value -> return False
    3. sys.stdout.isatty() -> return its value
    """
    if no_color_flag:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def render_error(exc: Exception, *, no_color: bool = False) -> None:
    """Print Error: + Hint: to stderr. Color gated by _should_color().

    Error strings are preserved verbatim — this function only
    adds Rich coloring and a Hint suffix. The token is never logged
    (the token never appears in exception messages; only the fixed
    hint string is added for AuthMissingError).
    """
    msg = str(exc)
    hint = _HINTS.get(type(exc))
    label = _LABELS.get(type(exc), "Error")

    if _should_color(no_color):
        try:
            from rich.console import Console

            console = Console(stderr=True, highlight=False)
            console.print(f"[bold red]{label}:[/bold red] {msg}")
            if hint:
                console.print(f"[dim]Hint:[/dim] {hint}")
            return
        except ImportError:
            pass  # fall through to plain typer.echo

    typer.echo(f"{label}: {msg}", err=True)
    if hint:
        typer.echo(f"Hint: {hint}", err=True)
