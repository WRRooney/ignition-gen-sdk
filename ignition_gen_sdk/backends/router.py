"""WriteRouter — single entry point for tag-push operations.

Callers (CLI, builders, future Perspective code) use ``WriteRouter.push_tags``
without caring whether the destination is the gateway HTTP API or the disk.
The router owns three pieces of policy:

1. **Static resource-type → default-backend map** (``_DEFAULT_BACKEND``)
   — declarative mapping. Tag imports default to API, disk-only
   resource shapes default to disk. Future Perspective views slot in here.
   The map is informational/extension-point; per-call ``backend=`` always
   overrides.

2. **Dry-run** — ``dry_run=True`` prints the would-be import body to stdout
   as JSON and returns ``[]`` without calling any backend. Useful for CLI
   ``--dry-run`` and test harnesses. The output is the Provider-root
   envelope produced by ``tags_to_import_body``.

3. **Auto fallback** — ``backend="auto"`` (default) tries the API first.
   On ``GatewayError`` (5xx — transient gateway-side failure) it falls
   back to disk. **Other errors propagate**:

   - ``PayloadError`` (400) is a programmer error — payload shape is wrong;
     falling back to disk would just hide the bug and write garbage.
   - ``AuthMissingError`` (401) and ``AuthScopeError`` (403) indicate
     credential or permission problems; falling back to disk could let
     unauthorized callers persist data through a different path.

"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from ..models.tags.tag import Tag
from ..serializers.tag_api import tags_to_import_body
from .api_backend import ApiBackend
from .api_client import GatewayError
from .disk_backend import DiskBackend


class AutoFallbackToDisk(GatewayError):
    """Raised by ``push_tags(backend="auto")`` after
    the gateway 5xx triggered a successful fallback write to disk.

    Inherits from ``GatewayError`` so existing ``except GatewayError``
    handlers still catch the underlying transient failure, but
    ``isinstance(e, AutoFallbackToDisk)`` lets fresh handlers
    distinguish "wrote to disk because gateway was 5xx" from "gateway
    5xx with no disk write attempted".

    The disk write completed before this exception is raised; callers
    should treat the situation as a WARNING (not an error), trigger a
    gateway scan, and surface the disk path so the user knows where
    the tags actually landed.
    """

    def __init__(self, disk_path: Path, gateway_error: GatewayError) -> None:
        super().__init__(
            f"gateway returned 5xx (auto fallback to disk at {disk_path}): "
            f"{gateway_error}"
        )
        self.disk_path = disk_path
        self.gateway_error = gateway_error

BackendChoice = Literal["api", "disk", "auto"]

# Resource-type → default backend map.
#
# This is the declarative source of truth for "which backend handles this
# resource type by default". It's currently informational — push_tags
# accepts a per-call ``backend=`` override. A future API may expose
# ``WriteRouter.push(resource_type=...)`` that consults the map directly.
#
# - tag_import          → API   (the gateway's /tags/import is the canonical path)
# - tag_definition_disk → disk  (callers explicitly need disk-format tags.json)
# - perspective_view    → disk  (Perspective views are file-only)
_DEFAULT_BACKEND: dict[str, BackendChoice] = {
    "tag_import": "api",
    "tag_definition_disk": "disk",
    "perspective_view": "disk",
}


class WriteRouter:
    """Routes tag-push operations to either the API or disk backend."""

    def __init__(self, api: ApiBackend, disk: DiskBackend) -> None:
        self._api = api
        self._disk = disk

    def push_tags(
        self,
        provider: str,
        path: str,
        tags: list[Tag],
        *,
        dry_run: bool = False,
        backend: BackendChoice = "auto",
        collision_policy: str = "Overwrite",
    ) -> Any:
        """Push tags to gateway (API) or filesystem (disk).

        Args:
            provider: Tag provider name (e.g. ``"default"``).
            path: Slash-separated path under the provider (``""`` = root).
            tags: List of ``Tag`` objects.
            dry_run: If True, print Provider-root JSON to stdout and return
                ``[]`` without calling any backend.
            backend: ``"api"`` | ``"disk"`` | ``"auto"`` (default).
            collision_policy: Forwarded to API backend; ignored for disk.
                Defaults to ``"Overwrite"`` — a tag push is an authoring
                edit, so the file being pushed is the intended end state.
                ``"MergeOverwrite"`` keeps stale members that were deleted
                from the source. Override per call when merging is wanted.

        Returns:
            For API backend: whatever ``ApiBackend.import_tags`` returns
            (typically ``{successCount, failureCount, failures}`` from
            gateway 8.3.4). For disk backend or dry-run: ``[]``.

        Raises:
            ValueError: if ``backend`` is not one of the allowed strings.
            PayloadError, AuthMissingError, AuthScopeError: surfaced from
                the API backend (NOT swallowed by auto fallback — see
                module docstring for rationale).
        """
        if backend not in ("api", "disk", "auto"):
            raise ValueError(
                f"Invalid backend {backend!r}. Choose 'api', 'disk', or 'auto'."
            )

        # Build the payload eagerly so dry-run sees the exact same shape
        # the API would receive.
        payload = tags_to_import_body(tags)

        if dry_run:
            # Pretty-print so a human can eyeball the structure. Return
            # an empty list (no diagnostics) so the caller's contract
            # matches the disk-write path.
            print(json.dumps(payload, indent=2))
            return []

        if backend == "disk":
            self._disk.write_tags(provider, path, tags)
            return []

        if backend == "api":
            return self._api.import_tags(provider, path, payload, collision_policy)

        # backend == "auto": API first, fall back to disk on 5xx only.
        try:
            return self._api.import_tags(provider, path, payload, collision_policy)
        except GatewayError as e:
            # Transient gateway-side failure — try disk so the work isn't lost.
            disk_path = self._disk.write_tags(provider, path, tags)
            # Signal the fallback to the caller via
            # AutoFallbackToDisk so it can warn the user and trigger a
            # scan. Previously this swallowed the GatewayError and
            # returned [] -- _print_diagnostics then printed "Push
            # successful." which hid the fact that the gateway was
            # unreachable AND the file is sitting on disk waiting for a
            # scan tick.
            raise AutoFallbackToDisk(disk_path, e) from e
        # PayloadError / AuthMissingError / AuthScopeError intentionally NOT
        # caught — they are programmer or operator errors, not transient
        # network conditions. Falling back would mask the real problem.
