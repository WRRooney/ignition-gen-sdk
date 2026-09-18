"""DiskBackend — atomic disk writes for tag-definition resources.

Writes ``tags.json`` (or ``udts.json``) plus the ``unary-resource.json``
sidecar to the gateway's ``core`` config layer:

    config/resources/core/ignition/tag-definition/<provider>/<path>/

Two safety rails are in place:

1. **Layer guard** — refuses to write under ``config/resources/local/``.
   The default ``_core_root`` always points at ``core``, but the guard is
   defense-in-depth in case the root is overridden.
2. **Path traversal** — ``_encode_segment`` rejects exact ``.``, ``..``,
   and whitespace-only segments (raises ``ValueError``). Other strings
   containing ``/`` or ``\\`` are percent-encoded so a single segment
   like ``"../local"`` becomes ``"..%2Flocal"`` and cannot escape.
   Defense-in-depth: ``_tag_def_path`` resolves the final path and
   asserts it sits under ``config/resources/core/ignition/tag-definition/``.

Atomic writes use ``Path.write_text`` to a ``.tmp`` file followed by
``Path.replace()`` (POSIX-atomic on the same filesystem). If the process
is killed mid-write, the ``.tmp`` is never renamed — the gateway never
sees a partially written ``tags.json``.

"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, List

from ..config import Settings
from ..models.tags.tag import Tag
from ..models.tags.udt import UdtInstance, UdtType
from ..serializers.tag_disk import tags_to_disk
from ..serializers.udt_disk import udt_types_to_disk, udts_to_disk
from ._fs_utils import _atomic_write, _encode_segment
from .project_disk import dumps_designer


class TagNotFoundError(FileNotFoundError):
    """Raised when the target tag-definition directory does not exist on disk."""

# Exact unary-resource.json fields, verified across multiple live gateway paths
# (standard, managed and System providers). 'files' is a placeholder the writer
# fills in; it sits HERE because a dict update keeps an existing key's original
# position, and the gateway emits 'files' before 'attributes'.
_UNARY_RESOURCE_BASE = {
    "scope": "G",
    "version": 1,
    "restricted": False,
    "overridable": True,
    "files": [],
    "attributes": {"config": {}},
}


class DiskBackend:
    """Writes tag-definition resources to ``config/resources/core/``."""

    def __init__(self, settings: Settings) -> None:
        self._core_root = (
            settings.ignition_data_root / "config" / "resources" / "core"
        )

    def _tag_def_path(self, provider: str, path: str) -> Path:
        """Resolve the tag-definition directory for a given provider + path.

        ``path`` is slash-separated (e.g. ``"Tanks/T01"``). Each segment
        and the provider go through ``_encode_segment`` which rejects
        ``.``, ``..``, and whitespace-only segments (shared
        with ProjectDiskBackend). Defense-in-depth: the resolved result
        must sit inside ``self._core_root / "ignition" / "tag-definition"``
        before being returned.
        """
        tag_def_root = self._core_root / "ignition" / "tag-definition"
        base = tag_def_root / _encode_segment(provider)
        if not path:
            result = base
        else:
            result = base
            for raw in path.split("/"):
                if not raw:
                    continue
                result = result / _encode_segment(raw)
        # Containment check (defense-in-depth, mirrors project_disk.py).
        result_resolved = Path(str(result)).resolve(strict=False)
        tag_def_root_resolved = tag_def_root.resolve()
        if (
            result_resolved != tag_def_root_resolved
            and tag_def_root_resolved not in result_resolved.parents
        ):
            raise ValueError(
                f"resolved tag-definition path containment violation: "
                f"{result_resolved} is not inside {tag_def_root_resolved}"
            )
        return result

    def _assert_not_local(self, resolved: Path) -> None:
        """Raise ValueError if the resolved path is under config/resources/local/.

        Defense-in-depth: ``_core_root`` defaults to ``.../core/`` so this
        only triggers if the caller has overridden ``_core_root`` or the
        OS resolved a symlink to ``local/``.
        """
        s = str(resolved.resolve())
        if "/config/resources/local/" in s or s.endswith(
            "/config/resources/local"
        ):
            raise ValueError(
                "Layer guard violation: writes to config/resources/local/ "
                "are forbidden for tag-definition resources. Use "
                f"config/resources/core/ instead. Resolved path: {resolved}"
            )

    #: Data files a tag-definition folder resource may hold side by side.
    _DATA_FILES = ("tags.json", "udts.json")

    def _write_payload_with_sidecar(
        self,
        dest: Path,
        payload_filename: str,
        payload_text: str,
    ) -> None:
        """Common write path: ensure dir, write payload, write sidecar.

        The sidecar ``files`` list is the UNION of the payload being written
        and any pre-existing sibling data file (a folder holds tags.json
        AND/OR udts.json). Listing only the payload would un-manifest the
        sibling — on a cold gateway load the unlisted file's tags vanish
        (a udts.json dir whose sidecar said ["tags.json"] would have dropped
        its UDT instances on restart).
        """
        dest.mkdir(parents=True, exist_ok=True)
        _atomic_write(dest / payload_filename, payload_text)
        files = sorted(
            {payload_filename}
            | {f for f in self._DATA_FILES if (dest / f).exists()}
        )
        sidecar = {**_UNARY_RESOURCE_BASE, "files": files}
        _atomic_write(dest / "unary-resource.json", dumps_designer(sidecar))

    def write_tags(
        self, provider: str, path: str, tags: List[Tag], wrap_usr: bool = False
    ) -> Path:
        """Write ``tags.json`` + ``unary-resource.json``.

        FLAT by default: 'usr' is the MANAGED-provider override envelope (see
        serializers/tag_disk.py). Pass ``wrap_usr=True`` only when writing into
        a MANAGED (driver-owned, e.g. MQTT) provider.

        Returns the directory the files were written to.
        """
        dest = self._tag_def_path(provider, path)
        self._assert_not_local(dest)
        payload = tags_to_disk(tags, wrap_usr)
        self._write_payload_with_sidecar(
            dest, "tags.json", dumps_designer(payload)
        )
        return dest

    def write_udts(
        self, provider: str, path: str, udts: List[UdtInstance]
    ) -> Path:
        """Write ``udts.json`` (flat) + ``unary-resource.json``.

        Returns the directory the files were written to.
        """
        dest = self._tag_def_path(provider, path)
        self._assert_not_local(dest)
        payload = udts_to_disk(udts)
        self._write_payload_with_sidecar(
            dest, "udts.json", dumps_designer(payload)
        )
        return dest

    def _tag_type_def_path(self, provider: str, path: str) -> Path:
        """Resolve the tag-TYPE-definition directory (UDT definitions).

        Like :meth:`_tag_def_path` but rooted at
        ``ignition/tag-type-definition`` — a distinct resource type from
        tag-definition (where instances/atomic tags live). Same segment
        encoding + containment guard.
        """
        root = self._core_root / "ignition" / "tag-type-definition"
        result = root / _encode_segment(provider)
        if path:
            for raw in path.split("/"):
                if raw:
                    result = result / _encode_segment(raw)
        result_resolved = Path(str(result)).resolve(strict=False)
        root_resolved = root.resolve()
        if (
            result_resolved != root_resolved
            and root_resolved not in result_resolved.parents
        ):
            raise ValueError(
                f"resolved tag-type-definition path containment violation: "
                f"{result_resolved} is not inside {root_resolved}"
            )
        return result

    def write_udt_types(
        self, provider: str, path: str, types: List[UdtType]
    ) -> Path:
        """Write a UDT *definition* ``udts.json`` (flat) + ``unary-resource.json``
        under ``config/resources/core/ignition/tag-type-definition/``.

        Returns the directory written to. Gateway needs a `/scan/config` after.
        """
        dest = self._tag_type_def_path(provider, path)
        self._assert_not_local(dest)
        payload = udt_types_to_disk(types)
        self._write_payload_with_sidecar(
            dest, "udts.json", dumps_designer(payload)
        )
        return dest

    def read_udt_types(self, provider: str, path: str) -> List[Any]:
        """Read the raw UDT *definition* list out of an existing ``udts.json``.

        Returns raw dicts rather than :class:`UdtType` so a caller can patch a
        single key and re-validate on the way out; round-trip fidelity through
        ``UdtType`` is CI-locked (tests/test_ix_ground_truth_roundtrip.py), so
        the untouched siblings survive the rewrite byte-identical.

        Raises :class:`TagNotFoundError` if the file does not exist.
        """
        src = self._tag_type_def_path(provider, path) / "udts.json"
        if not src.exists():
            raise TagNotFoundError(
                f"UDT type definition not found at {src}; "
                f"check --provider ({provider!r}) and --path ({path!r}) are correct."
            )
        data = json.loads(src.read_text())
        return data if isinstance(data, list) else [data]

    def delete_tag(self, provider: str, path: str) -> Path:
        """Remove the tag-definition directory (tags.json / udts.json + sidecar) from disk.

        Uses :meth:`_tag_def_path` — the same resolver as ``write_tags`` /
        ``write_udts`` — so the containment guard and segment encoding are
        inherited automatically.

        Raises :class:`TagNotFoundError` if the directory does not exist.
        Raises :class:`ValueError` if the path fails the containment guard
        (path traversal / outside tag-definition root).
        """
        dest = self._tag_def_path(provider, path)
        self._assert_not_local(dest)

        if not dest.exists():
            raise TagNotFoundError(
                f"Tag definition not found at {dest}; "
                f"check --provider ({provider!r}) and --path ({path!r}) are correct."
            )

        shutil.rmtree(dest)
        return dest

    # ------------------------------------------------------------------
    # Perspective themes
    # ------------------------------------------------------------------
    #: Module id owning the ``themes`` config resource type.
    _PERSPECTIVE = "com.inductiveautomation.perspective"

    #: Theme names the Perspective module owns. ``copy-base-themes`` writes
    #: these into ``core`` so they can be READ, but the gateway ignores any
    #: edit to them — writing one would be a silent no-op, so refuse.
    BASE_THEME_NAMES = frozenset({"light", "dark"})

    def _theme_path(self, name: str) -> Path:
        root = self._core_root / self._PERSPECTIVE / "themes"
        dest = root / _encode_segment(name)
        resolved = dest.resolve()
        if not str(resolved).startswith(str(root.resolve()) + "/"):
            raise ValueError(
                f"theme {name!r} resolves outside {root} (path traversal): {resolved}"
            )
        self._assert_not_local(dest)
        return dest

    def list_themes(self) -> List[str]:
        """Theme names present in ``core`` (read-only)."""
        root = self._core_root / self._PERSPECTIVE / "themes"
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir() if (p / "config.json").is_file())

    def write_theme(
        self,
        name: str,
        files: dict,
        *,
        entrypoint: str = "index.css",
        description: str = "",
        is_private: bool = False,
    ) -> Path:
        """Write a Perspective theme resource: ``files`` + config.json + resource.json.

        ``files`` maps filename -> text content. The ``entrypoint`` must be one
        of them, otherwise the gateway loads a theme that renders nothing.
        Themes are THIN by convention — they ``@import`` a base theme's
        stylesheets and override the handful of custom properties they mean to
        change — so no attempt is made to validate the CSS itself.
        """
        if name in self.BASE_THEME_NAMES:
            raise ValueError(
                f"{name!r} is a Perspective BASE theme. copy-base-themes writes it "
                "into core so it can be read, but the gateway ignores every edit to "
                "it — a write here would silently do nothing. Create a new theme "
                "that @imports it instead."
            )
        if entrypoint not in files:
            raise ValueError(
                f"entrypoint {entrypoint!r} is not among the supplied files "
                f"({sorted(files)!r}); the theme would load nothing."
            )
        for fname in files:
            _encode_segment(fname)  # reject '..', '/', empty

        dest = self._theme_path(name)
        dest.mkdir(parents=True, exist_ok=True)
        for fname, text in sorted(files.items()):
            _atomic_write(dest / fname, text)
        _atomic_write(
            dest / "config.json",
            dumps_designer({"entrypoint": entrypoint, "isPrivate": is_private}),
        )
        # The stamp is load-bearing, not bookkeeping: Perspective compiles a
        # theme the first time it is used and keys the result on the theme
        # NAME, so a rewrite of the same name is served from that cache and the
        # new CSS never reaches a client. A changed lastModification is what
        # tells the config layer the resource actually moved.
        from datetime import datetime, timezone

        _atomic_write(
            dest / "resource.json",
            dumps_designer(
                {
                    "scope": "G",
                    "description": description or f"The {name} theme for Perspective.",
                    "version": 1,
                    "restricted": False,
                    "overridable": True,
                    "files": sorted({*files, "config.json"}),
                    "attributes": {
                        "lastModification": {
                            "actor": "ign",
                            "timestamp": datetime.now(timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                        }
                    },
                }
            ),
        )
        return dest

    def delete_theme(self, name: str) -> Path:
        """Remove a theme directory from ``core``."""
        dest = self._theme_path(name)
        if not dest.exists():
            raise FileNotFoundError(
                f"Theme not found at {dest}; check --name ({name!r})."
            )
        shutil.rmtree(dest)
        return dest

    def delete_udt_type(self, provider: str, path: str) -> Path:
        """Remove the tag-type-definition directory (udts.json + sidecar) from disk.

        Uses :meth:`_tag_type_def_path` — the same resolver as
        ``write_udt_types`` — so the containment guard and segment encoding
        are inherited automatically.

        Raises :class:`TagNotFoundError` if the directory does not exist.
        Raises :class:`ValueError` if the path fails the containment guard
        (path traversal / outside tag-type-definition root).
        """
        dest = self._tag_type_def_path(provider, path)
        self._assert_not_local(dest)

        if not dest.exists():
            raise TagNotFoundError(
                f"UDT type definition not found at {dest}; "
                f"check --provider ({provider!r}) and --path ({path!r}) are correct."
            )

        shutil.rmtree(dest)
        return dest
