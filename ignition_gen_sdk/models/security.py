"""Security-level permission sets, shared by every gateway resource that gates access.

Ignition 8.3 expresses "who may do X" as a **permission set**::

    {"type": "AnyOf", "securityLevels": [
        {"name": "Authenticated", "children": [
            {"name": "Roles", "children": [{"name": "Administrator", "children": []}]}]},
        {"name": "APIKey", "children": [{"name": "Write", "children": []}]}]}

``securityLevels`` is a tree that mirrors the gateway's Security Levels page;
a leaf grants the path from the root to it. ``type`` says whether an actor
needs any one of the leaf paths (``AnyOf``) or all of them (``AllOf``).
An empty ``securityLevels`` list grants everyone.

The same shape appears as:

* ``readPermissions`` / ``writePermissions`` on tags, folders and UDT instances
* ``readPermissions`` / ``writePermissions`` / ``editPermissions`` in tag-provider settings
* ``accessPermissions`` / ``readPermissions`` / ``writePermissions`` /
  ``designerPermissions`` / ``createProjectPermissions`` in gateway security-properties

Build one from slash paths instead of nesting dicts by hand::

    PermissionSet.any_of("Authenticated/Roles/Operator", "APIKey/Write")
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field

from .base import IgnitionBaseModel

PermissionType = Literal["AnyOf", "AllOf"]


class SecurityLevel(IgnitionBaseModel):
    """One node of the security-level tree (``name`` plus nested ``children``)."""

    name: str
    description: Optional[str] = None
    children: list["SecurityLevel"] = Field(default_factory=list)

    def leaf_paths(self, prefix: str = "") -> list[str]:
        """Slash paths of every leaf under this node (the node itself if it has none)."""
        here = f"{prefix}/{self.name}" if prefix else self.name
        if not self.children:
            return [here]
        return [p for c in self.children for p in c.leaf_paths(here)]


SecurityLevel.model_rebuild()


class PermissionSet(IgnitionBaseModel):
    """``{"type": "AnyOf"|"AllOf", "securityLevels": [...]}``."""

    type: PermissionType = "AnyOf"
    securityLevels: list[SecurityLevel] = Field(default_factory=list)

    @classmethod
    def from_paths(cls, *paths: str, type: PermissionType = "AnyOf") -> "PermissionSet":
        """Build the tree from slash paths such as ``"Authenticated/Roles/Operator"``.

        Paths sharing a prefix merge into one branch, matching what the gateway
        stores when several leaves are ticked under the same parent.
        """
        roots: list[SecurityLevel] = []
        for path in paths:
            segments = [s for s in path.strip("/").split("/") if s]
            if not segments:
                raise ValueError("a security level path must not be empty")
            siblings = roots
            for seg in segments:
                node = next((n for n in siblings if n.name == seg), None)
                if node is None:
                    node = SecurityLevel(name=seg)
                    siblings.append(node)
                siblings = node.children
        return cls(type=type, securityLevels=roots)

    @classmethod
    def any_of(cls, *paths: str) -> "PermissionSet":
        return cls.from_paths(*paths, type="AnyOf")

    @classmethod
    def all_of(cls, *paths: str) -> "PermissionSet":
        return cls.from_paths(*paths, type="AllOf")

    @classmethod
    def everyone(cls) -> "PermissionSet":
        """No security levels: the gateway grants the action to any actor."""
        return cls(type="AnyOf", securityLevels=[])

    def paths(self) -> list[str]:
        """Flat slash paths of every granted leaf."""
        return [p for lvl in self.securityLevels for p in lvl.leaf_paths()]

    def is_open(self) -> bool:
        return not self.securityLevels
