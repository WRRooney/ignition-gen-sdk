"""Gateway security properties (``ignition/security-properties``, a singleton resource).

The five permission sets decide who may reach the gateway web UI and API:

* ``accessPermissions``: see Home-section pages (implied by read)
* ``readPermissions``: read every Gateway page and setting (implied by write)
* ``writePermissions``: change gateway configuration
* ``designerPermissions``: open the Designer
* ``createProjectPermissions``: create projects

API tokens live under the ``APIKey/...`` security levels, so a token that must
write configuration needs ``APIKey/Write`` (or another level it holds) granted in
``writePermissions``. Read with ``ign security get``; change one set with
``ign security set-permissions``.
"""
from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict

from .base import IgnitionBaseModel
from .security import PermissionSet

PERMISSION_KEYS = (
    "accessPermissions",
    "readPermissions",
    "writePermissions",
    "designerPermissions",
    "createProjectPermissions",
)


class SecurityProperties(IgnitionBaseModel):
    """The ``config`` object of the security-properties resource. Extras are kept
    so a round trip never drops a field this version does not know."""

    model_config = ConfigDict(use_enum_values=True, populate_by_name=True, extra="allow")

    accessPermissions: Optional[PermissionSet] = None
    readPermissions: Optional[PermissionSet] = None
    writePermissions: Optional[PermissionSet] = None
    designerPermissions: Optional[PermissionSet] = None
    createProjectPermissions: Optional[PermissionSet] = None

    systemAuthProfile: Optional[str] = None
    systemIdentityProvider: Optional[str] = None
    forceIdpAuth: Optional[bool] = None
    allowDesignerSSO: Optional[bool] = None
    allowUserAdmin: Optional[bool] = None
    designerAuthStrategy: Optional[str] = None
    designerRoleName: Optional[str] = None
    designerAuthTokenInactivityTimeout: Optional[int] = None
    designerAuthTokenTimeToLive: Optional[int] = None
    userInactivityTimeout: Optional[int] = None
