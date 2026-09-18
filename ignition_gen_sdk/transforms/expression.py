"""ExpressionTransform — Ignition 8.3 expression transform.

Discriminator is "expression" (full word). The expression *binding*
uses "expr" (abbreviated) — they are different, and easy to conflate.
"""
from __future__ import annotations

from typing import Literal

from ..models.base import IgnitionBaseModel


class ExpressionTransform(IgnitionBaseModel):
    """Ignition 8.3 expression transform.

    CRITICAL: discriminator value is `"expression"` (full word) for the
    TRANSFORM. The BINDING variant uses `"expr"` (abbreviated).
    Do not conflate.

    Verified live shape (Layouts/Layout Card/view.json line 186-192):
        {"expression": "{view.params.value} * 100", "type": "expression"}

    Expression-language tokens are passed through verbatim to the gateway
    (schema-only, no expression-language parsing). Canonical tokens
    available inside a transform expression:

        {value}      — the input value flowing into this transform
        {quality}    — quality code of the input
        {timestamp}  — timestamp of the input value

    See the Ignition 8.3 Perspective property-binding-transform docs for
    the full token grammar and operator/function reference. This model
    does not validate the body — the gateway parses it at load time.
    """

    type: Literal["expression"] = "expression"
    expression: str  # required; plain string of Ignition expression-language
