"""OpenAPI path resolver — always-on light validation.

load_spec() parses <state-dir>/openapi.json once per process
(module-level cache keyed by the resolved Path) and returns the parsed
dict. resolve_path_against_spec() validates (method, path) against the
spec's `paths` mapping with template-segment substitution:

- A literal path equal to a spec key passes.
- A literal path that matches a template key segment-by-segment (where
  spec segments of the form `{param}` accept any non-empty concrete
  literal segment) passes. The candidate must NOT itself contain `{...}`
  segments (those represent unsubstituted templates and are rejected so
  the caller supplies a real value).
- A miss raises UnknownPathError.
- A path that matches but whose method is not in the operations dict
  raises MethodNotAllowedError. Method comparison is case-insensitive.

This module exists so cli.cmd_api can fail fast before any HTTP round-trip
when the path or method is wrong. The cache means a long-lived skill loop
of calls pays the parse cost once, not per invocation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..backends.api_client import MethodNotAllowedError, UnknownPathError
from ..config import Settings


# Module-level cache: resolved spec Path -> parsed dict. One entry per
# distinct openapi_spec_path; identity test in the unit suite asserts
# repeated load_spec(settings) calls return the SAME dict object.
_SPEC_CACHE: dict[Path, dict[str, Any]] = {}


# A template segment looks like `{name}`. Used to detect both spec
# placeholders and rejection of user-supplied unsubstituted templates.
_TEMPLATE_SEG = re.compile(r"^\{[^/{}]+\}$")


def load_spec(settings: Settings) -> dict[str, Any]:
    """Read settings.openapi_spec_path once; return the cached parsed dict.

    The cache key is the resolved Path so callers with different Settings
    instances that point at the same file share a cache entry.
    """
    key = settings.openapi_spec_path.resolve()
    cached = _SPEC_CACHE.get(key)
    if cached is not None:
        return cached
    if not key.exists():
        from ..regen.engine import fetch_spec  # noqa: PLC0415

        fetch_spec(settings)  # first use: pull the spec from the gateway
    with key.open("r", encoding="utf-8") as fp:
        spec = json.load(fp)
    _SPEC_CACHE[key] = spec
    return spec


def _match_path(candidate: str, spec_path: str) -> bool:
    """Segment-by-segment match between a concrete candidate and a spec key.

    Returns True only if the segment counts match AND every segment is
    either a literal equality OR the spec segment is a `{param}` template
    accepting the candidate's literal value. A `{...}` template literal in
    the candidate is rejected (caller must substitute a real value).
    """
    if candidate == spec_path:
        return True
    cand_segs = candidate.split("/")
    spec_segs = spec_path.split("/")
    if len(cand_segs) != len(spec_segs):
        return False
    for c, s in zip(cand_segs, spec_segs):
        if _TEMPLATE_SEG.match(s):
            # Spec template segment -- accept any non-empty literal
            # candidate segment that is itself NOT a template literal.
            if not c or _TEMPLATE_SEG.match(c):
                return False
            continue
        if c != s:
            return False
    return True


def resolve_path_against_spec(
    settings: Settings, method: str, path: str,
) -> None:
    """Validate (method, path) against the OpenAPI spec; raise on mismatch.

    Raises:
        UnknownPathError: path is not in the spec (including the case of
            an unsubstituted `{name}` literal in the candidate).
        MethodNotAllowedError: path matched but the method is not in the
            matched operations dict.

    Returns:
        None on success. Callers proceed with the HTTP call.
    """
    spec = load_spec(settings)
    paths_obj = spec.get("paths") or {}

    # Strip query string + fragment before spec lookup. The validator
    # only cares about the path portion; httpx forwards the original
    # path?query verbatim to the gateway.
    path_only = path.split("?", 1)[0].split("#", 1)[0]

    # Reject early any candidate that still contains an unsubstituted
    # template segment -- otherwise the segment matcher below would let
    # a literal `{name}` masquerade as a real value via direct equality
    # to the spec key.
    for seg in path_only.split("/"):
        if _TEMPLATE_SEG.match(seg):
            raise UnknownPathError(
                f"path '{path}' contains an unsubstituted template segment "
                f"'{seg}' -- supply a concrete value"
            )

    # Try literal match first, then template-aware match.
    matched_key: str | None = None
    if path_only in paths_obj:
        matched_key = path_only
    else:
        for spec_path in paths_obj:
            if _match_path(path_only, spec_path):
                matched_key = spec_path
                break

    if matched_key is None:
        raise UnknownPathError(f"path '{path}' not in openapi.json")

    operations = paths_obj[matched_key] or {}
    method_lower = method.lower()
    # OpenAPI operation keys are lowercase HTTP verbs; ignore the other
    # PathItem fields (summary, parameters, etc.) which are not verbs.
    http_verbs = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
    allowed = sorted(
        k.upper() for k in operations.keys() if k.lower() in http_verbs
    )
    if method_lower not in {m.lower() for m in allowed}:
        raise MethodNotAllowedError(
            f"method '{method.upper()}' not allowed on '{matched_key}' "
            f"-- allowed: {allowed}"
        )

    return None
