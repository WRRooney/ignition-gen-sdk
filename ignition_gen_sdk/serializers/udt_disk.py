"""UdtDiskSerializer — emits the FLAT udts.json format (no 'usr' wrapper).

Verified ground truth from
config/resources/core/ignition/tag-definition/<provider>/<path>/udts.json:

    [
      {
        "name": "Pump01",
        "typeId": "Pump",
        "parameters": {"deviceRoot": {"dataType": "String", "value": "..."}},
        "tagType": "UdtInstance"
      }
    ]

UDT instances are NEVER 'usr'-wrapped. The 'usr' envelope is specific to
``tags.json`` (AtomicTag / Folder rows). Applying the wrapper to UDT
content corrupts the gateway's parser.
"""
from __future__ import annotations

from typing import Any, List

from ..models.tags.udt import UdtInstance, UdtType


def _gateway_key_order(node: Any) -> Any:
    """Recursively order dict keys the way the gateway serializes udts.json:
    ASCII-alphabetical (``bindType`` < ``binding``), with the ``tags``
    (children) array forced LAST. Verified against Designer-written udts.json:
    meta_* … name, tagType, tooltip, typeColor, typeId, tags. Keeps
    ign writes git-diff-minimal against Designer-saved files."""
    if isinstance(node, dict):
        keys = sorted(node.keys(), key=lambda k: (k == "tags", k))
        return {k: _gateway_key_order(node[k]) for k in keys}
    if isinstance(node, list):
        return [_gateway_key_order(v) for v in node]
    return node


def udts_to_disk(udts: List[UdtInstance]) -> list[dict]:
    """Produce the full ``udts.json`` content (flat list, no 'usr' wrapper)."""
    return [_gateway_key_order(u.model_dump(exclude_none=True, mode="json")) for u in udts]


def udt_types_to_disk(types: List[UdtType]) -> list[dict]:
    """Produce the ``udts.json`` content for UDT *definitions* (tag-type-definition).

    Same flat-list, no-'usr'-wrapper rule as instances. Each entry is a
    ``UdtType`` carrying its member ``tags``/``parameters``. Goes under
    ``config/resources/core/ignition/tag-type-definition/<provider>/<path>/udts.json``.
    """
    return [_gateway_key_order(t.model_dump(exclude_none=True, mode="json")) for t in types]
