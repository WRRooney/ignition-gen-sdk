"""resource_metadata — emits resource.json sidecar for Perspective views.

Verified live shape across Designer-exported view fixtures:
- scope "G", version 1, restricted False, overridable True (universal)
- files: ["view.json"] on write; Designer appends "thumbnail.png" after
  it generates the thumbnail on first open (see view_resource_json for why
  it must NOT be pre-listed).

``attributes`` carries an ign origin
marker via ``lastModification.actor = "ign"``. The signature
cannot be fabricated (HMAC over Designer-side state) so it is
omitted; Designer will write a real ``lastModificationSignature``
on first save. Documenting the actor at least leaves an audit
trail of which writer touched the resource last.

Distinct from tag unary-resource.json (different filename, different
files contents, different attributes shape).
"""
from __future__ import annotations

from datetime import datetime, timezone


def style_class_resource_json() -> dict:
    """resource.json for a style-classes/<name>/ resource.

    Same envelope as views but files=["style.json"] — verified vs
    a Designer-written style-classes/<name>/resource.json."""
    out = view_resource_json()
    out["files"] = ["style.json"]
    return out


def stylesheet_resource_json() -> dict:
    """resource.json for the perspective stylesheet resource.

    Same envelope as views but files=["stylesheet.css"] — verified vs
    a Designer-written stylesheet/resource.json."""
    out = view_resource_json()
    out["files"] = ["stylesheet.css"]
    return out


def named_query_resource_json(attributes: dict) -> dict:
    """resource.json for a named-query resource.

    A named query has NO config.json — ``attributes`` carries the whole query
    configuration (database, parameters, caching). ``scope`` is "DG" and
    ``version`` 2, both distinct from every other project resource; verified
    against ExchangeResources/ignition/named-query/DMC/Analysis/*/resource.json.
    """
    return {
        "scope": "DG",
        "version": 2,
        "restricted": False,
        "overridable": True,
        "files": ["query.sql"],
        "attributes": dict(
            attributes,
            lastModification={
                "actor": "ign",
                "timestamp": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            },
        ),
    }


def view_resource_json(documentation: str | None = None) -> dict:
    """Return a fresh dict matching the Designer-exported shape.

    Each call constructs a NEW dict (so mutation by the caller does
    not pollute subsequent callers) and a fresh ISO-8601 UTC timestamp
    (so the lastModification.timestamp reflects when the write
    happened, not module-load time). ``documentation`` (Designer view
    docs — e.g. an MIT notice on derived artwork) sits right after
    ``scope``, where the Designer writes it; omitted when empty.
    """
    return {
        "scope": "G",
        **({"documentation": documentation} if documentation else {}),
        "version": 1,
        "restricted": False,
        "overridable": True,
        # List ONLY view.json. Pre-listing thumbnail.png
        # "harmlessly" — but the gateway log sweep proved it is NOT harmless: a
        # manifest that lists a file ign never writes makes the gateway throw
        # NoSuchFileException + log an ERROR on EVERY project scan
        # ("Error creating dataFile ... file=thumbnail.png"). The thumbnail is
        # optional (Designer generates it on first open + appends it to files),
        # so omitting it is correct and silences the recurring error.
        "files": ["view.json"],
        # Carry an actor stamp; signature is intentionally omitted
        # (Designer rewrites both on first save).
        "attributes": {
            "lastModification": {
                "actor": "ign",
                "timestamp": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        },
    }


def page_config_resource_json() -> dict:
    """resource.json sidecar for the Perspective page-config resource.

    Same scope/metadata shape as views, but ``files`` is ["config.json"]
    (verified against an on-disk page-config). Signature omitted — the
    gateway recomputes lastModificationSignature on scan.
    """
    return {
        "scope": "G",
        "version": 1,
        "restricted": False,
        "overridable": True,
        "files": ["config.json"],
        "attributes": {
            "lastModification": {
                "actor": "ign",
                "timestamp": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        },
    }


def session_props_resource_json() -> dict:
    """resource.json sidecar for the Perspective session-props resource.

    ``files`` is ["props.json"] (verified against on-disk session-props).
    Signature omitted — the gateway recomputes it on scan.
    """
    return {
        "scope": "G",
        "version": 1,
        "restricted": False,
        "overridable": True,
        "files": ["props.json"],
        "attributes": {
            "lastModification": {
                "actor": "ign",
                "timestamp": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        },
    }
