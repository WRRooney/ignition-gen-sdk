"""Unit tests locking the events emit shape."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# ScriptEventHandler / NavEventHandler unit tests
# ---------------------------------------------------------------------------


def test_script_handler_emit_exact_keys():
    """ScriptEventHandler emits exactly {type, scope, config} — no phantom keys."""
    from ignition_gen_sdk.models.views.events import ScriptEventHandler, ScriptEventConfig

    h = ScriptEventHandler(type="script", scope="G", config=ScriptEventConfig(script="pass"))
    out = h.model_dump(exclude_none=True, mode="json")

    assert set(out.keys()) == {"type", "scope", "config"}, f"Unexpected keys: {out.keys()}"
    assert out["type"] == "script"
    assert out["scope"] == "G"
    assert set(out["config"].keys()) == {"script"}, f"Unexpected config keys: {out['config'].keys()}"
    assert out["config"]["script"] == "pass"


def test_nav_handler_emit_exact_keys():
    """NavEventHandler emits exactly {type, scope, config:{newTab, url}} — no phantom keys."""
    from ignition_gen_sdk.models.views.events import NavEventHandler, NavEventConfig

    h = NavEventHandler(type="nav", scope="C", config=NavEventConfig(url="http://x", newTab=True))
    out = h.model_dump(exclude_none=True, mode="json")

    assert set(out.keys()) == {"type", "scope", "config"}, f"Unexpected keys: {out.keys()}"
    assert out["type"] == "nav"
    assert out["scope"] == "C"
    assert out["config"]["newTab"] is True
    assert out["config"]["url"] == "http://x"


def test_nav_handler_without_newTab():
    """NavEventHandler with newTab=None omits it (exclude_none)."""
    from ignition_gen_sdk.models.views.events import NavEventHandler, NavEventConfig

    h = NavEventHandler(type="nav", scope="C", config=NavEventConfig(url="http://x"))
    out = h.model_dump(exclude_none=True, mode="json")

    assert "newTab" not in out["config"], "newTab should be omitted when None"
    assert out["config"]["url"] == "http://x"


def test_script_handler_discriminator():
    """EventHandler discriminated union resolves ScriptEventHandler from type='script'."""
    from typing import Union, Annotated
    from pydantic import Field, TypeAdapter
    from ignition_gen_sdk.models.views.events import (
        ScriptEventHandler,
        NavEventHandler,
    )

    EventHandler = Annotated[
        Union[ScriptEventHandler, NavEventHandler],
        Field(discriminator="type"),
    ]
    ta = TypeAdapter(EventHandler)
    h = ta.validate_python(
        {"type": "script", "scope": "G", "config": {"script": "pass"}}
    )
    assert isinstance(h, ScriptEventHandler)


def test_nav_handler_discriminator():
    """EventHandler discriminated union resolves NavEventHandler from type='nav'."""
    from typing import Union, Annotated
    from pydantic import Field, TypeAdapter
    from ignition_gen_sdk.models.views.events import (
        ScriptEventHandler,
        NavEventHandler,
    )

    EventHandler = Annotated[
        Union[ScriptEventHandler, NavEventHandler],
        Field(discriminator="type"),
    ]
    ta = TypeAdapter(EventHandler)
    h = ta.validate_python(
        {"type": "nav", "scope": "C", "config": {"newTab": True, "url": "http://x"}}
    )
    assert isinstance(h, NavEventHandler)


def test_eventsmap_type_importable():
    """EventsMap is importable as a type alias."""
    from ignition_gen_sdk.models.views.events import EventsMap  # noqa: F401


def test_all_exports_importable():
    """All required exports are importable from events module."""
    from ignition_gen_sdk.models.views.events import (  # noqa: F401
        EventHandler,
        EventsMap,
        ScriptEventHandler,
        NavEventHandler,
        ScriptEventConfig,
        NavEventConfig,
    )


# ---------------------------------------------------------------------------
# Component.events wired + add_event builder + empty-omission regression
# ---------------------------------------------------------------------------


def test_component_events_layer_structure():
    """Component.add_event emits three-layer category->eventName->handler."""
    from ignition_gen_sdk.models.views.component import Component
    from ignition_gen_sdk.models.views.events import ScriptEventHandler, ScriptEventConfig

    handler = ScriptEventHandler(
        type="script",
        scope="G",
        config=ScriptEventConfig(script="\tvalue = self.props.value\n"),
    )
    c = Component(type="ia.input.slider")
    c.add_event("component", "onActionPerformed", handler)
    out = c.emit()

    assert "events" in out, "events must be present when non-empty"
    assert "component" in out["events"], "category layer must be present"
    assert "onActionPerformed" in out["events"]["component"], "event name layer must be present"
    assert out["events"]["component"]["onActionPerformed"]["type"] == "script"
    assert out["events"]["component"]["onActionPerformed"]["scope"] == "G"


def test_component_empty_events_omitted():
    """Component with no events must omit 'events' from emit."""
    from ignition_gen_sdk.models.views.component import Component

    out = Component(type="ia.display.label").emit()
    assert "events" not in out, f"empty events must be omitted, got: {out}"


def test_component_add_event_returns_self():
    """add_event returns Self for fluent chaining."""
    from ignition_gen_sdk.models.views.component import Component
    from ignition_gen_sdk.models.views.events import ScriptEventHandler, ScriptEventConfig

    handler = ScriptEventHandler(
        type="script", scope="G", config=ScriptEventConfig(script="pass")
    )
    c = Component(type="ia.input.slider")
    result = c.add_event("component", "onActionPerformed", handler)
    assert result is c


def test_component_add_event_multiple_categories():
    """add_event supports multiple categories on one component."""
    from ignition_gen_sdk.models.views.component import Component
    from ignition_gen_sdk.models.views.events import (
        ScriptEventHandler, NavEventHandler,
        ScriptEventConfig, NavEventConfig,
    )

    c = Component(type="ia.display.label")
    c.add_event(
        "component",
        "onActionPerformed",
        ScriptEventHandler(type="script", scope="G", config=ScriptEventConfig(script="pass")),
    )
    c.add_event(
        "dom",
        "onClick",
        NavEventHandler(type="nav", scope="C", config=NavEventConfig(url="http://x", newTab=True)),
    )
    out = c.emit()
    assert "component" in out["events"]
    assert "dom" in out["events"]


def test_eventsmap_in_views_init():
    """EventsMap and related types are exported from models.views."""
    from ignition_gen_sdk.models.views import (  # noqa: F401
        EventHandler,
        EventsMap,
        ScriptEventHandler,
        NavEventHandler,
        ScriptEventConfig,
        NavEventConfig,
    )
