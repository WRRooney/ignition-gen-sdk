"""TagDiskSerializer — emits tags.json, FLAT by default.

Verified ground truth from live MANAGED-provider paths
(config/resources/core/ignition/tag-definition/<managed provider>/...):

    [
      {
        "usr": {"readOnly": false, "dataType": "Boolean", "enabled": true},
        "name": "online",
        "tagType": "AtomicTag"
      }
    ]

Rule: only ``name``, ``tagType``, and ``tags`` are top-level. Every other
emitted field — including ``alarms``, ``alarmEvalEnabled``, ``historyEnabled``,
``opcItemPath``, ``opcServer``, etc. — goes under ``"usr"``.

Recursion: ``tags`` (children) is wrapped at every level, not flattened.
"""
from __future__ import annotations

from typing import List

from ..models.tags.tag import Tag
# tags.json and udts.json are written by the same gateway serializer, so they
# want the same key order. Reused rather than re-derived: emitting Pydantic
# field order instead made every tags.json write a whole-file diff against the
# Designer's copy, which buries the one line that actually changed.
from .udt_disk import _gateway_key_order

# Top-level keys that stay at the dict root in disk format.
# Everything else gets demoted under 'usr'.
_TOP_LEVEL_KEYS = frozenset({"name", "tagType", "tags"})


def tag_to_disk_format(tag: Tag, wrap_usr: bool = False) -> dict:
    """Convert a Tag to its disk dict.

    ``wrap_usr`` selects the envelope, and the DEFAULT IS FLAT because that is
    what a STANDARD tag provider stores. Every STANDARD provider's tags.json
    is flat (including Designer-written folders); the ONLY 'usr'-wrapped
    files belong to MANAGED (driver-owned, e.g. MQTT) providers, where 'usr'
    is the user-override envelope over driver-supplied config. Emitting
    'usr' into a STANDARD provider produces a tag the gateway does not read
    back the way it was written, so pass ``wrap_usr=True`` only for MANAGED
    providers.

    Recursive: each child Tag in ``tag.tags`` is converted with the same
    envelope choice, using the original Tag object.
    """
    flat = tag.model_dump(exclude_none=True, mode="json")
    if not wrap_usr:
        top = dict(flat)
        if tag.tags:
            top["tags"] = [tag_to_disk_format(child, wrap_usr) for child in tag.tags]
        return top
    top: dict = {k: flat[k] for k in _TOP_LEVEL_KEYS if k in flat}
    usr = {k: v for k, v in flat.items() if k not in _TOP_LEVEL_KEYS}
    if usr:
        top["usr"] = usr
    # Re-apply the wrapper to children using the original Tag objects so
    # nested children also receive their own 'usr' envelope. ``flat["tags"]``
    # would already be a list of plain dicts (not 'usr'-wrapped) because
    # ``model_dump`` does a flat recursive emit.
    if tag.tags:
        top["tags"] = [tag_to_disk_format(child, wrap_usr) for child in tag.tags]
    return top


def tags_to_disk(tags: List[Tag], wrap_usr: bool = False) -> list[dict]:
    """Produce the full ``tags.json`` content (a list of disk-format tags).

    Flat by default — see :func:`tag_to_disk_format` for why 'usr' is
    MANAGED-provider-only. Keys come out in the gateway's own order so a write
    diffs against a Designer save on the values that changed, and nothing else.
    """
    return [_gateway_key_order(tag_to_disk_format(t, wrap_usr)) for t in tags]
