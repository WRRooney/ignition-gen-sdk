"""Shared @model_serializer helper for binding classes.

Every binding subclass declares ``enabled: bool = True``,
``overlayOptOut: bool = False``, and ``transforms: list[Transform] =
default_factory(list)`` as non-Optional fields. ``exclude_none=True``
cannot strip them because their values aren't None — they're the defaulted
True/False/[] primitives. EVERY observed gateway sample binding shape
(Designer-exported views) omits these three keys.

This wrap-mode serializer is attached as a ClassVar on each binding via:

    _strip_defaults = model_serializer(mode="wrap")(strip_binding_defaults)

The serializer runs after Pydantic's default model_dump and pops the
three keys when they match their default ("no override") values:

    enabled == True          -> drop (gateway default)
    overlayOptOut == False   -> drop (gateway default)
    transforms == []         -> drop (no transforms attached)

Non-default values are preserved (enabled=False / overlayOptOut=True
both emit because the user explicitly opted in to a non-gateway-default
state).
"""
from __future__ import annotations

from typing import Any


def strip_binding_defaults(self: Any, handler, _info) -> dict:
    """Wrap-mode model_serializer body shared by every Binding subclass.

    Removes gateway-default keys so emit matches every observed
    Designer-exported fixture.
    """
    out = handler(self)
    # enabled defaults True on every binding subclass; gateway omits it.
    if out.get("enabled") is True:
        out.pop("enabled", None)
    # overlayOptOut defaults False on every binding subclass; gateway omits it.
    if out.get("overlayOptOut") is False:
        out.pop("overlayOptOut", None)
    # transforms defaults to []; gateway omits the key when no transforms.
    if out.get("transforms") == []:
        out.pop("transforms", None)
    return out
