"""Builder + serializer emit the registered type string for every container root."""
from __future__ import annotations

import pytest

from ignition_gen_sdk.builders.view import ViewBuilder
from ignition_gen_sdk.serializers.view_disk import view_to_disk


# ---- Builder-emitted minimal view round-trips through serializer ----

@pytest.mark.parametrize("container,expected_type", [
    ("flex", "ia.container.flex"),
    ("coord", "ia.container.coord"),
    ("split", "ia.container.split"),
    ("tab", "ia.container.tab"),
    ("breakpoint", "ia.container.breakpt"),
    ("column", "ia.container.column"),
])
def test_minimal_builder_view_serializes_consistently(container: str, expected_type: str):
    """Builder + serializer produces a view whose root.type matches the registry.

    Constructs a minimal one-method ViewBuilder chain and verifies the emitted
    JSON has the locked type-string. Any drift between containers.py Literal
    and ViewBuilder._root() construction would surface here.
    """
    method = getattr(ViewBuilder(), f"{container}_root")
    view = method().build()
    out = view_to_disk(view)

    assert out["root"]["type"] == expected_type
    assert out["root"]["meta"]["name"] == "root"
    # Empty children OMITTED from emit. Matches every
    # observed gateway sample — no fixture emits children:[] at any
    # component level.
    assert "children" not in out["root"]
    # Top-level always has these 4 (View-level; only Component-
    # level empties are stripped, View-level dicts are preserved).
    assert set(out.keys()) >= {"custom", "params", "props", "root"}
