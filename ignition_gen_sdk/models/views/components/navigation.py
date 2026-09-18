"""Navigation palette component models — all 3 ia.navigation.* types.

Doc: https://docs.inductiveautomation.com/docs/8.3/appendix/components/
     perspective-components/perspective-navigation-palette
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from ...base import IgnitionBaseModel
from ..component import Component


# ---------------------------------------------------------------------------
# Link
# ---------------------------------------------------------------------------

class LinkProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    text: str | None = None
    url: str | None = None
    target: str | None = None  # "tab", "blank", etc.
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Link(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.navigation.link"] = "ia.navigation.link"
    props: LinkProps = Field(default_factory=LinkProps)


# ---------------------------------------------------------------------------
# MenuTree
# ---------------------------------------------------------------------------

class MenuTreeProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    items: list[Any] | None = None  # list of menu item dicts; complex nested structure
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class MenuTree(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.navigation.menutree"] = "ia.navigation.menutree"
    props: MenuTreeProps = Field(default_factory=MenuTreeProps)


# ---------------------------------------------------------------------------
# HorizontalMenu
# ---------------------------------------------------------------------------

class HorizontalMenuProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    items: list[Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class HorizontalMenu(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.navigation.horizontalmenu"] = "ia.navigation.horizontalmenu"
    props: HorizontalMenuProps = Field(default_factory=HorizontalMenuProps)


__all__ = [
    "Link",
    "LinkProps",
    "MenuTree",
    "MenuTreeProps",
    "HorizontalMenu",
    "HorizontalMenuProps",
]
