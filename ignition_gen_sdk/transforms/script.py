"""ScriptTransform — Ignition 8.3 script transform.

code is a plain string containing Jython source. The gateway parses it
at load time. No AST extraction is performed on Python side. Whitespace
(including leading tabs and newlines) is preserved verbatim — fixtures rely
on this.

Verified live shape (Designer-exported view.json):
    {"code": "\\t\\n\\treturn \\"The square of the value is %0.2f\\" %(value*value)",
     "type": "script"}
"""
from __future__ import annotations

from typing import Literal

from ..models.base import IgnitionBaseModel


class ScriptTransform(IgnitionBaseModel):
    # CRITICAL: discriminator value is "script" (Pydantic v2 Annotated discriminator dispatch).
    type: Literal["script"] = "script"
    code: str   # REQUIRED — no default (rejects seed's "\treturn value" placeholder)
