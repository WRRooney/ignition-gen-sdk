"""SessionProps — Perspective session-props model (declares custom session props).

Custom SESSION properties (cross-view shared state, e.g. a nav selection or an
offline queue) must be DECLARED in a per-project resource
``projects/<P>/com.inductiveautomation.perspective/session-props/props.json``,
then accessed in component scripts via ``self.session.custom.<path>``. They are
NOT created at runtime (`system.perspective.setSessionProperty` does not
exist in 8.3).

Shape verified against an on-disk Designer-written session-props/props.json:

    {"custom": {"<name>": <default>, ...},
     "propConfig": {"custom.<name>": {...optional onChange/access...}},
     "props": {...built-in session props...}}

This model is the sanctioned (ign-only) way to write that resource; never
hand-write it (the disk-write ban).
"""
from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from .base import IgnitionBaseModel


class SessionProps(IgnitionBaseModel):
    """A project's Perspective session-props resource (props.json)."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    custom: dict[str, Any] = Field(default_factory=dict)
    propConfig: dict[str, Any] = Field(default_factory=dict)
    props: dict[str, Any] = Field(default_factory=dict)

    def props_json(self) -> dict:
        """The props.json payload (custom + propConfig + props, always present)."""
        return {
            "custom": self.custom,
            "propConfig": self.propConfig,
            "props": self.props,
        }
