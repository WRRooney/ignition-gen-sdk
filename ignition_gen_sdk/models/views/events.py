"""Event handler models for Ignition 8.3 Perspective component events.

Replaces a freeform ``dict[str, Any]`` on ``Component.events`` with a
typed discriminated union on the handler's
``type`` field, enforcing the three-layer structure the gateway requires:

    events -> category ("component"/"dom") -> eventName -> handler

Ground-truth source: Designer-exported views.

Handler shapes observed:
    Script handler (ia.input.slider Brightness, scope "G"):
        {"type": "script", "scope": "G", "config": {"script": "<jython>"}}

    Nav handler (ia.display.label Footnote, scope "C"):
        {"type": "nav", "scope": "C", "config": {"newTab": true, "url": "..."}}

IgnitionBaseModel already sets:
    model_config = ConfigDict(use_enum_values=True, populate_by_name=True, extra="forbid")

No custom @field_serializer or @model_serializer needed — Pydantic v2 default
emit with model_dump(exclude_none=True, mode="json") produces the exact shape.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import ConfigDict, Field

from ..base import IgnitionBaseModel


# ---------------------------------------------------------------------------
# Config sub-models
# ---------------------------------------------------------------------------


class ScriptEventConfig(IgnitionBaseModel):
    """Config payload for a script event handler.

    Emits: {"script": "<jython source>"}
    """

    script: str


class NavEventConfig(IgnitionBaseModel):
    """Config payload for a navigation event handler.

    Emits: {"url": "...", "newTab": true}  (newTab omitted when None)
    """

    url: str
    newTab: bool | None = None


# ---------------------------------------------------------------------------
# Handler models
# ---------------------------------------------------------------------------


class PopupEventConfig(IgnitionBaseModel):
    """Config payload for the Designer's built-in Popup action.

    Ground truth (a Designer-authored popup action):
        {"type": "open", "id": "{view.params.tagPath}",
         "viewPath": "Popups/AddNote",
         "viewParams": {"tagPath": "{view.params.tagPath}"},
         "draggable": true, "modal": false, "overlayDismiss": false,
         "resizable": true, "showCloseIcon": true, "viewportBound": true}

    ``type`` is the popup ACTION (open/close/toggle), distinct from the
    handler's own ``type: "popup"``. Everything else is optional because the
    Designer omits whatever is left at its default.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["open", "close", "toggle"] = "open"
    id: Optional[str] = None
    viewPath: Optional[str] = None
    viewParams: Optional[dict] = None
    title: Optional[str] = None
    draggable: Optional[bool] = None
    modal: Optional[bool] = None
    overlayDismiss: Optional[bool] = None
    resizable: Optional[bool] = None
    showCloseIcon: Optional[bool] = None
    viewportBound: Optional[bool] = None
    position: Optional[dict] = None


class PopupEventHandler(IgnitionBaseModel):
    """Popup handler attached to a Perspective component event.

    The Designer writes this instead of a script when the user picks the Popup
    action, so any view built in the Designer can carry one — a model that only
    knows script/nav rejects the whole view on load.
    """

    type: Literal["popup"]
    scope: str
    config: PopupEventConfig
    #: Designer "enabled" toggle. A handler can be DISABLED rather than
    #: deleted — that is how you free a click for a nested view's own
    #: full-size target without losing the script. Absent means enabled.
    enabled: bool | None = None


class ScriptEventHandler(IgnitionBaseModel):
    """Jython script handler attached to a Perspective component event.

    Ground-truth shape (Designer export):
        {
          "type": "script",
          "scope": "G",
          "config": {"script": "\\tvalue = self.props.value\\n..."}
        }

    ``scope`` values observed: "G" (gateway), "C" (client).
    """

    type: Literal["script"]
    scope: str
    config: ScriptEventConfig
    #: Designer "enabled" toggle. A handler can be DISABLED rather than
    #: deleted — that is how you free a click for a nested view's own
    #: full-size target without losing the script. Absent means enabled.
    enabled: bool | None = None


class NavEventHandler(IgnitionBaseModel):
    """Navigation (URL) handler attached to a Perspective component event.

    Ground-truth shape (Designer export):
        {
          "type": "nav",
          "scope": "C",
          "config": {"newTab": true, "url": "{view.custom.hostname}"}
        }
    """

    type: Literal["nav"]
    scope: str
    config: NavEventConfig
    #: Designer "enabled" toggle. A handler can be DISABLED rather than
    #: deleted — that is how you free a click for a nested view's own
    #: full-size target without losing the script. Absent means enabled.
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# Discriminated union + map type alias
# ---------------------------------------------------------------------------

EventHandler = Annotated[
    Union[ScriptEventHandler, NavEventHandler, PopupEventHandler],
    Field(discriminator="type"),
]
"""Discriminated union of all known event handler types.

Pydantic resolves the concrete type from the ``type`` field value:
  - "script"  ->  ScriptEventHandler
  - "nav"     ->  NavEventHandler
  - "popup"   ->  PopupEventHandler
"""

EventsMap = dict[str, dict[str, EventHandler]]
"""Three-layer event map: category -> eventName -> handler.

Example:
    {
      "component": {
        "onActionPerformed": ScriptEventHandler(...)
      },
      "dom": {
        "onClick": NavEventHandler(...)
      }
    }
"""

__all__ = [
    "ScriptEventConfig",
    "NavEventConfig",
    "ScriptEventHandler",
    "NavEventHandler",
    "EventHandler",
    "EventsMap",
]
