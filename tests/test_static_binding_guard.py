"""Tests for the StaticBindingError guard and the binding-performance documentation.

bind_expression() must RAISE StaticBindingError when given a constant string
    (no { and no ( in the expression). Constants belong in props, not propConfig.
    Callers must use set_prop() for constant values.

PERFORMANCE_ORDER constant documents the binding performance hierarchy:
    property > expression > script_transform > event_script.
    Builders make property/expression bindings the ergonomic default path.

set_prop() routing table:
    "props.*"  -> navigate/create nested keys in self.props
    "custom.*" -> navigate/create nested keys in self.custom
    anything else -> ValueError
"""
import pytest

from ignition_gen_sdk.models.views.component import (
    Component,
    StaticBindingError,
    _is_static_expression,
    PERFORMANCE_ORDER,
)
from ignition_gen_sdk.models.views.components.display import Label


# ------------------------------------------------------------
# _is_static_expression() heuristic
# ------------------------------------------------------------


def test_is_static_bare_word():
    """A bare word with no { or ( is static."""
    assert _is_static_expression("alarm") is True


def test_is_static_css_class_with_hyphen():
    """A CSS class string with hyphens but no { or ( is static."""
    assert _is_static_expression("card-name") is True


def test_is_static_css_class_multi_word():
    """Multiple CSS classes separated by space, no { or ( — static."""
    assert _is_static_expression("card-name card-name-on") is True


def test_is_static_empty_string():
    """Empty string is a static constant."""
    assert _is_static_expression("") is True


def test_is_static_plain_number():
    """Numeric literal string is static."""
    assert _is_static_expression("42") is True


def test_is_static_boolean_literal():
    """Boolean literal string is static."""
    assert _is_static_expression("true") is True


def test_not_static_curly_brace():
    """String containing { is dynamic (property reference)."""
    assert _is_static_expression("{view.custom.on}") is False


def test_not_static_function_call():
    """String containing ( is dynamic (function call)."""
    assert _is_static_expression("if({x}, 'a', 'b')") is False


def test_not_static_expression_binding_ref():
    """Full expression with property path is dynamic."""
    assert _is_static_expression("{view.params.tagPath}") is False


def test_not_static_number_format():
    """numberFormat(...) expression is dynamic — has both { and (."""
    assert _is_static_expression("numberFormat({view.custom.v}, '#0.0')") is False


def test_not_static_tobooleon_expression():
    """toBoolean({...}) is dynamic."""
    assert _is_static_expression("toBoolean({view.params.animate})") is False


def test_not_static_custom_ref():
    """Custom param reference is dynamic."""
    assert _is_static_expression("{custom.x}") is False


# ------------------------------------------------------------
# bind_expression() guard raises on static input
# ------------------------------------------------------------


def test_bind_expression_static_raises():
    """bind_expression with a static constant raises StaticBindingError."""
    comp = Component(type="ia.display.label")
    with pytest.raises(StaticBindingError) as exc_info:
        comp.bind_expression("props.style.classes", "alarm")
    msg = str(exc_info.value)
    # Error message must name the prop_path and suggest set_prop()
    assert "alarm" in msg
    assert "set_prop" in msg


def test_bind_expression_static_raises_names_prop_path():
    """StaticBindingError message must include the prop_path."""
    comp = Component(type="ia.display.label")
    with pytest.raises(StaticBindingError) as exc_info:
        comp.bind_expression("props.style.classes", "alarm")
    assert "props.style.classes" in str(exc_info.value)


def test_bind_expression_dynamic_passes():
    """bind_expression with a dynamic expression (containing {) does not raise."""
    comp = Component(type="ia.display.label")
    result = comp.bind_expression("props.style.classes", "if({view.custom.on}, 'on', 'off')")
    assert result is comp
    assert len(comp.propConfig) == 1


def test_bind_expression_dynamic_with_function_call_passes():
    """bind_expression with a function call (containing () passes."""
    comp = Component(type="ia.display.label")
    result = comp.bind_expression("props.text", "toBoolean({view.params.animate})")
    assert result is comp


def test_static_binding_error_is_value_error():
    """StaticBindingError must be a subclass of ValueError."""
    assert isinstance(StaticBindingError(), ValueError)


def test_static_binding_error_importable():
    """StaticBindingError is importable from ignition_gen_sdk.models.views.component."""
    from ignition_gen_sdk.models.views.component import StaticBindingError as SBE
    assert issubclass(SBE, ValueError)


def test_bind_expression_static_does_not_mutate_propconfig():
    """When StaticBindingError is raised, propConfig must NOT be modified."""
    comp = Component(type="ia.display.label")
    with pytest.raises(StaticBindingError):
        comp.bind_expression("props.style.classes", "alarm")
    assert len(comp.propConfig) == 0


# ------------------------------------------------------------
# PERFORMANCE_ORDER constant
# ------------------------------------------------------------


def test_performance_order_constant_exists():
    """PERFORMANCE_ORDER importable and contains all three tiers."""
    assert "property" in PERFORMANCE_ORDER
    assert "expression" in PERFORMANCE_ORDER
    assert "script" in PERFORMANCE_ORDER


def test_performance_order_hierarchy():
    """property comes before expression which comes before script in the ordering."""
    p_idx = PERFORMANCE_ORDER.index("property")
    e_idx = PERFORMANCE_ORDER.index("expression")
    s_idx = PERFORMANCE_ORDER.index("script")
    assert p_idx < e_idx < s_idx, (
        f"Expected property({p_idx}) < expression({e_idx}) < script({s_idx})"
    )


# ------------------------------------------------------------
# set_prop() routing table
# ------------------------------------------------------------


def test_set_prop_routes_props_prefix():
    """set_prop('props.style.classes', ...) sets component.props['style']['classes']."""
    comp = Component(type="ia.display.label")
    comp.set_prop("props.style.classes", "alarm")
    assert comp.props["style"]["classes"] == "alarm"


def test_set_prop_does_not_modify_propconfig():
    """set_prop must NOT add anything to propConfig."""
    comp = Component(type="ia.display.label")
    comp.set_prop("props.style.classes", "alarm")
    assert len(comp.propConfig) == 0


def test_set_prop_routes_custom_prefix():
    """set_prop('custom.label', ...) sets component.custom['label']."""
    comp = Component(type="ia.display.label")
    comp.set_prop("custom.label", "Hello")
    assert comp.custom["label"] == "Hello"


def test_set_prop_unknown_prefix_raises():
    """set_prop with a path that doesn't start with 'props.' or 'custom.' raises ValueError."""
    comp = Component(type="ia.display.label")
    with pytest.raises(ValueError) as exc_info:
        comp.set_prop("text", "hello")
    msg = str(exc_info.value)
    assert "props." in msg
    assert "custom." in msg


def test_set_prop_returns_self():
    """set_prop returns the Component for fluent chaining."""
    comp = Component(type="ia.display.label")
    result = comp.set_prop("props.text", "Hello")
    assert result is comp


def test_set_prop_nested_props():
    """set_prop navigates multi-level nested props paths correctly."""
    comp = Component(type="ia.display.label")
    comp.set_prop("props.style.backgroundColor", "#FF0000")
    assert comp.props["style"]["backgroundColor"] == "#FF0000"


def test_set_prop_nested_custom():
    """set_prop navigates multi-level nested custom paths correctly."""
    comp = Component(type="ia.display.label")
    comp.set_prop("custom.config.mode", "dark")
    assert comp.custom["config"]["mode"] == "dark"


def test_set_prop_props_top_level():
    """set_prop('props.text', ...) sets a top-level props key."""
    comp = Component(type="ia.display.label")
    comp.set_prop("props.text", "Hello world")
    assert comp.props["text"] == "Hello world"


def test_set_prop_chain_with_dynamic_bind():
    """set_prop can be chained with bind_expression for dynamic values."""
    comp = Component(type="ia.display.label")
    comp.set_prop("props.style.classes", "base-class").bind_expression(
        "props.text", "{view.params.label}"
    )
    assert comp.props["style"]["classes"] == "base-class"
    assert len(comp.propConfig) == 1


# ------------------------------------------------------------
# set_prop() — typed Pydantic props (LabelProps, etc.)
# ------------------------------------------------------------


def test_set_prop_typed_props_single_segment():
    """set_prop('props.text', ...) on a Label (typed LabelProps) uses setattr."""
    label = Label()
    label.set_prop("props.text", "hello")
    assert label.props.text == "hello"


def test_set_prop_typed_props_returns_self():
    """set_prop on typed props returns the component for fluent chaining."""
    label = Label()
    result = label.set_prop("props.text", "hi")
    assert result is label


def test_set_prop_typed_props_style_classes():
    """set_prop('props.style.classes', ...) on Label sets props.style dict correctly."""
    label = Label()
    label.set_prop("props.style.classes", "state/on")
    assert label.props.style == {"classes": "state/on"}


def test_set_prop_typed_props_style_classes_model_dump():
    """Typed-props set_prop emits correctly via model_dump."""
    label = Label()
    label.set_prop("props.style.classes", "state/on")
    dumped = label.model_dump(exclude_none=True)
    assert dumped["props"]["style"]["classes"] == "state/on"


def test_set_prop_typed_props_style_none_then_set():
    """set_prop creates the style dict when it starts as None."""
    label = Label()
    assert label.props.style is None
    label.set_prop("props.style.backgroundColor", "#FF0000")
    assert isinstance(label.props.style, dict)
    assert label.props.style["backgroundColor"] == "#FF0000"


def test_set_prop_typed_props_overwrites_existing():
    """set_prop on typed props overwrites a previously set value."""
    label = Label()
    label.set_prop("props.text", "first")
    label.set_prop("props.text", "second")
    assert label.props.text == "second"


def test_set_prop_dict_props_unchanged():
    """Existing dict-props path (bare Component) still works after the fix."""
    comp = Component(type="ia.display.label")
    comp.set_prop("props.style.classes", "alarm")
    assert comp.props["style"]["classes"] == "alarm"


def test_set_prop_custom_unchanged():
    """custom.* path is unaffected — still uses dict navigation."""
    label = Label()
    label.set_prop("custom.foo", "bar")
    assert label.custom["foo"] == "bar"


def test_set_prop_unknown_prefix_raises_on_typed():
    """ValueError is raised for non-props/custom prefix on typed-props component too."""
    label = Label()
    with pytest.raises(ValueError) as exc_info:
        label.set_prop("text", "hello")
    assert "props." in str(exc_info.value)
    assert "custom." in str(exc_info.value)
