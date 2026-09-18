"""Push manifest — atomic JSON file per resource-type.

Location: <state-dir>/manifest/<resource-type>.json (default ./.ign/manifest/)
Gitignored — tooling-local state, not committed.

Shape:
    {
        "<resource-id>": {
            "payload": {...} | [...], # JSON-serializable; matches the
                                      # SHAPE that lives in the live artifact
                                      # (api envelope for api backend; bare
                                      # disk-shape list for disk backend per
                                      # disk shape). cmd_diff loads the current
                                      # artifact and compares sha256.
            "sha256": "<64-hex>",     # sha256(canonical_bytes) where canonical
                                      # uses sort_keys=True, separators=(',',':')
            "timestamp": "<iso8601>", # UTC
            "backend": "api|disk"
        },
        ...
    }

resource-id conventions:
    tags:      <provider>/<path>   (e.g., "default/Tanks/T01")
    views:     <project>/<path>    (e.g., "MyProject/Main/Overview")
    providers: <provider-name>     (e.g., "default")

The stored sha256 is computed over the CANONICAL form of the
payload (sort_keys=True, separators=(',',':')). The on-disk artifact
is pretty-printed (json.dumps indent=2). These two byte streams are
NOT identical; do NOT hash the file bytes directly to verify
integrity. cmd_diff re-parses the file and re-canonicalizes via
_sha256(parsed_dict), so this works as long as the SHAPE matches.

NEVER call record() inside dry-run branches.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Union

# Manifests live in the SDK state dir under the caller's cwd (IGNITION_STATE_DIR, default .ign/).
_MANIFEST_ROOT = Path(os.environ.get("IGNITION_STATE_DIR", ".ign")) / "manifest"


def _sha256(payload: Any) -> str:
    """Compute sha256 of payload using canonical JSON bytes.

    Accepts dict OR list (the disk backend stores bare lists to match
    the on-disk tags.json shape).

    CRITICAL: Always use separators=(',',':') for canonical form.
    json.dumps(..., sort_keys=True) alone still adds spaces after : and ,
    by default — those spaces change the hash. separators=(',',':') removes
    all whitespace for a stable, reproducible canonical form.

    NOTE: this hash is computed over the CANONICAL DICT, NOT over
    the bytes of the file on disk. The on-disk artifact uses
    json.dumps(payload, indent=2) which produces a DIFFERENT byte stream
    than the canonical form. Do NOT compare manifest.sha256 against
    sha256(file.read_bytes()) — they will not match even if the file is
    semantically identical to the manifest. cmd_diff parses the file
    first and re-canonicalizes via _sha256(parsed_dict), so its
    comparison is correct.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def record(
    resource_type: str,
    resource_id: str,
    payload: Union[dict, list],
    backend: str,
) -> None:
    """Write (or overwrite) manifest entry for resource_id.

    Atomic: writes to a .tmp file then renames. Safe against partial-write
    corruption.

    Never call this on the dry-run code path.
    """
    _MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = _MANIFEST_ROOT / f"{resource_type}.json"

    existing: dict = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}  # corrupt manifest — start fresh

    existing[resource_id] = {
        "payload": payload,
        "sha256": _sha256(payload),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
    }

    from ..backends._fs_utils import _atomic_write  # deferred to avoid circular import

    _atomic_write(manifest_path, json.dumps(existing, indent=2))


def read(resource_type: str, resource_id: str) -> dict | None:
    """Return manifest entry for resource_id, or None if not present."""
    manifest_path = _MANIFEST_ROOT / f"{resource_type}.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data.get(resource_id)


def read_all(resource_type: str) -> dict:
    """Return full manifest for a resource-type, or empty dict."""
    manifest_path = _MANIFEST_ROOT / f"{resource_type}.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
