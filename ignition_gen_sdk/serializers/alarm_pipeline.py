"""Read and surgically edit an Ignition alarm-pipeline ``data.bin``.

An alarm pipeline is the one gateway resource with no write API and no text
form: it is a gzipped, binary-tokenised serialization that only the Designer
authors. That is a problem for a pipeline whose behaviour lives in inline
Jython, because the logic is then unversioned, unreviewable, and only editable
by hand in a GUI.

This module does NOT try to author a pipeline. It does exactly one thing: swap
the CONTENT of entries in the file's string pool, leaving the block graph
untouched. That is enough to lift every inline script out into a project
library call, which is the change that matters -- after it, the pipeline is
wired once and the behaviour is edited in git.

FORMAT (reverse-engineered; round-trips byte-exact on all four pipelines this
gateway ships)::

    [16-byte magic][u32 version][u64 epoch-ms][20 zero bytes]
    [u32 stringCount]
    [ (u32 id, u24 length, utf-8 bytes) * stringCount ]
    [node stream ...]

The node stream refers to strings BY ID, never by offset, so changing the bytes
of a pooled string -- and its length prefix -- cannot disturb the graph. That
property is the whole reason this is safe; anything that had to renumber ids or
move nodes would not be.
"""
from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass, field

# Offset of the string-pool count: 16 magic + 4 version + 8 timestamp + 20 pad.
_POOL_OFFSET = 0x30
_MAGIC_LENGTH = 16
# A u24 length prefix caps any single pooled string.
_MAX_STRING = (1 << 24) - 1


class AlarmPipelineFormatError(ValueError):
    """The file is not a pipeline data.bin this module understands."""


@dataclass
class AlarmPipeline:
    """A parsed pipeline: its header, its string pool, and its node stream."""

    header: bytes
    ids: list[int]
    strings: list[str]
    body: bytes
    # Set when the payload was gzipped, which is how it is stored on disk.
    gzipped: bool = True
    _index: dict = field(default_factory=dict, repr=False)

    @classmethod
    def parse(cls, raw: bytes) -> "AlarmPipeline":
        """Parse a data.bin, transparently ungzipping it."""
        gzipped = raw[:2] == b"\x1f\x8b"
        data = gzip.decompress(raw) if gzipped else raw
        if len(data) < _POOL_OFFSET + 4:
            raise AlarmPipelineFormatError(
                "file is too short to be an alarm pipeline (%d bytes)" % len(data))
        offset = _POOL_OFFSET
        (count,) = struct.unpack_from(">I", data, offset)
        offset += 4
        if count > 100000:
            raise AlarmPipelineFormatError(
                "implausible string-pool count %d; this is probably not a "
                "pipeline data.bin" % count)
        ids: list[int] = []
        strings: list[str] = []
        for _ in range(count):
            (sid,) = struct.unpack_from(">I", data, offset)
            offset += 4
            length = int.from_bytes(data[offset:offset + 3], "big")
            offset += 3
            if offset + length > len(data):
                raise AlarmPipelineFormatError(
                    "string pool runs past end of file; format not recognised")
            ids.append(sid)
            # surrogateescape, not "replace". "replace" turns any byte that is
            # not strict UTF-8 into U+FFFD, and emit() then writes those three
            # replacement bytes back -- a silent corruption that grows the file
            # and cannot be detected by re-parsing, because the lossy decode is
            # idempotent. surrogateescape round-trips arbitrary bytes exactly,
            # which makes byte-exactness a property of the codec rather than a
            # lucky consequence of every pipeline on this gateway being ASCII.
            strings.append(data[offset:offset + length].decode("utf-8", "surrogateescape"))
            offset += length
        return cls(header=data[:_POOL_OFFSET], ids=ids, strings=strings,
                   body=data[offset:], gzipped=gzipped)

    def emit(self) -> bytes:
        """Serialize back, re-gzipping when the source was gzipped."""
        parts = [self.header, struct.pack(">I", len(self.strings))]
        for sid, text in zip(self.ids, self.strings):
            encoded = text.encode("utf-8", "surrogateescape")
            if len(encoded) > _MAX_STRING:
                raise AlarmPipelineFormatError(
                    "string of %d bytes exceeds the format's 24-bit length "
                    "field" % len(encoded))
            parts.append(struct.pack(">I", sid))
            parts.append(len(encoded).to_bytes(3, "big"))
            parts.append(encoded)
        parts.append(self.body)
        data = b"".join(parts)
        # mtime=0 so the same input always produces the same bytes; a gzip
        # header carrying "now" would make every write look like a change.
        return gzip.compress(data, mtime=0) if self.gzipped else data

    def find(self, text: str) -> list[int]:
        """Indexes of pool entries exactly equal to `text`."""
        return [i for i, s in enumerate(self.strings) if s == text]

    def replace(self, old: str, new: str) -> int:
        """Replace every pool entry exactly equal to `old`.

        Exact whole-string matching, not substring: a pooled string is one
        complete value (a script body, an expression, a property name), and a
        substring edit could silently corrupt an unrelated entry that happened
        to share a prefix.

        Args:
            old (str): Existing pool entry, matched in full.
            new (str): Replacement.
        Returns:
            int: How many entries were replaced.
        Raises:
            KeyError: When nothing matched.
        """
        hits = self.find(old)
        if not hits:
            raise KeyError(old)
        for i in hits:
            self.strings[i] = new
        return len(hits)

    def scripts(self, minimum_lines: int = 1) -> list[tuple[int, str]]:
        """Pool entries that look like Jython bodies.

        A pipeline stores script blocks tab-indented and with no `def` header,
        which is a distinctive enough shape to pick out of the pool without
        walking the node stream.

        Args:
            minimum_lines (int): Ignore anything shorter.
        Returns:
            list: (poolIndex, text) for each candidate.
        """
        found = []
        for i, text in enumerate(self.strings):
            if not text.startswith("\t"):
                continue
            if len(text.splitlines()) < minimum_lines:
                continue
            found.append((i, text))
        return found
