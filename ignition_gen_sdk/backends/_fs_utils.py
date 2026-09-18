"""Shared filesystem helpers used by DiskBackend and ProjectDiskBackend.

Hardened against path traversal and empty-segment corruption. The
public guarantees enforced here:

1. ``_encode_segment`` rejects exact ``.``, ``..``, whitespace-only,
   empty segments, and any segment containing ``/``, ``\\``, or NUL
   (raises ValueError). These rejections prevent both directory
   traversal AND silent multi-segment-to-single-segment misuse.

2. Segments are NOT percent-encoded for ASCII
   spaces or other URL-reserved characters. The gateway uses LITERAL
   spaces in disk paths (``Home/Home Large``, ``Area 1``,
   ``Layouts/Layout Card``). Encoding spaces to ``%20`` produces
   directories the gateway does not recognize. The only character
   the live gateway is observed to encode is ``:`` -> ``%3a``;
   this helper mirrors that single substitution and otherwise
   returns the segment verbatim.

3. Callers (ProjectDiskBackend.write_view, DiskBackend._tag_def_path)
   additionally ``Path.resolve()`` the final destination and assert it
   sits inside their declared write root. Defense-in-depth in case
   a future rule change slips through guard #1.
"""
from __future__ import annotations

from pathlib import Path

# Characters that may NEVER appear inside a single segment. ``/`` and ``\\``
# are path separators; allowing them in a single segment would silently
# turn a single-segment caller into a multi-segment write. ``\x00`` is the
# filesystem-end-of-string marker on POSIX.
_FORBIDDEN_CHARS = frozenset({"/", "\\", "\x00"})


def _encode_segment(segment: str) -> str:
    """Validate a single path segment and return its on-disk form.

    Rejects (raises ValueError):
    - The exact string ``"."`` (current-directory marker)
    - The exact string ``".."`` (parent-directory marker)
    - Empty or whitespace-only segments
    - Segments containing ``/``, ``\\``, or NUL (multi-segment misuse
      or filesystem-illegal characters)

    Otherwise mirrors the live gateway's encoding rule: only ``:`` is
    substituted with ``%3a``; ASCII spaces and other characters pass
    through verbatim. The gateway uses literal spaces in directory
    names (verified across Designer exports + live config/resources/
    fixtures) so encoding spaces to ``%20`` produces unrecognized
    paths.
    """
    if not segment or not segment.strip():
        raise ValueError(
            f"path segment is empty or whitespace-only: {segment!r}"
        )
    if segment in (".", ".."):
        raise ValueError(
            f"path segment {segment!r} is a directory-traversal marker "
            f"and is forbidden; use an explicit subdirectory name instead"
        )
    bad = [ch for ch in segment if ch in _FORBIDDEN_CHARS]
    if bad:
        raise ValueError(
            f"path segment {segment!r} contains forbidden character(s) "
            f"{sorted(set(bad))!r} (slash, backslash, or NUL); pass each "
            f"path component as a separate segment instead"
        )
    # Match the gateway's observed encoding rule: only ``:`` is escaped
    # (to lowercase %3a, matching live managed-provider paths like ``light%3a0``).
    return segment.replace(":", "%3a")


# ↓ existing _atomic_write preserved below ↓
def _atomic_write(path: Path, content: str) -> None:
    """Write content to ``path`` via a sibling ``.tmp`` + atomic rename.

    On POSIX, ``Path.replace`` calls ``rename(2)`` which is atomic on the
    same filesystem. If the process dies between ``write_text`` and
    ``replace``, the ``.tmp`` survives but the destination is unchanged —
    the gateway only ever sees the prior or the new file, never a mix.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """Binary counterpart of :func:`_atomic_write`.

    Alarm pipelines are gzipped binary, and a half-written one would be a
    resource the gateway cannot deserialize at all — exactly the case the
    write-to-temp-then-rename dance exists for.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
