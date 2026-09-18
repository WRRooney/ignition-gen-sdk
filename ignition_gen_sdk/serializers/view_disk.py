"""ViewDiskSerializer — emits view.json content (flat, no envelope).

Mirrors the udt_disk.py pattern (flat model_dump pass-through), NOT
the tag_disk.py pattern (which wraps in 'usr' envelope — tag-specific).

``exclude_none=True`` strips Pydantic FIELDS whose value is
None — it does NOT strip nested dict entries with None values. So
``View.params={"TankNo": None}`` correctly serializes to JSON ``null``.
That is intentional for declared properties (a param/custom key must
exist even with no value), but NOT for ``position``/``props``, where the
Designer deletes unset keys on save — see _NULL_STRIPPED_SUBTREES.
"""
from __future__ import annotations

from typing import Any

from ..models.views.view import View


# Subtrees the Designer strips nulls from on save. A null INSIDE position/props
# is an unset layout or style value: the Designer deletes the key outright, so
# emitting it produces a phantom diff on every round-trip. Everywhere else a
# null is a DECLARED property with no value yet (params.tagPath, custom.value)
# and deleting the key would delete the declaration — never strip those.
_NULL_STRIPPED_SUBTREES = ("position", "props")


def _drop_nulls(node: Any) -> Any:
    """Recursively drop dict entries whose value is None."""
    if isinstance(node, dict):
        return {k: _drop_nulls(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [_drop_nulls(v) for v in node]
    return node


def _sorted_keys(node: Any) -> Any:
    """Recursive ASCII key sort — Designer/gateway serialize view.json with
    all object keys sorted (verified across Designer-written views). Keeps
    ign writes git-diff-minimal against Designer-saved files.

    Doubles as the null-strip pass for `position`/`props` subtrees, for the
    same diff-minimal reason (see _NULL_STRIPPED_SUBTREES)."""
    if isinstance(node, dict):
        out = {}
        for k in sorted(node):
            v = _sorted_keys(node[k])
            out[k] = _drop_nulls(v) if k in _NULL_STRIPPED_SUBTREES else v
        return out
    if isinstance(node, list):
        return [_sorted_keys(v) for v in node]
    return node


def view_to_disk(view: View) -> dict:
    """Produce the full view.json content (model emit, Designer key order)."""
    return _sorted_keys(view.model_dump(exclude_none=True, mode="json"))
