"""Tag-provider resource config (``/data/api/v1/resources/ignition/tag-provider``).

Only the fields the STANDARD profile is known to carry are typed; other
profile types (remote, managed) add their own keys, so both blocks accept
extras. The value of typing this at all is the three permission sets:
``ign provider create/update`` validates the config file through this model
so a malformed ``readPermissions`` fails locally instead of as a gateway 400.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import ConfigDict

from .base import IgnitionBaseModel
from .security import PermissionSet

_ALLOW_EXTRA = ConfigDict(use_enum_values=True, populate_by_name=True, extra="allow")


class TagProviderProfile(IgnitionBaseModel):
    model_config = _ALLOW_EXTRA

    type: str = "STANDARD"
    allowBackfill: Optional[bool] = None
    enableTagReferenceStore: Optional[bool] = None


class TagProviderSettings(IgnitionBaseModel):
    """``settings`` block. ``editPermissions`` gates tag CONFIG edits, ``writePermissions``
    gates value writes, ``readPermissions`` gates reads; each is checked in addition
    to the target tag's own read/write permissions."""

    model_config = _ALLOW_EXTRA

    defaultDatasourceName: Optional[str] = None
    readOnly: Optional[bool] = None
    valuePersistence: Optional[Literal["None", "Database", "Configuration"]] = None
    readPermissions: Optional[PermissionSet] = None
    writePermissions: Optional[PermissionSet] = None
    editPermissions: Optional[PermissionSet] = None


class TagProviderConfig(IgnitionBaseModel):
    """The ``config`` object of a tag-provider resource envelope."""

    model_config = _ALLOW_EXTRA

    profile: TagProviderProfile
    settings: TagProviderSettings
