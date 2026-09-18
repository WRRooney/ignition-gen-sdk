"""Tag — Ignition 8.3 full tag model.

Notes:
- Inherits IgnitionBaseModel (credential guard + ConfigDict).
- ``opcServer`` defaults to ``None``, not "Ignition OPC UA Server": with
  ``exclude_none=True``, a string default would emit opcServer on every
  tag, including memory tags.
- Recursive ``tags`` self-reference resolved by the ``Tag.model_rebuild()``
  call at module bottom.
- Full 8.3 schema coverage:
  * Adds ``defaultValue`` distinct from ``value``.
  * Adds ``valuePersistence``.
  * Adds 8.3 history fields ``historyTimeDeadbandUnits``,
    ``historyMaxAge``, ``historyMaxAgeUnits``,
    ``maxTimeBetweenSamples``, ``maxTimeBetweenSamplesUnits``.
  * Adds ``preserveSourceTimestamp`` (8.3.1 Derived tags).
  * Removes deprecated ``"Analog"`` from ``historicalDeadbandStyle`` —
    only ``"Analog_Compressed"`` is accepted in 8.3.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar, List, Literal, Optional, Union

from typing import Annotated

from pydantic import BeforeValidator, ConfigDict, create_model, field_validator, model_validator

from ..base import IgnitionBaseModel
from .alarm import Alarm
from .enums.tag_datatype import TagDataType
from .enums.tag_scale_mode import TagScaleMode
from .enums.tag_type import TagType
from .enums.tag_value_source import TagValueSource

# Time-unit Literal shared by every 8.3 history-window field. Defining it
# once avoids drift between historySampleRateUnits, historyTimeDeadbandUnits,
# historyMaxAgeUnits, and maxTimeBetweenSamplesUnits.
TimeUnits = Literal["MS", "SEC", "MIN", "HOUR", "DAY", "WEEK", "MONTH", "YEAR"]


class TagEventScript(IgnitionBaseModel):
    """One tag-level event script.

    Ground truth (a real Designer UDT
    export): ``{"eventid": "valueChanged", "script": "\\t..."}`` — nothing else.
    The script body runs on the GATEWAY in Jython 2.7 with ``tag``, ``tagPath``,
    ``previousValue``, ``currentValue``, ``initialChange``, ``missedEvents``
    and ``event`` in scope, and like every project library script it MUST be
    TAB-indented (a space-indented body is a silent no-op risk, so it is
    rejected here the same way ``write_script`` rejects it).

    The self-resetting trigger idiom — a Boolean memory tag that does work when
    written True and clears itself — is:
        if currentValue.value:
            ...do work...
            system.tag.writeBlocking([event.tagPath], [False])
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    eventid: Literal[
        "valueChanged", "qualityChanged", "alarmActive", "alarmAcknowledged", "alarmCleared"
    ]
    script: str

    @field_validator("script")
    @classmethod
    def _require_tab_indentation(cls, v: str) -> str:
        for line in v.splitlines():
            if line and line[0] == " ":
                raise ValueError(
                    "tag event scripts are Jython and must be TAB-indented; "
                    "found a space-indented line."
                )
        return v


class Tag(IgnitionBaseModel):
    # UdtMemberTag flips this off: members inherit dataType/valueSource from
    # the parent type (typeId inheritance), so the AtomicTag both-required
    # rule only applies to standalone tags.
    _require_atomic_fields: ClassVar[bool] = True

    # Basic Properties
    name: str
    tagGroup: Optional[str] = None
    enabled: Optional[bool] = None

    # Folder and UDT Properties
    typeId: Optional[str] = None
    tags: Optional[List["Tag"]] = None

    # Meta Properties
    tooltip: Optional[str] = None
    documentation: Optional[str] = None

    # Value Properties
    tagType: TagType
    dataType: Optional[TagDataType] = None
    valueSource: Optional[TagValueSource] = None
    value: Optional[Union[int, float, str, bool, dict, list]] = None
    # 8.3: distinct from `value`. `value` is the live/current writable value;
    # `defaultValue` is the initial/reset value for memory tags. Both are
    # Optional[...] = None and emit independently under exclude_none=True.
    defaultValue: Optional[Union[int, float, str, bool, dict, list]] = None
    executionMode: Optional[Literal["EventDriven", "FixedRate", "TagGroupRate"]] = None
    executionRate: Optional[int] = None
    # 8.3: how the gateway persists the tag's last known value across restarts.
    valuePersistence: Optional[Literal["None", "Database", "Configuration"]] = None

    # OPC Properties — opcServer default fixed: was "Ignition OPC UA Server"
    # in seed, which leaked into every non-OPC tag's emit() output.
    opcServer: Optional[str] = None
    opcItemPath: Optional[str] = None

    # Reference Tag Properties
    sourceTagPath: Optional[str] = None

    # Expression Tag Properties
    expression: Optional[str] = None

    # Query Tag Properties
    datasource: Optional[str] = None
    query: Optional[str] = None
    queryType: Optional[Literal["AutoDetect", "Select", "Update"]] = None

    # Derived Tag Properties
    deriveExpressionGetter: Optional[str] = None
    deriveExpressionSetter: Optional[str] = None
    # 8.3.1: preserve the source tag's quality/timestamp on Derived tags
    # rather than stamping with the derive evaluation time.
    preserveSourceTimestamp: Optional[bool] = None

    # Numeric Properties
    deadband: Optional[float] = None
    deadbandMode: Optional[Literal["Absolute", "Percent", "Off"]] = None
    scaleMode: Optional[TagScaleMode] = None
    rawLow: Optional[float] = None
    rawHigh: Optional[float] = None
    scaledLow: Optional[float] = None
    scaledHigh: Optional[float] = None
    clampMode: Optional[Literal["No_Clamp", "Clamp_Low", "Clamp_High", "Clamp_Both"]] = None
    scaleFactor: Optional[float] = None

    # Engineering units and limits
    engUnit: Optional[str] = None
    engLow: Optional[float] = None
    engHigh: Optional[float] = None
    engLimitMode: Optional[Literal["No_Clamp", "Clamp_Low", "Clamp_High", "Clamp_Both"]] = None

    # Formatting
    formatString: Optional[str] = None

    # Security Data Properties
    readOnly: Optional[bool] = None

    # History Properties
    historyEnabled: Optional[bool] = None
    historyProvider: Optional[str] = None
    # 8.3 rename: "Analog" → "Analog_Compressed". The legacy string is
    # NO LONGER accepted.
    historicalDeadbandStyle: Optional[Literal["Auto", "Analog_Compressed", "Discrete"]] = None
    historicalDeadbandMode: Optional[Literal["Absolute", "Percent", "Off"]] = None
    historicalDeadband: Optional[float] = None
    sampleMode: Optional[Literal["OnChange", "Periodic", "TagGroup"]] = None
    historySampleRate: Optional[float] = None
    historySampleRateUnits: Optional[TimeUnits] = None
    historyTagGroup: Optional[str] = None
    historyTimeDeadband: Optional[float] = None
    # 8.3 history fields:
    historyTimeDeadbandUnits: Optional[TimeUnits] = None
    # int | float: Designer writes whole values as INT (``historyMaxAge: 1``);
    # a bare float field re-emitted every one as ``1.0`` (20-line churn per save).
    historyMaxAge: Optional[int | float] = None
    historyMaxAgeUnits: Optional[TimeUnits] = None
    maxTimeBetweenSamples: Optional[float] = None
    maxTimeBetweenSamplesUnits: Optional[TimeUnits] = None

    # Alarm Properties
    alarms: Optional[List[Alarm]] = None
    alarmEvalEnabled: Optional[bool] = None

    # Scripting Properties — tag-level event scripts (Jython, gateway scope).
    eventScripts: Optional[List["TagEventScript"]] = None

    @staticmethod
    def get_standard_opc_item_path(device: str, address: str) -> str:
        return f"ns=1;s=[{device}]{address}"

    @field_validator("name", mode="before")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        # Enforce max length of 255 characters
        if len(v) > 255:
            v = v[:255]

        # Allowed characters: letters, digits, underscores, spaces, parens,
        # single quotes, dashes, colons.
        allowed_chars_pattern = r"[A-Za-z0-9_ ()':\-]"
        v = "".join(ch for ch in v if re.match(allowed_chars_pattern, ch))

        # First character must be letter or underscore.
        if not v or not re.match(r"[A-Za-z_]", v[0]):
            v = "_" + v
        return v

    @model_validator(mode="after")
    def _require_fields_by_tagtype(self) -> "Tag":
        # `dataType`/`valueSource` are Optional on the model because Folder
        # member tags (inside a UdtType definition) legitimately carry
        # neither. But an AtomicTag MUST have both — keeping the model field
        # unconditionally required broke Folder tags; making it unconditionally
        # Optional re-opened the silent-corruption trap and dropped atomic
        # validation. Enforce conditionally by tagType instead.
        # NOTE: use_enum_values=True means self.tagType is the string value.
        tt = self.tagType.value if hasattr(self.tagType, "value") else self.tagType
        if tt == TagType.ATOMIC.value and self._require_atomic_fields:
            missing = [
                n for n, v in (("dataType", self.dataType), ("valueSource", self.valueSource))
                if v is None
            ]
            if missing:
                raise ValueError(
                    f"AtomicTag '{self.name}' requires {' and '.join(missing)} "
                    f"(only Folder/UDT member tags may omit them)."
                )
        elif tt == TagType.UDT.value:
            # A UdtType *definition* is not a standalone Tag — it has a dedicated
            # UdtType model and the `ign tag udt-type` path. Rejecting it here
            # preserves the guarantee that feeding a UdtType node to
            # `tag build`/`push` fails loudly instead of being mis-handled.
            raise ValueError(
                f"'{self.name}' has tagType 'UdtType' — a UDT definition is not a "
                f"standalone Tag. Author it with `ign tag udt-type` (UdtType model)."
            )
        return self


class BoundParam(IgnitionBaseModel):
    """A UDT member property bound to a type parameter or expression.

    Ground-truth shapes (Designer-authored udts.json):
    - ``{"bindType": "parameter", "binding": "{EngUnit}"}``
    - ``{"bindType": "UDTParameter", "value": "{Message}"}``
    - ``{"bindType": "Expression", "value": "coalesce({[.]Enabled/Value}, True)"}``
    """

    bindType: str
    binding: Optional[Union[int, float, str, bool]] = None
    value: Optional[Union[int, float, str, bool]] = None


class _UdtMemberTagBase(Tag):
    """Member tag inside a UdtType definition (Designer ground truth).

    Members differ from standalone tags:
    - ``dataType``/``valueSource`` may be omitted — inherited from the parent
      type via ``typeId`` inheritance (a child member can override just
      ``dataType`` while a base member type supplies ``valueSource``).
    - Flat ``meta_*`` custom props are allowed on the member itself
      (e.g. a UDT member such as ``Header`` carries a ``meta_align`` prop).
    - ANY scalar property may instead be a :class:`BoundParam` dict — the
      concrete ``UdtMemberTag`` below wraps every field annotation in
      ``Union[BoundParam, <orig>]`` automatically so new Tag fields stay
      bindable without hand-maintained duplication.
    """

    _require_atomic_fields: ClassVar[bool] = False

    model_config = ConfigDict(
        use_enum_values=True,
        populate_by_name=True,
        extra="allow",
    )

    tags: Annotated[Optional[List["UdtMemberTag"]], BeforeValidator(lambda v: coerce_member_tags(v))] = None
    # Embedded UdtInstance members carry their own typeColor + parameters
    # (e.g. Alarm/Analog members "Low"/"High"…). Parameter values
    # vary (scalars or bound dicts) — keep Any.
    typeColor: Optional[int] = None
    parameters: Optional[dict[str, Any]] = None
    # Alarm props may be bound too ({"bindType": "UDTParameter", ...}).
    alarms: Optional[List["MemberAlarm"]] = None

    @model_validator(mode="after")
    def _extras_meta_prefixed_only(self) -> "_UdtMemberTagBase":
        extras = self.__pydantic_extra__ or {}
        bad = [k for k in extras if not k.startswith("meta_")]
        if bad:
            raise ValueError(
                f"UDT member tag '{self.name}': unknown field(s) {sorted(bad)!r}. "
                "Only flat 'meta_*' custom props may be added beyond the Tag schema."
            )
        return self


# Alarm variant whose every prop (except name) may be a BoundParam dict.
MemberAlarm = create_model(
    "MemberAlarm",
    __base__=Alarm,
    **{
        fname: (Optional[Union[BoundParam, finfo.annotation]], None)
        for fname, finfo in Alarm.model_fields.items()
        if fname != "name"
    },
)

def coerce_member_tags(value: object) -> object:
    """BeforeValidator for ``tags: list[UdtMemberTag]`` fields: accept plain
    ``Tag`` instances (the pre-UdtMemberTag construction style used by tests
    and builder code) by re-validating them through their dict dump."""
    if isinstance(value, list):
        return [
            v.model_dump(exclude_none=True) if isinstance(v, Tag) and not isinstance(v, _UdtMemberTagBase) else v
            for v in value
        ]
    return value


# Fields that must keep their exact base annotation (identity, recursion, and
# list-of-model fields where a BoundParam arm makes no sense).
_UNBOUND_MEMBER_FIELDS = frozenset({"name", "tagType", "tags", "alarms", "typeColor", "parameters"})

UdtMemberTag = create_model(
    "UdtMemberTag",
    __base__=_UdtMemberTagBase,
    **{
        fname: (Optional[Union[BoundParam, finfo.annotation]], None)
        for fname, finfo in Tag.model_fields.items()
        if fname not in _UNBOUND_MEMBER_FIELDS
    },
)
UdtMemberTag.__doc__ = _UdtMemberTagBase.__doc__


# Resolve forward ref for recursive `tags: Optional[List["Tag"]]`.
# Required even with `extra="forbid"`.
Tag.model_rebuild()
UdtMemberTag.model_rebuild()
