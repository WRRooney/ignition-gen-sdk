"""Embedding palette component models — all 5 ia.display.* embedding types.

NAMING NOTE: All embedding palette types use the ia.display.* prefix,
NOT ia.embedding.*. This is confirmed by
Designer-exported sample views.

accordion and carousel belong to the Embedding palette, not the Display
palette (verified against Designer-exported sample views). Both use the
ia.display.* prefix (ia.display.accordion, ia.display.carousel) consistent
with all other embedding types.

Doc source: https://docs.inductiveautomation.com/docs/8.3/appendix/components/
            perspective-components/perspective-embedding-palette
Cross-verified against Designer-exported sample views for EmbeddedView,
Accordion, Carousel, Flex Repeater and View Canvas.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from ...base import IgnitionBaseModel
from ..component import Component


# ---------------------------------------------------------------------------
# EmbeddedView
# ---------------------------------------------------------------------------

class EmbeddedViewProps(IgnitionBaseModel):
    """Props for ia.display.view.

    Verified props: path, style, params -- params is a props-level sibling of
    path/style, NOT viewParams; confirmed against real view.json embeds under
    projects/**.
    """
    model_config = ConfigDict(extra="allow")
    path: str | None = None
    params: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    useDefaultViewHeight: bool | None = None
    useDefaultViewWidth: bool | None = None


class EmbeddedView(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.view"] = "ia.display.view"
    props: EmbeddedViewProps = Field(default_factory=EmbeddedViewProps)


# ---------------------------------------------------------------------------
# FlexRepeater
# ---------------------------------------------------------------------------

class FlexRepeaterProps(IgnitionBaseModel):
    """Props for ia.display.flex-repeater.

    Verified props from a Designer-exported Flex Repeater view:
      direction, elementPosition, instances, path, style,
      useDefaultViewHeight, useDefaultViewWidth
    """
    model_config = ConfigDict(extra="allow")
    path: str | None = None
    instances: list[Any] | None = None
    instanceCommon: dict[str, Any] | None = None
    direction: str | None = None
    wrap: str | None = None
    elementPosition: dict[str, Any] | None = None
    useDefaultViewHeight: bool | None = None
    useDefaultViewWidth: bool | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class FlexRepeater(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.flex-repeater"] = "ia.display.flex-repeater"
    props: FlexRepeaterProps = Field(default_factory=FlexRepeaterProps)


# ---------------------------------------------------------------------------
# ViewCanvas
# ---------------------------------------------------------------------------

class ViewCanvasProps(IgnitionBaseModel):
    """Props for ia.display.viewcanvas.

    Verified props from a Designer-exported View Canvas view:
      instances (list of positioned view overlays), style,
      transitionSettings, useDefaultViewHeight, useDefaultViewWidth
    """
    model_config = ConfigDict(extra="allow")
    instances: list[Any] | None = None
    style: dict[str, Any] | None = None
    transitionSettings: dict[str, Any] | None = None
    useDefaultViewHeight: bool | None = None
    useDefaultViewWidth: bool | None = None
    enabled: bool | None = None
    visible: bool | None = None


class ViewCanvas(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.viewcanvas"] = "ia.display.viewcanvas"
    props: ViewCanvasProps = Field(default_factory=ViewCanvasProps)


# ---------------------------------------------------------------------------
# Accordion
# ---------------------------------------------------------------------------

class AccordionProps(IgnitionBaseModel):
    """Props for ia.display.accordion.

    Verified props from a Designer-exported Accordion view:
      items (list of {body, expanded, header} accordion sections)
    Palette: Embedding (confirmed against Designer-exported views).
    Type prefix: ia.display.* (consistent with all embedding types).
    """
    model_config = ConfigDict(extra="allow")
    items: list[Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Accordion(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.accordion"] = "ia.display.accordion"
    props: AccordionProps = Field(default_factory=AccordionProps)


# ---------------------------------------------------------------------------
# Carousel
# ---------------------------------------------------------------------------

class CarouselProps(IgnitionBaseModel):
    """Props for ia.display.carousel.

    Verified props from a Designer-exported Carousel view:
      views (list of {alignItems, direction, justify, viewParams, viewPath})
    NOTE: The prop is 'views' (not 'items') — confirmed from live fixture.
    Palette: Embedding (confirmed against Designer-exported views).
    Type prefix: ia.display.* (consistent with all embedding types).
    """
    model_config = ConfigDict(extra="allow")
    views: list[Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    interval: int | None = None


class Carousel(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.carousel"] = "ia.display.carousel"
    props: CarouselProps = Field(default_factory=CarouselProps)


__all__ = [
    "EmbeddedViewProps",
    "EmbeddedView",
    "FlexRepeaterProps",
    "FlexRepeater",
    "ViewCanvasProps",
    "ViewCanvas",
    "AccordionProps",
    "Accordion",
    "CarouselProps",
    "Carousel",
]
