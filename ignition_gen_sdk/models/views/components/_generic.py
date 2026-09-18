"""GenericComponent — fallback for any ia.* type not in the typed palette.

Receives Tag("generic") in the ComponentUnion callable discriminator.
type is inherited as str from Component — no Literal restriction.
extra="allow" absorbs any gateway-emitted fields.
"""
from __future__ import annotations

from pydantic import ConfigDict

from ..component import Component


class GenericComponent(Component):
    """Fallback for unknown or future ia.* component types."""

    model_config = ConfigDict(extra="allow")
