"""Token-redaction defense-in-depth scrub helper.

Pure str -> str function: masks any sequence matching
``<name>:<secret>`` to ``***REDACTED***``.

Defense in depth: the normal `ign api` path never emits the token to begin with
(the long-lived httpx Client owns the X-Ignition-API-Token header; the
token never enters argv, exception messages, or the request/response
payloads observed in the wild). This helper is the belt-and-suspenders
backstop against future regressions -- e.g. a hypothetical ``--verbose``
flag that dumps request headers, or a response body that happens to
echo the token back.

Usage:
    from ignition_gen_sdk.cli._redact import scrub_token
    typer.echo(scrub_token(text))

The secret must be 20+ chars (after the colon) -- shorter sequences are
too likely to collide with legitimate non-token text and would generate
false-positive redactions.
"""
from __future__ import annotations

import re

# Token shape: <name>:<secret>; secrets are long URL-safe strings, so a 20+ char body
# never collides with host:port or hh:mm text.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.\-]{1,64}:[A-Za-z0-9_\-]{20,}")


def scrub_token(text: str) -> str:
    """Return ``text`` with every <name>:<secret> token sequence redacted.

    Pure function -- no I/O, no logging, no side effects. Callers wrap
    every variable-content ``typer.echo`` site to mask any token that
    might leak through (defense-in-depth).

    Args:
        text: Arbitrary string -- response body, error message, etc.

    Returns:
        The input with every ``<name>:<secret>`` substring
        replaced by ``***REDACTED***``. Returns the input unchanged if
        no match is found.
    """
    return _TOKEN_PATTERN.sub("***REDACTED***", text)
