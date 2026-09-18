"""Component — Ignition 8.3 generic Perspective component.

GENERIC model: type is a plain str, props is a plain dict. propConfig is
Annotated[list[PropConfig], BeforeValidator(_deserialize_prop_config)] with a
@field_serializer that emits the gateway's inner-"binding"-wrapper shape, as
seen in every Designer-exported view.json sample.

Verified emit shape (from a Designer-exported view.json):
    "propConfig": {
      "props.text": {
        "binding": {
          "config": { "path": "view.params.title" },
          "type": "property"
        }
      }
    }

The INNER "binding" wrapper key is REQUIRED. Emitting
{prop: binding.model_dump()} WITHOUT the wrapper produces a wire format the
gateway silently ignores.

Position distinction: None (not specified) vs {} (explicit empty).
The credential guard inspects only TOP-LEVEL Pydantic fields; nested dict
keys are data, not fields.
Component.model_rebuild() at module bottom resolves the recursive children
forward ref AND the chain Component -> PropConfig -> Binding -> Transform.
"""
from __future__ import annotations

import re
import warnings
from datetime import datetime as _datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, Field, PrivateAttr, SerializeAsAny, TypeAdapter, model_serializer

from ..base import IgnitionBaseModel
from ...bindings import Binding
from ...bindings.property import PropertyBinding, PropertyBindingConfig
from ...bindings.tag import TagBinding, TagBindingConfig
from ...bindings.expression import ExpressionBinding, ExpressionBindingConfig
from ...bindings.expression_structure import (
    ExpressionStructureBinding,
    ExpressionStructureBindingConfig,
)
from ...bindings.query import QueryBinding, QueryBindingConfig, PollingConfig
from ...bindings.tag_history import (
    AbsoluteRange,
    DurationRange,
    ReturnSize,
    TagHistoryBinding,
    TagHistoryBindingConfig,
    TagHistoryTag,  # noqa: F401 — re-exported via builder kwargs typing
)
from ...bindings.http import (
    HttpAuth,
    HttpBinding,
    HttpBindingConfig,
    HttpHeader,
    HttpRequest,
)
from ...bindings.enums import HttpMethod, TagBindingMode, TagHistoryAggregation
from ...bindings.prop_config import PropConfig
from ...transforms import Transform  # noqa: F401 — needed so model_rebuild can resolve forward refs in PropertyBinding.transforms
from ...transforms.expression import ExpressionTransform
from ...transforms.map import MapTransform, MapMapping
from ...transforms.format import FormatTransform
from ...transforms.script import ScriptTransform
from .events import EventHandler, EventsMap
from .meta import Meta


# ---------------------------------------------------------------------------
# Static binding guard
# ---------------------------------------------------------------------------


class StaticBindingError(ValueError):
    """Raised when bind_expression() receives a constant string that should be
    a plain prop value instead of an expression binding.

    Use set_prop(prop_path, value) for constants. Bindings are for dynamic
    values only. A constant in propConfig is a gateway anti-pattern — it
    adds overhead with no dynamic benefit.

    Example fix::

        # Wrong — constant in bind_expression raises StaticBindingError:
        comp.bind_expression("props.style.classes", "alarm")

        # Correct — constant goes directly into props:
        comp.set_prop("props.style.classes", "alarm")
    """


class ExpressionSyntaxError(ValueError):
    """Raised when an expression uses a syntax the Ignition expression language
    does not accept — most commonly the Python equality operator ``==``.

    Ignition's expression language uses a SINGLE ``=`` for equality (``!=`` for
    not-equal). ``==`` is a parse error at runtime: the binding silently fails
    to evaluate, so a bug like a never-resolving alarm-coloring class survives
    every JSON/model validation and only shows as "no color" in the Designer.
    Verified against IA ground truth (IndustryPack views: 0 uses of ``==``,
    equality always ``=``; ``&&``/``||`` ARE accepted so they are left alone).

    Example fix::

        # Wrong — Python equality; raises ExpressionSyntaxError:
        comp.bind_expression("props.style.classes",
                             'if({view.custom.alarmState} == "alarm", ...)')

        # Correct — single = is Ignition equality:
        comp.bind_expression("props.style.classes",
                             'if({view.custom.alarmState} = "alarm", ...)')
    """


# Quoted string literals ('...' or "...") — stripped before operator scanning so
# a literal that contains "==" (rare) does not false-trigger the equality guard.
_QUOTED_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
# Python equality operator: "==" not part of "!=", ">=", "<=" (none of which
# contain "=="). Any bare "==" is invalid Ignition expression syntax.
_PY_EQ = re.compile(r"==")


def _balanced(s: str, open_ch: str, close_ch: str) -> bool:
    """True if *s* has matched, non-negative-running open/close delimiters."""
    depth = 0
    for ch in s:
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _check_expression_syntax(expr: str) -> None:
    """Raise ExpressionSyntaxError on author-time Ignition expression mistakes
    that pass JSON/model validation but fail (silently) at runtime.

    Checks (all after stripping quoted string literals so literal content never
    false-triggers):
      1. Python ``==`` for equality — Ignition uses a single ``=`` (``!=`` for
         not-equal). The most common cross-language mistake; the binding never
         evaluates.
      2. Unbalanced ``()`` — a function call / grouping with mismatched parens
         is a parse error.
      3. Unbalanced ``{}`` — ``{...}`` delimits a property/tag reference; a
         mismatched brace is a malformed reference.

    Intentionally NOT flagged (valid Ignition syntax, verified vs IA ground
    truth): ``&&``/``||`` logical ops, ``!=`` not-equal, single ``&``/``|``.
    """
    scrubbed = _QUOTED_LITERAL.sub("", expr)
    if _PY_EQ.search(scrubbed):
        raise ExpressionSyntaxError(
            f"Expression uses Python equality '==': {expr!r}. "
            f"Ignition expression language uses a single '=' for equality "
            f"(and '!=' for not-equal). '==' is a runtime parse error — the "
            f"binding silently fails to evaluate. Replace '==' with '='."
        )
    if not _balanced(scrubbed, "(", ")"):
        raise ExpressionSyntaxError(
            f"Expression has unbalanced parentheses: {expr!r}. "
            f"Every '(' needs a matching ')'."
        )
    if not _balanced(scrubbed, "{", "}"):
        raise ExpressionSyntaxError(
            f"Expression has unbalanced braces: {expr!r}. "
            f"'{{...}}' delimits a property/tag reference — every '{{' needs a matching '}}'."
        )
    # PERFORMANCE_ORDER caveat (non-fatal): runScript() runs Jython on every
    # evaluation — SCRIPT-tier cost, not cheap-expression cost.
    # Warn (don't raise — runScript is sometimes the only option). Uses the
    # quoted-stripped form so a runScript inside a string literal isn't flagged.
    if _RUNSCRIPT_CALL.search(scrubbed):
        warnings.warn(
            "Expression calls runScript(): it runs Jython on every evaluation — "
            "SCRIPT-tier cost, not cheap expression cost. Prefer a property/expression/"
            "tag binding; use runScript only when no binding or pure expression-function "
            f"can satisfy it. Performance order: {PERFORMANCE_ORDER}.",
            BindingPerformanceWarning,
            stacklevel=2,
        )

    from ...validation import unknown_expression_functions

    unknown = unknown_expression_functions(expr)
    if unknown:
        raise ExpressionSyntaxError(
            f"Expression calls unknown function(s) {unknown} in {expr!r}. "
            f"Not built-in Ignition expression functions. Check spelling, or if "
            f"this is a real function add it to "
            f"ignition_gen_sdk.validation.ignition_builtins.EXPRESSION_FUNCTIONS."
        )


# ---------------------------------------------------------------------------
# Binding performance order
#
# Ignition Perspective evaluates bindings fastest-to-slowest:
#   property   — direct reactive reference to another component/view property;
#                lowest overhead, evaluated by the runtime subscription graph.
#   expression — Ignition expression language; evaluated on each dependency
#                change; fast but runs through the expression engine.
#   script_transform — Jython script attached as a transform pipeline stage;
#                significantly slower than expression transforms.
#   event_script — full Jython script wired to a component event (onClick etc.);
#                the slowest path, runs on the scripting thread.
#
# Builders make property/expression bindings the ergonomic default.
# Scripts are opt-in via Component.add_event() or Component.script().
# Use scripts only when no binding expression can satisfy the requirement.
# ---------------------------------------------------------------------------

PERFORMANCE_ORDER: str = "property > expression > script_transform > event_script"
"""Ignition Perspective binding performance order, fastest to slowest.

Use to document architectural intent in code comments, docstrings, or
error messages. The hierarchy guides which binding type to choose:
- property  : reactive; cheapest; use for cross-component/view-parameter wiring
- expression: expression-language formula; use for derived computed values
- script_transform: Jython transform in a binding pipeline; avoid when expression works
- event_script: Jython on component events (click, change); slowest; interaction-only

CAVEAT — ``runScript(...)`` in an expression is SCRIPT-tier, not expression-tier.
The ``runScript`` expression function is the expression language's escape hatch
into Jython: it executes a script body on every evaluation, so it carries the
same performance cost as a ``script_transform``/``event_script`` — NOT the cheap
expression cost. Treat an expression that calls ``runScript`` as a script for
performance purposes: prefer a real property/expression/tag binding; reach for
``runScript`` only when no binding or pure expression-function can satisfy the
requirement.
"""


class BindingPerformanceWarning(UserWarning):
    """A binding was authored in a way that carries avoidable runtime cost.

    Non-fatal (the binding is still valid) — surfaces a PERFORMANCE_ORDER smell,
    e.g. an expression that calls ``runScript`` (script-tier cost masquerading as
    a cheap expression). Filterable/assertable via ``warnings``/``pytest.warns``.
    """


# An expression that invokes runScript( — case-insensitive (Ignition expression
# function names are case-insensitive). Quoted-literal stripping is unnecessary
# here: a runScript token is a perf smell whether or not it is also quoted.
_RUNSCRIPT_CALL = re.compile(r"\brunScript\s*\(", re.IGNORECASE)


def _is_static_expression(expr: str) -> bool:
    """Return True if *expr* is a static constant that should NOT be wrapped
    in an ExpressionBinding.

    A string is STATIC (no dynamic content) when it contains NEITHER:
      - ``{``  — property/parameter reference (e.g. ``{view.custom.x}``)
      - ``(``  — function call (e.g. ``toBoolean(...)``, ``if(...)``)

    This minimal two-character guard catches static-constant misuse (bare CSS
    class strings like ``"alarm"``, ``"card-name"``, ``"seg-btn"``) without
    false-positiving on arithmetic or hyphenated CSS class names that may
    contain ``-`` or ``*`` but never ``{`` or ``(``.

    Examples::

        _is_static_expression("alarm")                              -> True
        _is_static_expression("card-name card-name-on")             -> True
        _is_static_expression("")                                   -> True
        _is_static_expression("{view.custom.on}")                   -> False
        _is_static_expression("if({view.custom.on}, 'ON', 'off')") -> False
        _is_static_expression("numberFormat({view.custom.v}, '#0.0')") -> False
    """
    return "{" not in expr and "(" not in expr


# ---------------------------------------------------------------------------
# Duration-string parsing helpers for bind_tag_history.
# Case-sensitive map (M=month vs m=minute).
# Validate bind_http headers via Pydantic TypeAdapter so the failure
# mode is ValidationError (same family as the rest of the chain) rather than
# a plain ValueError that callers wrapping in `except ValidationError` would
# miss.
_HEADER_INPUT_TA = TypeAdapter(list[HttpHeader | tuple[str, str]])


def _build_polling(
    enabled: bool | None,
    rate: str | int | float | None,
) -> PollingConfig | None:
    """Single source of truth for the conditional polling sub-object
    constructed by bind_query / bind_tag_history / bind_http.

    Returns None when neither kwarg was supplied — matches the fixture
    shape for non-polling bindings (no `polling` key in emit).
    """
    if enabled is None and rate is None:
        return None
    return PollingConfig(
        enabled=bool(enabled) if enabled is not None else False,
        rate=rate if rate is not None else "",
    )


_DURATION_SUFFIX_MAP: dict[str, str] = {
    "ms": "MS",
    "s": "SEC",
    "m": "MIN",
    "h": "HOUR",
    "d": "DAY",
    "w": "WEEK",
    "M": "MONTH",  # UPPERCASE M for month — distinct from minute "m"
    "y": "YEAR",
}


def _parse_duration_string(s: str) -> "DurationRange":
    """Parse a duration string like '1h', '30m', '1ms', '1M' into a DurationRange.

    Suffix table (case-sensitive on M vs m):
        ms = milliseconds
        s  = seconds
        m  = minutes
        h  = hours
        d  = days
        w  = weeks
        M  = months (UPPERCASE — distinct from minute)
        y  = years

    Raises ValueError on unparseable input (loud-error contract).
    """
    # Two-char suffix 'ms' must be checked before the 1-char map (which
    # contains 's' that would otherwise match).
    suffix: str | None = None
    num: str | None = None
    if s.endswith("ms"):
        suffix, num = _DURATION_SUFFIX_MAP["ms"], s[:-2]
    elif len(s) >= 2 and s[-1] in _DURATION_SUFFIX_MAP:
        suffix, num = _DURATION_SUFFIX_MAP[s[-1]], s[:-1]

    # Require a non-empty numeric prefix. 'ms' alone (or 'sm', 's' alone)
    # previously matched and produced DurationRange(mostRecent='') which the
    # gateway either rejects or behaves unpredictably on. Loud-fail here.
    if suffix is None or not num or not num.lstrip("-").replace(".", "", 1).isdigit():
        raise ValueError(
            f"Cannot parse duration string {s!r}. Expected <number><suffix> "
            "where number is non-empty digits and suffix is one of "
            "ms (millisecond), s (second), m (minute), h (hour), d (day), "
            "w (week), M (month — UPPERCASE), y (year). "
            "Example: '1h' (1 hour), '30m' (30 minutes), '100ms' (100 ms), "
            "'1M' (1 month, capital M)."
        )
    return DurationRange(mostRecent=num, mostRecentUnits=suffix)


def _deserialize_prop_config(value: Any) -> Any:
    """Backwards-compat BeforeValidator.

    Accepts THREE input shapes:
    1) list[PropConfig] — pass-through (the canonical internal form).
    2) dict[prop, {"binding": <binding-dict>}] — the gateway emit shape;
       used by round-trip parsing and by any test that constructs
       propConfig from a literal dict matching the emit format.
    3) dict[prop, <binding-fields-directly>] — the legacy flat shape with
       the discriminator `type` at the top level. Treated as the binding
       object.

    Entry-level keys ``persistent``/``access``/``paramDirection``/``onChange``
    (seen in Designer-authored views and onChange scripts) are
    carried through — including binding-LESS entries like
    ``{"access": "PROTECTED", "persistent": true}``. Any OTHER sibling key
    next to ``binding`` is rejected loudly — silently dropping it would
    destroy data on re-emit (the sole-writer mandate forbids that).

    A dict entry whose value is a dict containing neither `"binding"`,
    a top-level `"type"` discriminator, nor an entry-level flag is almost
    certainly a typo (e.g. `"binding-typo"`). Fail loud with the actual keys
    so the user sees `you probably meant 'binding'` rather than a generic
    "discriminator field 'type' missing" deep inside Pydantic.
    """
    _FLAGS = ("persistent", "access", "paramDirection", "onChange")
    if isinstance(value, dict):
        out: list[PropConfig] = []
        for k, v in value.items():
            flags: dict[str, Any] = {}
            if isinstance(v, dict):
                flags = {f: v[f] for f in _FLAGS if f in v}
                if "binding" in v:
                    binding_data = v["binding"]
                    unknown = set(v) - {"binding", *_FLAGS}
                    if unknown:
                        raise ValueError(
                            f"propConfig entry {k!r} carries unsupported "
                            f"entry-level key(s) {sorted(unknown)!r} next to "
                            "'binding' — the model would silently drop them "
                            "on emit. Supported: persistent/access/"
                            "paramDirection/onChange; extend PropConfig if "
                            "the gateway shape grew."
                        )
                elif "type" in v:
                    binding_data = v  # flat-binding legacy shape
                    flags = {}
                elif flags:
                    if set(v) - set(_FLAGS):
                        raise ValueError(
                            f"propConfig entry {k!r} mixes entry-level flags "
                            f"with unknown key(s) {sorted(set(v) - set(_FLAGS))!r}."
                        )
                    binding_data = None  # flag-only entry (e.g. access/persistent)
                else:
                    raise ValueError(
                        f"propConfig entry {k!r} must be a dict containing "
                        "'binding' (gateway emit shape), 'type' (flat-binding "
                        "legacy shape), or an entry-level flag "
                        f"(persistent/access/paramDirection/onChange); got keys "
                        f"{sorted(v.keys())!r}. Most likely you meant the "
                        f"'binding' key."
                    )
            else:
                binding_data = v
            out.append(PropConfig(prop=k, binding=binding_data, **flags))
        return out
    return value


class Component(IgnitionBaseModel):
    type: str
    meta: Meta = Field(default_factory=Meta)
    props: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, Any] | None = None  # None (unset) vs {} (explicit empty)
    # SerializeAsAny: children hold typed Component subclasses (Label, Button, …)
    # whose `props` are typed models; without this, serializing through the base
    # `Component` schema emits a spurious PydanticSerializationUnexpectedValue
    # warning. SerializeAsAny serializes each child by its runtime type.
    children: list[SerializeAsAny["Component"]] = Field(default_factory=list)
    propConfig: Annotated[
        list[PropConfig],
        BeforeValidator(_deserialize_prop_config),
    ] = Field(default_factory=list)
    custom: dict[str, Any] = Field(default_factory=dict)
    events: EventsMap = Field(default_factory=dict)
    scripts: dict[str, Any] = Field(default_factory=dict)

    # Private builder-state for the transform chain.
    # PrivateAttr is excluded from model_dump() and model_validate().
    # Set by the .bind_*() helpers; read by .expression()/.map()/.format()/.script().
    _last_binding: Binding | None = PrivateAttr(default=None)

    def _propconfig_emit(self) -> dict[str, Any]:
        """Reshape list[PropConfig] -> dict[prop_path, {"binding": <dump>}].

        CRITICAL: the inner "binding" wrapper key is REQUIRED. Emitting
        {prop: binding.model_dump()} directly produces a wire-format the gateway
        silently rejects.

        Verified shape (Layout Card/view.json line 41-51):
            {"props.text": {"binding": {"type": "property", "config": {...}}}}

        Entry-level flags ride alongside the binding (Designer ground truth):
            {"position.basis": {"binding": {...}, "persistent": true}}
            {"meta.visible": {"access": "PROTECTED", "persistent": true}}
        """
        out: dict[str, Any] = {}
        for pc in self.propConfig:
            entry: dict[str, Any] = {}
            if pc.access is not None:
                entry["access"] = pc.access
            if pc.binding is not None:
                entry["binding"] = pc.binding.model_dump(exclude_none=True, mode="json")
            if pc.onChange is not None:
                entry["onChange"] = pc.onChange
            if pc.paramDirection is not None:
                entry["paramDirection"] = pc.paramDirection
            if pc.persistent is not None:
                entry["persistent"] = pc.persistent
            out[pc.prop] = entry
        return out

    def add_event(self, category: str, event_name: str, handler: EventHandler) -> Self:
        """Attach a typed event handler to this component.

        Establishes the three-layer category->eventName->handler
        structure that Perspective requires. The handler must be a ScriptEventHandler
        or NavEventHandler; it is typed as EventHandler (discriminated union).

        Usage::

            from ignition_gen_sdk.models.views.events import ScriptEventHandler, ScriptEventConfig
            slider.add_event(
                "component",
                "onActionPerformed",
                ScriptEventHandler(type="script", scope="G",
                                   config=ScriptEventConfig(script="pass")),
            )

        Returns Self for fluent chaining.

        A ScriptEventHandler's script body is validated against the system.*
        whitelist — an unknown system namespace/leaf would throw at runtime
        but pass model validation; caught here at author time.
        """
        config = getattr(handler, "config", None)
        script = getattr(config, "script", None)
        if isinstance(script, str):
            from ...validation import unknown_system_calls

            bad = unknown_system_calls(script)
            if bad:
                raise ExpressionSyntaxError(
                    f"event handler '{category}.{event_name}' references unknown "
                    f"system.* function(s): {bad}. Check namespace/spelling, or add "
                    f"to ignition_gen_sdk.validation.ignition_builtins.SYSTEM_FUNCTIONS."
                )
        self.events.setdefault(category, {})[event_name] = handler
        return self

    # ---------- bind_property + transform-chain helpers ----------

    def bind_property(
        self,
        prop_path: str,
        path: str,
        *,
        bidirectional: bool | None = None,
        enabled: bool = True,
        overlayOptOut: bool = False,
        persistent: bool | None = None,
        access: str | None = None,
    ) -> Self:
        """Attach a property binding to the given prop_path.

        Explicit prop_path is the first argument. enabled defaults True,
        overlayOptOut defaults False. Returns Self so transform-chain methods
        can chain off.

        persistent/access are entry-level propConfig flags emitted alongside
        the binding (observed in Designer-authored views: `persistent: true`
        on position.* bindings, `access: "PROTECTED"` on props.enabled).

        Subsequent .expression()/.map()/.format()/.script() calls attach
        transforms to THIS binding via the private _last_binding handle.
        Calling .bind_*() again creates a new binding and updates _last_binding
        to point at it; transforms attached AFTER the second .bind_*() go to
        the second binding, not the first.
        """
        binding = PropertyBinding(
            enabled=enabled,
            overlayOptOut=overlayOptOut,
            config=PropertyBindingConfig(
                path=path,
                bidirectional=bidirectional,
            ),
            transforms=[],
        )
        self.propConfig.append(
            PropConfig(prop=prop_path, binding=binding, persistent=persistent, access=access)
        )
        self._last_binding = binding
        return self

    def bind_tag(
        self,
        prop_path: str,
        tagPath: str,
        *,
        mode: TagBindingMode = TagBindingMode.DIRECT,
        bidirectional: bool | None = None,
        fallbackDelay: float = 2.5,
        references: dict[str, str] | None = None,
        publishInitial: bool | None = None,
        enabled: bool = True,
        overlayOptOut: bool = False,
        persistent: bool | None = None,
        access: str | None = None,
    ) -> Self:
        """Attach a tag binding to the given prop_path.

        Modes:
        - DIRECT: tagPath is a literal tag reference like "[default]Tanks/T01/Level".
        - INDIRECT: tagPath contains placeholders like "{1}" or "{tagPath}";
          references maps placeholder names -> expression strings like
          "{view.params.tagPath}".
        - EXPRESSION: tagPath is an expression-language string.

        references is dict[str, str], NOT a list of reference objects —
        the field_validator on TagBindingConfig enforces this typed shape and
        raises ValueError on construction for non-dict / non-string-keys /
        non-string-values inputs.

        Returns Self; sets _last_binding for the transform chain
        (.expression()/.map()/.format()/.script()).
        """
        binding = TagBinding(
            enabled=enabled,
            overlayOptOut=overlayOptOut,
            config=TagBindingConfig(
                mode=mode,
                tagPath=tagPath,
                bidirectional=bidirectional,
                fallbackDelay=fallbackDelay,
                references=references,
                publishInitial=publishInitial,
            ),
            transforms=[],
        )
        self.propConfig.append(
            PropConfig(prop=prop_path, binding=binding, persistent=persistent, access=access)
        )
        self._last_binding = binding
        return self

    # ---------- per-property bind shortcuts ----------

    def bind_text(self, tagPath: str, **kwargs: Any) -> Self:
        """Shortcut: bind props.text to a tag path.

        Equivalent to .bind_tag("props.text", tagPath, **kwargs).
        Accepts all bind_tag keyword args (mode, bidirectional, etc.).

        Example:
            label.bind_text("[default]MyTag.value")
        emits:
            propConfig["props.text"] = {"binding": {"type": "tag",
              "config": {"tagPath": "[default]MyTag.value", "mode": "direct", ...}}}
        """
        return self.bind_tag("props.text", tagPath, **kwargs)

    def bind_value(self, tagPath: str, **kwargs: Any) -> Self:
        """Shortcut: bind props.value to a tag path.

        Equivalent to .bind_tag("props.value", tagPath, **kwargs).
        Used by Dropdown, Slider, NumericEntryField and other value-bearing components.

        Example:
            slider.bind_value("[default]Tanks/T01/Level")
        """
        return self.bind_tag("props.value", tagPath, **kwargs)

    def bind_visible(self, tagPath: str, **kwargs: Any) -> Self:
        """Shortcut: bind props.visible to a tag path.

        Equivalent to .bind_tag("props.visible", tagPath, **kwargs).

        Example:
            label.bind_visible("[default]System/ShowLabel")
        """
        return self.bind_tag("props.visible", tagPath, **kwargs)

    def bind_enabled(self, tagPath: str, **kwargs: Any) -> Self:
        """Shortcut: bind props.enabled to a tag path.

        Equivalent to .bind_tag("props.enabled", tagPath, **kwargs).

        Example:
            button.bind_enabled("[default]System/ButtonEnabled")
        """
        return self.bind_tag("props.enabled", tagPath, **kwargs)

    def set_prop(self, prop_path: str, value: Any) -> Self:
        """Set a static constant prop value directly — no binding involved.

        Companion to bind_expression(). Use this method for constant values
        that do NOT need dynamic evaluation (CSS class strings, literal labels,
        fixed numeric defaults, etc.). Constants must NEVER be wrapped in an
        ExpressionBinding — that rule is enforced by bind_expression().

        Routing table (explicit — no ambiguity):
          ``props.*``   → navigate/create nested keys in ``self.props``
                          starting after the ``"props."`` prefix.
                          Works whether ``self.props`` is a plain dict OR a
                          typed Pydantic BaseModel (e.g. LabelProps, IconProps).
          ``custom.*``  → navigate/create nested keys in ``self.custom``
                          starting after the ``"custom."`` prefix.
                          ``self.custom`` is always a plain dict.
          anything else → raises ValueError with a clear message naming both
                          valid prefixes.

        Navigation for dict props: the remainder after stripping the prefix is
        split on ``"."``. Missing intermediate dicts are created automatically.
        The leaf key is set to *value* unconditionally (overwrites prior value
        if present).

        Navigation for typed Pydantic model props:
          - Single segment (e.g. ``props.text``): ``setattr(self.props, seg, value)``.
          - Multiple segments (e.g. ``props.style.classes``): the first segment
            names a model field that holds a ``dict`` (or ``None``). The field is
            retrieved via ``getattr``; if ``None``, a fresh ``{}`` is setattr'd
            back first. The remaining segments are navigated as nested dict keys
            (intermediate dicts created as needed), and the leaf is set.

        Returns Self for fluent chaining.

        Examples::

            # dict props (bare Component):
            comp.set_prop("props.style.classes", "alarm")
            # → comp.props["style"]["classes"] == "alarm"

            # typed props (factory-built Label):
            label.set_prop("props.text", "Hello")
            # → label.props.text == "Hello"

            label.set_prop("props.style.classes", "state/on")
            # → label.props.style == {"classes": "state/on"}

            comp.set_prop("custom.label", "My Label")
            # → comp.custom["label"] == "My Label"

            comp.set_prop("text", "hello")
            # → ValueError: set_prop path must start with 'props.' or 'custom.'

        Raises:
            ValueError: if *prop_path* does not start with ``"props."`` or
                ``"custom."``.
        """
        import pydantic

        if prop_path.startswith("props."):
            remainder = prop_path[len("props."):]
            props = self.props

            if isinstance(props, pydantic.BaseModel):
                # Typed Pydantic props (e.g. LabelProps, IconProps).
                parts = remainder.split(".")
                if len(parts) == 1:
                    # Single-segment: direct attribute set.
                    setattr(props, parts[0], value)
                else:
                    # Multi-segment: first segment is a model field holding a
                    # dict (e.g. style: dict[str, Any] | None). Retrieve it,
                    # create {} if None, then navigate the rest as dict keys.
                    field_name = parts[0]
                    field_dict = getattr(props, field_name, None)
                    if not isinstance(field_dict, dict):
                        field_dict = {}
                        setattr(props, field_name, field_dict)
                    # Navigate/create nested dicts for intermediate segments.
                    target: dict[str, Any] = field_dict
                    for part in parts[1:-1]:
                        if part not in target or not isinstance(target[part], dict):
                            target[part] = {}
                        target = target[part]
                    target[parts[-1]] = value
                return self

            # Plain dict props path (unchanged).
            target = props  # type: ignore[assignment]

        elif prop_path.startswith("custom."):
            remainder = prop_path[len("custom."):]
            target = self.custom
        else:
            raise ValueError(
                f"set_prop path must start with 'props.' or 'custom.', "
                f"got {prop_path!r}. "
                f"Use 'props.<key>' to set a component prop, or "
                f"'custom.<key>' to set a custom property."
            )

        # Navigate/create nested dicts for all segments except the final leaf.
        parts = remainder.split(".")
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value
        return self

    def bind_expression(
        self,
        prop_path: str,
        expression: str,
        *,
        enabled: bool = True,
        overlayOptOut: bool = False,
        persistent: bool | None = None,
        access: str | None = None,
    ) -> Self:
        """Attach an expression binding to the given prop_path.

        persistent/access are entry-level propConfig flags emitted alongside
        the binding (observed in Designer-authored views: `persistent: true`
        on every position.display expr binding; same contract as
        bind_property).

        Guard: raises StaticBindingError if *expression* is a constant string
        (no ``{`` and no ``(``). Constants belong in ``props`` via set_prop() —
        wrapping them in an ExpressionBinding is a gateway anti-pattern (adds
        overhead with no dynamic benefit). Use set_prop(prop_path, value) instead.

        Performance note (see PERFORMANCE_ORDER):
        property > expression > script_transform > event_script.
        bind_expression() is the second-fastest binding path. Prefer bind_property()
        for simple cross-component wiring; use bind_expression() for computed values
        that require the expression language.

        Discriminator is "expr" (abbreviated). The expression TRANSFORM
        (the `.expression()` chain helper) uses "expression" (full
        word) — these are different and non-interchangeable.

        Returns Self; sets _last_binding so subsequent
        .map() / .format() / .script() / .expression() transform-chain
        helpers attach transforms to THIS binding.

        Raises:
            StaticBindingError: if *expression* contains no ``{`` and no ``(``.
                Use ``set_prop(prop_path, expression)`` for constant values.

        Example:
            c.bind_expression("props.animate", "toBoolean({view.params.animate})")
        emits:
            "propConfig": {"props.animate": {"binding":
              {"config": {"expression": "toBoolean({view.params.animate})"},
               "type": "expr", "enabled": true, "overlayOptOut": false,
               "transforms": []}}}
        """
        # Raise BEFORE mutating propConfig so the guard has no side-effects.
        if _is_static_expression(expression):
            raise StaticBindingError(
                f"bind_expression() received a static constant for prop '{prop_path}': "
                f"{expression!r}. "
                f"Constants must not be wrapped in ExpressionBindings. "
                f"Use set_prop({prop_path!r}, {expression!r}) instead. "
                f"Binding performance order: {PERFORMANCE_ORDER}."
            )
        # Reject Python '==' before mutating propConfig — Ignition equality is '='.
        # (_check_expression_syntax also warns on runScript() — script-tier cost.)
        _check_expression_syntax(expression)
        binding = ExpressionBinding(
            enabled=enabled,
            overlayOptOut=overlayOptOut,
            config=ExpressionBindingConfig(expression=expression),
            transforms=[],
        )
        self.propConfig.append(
            PropConfig(prop=prop_path, binding=binding, persistent=persistent, access=access)
        )
        self._last_binding = binding
        return self

    def bind_expression_structure(
        self,
        prop_path: str,
        struct: dict[str, Any] | None = None,
        *,
        waitOnAll: bool = True,
        enabled: bool = True,
        overlayOptOut: bool = False,
    ) -> Self:
        """Attach an expression-structure binding to the given prop_path.

        Discriminator is "expr-struct" (with hyphen). `struct` is a dict
        whose values are expression-language strings (`"{x.props.value}"`),
        quoted literals (`"\\"#CCCCFF\\""`), primitives (`0`), or further
        nested structures. Inner values pass
        through verbatim to the gateway — this is schema-only, no
        expression-language parsing.

        `struct` is accepted as `dict[str, Any] | None = None` for
        ergonomics — `.bind_expression_structure("p")` is valid and
        constructs with an empty struct. The None is replaced with `{}`
        at construction time so the underlying Pydantic field always
        holds a dict (never None).

        Returns Self; sets _last_binding for the transform chain.

        Example:
            c.bind_expression_structure(
                "props.arc",
                struct={"color": '"#CCCCFF"', "width": "{../Slider.props.value}"},
            )
        """
        binding = ExpressionStructureBinding(
            enabled=enabled,
            overlayOptOut=overlayOptOut,
            config=ExpressionStructureBindingConfig(
                struct=struct if struct is not None else {},
                waitOnAll=waitOnAll,
            ),
            transforms=[],
        )
        self.propConfig.append(PropConfig(prop=prop_path, binding=binding))
        self._last_binding = binding
        return self

    def bind_query(
        self,
        prop_path: str,
        queryPath: str,
        *,
        polling_enabled: bool | None = None,
        polling_rate: str | int | float | None = None,
        parameters: dict[str, str] | None = None,
        returnFormat: Literal["auto", "json", "dataset", "scalar"] | None = None,
        cacheAndShare: bool | None = None,
        enabled: bool = True,
        overlayOptOut: bool = False,
    ) -> Self:
        """Attach a query binding (named-query result) to the given prop_path.

        The model field and emitted JSON key is `queryPath`, NOT `path`;
        every observed live fixture and Designer export emits `queryPath`.

        Polling rate is a STRING on the
        wire ("5", "30", "1"). The PollingConfig field_validator coerces
        int/float -> str so users can write `polling_rate=5` naturally and
        still get gateway-correct emit.

        Polling sub-object is constructed ONLY when at least one of
        polling_enabled / polling_rate is supplied. With neither set, polling
        stays None and is excluded from emit by exclude_none — matches the
        fixture shape (no polling key) for non-polling bindings.

        Returns Self; sets _last_binding so subsequent
        .map() / .format() / .script() / .expression() transform-chain
        helpers attach transforms to THIS binding.

        Example:
            c.bind_query(
                "props.data",
                queryPath="Ignition 101/Named Query Binding",
                polling_enabled=True,
                polling_rate="5",
            )
        emits:
            "propConfig": {"props.data": {"binding":
              {"config": {"polling": {"enabled": true, "rate": "5"},
                          "queryPath": "Ignition 101/Named Query Binding"},
               "type": "query", "enabled": true, "overlayOptOut": false,
               "transforms": []}}}
        """
        polling = _build_polling(polling_enabled, polling_rate)
        binding = QueryBinding(
            enabled=enabled,
            overlayOptOut=overlayOptOut,
            config=QueryBindingConfig(
                queryPath=queryPath,
                polling=polling,
                parameters=parameters,
                returnFormat=returnFormat,
                cacheAndShare=cacheAndShare,
            ),
            transforms=[],
        )
        self.propConfig.append(PropConfig(prop=prop_path, binding=binding))
        self._last_binding = binding
        return self

    def bind_tag_history(
        self,
        prop_path: str,
        *,
        paths: str | list[str] | list[TagHistoryTag] | None = None,
        range: str | tuple[_datetime, _datetime] | DurationRange | AbsoluteRange | None = None,
        aggregation_mode: TagHistoryAggregation | None = None,
        return_format: Literal["Wide", "Tall", "Calculations"] | None = None,
        return_size_type: Literal["RAW", "FIXED"] | None = None,
        return_size_num_rows: str | None = None,
        return_size: ReturnSize | None = None,
        value_format: str | None = None,
        polling_enabled: bool | None = None,
        polling_rate: str | int | float | None = None,
        ignore_bad_quality: bool | None = None,
        prevent_interpolation: bool | None = None,
        avoid_scan_class_validation: bool | None = None,
        enable_value_cache: bool | None = None,
        query_mode: Literal["Realtime", "Historical"] | None = None,
        value_mode: Literal["delta", "cumulative"] | None = None,
        bounds: str | None = None,
        include_bounding_values: bool | None = None,
        deadband: float | None = None,
        enabled: bool = True,
        overlayOptOut: bool = False,
    ) -> Self:
        """Attach a tag-history binding to the given prop_path.

        Ergonomic-kwarg-to-gateway-field-name mapping:

            Builder kwarg          Model / emitted field
            -------------------    ---------------------
            paths                  tags
            range                  dateRange
            aggregation_mode       aggregate
            return_size_type +     returnSize
              return_size_num_rows (kwarg-pair builds ReturnSize)
            return_size            returnSize (pre-built passthrough)

        `range` accepts:
        - str like "1h", "30m" — parsed by _parse_duration_string into
          DurationRange.
        - (start_datetime, end_datetime) tuple — converted to AbsoluteRange.
        - DurationRange or AbsoluteRange instance — passes through verbatim.
        - None — dateRange stays None and is dropped from emit.

        `paths` is forwarded to TagHistoryBindingConfig.tags whose
        @field_validator handles the str / list / expression-string coercion.
        Direct list[TagHistoryTag] also works (passthrough).

        ReturnSize: pre-built `return_size=` wins over the kwarg pair
        return_size_type + return_size_num_rows; if neither form is supplied,
        returnSize stays None.

        Polling: built only when at least one of polling_enabled / polling_rate
        is supplied (same conditional pattern as bind_query).

        Returns Self for chain composition; sets _last_binding
        so subsequent .map() / .format() / .script() / .expression() transform
        helpers attach to THIS binding.

        Example (relative range, single tag, polling — Bindings/view.json
        fixture):
            c.bind_tag_history(
                "props.series[0].data",
                paths="[Sample_Tags]Realistic/Realistic0",
                range="1m",
                polling_enabled=True,
                polling_rate="1",
                return_format="Wide",
                return_size_type="RAW",
                value_format="DATASET",
                ignore_bad_quality=False,
                prevent_interpolation=False,
                avoid_scan_class_validation=True,
            )

        Example (absolute range, expression-string tags, aggregate=MinMax —
        Historical Data/view.json fixture):
            c.bind_tag_history(
                "props.series[0].data",
                paths="{parent.custom.selectedTags}",
                range=AbsoluteRange(
                    startDate="{...selectedRange.start}",
                    endDate="{...selectedRange.end}",
                ),
                aggregation_mode=TagHistoryAggregation.MIN_MAX,
                return_size_type="FIXED",
                return_size_num_rows="100",
                ...
            )
        """
        # `range` is the API parameter name (matches the Designer wording) but
        # shadows the builtin. Rebind to `_range` locally and del the param
        # so the builtin remains callable inside this function body.
        _range = range
        del range

        # paths -> tags field (model's @field_validator does the actual coercion)
        tags = paths

        # _range -> dateRange parsing
        dateRange: DurationRange | AbsoluteRange | None = None
        if isinstance(_range, str):
            dateRange = _parse_duration_string(_range)
        elif isinstance(_range, tuple) and len(_range) == 2:
            start, end = _range
            dateRange = AbsoluteRange(startDate=start, endDate=end)
        elif isinstance(_range, (DurationRange, AbsoluteRange)):
            dateRange = _range
        elif _range is not None:
            raise ValueError(
                f"range must be str | tuple[datetime, datetime] | DurationRange | "
                f"AbsoluteRange, got {type(_range).__name__}"
            )

        # returnSize: pre-built wins; otherwise build from kwarg-pair if type set.
        if return_size is None and return_size_type is not None:
            return_size = ReturnSize(type=return_size_type, numRows=return_size_num_rows)

        # Polling sub-object — only built if at least one polling kwarg supplied.
        polling = _build_polling(polling_enabled, polling_rate)

        binding = TagHistoryBinding(
            enabled=enabled,
            overlayOptOut=overlayOptOut,
            config=TagHistoryBindingConfig(
                tags=tags,
                dateRange=dateRange,
                aggregate=aggregation_mode,
                returnSize=return_size,
                returnFormat=return_format,
                valueFormat=value_format,
                polling=polling,
                ignoreBadQuality=ignore_bad_quality,
                preventInterpolation=prevent_interpolation,
                avoidScanClassValidation=avoid_scan_class_validation,
                enableValueCache=enable_value_cache,
                queryMode=query_mode,
                valueMode=value_mode,
                bounds=bounds,
                includeBoundingValues=include_bounding_values,
                deadband=deadband,
            ),
            transforms=[],
        )
        self.propConfig.append(PropConfig(prop=prop_path, binding=binding))
        self._last_binding = binding
        return self

    def bind_http(
        self,
        prop_path: str,
        url: str,
        *,
        method: HttpMethod | str = HttpMethod.GET,
        auth_type: Literal["None", "Basic", "Bearer", "Digest"] | None = None,
        auth_value: str | None = None,
        headers: list[HttpHeader] | list[tuple[str, str]] | None = None,
        body: str | None = None,
        content_type: str | None = None,
        query_params: dict[str, str] | None = None,
        connect_timeout: int | None = None,
        socket_timeout: int | None = None,
        polling_enabled: bool | None = None,
        polling_rate: str | int | float | None = None,
        enable_cookies: bool | None = None,
        enable_value_cache: bool | None = None,
        error_handling: dict[str, Any] | None = None,
        enabled: bool = True,
        overlayOptOut: bool = False,
    ) -> Self:
        """Attach an HTTP binding to the given prop_path.

        Gateway shape:
        - INSIDE request sub-object: method, url, auth, headers, body,
          contentType, queryParams.
        - OUTSIDE request (config-level siblings): connectTimeout,
          socketTimeout, polling, enableCookies, enableValueCache,
          errorHandling.

        FEATURES.md flattened all of these into one dict; the actual
        gateway emit (Bindings/view.json line 1086-1107) puts the request
        fields under `request: {...}` and the timeouts/polling/etc. at
        the config root. This builder constructs the nested shape
        unconditionally.

        URL convention: the gateway expects URLs as JSON-encoded strings.
            url='"https://example.com"'            # literal — inner quotes
            url='{"http://" + view.params.host}'   # expression — no inner quotes

        Headers ergonomic forms: `headers=[("X-API-Key", "abc"), ...]`
        accepts 2-tuples that the builder converts to HttpHeader objects;
        `headers=[HttpHeader(...)]` passthrough is also valid.

        Auth: `auth_type` + `auth_value` build the HttpAuth sub-object
        ONLY when at least one is supplied; with neither set, request.auth
        stays None and is excluded from emit.

        Polling: same conditional pattern as bind_query / bind_tag_history —
        PollingConfig built only when at least one of polling_enabled /
        polling_rate is supplied.

        Full 8.3 surface. No module-availability pre-flight check:
        HTTP binding is stock Perspective (no module required).

        Credential guard: HttpAuth.value is a plain string
        field; IgnitionBaseModel._block_credential_fields inspects raw
        TOP-LEVEL dict keys (ciphertext / encrypted_key / iv / protected /
        tag), not nested string contents. `auth_value='Bearer xyz'` passes
        through safely; the top-level guard still fires on any attempt to
        smuggle JWE keys into the HttpBindingConfig dict directly.

        Returns Self for chain composition; sets
        _last_binding so subsequent .map() / .format() / .script() /
        .expression() transform helpers attach to THIS binding.

        Example (matches Bindings/view.json line 1086-1107 weather API):
            c.bind_http(
                "custom.response",
                url='"https://api.weather.gov/stations/KSMF/observations/latest"',
                method=HttpMethod.GET,
                connect_timeout=60000,
                socket_timeout=60000,
                enable_cookies=True,
                enable_value_cache=True,
                polling_enabled=False,
                polling_rate="",
            )
        """
        # Validate headers via TypeAdapter so unrecognized entries
        # surface as ValidationError (consistent with the rest of the chain),
        # then convert tuples to HttpHeader objects in one pass.
        http_headers: list[HttpHeader] | None = None
        if headers is not None:
            validated = _HEADER_INPUT_TA.validate_python(headers)
            http_headers = [
                h if isinstance(h, HttpHeader) else HttpHeader(key=h[0], value=h[1])
                for h in validated
            ]

        # Auth sub-object — built only if at least one kwarg supplied.
        auth: HttpAuth | None = None
        if auth_type is not None or auth_value is not None:
            auth = HttpAuth(
                type=auth_type if auth_type is not None else "None",
                value=auth_value if auth_value is not None else "",
            )

        # Polling sub-object — same conditional pattern as bind_query /
        # bind_tag_history.
        polling = _build_polling(polling_enabled, polling_rate)

        # Build the nested request sub-object.
        request = HttpRequest(
            method=method,
            url=url,
            auth=auth,
            headers=http_headers,
            body=body,
            contentType=content_type,
            queryParams=query_params,
        )

        binding = HttpBinding(
            enabled=enabled,
            overlayOptOut=overlayOptOut,
            config=HttpBindingConfig(
                request=request,
                connectTimeout=connect_timeout,
                socketTimeout=socket_timeout,
                polling=polling,
                enableCookies=enable_cookies,
                enableValueCache=enable_value_cache,
                errorHandling=error_handling,
            ),
            transforms=[],
        )
        self.propConfig.append(PropConfig(prop=prop_path, binding=binding))
        self._last_binding = binding
        return self

    def expression(self, expr: str) -> Self:
        """Append an ExpressionTransform to the most-recently-attached binding.

        Reads _last_binding (set by the preceding .bind_*() call),
        appends an ExpressionTransform to its transforms list, returns Self.

        Raises RuntimeError if called without a preceding .bind_*() call —
        explicit error is preferable to silent transform-loss.

        NOTE: this is the TRANSFORM (discriminator "expression"). The
        expression *binding* is a separate thing with discriminator
        "expr". The .bind_expression() helper attaches that binding;
        this .expression() method attaches a transform to ANY preceding
        binding (property, tag, query, etc.).
        """
        if self._last_binding is None:
            raise RuntimeError(
                ".expression() called without a preceding .bind_*() call. "
                "Chain transforms AFTER attaching a binding: "
                "component.bind_property('props.text', 'x').expression('upper({value})')"
            )
        # Same Ignition-expression syntax guard as bind_expression: a
        # transform expression is the same language — reject Python '==',
        # unbalanced ()/{} before they reach the gateway as a silent parse error.
        _check_expression_syntax(expr)
        self._last_binding.transforms.append(ExpressionTransform(expression=expr))
        return self

    def map(self, mappings: dict[str | int | float, Any]) -> Self:
        """Append a MapTransform to the most-recently-attached binding.

        Dict input. The 'fallback' key (if present) is popped and used as
        MapTransform.fallback; remaining keys become MapMapping entries with
        input=key, output=value. The caller's dict is NOT mutated — we copy
        first via dict(mappings) before popping.

        Example:
            c.bind_tag('props.text', '[default]X')
             .map({'true': 'ON', 'false': 'OFF', 'fallback': 'UNK'})
        emits transforms[0] = {"type": "map", "inputType": "scalar",
                                "outputType": "scalar",
                                "mappings": [{"input": "true", "output": "ON"},
                                             {"input": "false", "output": "OFF"}],
                                "fallback": "UNK"}.

        Raises RuntimeError if no binding has been attached via a preceding
        .bind_*() call — explicit error over silent transform-loss.
        """
        if self._last_binding is None:
            raise RuntimeError(
                ".map() called without a preceding .bind_*() call. "
                "Chain transforms AFTER attaching a binding: "
                "component.bind_property('props.text', 'x').map({'a': 'A'})"
            )
        # Pop 'fallback' BEFORE iterating; copy first so caller's dict is unaffected.
        mappings_copy = dict(mappings)
        fallback = mappings_copy.pop("fallback", None)
        transform = MapTransform(
            mappings=[MapMapping(input=k, output=v) for k, v in mappings_copy.items()],
            fallback=fallback,
        )
        self._last_binding.transforms.append(transform)
        return self

    def format(self, format_string: str) -> Self:
        """Append a FormatTransform (numeric, printf-style) to the most-recently-attached binding.

        format() always uses formatType="numeric". For datetime formats,
        construct FormatTransform(formatType="datetime",
        formatValue=FormatDatetimeConfig(date=..., time=...)) directly and
        append via self._last_binding.transforms.append(...).

        Raises RuntimeError if no binding has been attached via a preceding
        .bind_*() call.

        Note: this method name shadows the Python builtin `format()`.
        Inside this method body the shadow is harmless (we never call
        builtins.format), but the choice is intentional to match the
        transform name. A v2 API redesign may rename to `.with_format()` /
        `.transform.format(...)` for consistency with future-introduced
        non-builtin-shadowing helpers; until then, keep the current name.
        """
        if self._last_binding is None:
            raise RuntimeError(
                ".format() called without a preceding .bind_*() call. "
                "Chain transforms AFTER attaching a binding: "
                "component.bind_property('props.text', 'x').format('0.00')"
            )
        self._last_binding.transforms.append(
            FormatTransform(formatType="numeric", formatValue=format_string)
        )
        return self

    def script(self, code: str) -> Self:
        """Append a ScriptTransform (plain Jython source string) to the most-recently-attached binding.

        code is a plain string. The gateway parses Jython at load time.
        Whitespace (leading tabs, newlines) is preserved verbatim — required
        for fixture parity.

        Raises RuntimeError if no binding has been attached via a preceding
        .bind_*() call.
        """
        if self._last_binding is None:
            raise RuntimeError(
                ".script() called without a preceding .bind_*() call. "
                "Chain transforms AFTER attaching a binding: "
                "component.bind_property('props.text', 'x').script('return value')"
            )
        self._last_binding.transforms.append(ScriptTransform(code=code))
        return self

    @model_serializer(mode="wrap")
    def _serialize(self, handler, _info):
        """Single model serializer that emits the propConfig dict shape and
        omits empty collections to match gateway-sample wire format.

        Previously this was split between a @field_serializer that
        returned None for empty and a @model_serializer that stripped the
        resulting `"propConfig": None` — fragile because it depended on
        precise interactions between three Pydantic v2 serializer behaviors.
        One serializer is easier to reason about than two coupled ones.

        Also pop empty ``children``, ``custom``,
        ``events``, ``scripts`` — these fields are non-Optional
        default-factory collections so ``exclude_none`` cannot strip them.
        EVERY Designer-exported component leaf is shaped
        ``{meta, position, props, type}`` only; the gateway never emits
        these four keys when they are empty. Keeping them produces
        permanent Designer round-trip drift even though the gateway
        tolerates them on import. View-level ``custom`` / ``params`` are
        unaffected — this serializer is on Component only.
        """
        out = handler(self)
        if self.propConfig:
            out["propConfig"] = self._propconfig_emit()
        else:
            out.pop("propConfig", None)
        # Omit empty collections so the emit shape matches every
        # observed gateway component leaf.
        for key in ("children", "custom", "events", "scripts"):
            if key in out and out[key] in ([], {}):
                out.pop(key)
        # Omit an EMPTY props dict that was never explicitly provided —
        # ground-truth components without a props key must round-trip without
        # gaining "props": {} (zero explicit empty-props exist in the corpus).
        if out.get("props") == {} and "props" not in self.model_fields_set:
            out.pop("props", None)
        return out


# Resolve forward refs after all imports complete: `children: list["Component"]`
# plus the chain:
#   - Component.propConfig -> PropConfig.binding -> Binding (discriminated union)
#   - Each Binding.transforms -> Transform (discriminated union)
# transforms/__init__.py calls Component.model_rebuild() again from its own
# module-load step.
Component.model_rebuild()

# The ComponentUnion type alias lives in models/views/components/__init__.py.
# Import it from there — not from this module — to avoid a circular import
# (components/__init__.py imports Component from this file).
# This Component class is the base for all typed palette subclasses.
# The bare Component class is preserved as-is for backward compat and
# as a GenericComponent-equivalent when constructing arbitrary component dicts.
