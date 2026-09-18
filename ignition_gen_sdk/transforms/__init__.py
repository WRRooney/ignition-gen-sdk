"""transforms package — Pydantic models for the 4 Ignition 8.3 Perspective transform types.

Transform discriminated union has all 4 members (MapTransform + FormatTransform +
ScriptTransform + ExpressionTransform). Dispatch is by the `type` Literal on each
member; order in the Union is purely stylistic.
"""
from typing import Annotated, Union

from pydantic import Discriminator

from .expression import ExpressionTransform
from .map import MapTransform
from .format import FormatTransform
from .script import ScriptTransform

Transform = Annotated[
    Union[
        MapTransform,
        FormatTransform,
        ScriptTransform,
        ExpressionTransform,
    ],
    Discriminator("type"),
]

__all__ = [
    "Transform",
    "MapTransform",
    "FormatTransform",
    "ScriptTransform",
    "ExpressionTransform",
]
