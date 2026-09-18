"""bindings package — Pydantic models for the 7 Ignition 8.3 Perspective binding types.

The Binding discriminated union has all 7 members. MongoDB is explicitly excluded
(module not installed on this gateway).

Discriminator-to-class map:
    "property"     -> PropertyBinding
    "tag"          -> TagBinding
    "expr"         -> ExpressionBinding
    "expr-struct"  -> ExpressionStructureBinding
    "query"        -> QueryBinding
    "tag-history"  -> TagHistoryBinding
    "http"         -> HttpBinding
"""
from typing import Annotated, Union

from pydantic import Discriminator

from .property import PropertyBinding
from .tag import TagBinding
from .expression import ExpressionBinding
from .expression_structure import ExpressionStructureBinding
from .query import QueryBinding
from .tag_history import TagHistoryBinding
from .http import HttpBinding

# Seven-member union — the full binding surface.
# Member order is purely stylistic; Pydantic v2 Discriminator("type")
# dispatches by the Literal value on each member, not by Union list position.
Binding = Annotated[
    Union[
        PropertyBinding,
        TagBinding,
        ExpressionBinding,
        ExpressionStructureBinding,
        QueryBinding,
        TagHistoryBinding,
        HttpBinding,
    ],
    Discriminator("type"),
]

__all__ = [
    "Binding",
    "PropertyBinding",
    "TagBinding",
    "ExpressionBinding",
    "ExpressionStructureBinding",
    "QueryBinding",
    "TagHistoryBinding",
    "HttpBinding",
]
