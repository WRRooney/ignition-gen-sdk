"""UdtInstance + UdtType — Ignition 8.3 UDT models.

Verified live shape (config/resources/core/ignition/tag-definition/<provider>/<path>/udts.json):
[
  {
    "name": "Pump01",
    "typeId": "Pump",
    "parameters": {
      "deviceRoot": {"dataType": "String", "value": "Area1/Pump01"}
    },
    "tagType": "UdtInstance"
  }
]

Designer-authored UDT types (config/resources/core/ignition/tag-type-definition/<provider>/<path>/udts.json):
- UDT types carry ``typeId`` = PARENT type path (inheritance): "_Global",
  "Field/_Field", "Field/Text"…
- Custom params are FLAT top-level ``meta_*`` keys on the type/instance node —
  NOT entries in the ``parameters`` dict. Values may be scalars, objects,
  arrays, or bound params ``{"bindType": "parameter", "binding": "{PathToParentFolder}"}``.
- Types may carry ``tooltip``.
- Member tags may omit dataType/valueSource (inherited) and carry their own
  ``meta_*`` — see :class:`UdtMemberTag`.

Notes:
- UdtParameter.dataType is typed as ``str`` (not TagDataType): live UDT
  parameters use type names like "String" that align with TagDataType
  string values, but the gateway also accepts UDT-defined parameter type
  names that may not exist in TagDataType. ``str`` keeps the door open.
- ``parameters`` is a dict keyed by parameter name; emit order follows
  Python dict insertion order.
- ``tagType`` is fixed per model so udts.json files always carry the
  correct discriminator.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BeforeValidator, ConfigDict, model_serializer, model_validator

from ..base import IgnitionBaseModel

# Shared ConfigDict for the two node models that accept flat meta_* extras.
_META_EXTRA_CONFIG = ConfigDict(
    use_enum_values=True,
    populate_by_name=True,
    extra="allow",
)


def _reject_non_meta_extras(model: IgnitionBaseModel, kind: str) -> None:
    extras = model.__pydantic_extra__ or {}
    bad = [k for k in extras if not k.startswith("meta_")]
    if bad:
        raise ValueError(
            f"{kind} '{getattr(model, 'name', '?')}': unknown field(s) {sorted(bad)!r}. "
            "Only flat 'meta_*' custom props may be added beyond the schema."
        )


class UdtParameter(IgnitionBaseModel):
    """One entry under UdtInstance.parameters.

    The ``value`` is unconstrained because UDT parameters may carry any
    JSON-scalar value (numeric, string, bool). The ``dataType`` field
    documents the intended scalar shape for the gateway.
    """

    dataType: str
    value: Union["BoundParam", int, float, str, bool]


class UdtInstance(IgnitionBaseModel):
    """A UDT instance written to ``udts.json`` (flat — no 'usr' wrapper).

    Lives at config/resources/core/ignition/tag-definition/<provider>/<path>/udts.json
    paired with a ``unary-resource.json`` whose ``files`` is ``["udts.json"]``.

    Instances may override type-level ``meta_*`` props (flat extras) and
    member tags (``tags`` — e.g. a UDT instance overriding a member such as
    ``Header``).

    ``tooltip`` and ``enabled`` are ordinary tag properties that an instance
    may set independently of its type. ``enabled`` matters when UDT-driven
    views filter on the tag's ``.enabled`` config property, so a disabled
    instance is not rendered at all — that is the "disabled by default in the
    type, switched on per instance" convention, and it cannot be expressed
    without this field.
    """

    model_config = _META_EXTRA_CONFIG

    name: str
    tagType: Literal["UdtInstance"] = "UdtInstance"
    typeId: str
    tooltip: Optional[str] = None
    enabled: Optional[bool] = None
    parameters: Optional[dict[str, UdtParameter]] = None
    tags: Annotated[
        Optional[list["UdtMemberTag"]],
        BeforeValidator(lambda v: coerce_member_tags(v)),
    ] = None

    @model_validator(mode="after")
    def _extras_meta_prefixed_only(self) -> "UdtInstance":
        _reject_non_meta_extras(self, "UdtInstance")
        return self


class UdtType(IgnitionBaseModel):
    """A UDT *definition* (the reusable type), written to ``udts.json`` under
    ``config/resources/core/ignition/tag-type-definition/<provider>/<path>/`` —
    a DIFFERENT resource type than tag-definition (where instances/atomic tags
    live). Paired with a ``unary-resource.json`` whose ``files`` is ``["udts.json"]``.

    Verified shapes:
    - A Designer-exported udts.json:
        {"name": "WaterTank", "tagType": "UdtType",
         "parameters": {"name": {"dataType": "String", "value": null}},
         "tags": [ {atomic member tag defs…} ], "typeColor": -2763307}
    - Inheriting types add ``typeId`` (parent-type
      inheritance), ``tooltip``, and flat ``meta_*`` custom props.

    Member ``tags`` use :class:`UdtMemberTag` — the Tag schema with the
    member-context relaxations (optional dataType/valueSource, meta_* extras).
    """

    model_config = _META_EXTRA_CONFIG

    name: str
    tagType: Literal["UdtType"] = "UdtType"
    typeId: Optional[str] = None  # PARENT type path ("_Global", "Field/_Field", …)
    tooltip: Optional[str] = None
    parameters: Optional[dict[str, "UdtTypeParameter"]] = None
    tags: Annotated[
        Optional[list["UdtMemberTag"]],
        BeforeValidator(lambda v: coerce_member_tags(v)),
    ] = None
    typeColor: Optional[int] = None

    @model_validator(mode="after")
    def _extras_meta_prefixed_only(self) -> "UdtType":
        _reject_non_meta_extras(self, "UdtType")
        return self


class UdtTypeParameter(IgnitionBaseModel):
    """One entry under ``UdtType.parameters``. Unlike instance parameters, a
    type-definition parameter may declare a default ``value`` of ``None``
    (unset). NOTE: parameter ``dataType`` literals are their own set — ground
    truth uses ``"String"``/``"Float"`` (NOT the member-tag ``Float4``/``Float8``
    literals)."""

    dataType: str
    value: Union["BoundParam", int, float, str, bool, None] = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler, _info):
        # Designer always writes "value" on a type parameter — explicitly null
        # when unset (Designer-authored type parameter ground truth).
        # exclude_none would drop it; re-add for round-trip fidelity.
        out = handler(self)
        if "value" not in out:
            out["value"] = None
        return out


# Resolve forward refs (`UdtMemberTag`, `UdtTypeParameter`, `BoundParam`).
from .tag import BoundParam, UdtMemberTag, coerce_member_tags  # noqa: E402  (deferred to avoid import cycle)

UdtParameter.model_rebuild()
UdtTypeParameter.model_rebuild()
UdtInstance.model_rebuild()
UdtType.model_rebuild()
