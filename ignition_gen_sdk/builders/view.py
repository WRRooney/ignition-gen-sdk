"""ViewBuilder — fluent DSL for building Ignition 8.3 View objects.

Roots: flex_root, coord_root, split_root, tab_root, breakpoint_root,
column_root + matching add_to_* methods, then build().

Mirrors the TagBuilder pattern: plain Python class, accumulate state,
.build() triggers Pydantic validation once.

position=None (developer didn't specify) vs position={} (developer
explicitly passed an all-defaults position) are DIFFERENT in the wire format.
add_to_* methods set component.position = None when no position-input kwarg
is given; set it to a dict only when the developer passes one.
"""
# Binding performance order: property > expression > script.
# Builders make property/expression bindings the ergonomic default.
# Scripts are opt-in via Component.add_event() (for interaction events)
# or Component.script() (for transform pipelines). Use scripts only when
# no binding expression can satisfy the requirement.
from __future__ import annotations

from typing import Any, Literal, Self

from ..models.views.component import Component
from ..models.views.containers import (
    BreakpointContainer,
    ColumnContainer,
    CoordinateContainer,
    FlexContainer,
    SplitContainer,
    TabContainer,
    TabSpec,
)
from ..models.views.meta import Meta
from ..models.views.positions import (
    BreakpointChildPosition,
    ColumnBreakpoint,
    ColumnChildPosition,
    CoordinatePosition,
    FlexChildPosition,
    SplitChildPosition,
    TabChildPosition,
)
from ..models.views.view import View


def _reject_snake_case_typos(props: dict[str, Any], props_cls: type) -> None:
    """Catch a snake_case kwarg that is really a typo of a camelCase wire prop.

    Component Props models use ``extra="allow"`` (so any documented Ignition prop
    rides through unmodeled). The downside: a natural snake_case guess of a
    camelCase prop (``view_params`` for ``viewParams``, ``read_only`` for
    ``readOnly``, ``x_axis`` for ``xAxis``, …) is silently KEPT as a junk prop
    and never applied — a silent-failure trap. If a passed key
    contains ``_``, is NOT itself a field, but its camelCase form IS a field of
    this Props class, raise a helpful error instead of letting it ride through.
    """
    fields = set(getattr(props_cls, "model_fields", {}))
    for key in props:
        if "_" not in key or key in fields:
            continue
        parts = key.split("_")
        camel = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)
        if camel in fields:
            raise ValueError(
                "%s: use %s=... (camelCase — the Ignition wire key), not %s=...; "
                "a snake_case key is silently kept as an unused prop, not applied."
                % (props_cls.__name__, camel, key)
            )


def tag_history_source(
    history_provider: str,
    tag_provider: str,
    tag_path: str,
    *,
    gateway: str,
) -> str:
    """Build a Power Chart pen ``data.source`` (Tag-Historian reference).

    Shape (reverse-engineered from a Designer-authored Power Chart view):
        ``histprov:<history_provider>:/drv:<gateway>:<tag_provider>:/tag:<tag_path>``
    The pen resolves to live history only if a historian named ``history_provider``
    exists on ``gateway`` and the tag is historized.
    """
    return f"histprov:{history_provider}:/drv:{gateway}:{tag_provider}:/tag:{tag_path}"


def power_chart_pen(
    name: str,
    source: str,
    *,
    plot: int = 0,
    axis: str = "",
    pen_type: str = "line",
    color: "str | None" = None,
    fill_opacity: "float | None" = None,
    enabled: bool = True,
    visible: bool = True,
    selectable: bool = True,
    aggregate_mode: str = "default",
) -> dict[str, Any]:
    """Build one Power Chart pen dict.

    ``source`` is a Tag-Historian reference — see :func:`tag_history_source`.
    When ``color`` (a CSS hex like ``"#34C3FF"``) is given, the full
    ``display.styles`` block (normal/highlighted/muted/selected, fill+stroke) is
    emitted with that color; otherwise the gateway fills style defaults. Pass the
    result list to :meth:`ViewBuilder.power_chart`.
    """
    display: dict[str, Any] = {"type": pen_type}
    if color is not None:
        def _state(opacity: float) -> dict[str, Any]:
            fop = fill_opacity if fill_opacity is not None else opacity
            return {
                "fill": {"color": color, "opacity": fop},
                "stroke": {"color": color, "dashArray": 0, "opacity": opacity, "width": 1},
            }
        display.update({
            "breakLine": True,
            "interpolation": "curveLinear",
            "radius": 3,
            "styles": {
                "normal": _state(0.8),
                "highlighted": _state(1),
                "muted": _state(0.4),
                "selected": _state(1),
            },
        })
    return {
        "name": name,
        "axis": axis,
        "enabled": enabled,
        "visible": visible,
        "selectable": selectable,
        "plot": plot,
        "data": {"source": source, "aggregateMode": aggregate_mode},
        "display": display,
    }


class ViewBuilder:
    def __init__(self, *, name: str | None = None) -> None:
        self._name: str | None = name
        self._root: Component | None = None
        self._params: dict[str, Any] = {}
        self._custom: dict[str, Any] = {}
        self._props: dict[str, Any] = {}
        self._propConfig: dict[str, Any] = {}

    # ---- Root container shortcuts ----

    def flex_root(self, *, direction: str = "column", **props: Any) -> Self:
        self._root = FlexContainer(
            meta=Meta(name="root"),
            props={"direction": direction, **props},
            children=[],
        )
        return self

    def coord_root(self, **props: Any) -> Self:
        self._root = CoordinateContainer(
            meta=Meta(name="root"),
            props=dict(props),
            children=[],
        )
        return self

    def split_root(self, *, orientation: str = "horizontal", **props: Any) -> Self:
        self._root = SplitContainer(
            meta=Meta(name="root"),
            props={"orientation": orientation, **props},
            children=[],
        )
        return self

    def tab_root(
        self,
        *,
        tabs: list[str | TabSpec | dict[str, Any]] | None = None,
        **props: Any,
    ) -> Self:
        merged: dict[str, Any] = dict(props)
        if tabs is not None:
            # Both forms are valid in 8.3: a bare string array
            # and an object array {text, disabled, icon} (Designer exports,
            # Designer-canonical). Normalize TabSpec -> plain dict; leave
            # str / pre-built dict entries untouched.
            merged["tabs"] = [
                t.model_dump(by_alias=True, exclude_none=True, mode="json")
                if isinstance(t, TabSpec)
                else t
                for t in tabs
            ]
        self._root = TabContainer(
            meta=Meta(name="root"),
            props=merged,
            children=[],
        )
        return self

    def breakpoint_root(self, *, breakpoint: int | None = None, **props: Any) -> Self:
        merged: dict[str, Any] = dict(props)
        if breakpoint is not None:
            merged["breakpoint"] = breakpoint
        self._root = BreakpointContainer(
            meta=Meta(name="root"),
            props=merged,
            children=[],
        )
        return self

    def column_root(self, **props: Any) -> Self:
        self._root = ColumnContainer(
            meta=Meta(name="root"),
            props=dict(props),
            children=[],
        )
        return self

    # ---- Add children: typed per-container entry points ----

    def _attach_once(self, component: Component) -> None:
        """Append a child to the current root exactly once, by IDENTITY.

        The element factories (``label()``, ``icon()``, …) AUTO-ATTACH the
        component they create to the current root. A natural pattern is then
        ``add_to_breakpoint(vb.label(...), size="large")`` — but a plain
        ``children.append`` would attach the SAME object a second time,
        producing duplicate children (the breakpt/split/tab/column trap).
        Identity de-dup makes the ``add_to_*`` helpers idempotent: a freshly
        constructed standalone component (not yet attached) is appended as
        before; an already-attached factory component just gets its position
        set in place. Two distinct components that happen to be field-equal are
        NOT collapsed (identity, not ``==``)."""
        if not any(c is component for c in self._root.children):
            self._root.children.append(component)

    def add_to_flex(
        self,
        component: Component,
        position: FlexChildPosition | None = None,
    ) -> Self:
        if not isinstance(self._root, FlexContainer):
            raise TypeError(
                f"add_to_flex requires flex_root() first, got "
                f"{type(self._root).__name__ if self._root else 'None'}"
            )
        if position is not None:
            # Only set position when developer passes one
            component.position = position.model_dump(exclude_none=True, mode="json")
        # else: leave component.position as None (default)
        self._attach_once(component)
        return self

    def add_to_coord(
        self,
        component: Component,
        position: CoordinatePosition | None = None,
    ) -> Self:
        if not isinstance(self._root, CoordinateContainer):
            raise TypeError(
                f"add_to_coord requires coord_root() first, got "
                f"{type(self._root).__name__ if self._root else 'None'}"
            )
        if position is not None:
            component.position = position.model_dump(exclude_none=True, mode="json")
        self._attach_once(component)
        return self

    def add_to_split(
        self,
        component: Component,
        side: Literal["left", "right", "top", "bottom"] | None = None,
    ) -> Self:
        if not isinstance(self._root, SplitContainer):
            raise TypeError(
                f"add_to_split requires split_root() first, got "
                f"{type(self._root).__name__ if self._root else 'None'}"
            )
        if side is not None:
            component.position = SplitChildPosition(position=side).model_dump(
                exclude_none=True, mode="json"
            )
        self._attach_once(component)
        return self

    def add_to_tab(
        self,
        component: Component,
        tab_index: int | None = None,
    ) -> Self:
        if not isinstance(self._root, TabContainer):
            raise TypeError(
                f"add_to_tab requires tab_root() first, got "
                f"{type(self._root).__name__ if self._root else 'None'}"
            )
        if tab_index is not None:
            component.position = TabChildPosition(tabIndex=tab_index).model_dump(
                exclude_none=True, mode="json"
            )
        self._attach_once(component)
        return self

    def add_to_breakpoint(
        self,
        component: Component,
        size: Literal["large", "small"] | None = None,
    ) -> Self:
        if not isinstance(self._root, BreakpointContainer):
            raise TypeError(
                f"add_to_breakpoint requires breakpoint_root() first, got "
                f"{type(self._root).__name__ if self._root else 'None'}"
            )
        if size is not None:
            component.position = BreakpointChildPosition(size=size).model_dump(
                exclude_none=True, mode="json"
            )
        self._attach_once(component)
        return self

    def add_to_column(
        self,
        component: Component,
        *,
        basis: str | None = None,
        breakpoints: list[ColumnBreakpoint | dict[str, Any]] | None = None,
        grow: int | float | None = None,
        height: int | float | None = None,
    ) -> Self:
        if not isinstance(self._root, ColumnContainer):
            raise TypeError(
                f"add_to_column requires column_root() first, got "
                f"{type(self._root).__name__ if self._root else 'None'}"
            )
        # Build a position only if at least one position kwarg was passed.
        has_pos = any(v is not None for v in (basis, breakpoints, grow, height))
        if has_pos:
            pos = ColumnChildPosition(
                basis=basis,
                breakpoints=breakpoints,
                grow=grow,
                height=height,
            )
            component.position = pos.model_dump(exclude_none=True, mode="json")
        self._attach_once(component)
        return self

    # ---- View-level setters ----

    def params(self, **kwargs: Any) -> Self:
        self._params.update(kwargs)
        return self

    def prop_config(self, key: str, config: dict[str, Any]) -> Self:
        """Raw dict-in escape hatch for a propConfig entry. Prefer the typed
        binding builders (`bind_expression`/`bind_custom_tag`/`bind_custom_expression`,
        which route through the author-time guards); use `prop_config` only for a
        binding shape those don't yet cover."""
        self._propConfig[key] = config
        return self

    def custom(self, name: str, value: Any = None) -> Self:
        """Set a view-level ``custom.<name>`` property (default value).

        View doctrine: components bind to ``view.custom.*``, never to a tag
        directly. This is the public setter for that data surface (previously
        only the private ``_custom`` dict existed). Pair with
        :meth:`bind_custom_tag` to tag-bind it.
        """
        self._custom[name] = value
        return self

    def drop_udt(self, type_id: str, param: str = "tagPath") -> Self:
        """Declare a Designer drag-and-drop target: dropping a UDT instance of
        ``type_id`` from the Tag Browser onto a container embeds this view with
        ``param`` = the instance path (``props.dropConfig.udts[]``, action
        ``path``). Typical on a view that renders one UDT instance (a UDT tile)."""
        udts = self._props.setdefault("dropConfig", {}).setdefault("udts", [])
        udts.append({"action": "path", "param": param, "type": type_id})
        return self

    def bind_custom_tag(
        self,
        name: str,
        tag_path: str,
        *,
        mode: str = "direct",
        bidirectional: bool = False,
        fallback_delay: float = 2.5,
        value: Any = None,
        references: dict[str, str] | None = None,
        transforms: list[dict[str, Any]] | None = None,
        persistent: bool | None = None,
    ) -> Self:
        """Declare ``custom.<name>`` and tag-bind it at the view level.

        Emits the canonical view-level tag binding under
        ``propConfig["custom.<name>"]`` and registers the ``custom.<name>``
        property — the one-call expression of "data → view.custom.*". Components
        then bind their props to ``{view.custom.<name>}`` via
        :meth:`Component.bind_property`.

        Args:
            references: explicit indirect-reference map. Perspective accepts
                BOTH forms — numbered (`tagPath:"{1}/State"`,
                `references:{"1":"{view.params.path}"}`) and NAMED
                (`tagPath:"{tagPath}.meta_label"`,
                `references:{"tagPath":"{view.params.tagPath}"}` — the
                named-reference idiom). When given, it is used as-is
                and no token rewriting happens. A bare `{param}` token is only
                malformed when NO references entry resolves it.
            transforms: raw transform dicts appended to the binding (e.g. an
                `isGood` enabled-guard expression transform).
            persistent: entry-level propConfig flag alongside the binding.
        """
        if references is not None and mode != "indirect":
            raise ValueError(
                "bind_custom_tag: references= only applies to mode='indirect' — "
                "a direct binding would silently drop them and leave literal "
                "{token}s in the tagPath (bad quality at runtime)."
            )
        self._custom.setdefault(name, value)
        config: dict[str, Any] = {"mode": mode, "tagPath": tag_path, "fallbackDelay": fallback_delay}
        if mode == "indirect":
            if references is not None:
                import re as _re

                unresolved = [
                    m.group(1)
                    for m in _re.finditer(r"\{([A-Za-z_]\w*)\}", tag_path)
                    if m.group(1) not in references
                ]
                if unresolved:
                    raise ValueError(
                        f"bind_custom_tag: bare token(s) {unresolved!r} in "
                        f"tagPath {tag_path!r} have no references entry — the "
                        "binding would not resolve. Add them to "
                        "references= or use the auto-numbering path."
                    )
                config["references"] = references
            else:
                # No explicit references: rewrite each bare {param} token to {N}
                # and build a numbered references map -> {view.params.<param>}.
                # Already-numbered ({1}) and dotted ({view.params.x}) tokens are
                # left untouched.
                import re as _re

                tokens: list[str] = []
                for m in _re.finditer(r"\{([A-Za-z_]\w*)\}", tag_path):
                    if m.group(1) not in tokens:
                        tokens.append(m.group(1))
                if tokens:
                    refs: dict[str, str] = {}
                    new_path = tag_path
                    for i, tok in enumerate(tokens, start=1):
                        new_path = new_path.replace("{%s}" % tok, "{%d}" % i)
                        refs[str(i)] = "{view.params.%s}" % tok
                    config["tagPath"] = new_path
                    config["references"] = refs
        if bidirectional:
            config["bidirectional"] = True
        binding: dict[str, Any] = {"type": "tag", "config": config}
        if transforms:
            binding["transforms"] = transforms
        entry: dict[str, Any] = {"binding": binding}
        if persistent is not None:
            entry["persistent"] = persistent
        self._propConfig[f"custom.{name}"] = entry
        return self

    def bind_custom_expression(
        self,
        name: str,
        expr: str,
        *,
        value: Any = None,
        persistent: bool | None = None,
    ) -> Self:
        """Declare ``custom.<name>`` and bind it to an Ignition EXPRESSION at the view level.

        The expression sibling of :meth:`bind_custom_tag` — for "data → view.custom.*"
        where the source is a computed expression, not a tag. Routes the expression
        through the same syntax guard as ``Component.bind_expression`` (rejects Python
        ``==`` and unbalanced ``()``/``{}``), so a view-level custom expression cannot
        bypass validation the way a hand-built ``_propConfig`` dict would.

        Args:
            value: optional default for the registered ``custom.<name>`` property.
            persistent: if set, emitted as the ``persistent`` flag on the propConfig
                entry (alongside ``binding``); omitted when None.
        """
        from ..models.views.component import _check_expression_syntax

        _check_expression_syntax(expr)
        self._custom.setdefault(name, value)
        entry: dict[str, Any] = {"binding": {"type": "expr", "config": {"expression": expr}}}
        if persistent is not None:
            entry["persistent"] = persistent
        self._propConfig[f"custom.{name}"] = entry
        return self

    # ---- Component factory helpers ----
    # Factory helpers return typed Component for .bind_*() chaining AND
    # auto-attach to root.children when a root has been set.
    # Deferred imports prevent circular import with models/views/components/__init__.py.

    def _auto_attach(self, component: "Any") -> "Any":
        """Append component to root.children if a root has been set.

        Auto-attach semantics: factory helpers return the component for
        .bind_*() chaining AND attach it to the current root container.
        If no root has been set yet, the component is returned standalone
        (backward-compatible with explicit add_to_* usage).
        """
        if self._root is not None and hasattr(self._root, "children"):
            self._root.children.append(component)
        return component

    def label(self, *, text: str = "", name: str = "Label", **props: Any) -> "Any":
        """Factory: create a typed Label component, auto-attached to root if set.

        Returns the Label for .bind_*() chaining:
            vb.flex_root()
            vb.label(text="Hello").bind_text("[default]MyTag.value")
            view = vb.build()
        """
        from ..models.views.components.display import Label, LabelProps
        from ..models.views.meta import Meta as _Meta
        _reject_snake_case_typos(props, LabelProps)
        return self._auto_attach(Label(
            meta=_Meta(name=name),
            props=LabelProps(text=text, **props),
        ))

    def power_chart(
        self,
        *,
        name: str = "PowerChart",
        pens: "list[dict[str, Any]] | None" = None,
        **props: Any,
    ) -> "Any":
        """Factory: create an ``ia.chart.powerchart`` component, auto-attached to root.

        Build pens with :func:`power_chart_pen` (+ :func:`tag_history_source`) and pass
        them here. Extra ``props`` (config/interaction/timeAxis/plots) ride through.
        """
        from ..models.views.components.chart import PowerChart, PowerChartProps
        from ..models.views.meta import Meta as _Meta
        prop_kwargs: dict[str, Any] = dict(props)
        if pens is not None:
            prop_kwargs["pens"] = pens
        _reject_snake_case_typos(prop_kwargs, PowerChartProps)
        return self._auto_attach(PowerChart(
            meta=_Meta(name=name),
            props=PowerChartProps(**prop_kwargs),
        ))

    def button(self, *, text: str = "Button", name: str = "Button", **props: Any) -> "Any":
        """Factory: create a typed Button component, auto-attached to root if set."""
        from ..models.views.components.input import Button, ButtonProps
        from ..models.views.meta import Meta as _Meta
        _reject_snake_case_typos(props, ButtonProps)
        return self._auto_attach(Button(
            meta=_Meta(name=name),
            props=ButtonProps(text=text, **props),
        ))

    def image(self, *, source: str = "", name: str = "Image", **props: Any) -> "Any":
        """Factory: create a typed Image component, auto-attached to root if set."""
        from ..models.views.components.display import Image, ImageProps
        from ..models.views.meta import Meta as _Meta
        _reject_snake_case_typos(props, ImageProps)
        return self._auto_attach(Image(
            meta=_Meta(name=name),
            props=ImageProps(source=source, **props),
        ))

    def alarm_status_table(self, *, name: str = "AlarmStatusTable", **props: Any) -> "Any":
        """Factory: create a typed AlarmStatusTable (ia.display.alarmstatustable), auto-attached to root if set.

        Live/active alarm table. Props are permissive (extra="allow") — any
        documented prop (alarmFilter, columns, alarmListConfig, ...) rides through.
        """
        from ..models.views.components.display import AlarmStatusTable, AlarmStatusTableProps
        from ..models.views.meta import Meta as _Meta
        _reject_snake_case_typos(props, AlarmStatusTableProps)
        return self._auto_attach(AlarmStatusTable(
            meta=_Meta(name=name),
            props=AlarmStatusTableProps(**props),
        ))

    def alarm_journal_table(self, *, name: str = "AlarmJournalTable", **props: Any) -> "Any":
        """Factory: create a typed AlarmJournalTable (ia.display.alarmjournaltable), auto-attached to root if set.

        Alarm history table. Props are permissive (extra="allow") — any
        documented prop (alarmFilter, columns, ...) rides through.
        """
        from ..models.views.components.display import AlarmJournalTable, AlarmJournalTableProps
        from ..models.views.meta import Meta as _Meta
        _reject_snake_case_typos(props, AlarmJournalTableProps)
        return self._auto_attach(AlarmJournalTable(
            meta=_Meta(name=name),
            props=AlarmJournalTableProps(**props),
        ))

    def embedded_view(self, *, view_path: str = "", name: str = "EmbeddedView", **props: Any) -> "Any":
        """Factory: create a typed EmbeddedView component, auto-attached to root if set.

        Pass params to the embedded view via the ``params`` dict (the wire
        key), e.g. ``embedded_view(view_path="Components/Symbols/Pump",
        params={"tagPath": "..."})``.
        """
        from ..models.views.components.embedding import EmbeddedView, EmbeddedViewProps
        from ..models.views.meta import Meta as _Meta
        # `view_params=` (snake, mirroring `view_path=`) is the natural wrong
        # guess. `params` has no camelCase form, so the generic snake-case-typo
        # guard below can't catch this one alone -- check it explicitly first.
        if "view_params" in props:
            raise ValueError(
                "EmbeddedViewProps: use params=... (the Ignition wire key), not "
                "view_params=...; a snake_case key is silently kept as an unused "
                "prop, never applied."
            )
        # Pre-2026-09 the field was (wrongly) named viewParams; extra="allow"
        # would keep the stale kwarg as a junk prop the runtime ignores.
        if "viewParams" in props:
            raise ValueError(
                "EmbeddedViewProps: use params=... (the Ignition wire key); "
                "viewParams was a model bug (renamed 2026-09) and would be "
                "kept as an unused prop, never applied."
            )
        # Catches every other snake/camel prop typo on this class
        # (e.g. use_default_view_height for useDefaultViewHeight).
        _reject_snake_case_typos(props, EmbeddedViewProps)
        return self._auto_attach(EmbeddedView(
            meta=_Meta(name=name),
            props=EmbeddedViewProps(path=view_path, **props),
        ))

    def flex_repeater(self, *, name: str = "FlexRepeater", **props: Any) -> "Any":
        """Factory: create a typed FlexRepeater component, auto-attached to root if set."""
        from ..models.views.components.embedding import FlexRepeater, FlexRepeaterProps
        from ..models.views.meta import Meta as _Meta
        _reject_snake_case_typos(props, FlexRepeaterProps)
        return self._auto_attach(FlexRepeater(
            meta=_Meta(name=name),
            props=FlexRepeaterProps(**props),
        ))

    def icon(self, *, path: str = "", name: str = "Icon", **props: Any) -> "Any":
        """Factory: create a typed Icon component (ia.display.icon), auto-attached to root if set.

        Used for Symbol Glyph and Row StateMarker components.
        Returns the Icon for .bind_*() chaining.

        Args:
            path: Icon library path, e.g. "material/alarm". Empty string is valid (no icon rendered).
            name: Component meta.name. Defaults to "Icon".
            **props: Additional IconProps fields (color, style, enabled, visible).
        """
        from ..models.views.components.display import Icon, IconProps
        from ..models.views.meta import Meta as _Meta
        from ..validation import unknown_material_icon

        # Reject an invalid Material icon at author time: a "material/<name>"
        # not in the gateway's bundled set renders nothing and CRASHES the
        # component at runtime (cloneElement null) while passing model validation.
        bad = unknown_material_icon(path)
        if bad is not None:
            raise ValueError(
                "Unknown Material icon 'material/%s' — not in the gateway's bundled "
                "icon set. Pick a valid name (e.g. plumbing, speed, settings) or add "
                "it to ignition_gen_sdk.validation.material_icons.MATERIAL_ICONS if the "
                "gateway has it." % bad
            )
        _reject_snake_case_typos(props, IconProps)
        return self._auto_attach(Icon(
            meta=_Meta(name=name),
            props=IconProps(path=path, **props),
        ))

    def flex_container(
        self,
        *,
        name: str = "FlexContainer",
        direction: str = "column",
        **props: Any,
    ) -> "Any":
        """Factory: create a standalone FlexContainer for use as a nested child.

        Does NOT auto-attach to the ViewBuilder root. The caller populates
        .children then passes the container to add_to_flex() or add_to_coord()
        as needed. Pattern::

            inner = vb.flex_container(name="Row", direction="row")
            inner.children.append(vb.label(text="value"))
            vb.add_to_flex(inner, position=FlexChildPosition(basis="32px"))

        This is the standard pattern for views where many flex
        containers are used, many as children of a root flex.

        Returns the FlexContainer for direct mutation (.children.append, .propConfig, etc).
        """
        merged: dict[str, Any] = {"direction": direction, **props}
        return FlexContainer(
            meta=Meta(name=name),
            props=merged,
            children=[],
        )

    # ---- Build ----

    def build(self) -> View:
        if self._root is None:
            raise ValueError(
                "ViewBuilder requires a root — call .flex_root() / .coord_root() / "
                ".split_root() / .tab_root() / .breakpoint_root() / .column_root() first."
            )
        return View(
            root=self._root,
            params=self._params,
            custom=self._custom,
            props=self._props,
            propConfig=self._propConfig if self._propConfig else None,
        )
