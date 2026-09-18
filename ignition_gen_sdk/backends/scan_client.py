"""ScanClient — POST /data/api/v1/scan/projects and /data/api/v1/scan/config.

Used after on-disk writes under projects/** or config/resources/** to
notify the Ignition gateway that the filesystem changed. Without these
calls, Designer/runtime keeps a stale view of disk until the next
scheduled scan tick.

Endpoints (verified from the generated api_reference/config-management.md):
- POST /data/api/v1/scan/projects -> { scanActive, lastScanTimestamp, lastScanDuration }
- POST /data/api/v1/scan/config   -> { scanActive, lastScanTimestamp, lastScanDuration }

Auth: X-Ignition-API-Token header. Same header-composition logic as
IgnitionAPIClient (api_client.py): if Settings.ignition_api_key already
is the full ``<name>:<secret>`` header value (validated by Settings).

Best-effort: any failure mode raises ScanWarning. The caller has
already completed its disk write; ScanWarning is for stderr + exit-0
surfacing, NOT for hard-failing the user command.
"""
from __future__ import annotations

from typing import Optional

import httpx

from ..config import Settings


_PROJECTS_PATH = "/data/api/v1/scan/projects"
_CONFIG_PATH = "/data/api/v1/scan/config"
_CONFIG_LOCK_PATH = "/data/api/v1/scan-lock/config"


class ScanWarning(Exception):
    """Raised on any non-2xx or transport error.

    Translated by callers to a stderr ``WARNING:`` line; the disk write
    has already succeeded by the time scan_*() is invoked.
    """


class ScanClient:
    """Sync httpx wrapper for the gateway scan endpoints.

    Use as a context manager to ensure the underlying TCP connection
    pool is closed::

        with ScanClient(Settings()) as c:
            c.scan_projects()
    """

    def __init__(
        self,
        settings: Settings,
        *,
        timeout: float = 5.0,
        _transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        """Construct the client.

        ``_transport`` is a test-only injection hook for
        ``httpx.MockTransport``. Production callers MUST NOT supply it.
        """
        key = settings.ignition_api_key
        token_header = key
        client_kwargs: dict = {
            "base_url": str(settings.ignition_base_url),
            "headers": {"X-Ignition-API-Token": token_header},
            "timeout": timeout,
        }
        if _transport is not None:
            client_kwargs["transport"] = _transport
        self._client = httpx.Client(**client_kwargs)

    def _post(self, path: str, json: Optional[dict] = None) -> None:
        try:
            r = self._client.post(path, json=json)
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.TransportError,
        ) as e:
            raise ScanWarning(
                f"scan POST {path} failed: {type(e).__name__}: {e}"
            ) from e
        if not (200 <= r.status_code < 300):
            # Slice response body to bound disclosure of any server-side leakage.
            raise ScanWarning(
                f"scan POST {path} returned HTTP {r.status_code}: "
                f"{r.text[:200]}"
            )

    def scan_projects(self) -> None:
        """POST /data/api/v1/scan/projects (notify gateway of projects/** disk change)."""
        self._post(_PROJECTS_PATH)

    def scan_config(self) -> None:
        """POST /data/api/v1/scan/config (notify gateway of config/resources/** disk change).

        Also RELEASES a config scan lock held via :meth:`acquire_config_lock`.
        """
        self._post(_CONFIG_PATH)

    def acquire_config_lock(
        self, *, acquire_timeout: int = 10, hold_timeout: int = 60
    ) -> None:
        """POST /data/api/v1/scan-lock/config — hold the config scan lock.

        The gateway queues (blocks) every other config change while the lock
        is held, which is what makes an external write + ``scan_config()``
        atomic from the gateway's point of view: without it the gateway may
        pick a disk edit up mid-write and apply its own internal collision
        policy (the ``abort collision policy`` errors).

        The NEXT ``scan_config()`` releases the lock; if it never runs, the
        lock self-expires after ``hold_timeout`` seconds. Always pair the two.

        Raises :class:`ScanWarning` like the scan calls — failing to get the
        lock is a warning, never fatal.
        """
        self._post(
            _CONFIG_LOCK_PATH,
            {"acquireTimeout": acquire_timeout, "holdTimeout": hold_timeout},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ScanClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
