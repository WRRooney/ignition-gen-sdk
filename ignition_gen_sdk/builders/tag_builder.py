"""TagBuilder — fluent DSL for Ignition 8.3 Tag construction.

A plain Python class (NOT a Pydantic model). Setters accumulate kwargs in
``self._data``; ``.build()`` calls ``Tag(**self._data)`` so Pydantic does
the validation in one place. Setters return ``Self`` so chains do not
require intermediate variables.

See ``Tag`` for the opcServer-default note (None, not a string, so memory
tags never emit ``opcServer``).
"""
from __future__ import annotations

from typing import Self, Union

from ..models.tags.alarm import Alarm
from ..models.tags.enums.tag_datatype import TagDataType
from ..models.tags.enums.tag_type import TagType
from ..models.tags.enums.tag_value_source import TagValueSource
from ..models.tags.tag import Tag


class TagBuilder:
    """Fluent DSL for building Ignition 8.3 ``Tag`` objects.

    Accumulates kwargs in ``self._data``; delegates validation to Pydantic
    on ``.build()``. All setters return ``Self`` for chain-ability.

    Example::

        tag = (
            TagBuilder()
            .name("Level")
            .datatype(TagDataType.DOUBLE)
            .opc("ns=1;s=[Sample_Device]_Meta:Sine/Sine1")
            .history(provider="default", deadband=0.1)
            .alarm(Alarm(name="Hi", mode=TagAlarmMode.ABOVE_SETPOINT, setpointA=90.0))
            .build()
        )
    """

    def __init__(self) -> None:
        # Per-builder dict — separate TagBuilder() calls do not share state.
        self._data: dict = {}

    # ---- Identity ----

    def name(self, v: str) -> Self:
        self._data["name"] = v
        return self

    def tag_type(self, v: TagType) -> Self:
        self._data["tagType"] = v
        return self

    def tag_group(self, v: str) -> Self:
        self._data["tagGroup"] = v
        return self

    def enabled(self, v: bool = True) -> Self:
        self._data["enabled"] = v
        return self

    # ---- Data type ----

    def datatype(self, v: TagDataType) -> Self:
        self._data["dataType"] = v
        return self

    # ---- Value-source shortcuts ----

    def opc(
        self,
        item_path: str,
        server: str | None = None,
    ) -> Self:
        """Configure an OPC value source.

        When ``server`` is not provided, the
        default is pulled from ``Settings.ignition_default_opc_server``
        (env-overridable as ``IGNITION_OPC_SERVER``). This lets
        non-default OPC deployments override via .env without touching
        the code. The default matches the live gateway shape
        ("Ignition OPC UA Server") so behavior is unchanged for stock
        gateways.
        """
        self._data["valueSource"] = TagValueSource.OPC
        self._data["opcItemPath"] = item_path
        if server is None:
            # Defer Settings import to call time so importing TagBuilder
            # does not require a populated .env. If Settings cannot be
            # constructed (e.g. tests with no IGNITION_API_TOKEN), fall
            # back to the static default rather than raising — opc() is
            # a pure model-construction helper and must remain offline.
            try:
                from ..config import Settings  # local import — see above
                server = Settings().ignition_default_opc_server  # type: ignore[call-arg]
            except Exception:  # noqa: BLE001 — env-dependent fallback path
                server = "Ignition OPC UA Server"
        self._data["opcServer"] = server
        return self

    def memory(self) -> Self:
        self._data["valueSource"] = TagValueSource.MEMORY
        return self

    def expression(self, expr: str) -> Self:
        self._data["valueSource"] = TagValueSource.EXPRESSION
        self._data["expression"] = expr
        return self

    def query(self, sql: str, datasource: str | None = None) -> Self:
        self._data["valueSource"] = TagValueSource.DB
        self._data["query"] = sql
        if datasource is not None:
            self._data["datasource"] = datasource
        return self

    def reference(self, source_path: str) -> Self:
        self._data["valueSource"] = TagValueSource.REFERENCE
        self._data["sourceTagPath"] = source_path
        return self

    # ---- Value ----

    def default_value(self, v: Union[int, float, str, bool]) -> Self:
        self._data["defaultValue"] = v
        return self

    def value(self, v: Union[int, float, str, bool]) -> Self:
        self._data["value"] = v
        return self

    # ---- History ----

    def history(
        self,
        provider: str,
        deadband: float = 0.0,
        *,
        sample_rate: float | None = None,
        sample_rate_units: str | None = None,
        max_age: float | None = None,
        max_age_units: str | None = None,
    ) -> Self:
        self._data["historyEnabled"] = True
        self._data["historyProvider"] = provider
        # deadband=0.0 is the "not set" sentinel — don't emit a useless 0.0.
        if deadband:
            self._data["historicalDeadband"] = deadband
        if sample_rate is not None:
            self._data["historySampleRate"] = sample_rate
        if sample_rate_units is not None:
            self._data["historySampleRateUnits"] = sample_rate_units
        if max_age is not None:
            self._data["historyMaxAge"] = max_age
        if max_age_units is not None:
            self._data["historyMaxAgeUnits"] = max_age_units
        return self

    # ---- Alarms ----

    def alarm(self, a: Alarm) -> Self:
        self._data.setdefault("alarms", []).append(a)
        return self

    # ---- Build ----

    def build(self) -> Tag:
        """Construct and return the ``Tag``.

        Pydantic validation runs here. Raises ``pydantic.ValidationError``
        if required fields (``name``, ``dataType``, ``valueSource``) are
        missing.

        ``tagType`` is IMPLICITLY DEFAULTED to
        ``TagType.ATOMIC`` when the builder caller did not invoke
        ``.tag_type(...)``. This is convenience for the common case
        (most authored tags are atomic), NOT a missing-required-field
        guard. If you intend to build a Folder or UdtInstance, you MUST
        call ``.tag_type(TagType.FOLDER)`` or ``.tag_type(TagType.UDT_INSTANCE)``
        explicitly -- forgetting will silently give you an AtomicTag,
        not raise. The previous docstring claimed this method raises on
        missing tagType -- it does not, and saying so was a trap.

        Example (atomic, implicit default):
            tag = TagBuilder().name("L").datatype(TagDataType.DOUBLE).opc("ns=1;s=x").build()

        Example (folder, explicit):
            tag = TagBuilder().name("Tanks").tag_type(TagType.FOLDER).build()
        """
        # Implicit-default behavior preserved (callers depend on
        # it) but the docstring above now states the behavior honestly.
        self._data.setdefault("tagType", TagType.ATOMIC)
        return Tag(**self._data)
