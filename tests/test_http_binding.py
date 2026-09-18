"""Tests for HttpBinding (the final binding type).

Verifies:
- HttpAuth (type Literal['None','Basic','Bearer','Digest'], value: str).
- HttpHeader (key str, value str — both required).
- HttpRequest (method HttpMethod, url required, optional auth/headers/body/
  contentType/queryParams).
- HttpBindingConfig with NESTED `request` sub-object (method/url/auth/headers/body live INSIDE request; connectTimeout/
  socketTimeout/polling/enableCookies/enableValueCache/errorHandling are SIBLINGS
  at the config root). PollingConfig is REUSED (not redefined).
- HttpBinding (Literal["http"]).
- Binding discriminated union expanded 6 -> 7 members.
- Component.bind_http() builder with ergonomic kwargs that construct the
  nested `request` correctly.
- Fixture diff against Bindings/view.json line 1086-1107 (weather API):
    {"config": {"connectTimeout": 60000,
                "enableCookies": true,
                "enableValueCache": true,
                "polling": {"enabled": false, "rate": ""},
                "request": {"auth": {"type": "None", "value": ""},
                            "method": "GET",
                            "url": "\\"https://...\\""},
                "socketTimeout": 60000},
     "type": "http"}
- Credential guard architectural confirmation: top-level dict-key inspection
  rejects {ciphertext,encrypted_key,...} on HttpBindingConfig; nested HttpAuth
  .value=`"Bearer xyz"` passes through.
- TypeAdapter(Binding) dispatches all 7 discriminator values (union closure).
"""
from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from ignition_gen_sdk.bindings import Binding
from ignition_gen_sdk.bindings.enums import HttpMethod
from ignition_gen_sdk.bindings.expression import ExpressionBinding
from ignition_gen_sdk.bindings.expression_structure import ExpressionStructureBinding
from ignition_gen_sdk.bindings.http import (
    HttpAuth,
    HttpBinding,
    HttpBindingConfig,
    HttpHeader,
    HttpRequest,
)
from ignition_gen_sdk.bindings.property import PropertyBinding
from ignition_gen_sdk.bindings.query import PollingConfig, QueryBinding
from ignition_gen_sdk.bindings.tag import TagBinding
from ignition_gen_sdk.bindings.tag_history import TagHistoryBinding
from ignition_gen_sdk.transforms.format import FormatTransform
from ignition_gen_sdk.models.views.component import Component



from conftest import FIXTURE_ROOT  # noqa: E402


# ============================================================
# HttpAuth + HttpHeader + HttpRequest + HttpBindingConfig + HttpBinding
# ============================================================


# ----- HttpAuth -----


def test_http_auth_defaults():
    """HttpAuth() constructs with type='None', value=''."""
    a = HttpAuth()
    assert a.type == "None"
    assert a.value == ""


def test_http_auth_bearer():
    """HttpAuth(type='Bearer', value='xyz') constructs."""
    a = HttpAuth(type="Bearer", value="xyz")
    assert a.type == "Bearer"
    assert a.value == "xyz"


def test_http_auth_invalid_type_rejected():
    """HttpAuth(type='Bogus') raises ValidationError (Literal restricts)."""
    with pytest.raises(ValidationError):
        HttpAuth(type="Bogus", value="x")  # type: ignore[arg-type]


def test_http_auth_value_with_bearer_prefix_passes_guard():
    """HttpAuth(value='Bearer xyz') constructs — passes credential
    guard. Guard checks TOP-LEVEL dict keys (ciphertext/encrypted_key/iv/
    protected/tag); `value` is a regular field whose string content is not
    inspected."""
    a = HttpAuth(value="Bearer xyz")
    assert a.value == "Bearer xyz"


def test_http_auth_top_level_credential_key_blocked():
    """HttpAuth(ciphertext='bad') — top-level credential key triggers
    guard. The validator inspects raw input dict; `ciphertext` is one of the
    guarded JWE field names."""
    with pytest.raises(ValueError, match="Encrypted credential"):
        HttpAuth(ciphertext="malicious")  # type: ignore[call-arg]


# ----- HttpHeader -----


def test_http_header_constructs():
    """HttpHeader(key='X-API-Key', value='abc') constructs."""
    h = HttpHeader(key="X-API-Key", value="abc")
    assert h.key == "X-API-Key"
    assert h.value == "abc"


def test_http_header_requires_both_fields():
    """HttpHeader() raises — both key and value REQUIRED."""
    with pytest.raises(ValidationError):
        HttpHeader()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        HttpHeader(key="X-API-Key")  # type: ignore[call-arg]


# ----- HttpRequest -----


def test_http_request_minimal():
    """HttpRequest(url='"https://..."') constructs with method=GET
    default; other fields None.

    NOTE: Pydantic v2 + use_enum_values=True coerces VALIDATED input enums
    to their .value strings — but FIELD DEFAULTS bypass validation, so a
    default of HttpMethod.GET is stored as the enum itself. Both the enum
    compare AND the emit-side string compare are valid; we assert via the
    enum (canonical) and via emit (the wire-shape lock pattern carried
    forward from other binding types).
    """
    r = HttpRequest(url='"https://example.com"')
    assert r.url == '"https://example.com"'
    assert r.method == HttpMethod.GET    # default field bypasses use_enum_values
    assert r.model_dump(mode="json")["method"] == "GET"   # emit-side string lock
    assert r.auth is None
    assert r.headers is None
    assert r.body is None
    assert r.contentType is None
    assert r.queryParams is None


def test_http_request_requires_url():
    """HttpRequest() raises — url is REQUIRED."""
    with pytest.raises(ValidationError):
        HttpRequest()  # type: ignore[call-arg]


def test_http_request_all_optional_fields():
    """HttpRequest with method/body/contentType/headers/queryParams
    populated; auth dict accepted."""
    r = HttpRequest(
        url="x",
        method="POST",
        body='{"k":"v"}',
        contentType="application/json",
        headers=[HttpHeader(key="X-API", value="abc")],
        queryParams={"q": "foo"},
    )
    assert r.method == "POST"
    assert r.body == '{"k":"v"}'
    assert r.contentType == "application/json"
    assert r.headers == [HttpHeader(key="X-API", value="abc")]
    assert r.queryParams == {"q": "foo"}


# ----- HttpBindingConfig: NESTED request + sibling timeouts/polling -----


def test_http_binding_config_minimal():
    """HttpBindingConfig(request=HttpRequest(url='"x"')) — all sibling
    optionals are None."""
    cfg = HttpBindingConfig(request=HttpRequest(url='"x"'))
    assert cfg.request.url == '"x"'
    assert cfg.connectTimeout is None
    assert cfg.socketTimeout is None
    assert cfg.polling is None
    assert cfg.enableCookies is None
    assert cfg.enableValueCache is None
    assert cfg.errorHandling is None


def test_http_binding_type_default():
    """HttpBinding default discriminator is 'http'."""
    b = HttpBinding(config=HttpBindingConfig(request=HttpRequest(url='"x"')))
    assert b.type == "http"
    assert b.enabled is True
    assert b.overlayOptOut is False


def test_http_binding_emits_nested_request_shape():
    """Emit verifies the NESTED request structure (gateway shape):
        INSIDE request: method, url, auth
        OUTSIDE request (config siblings): connectTimeout, socketTimeout,
                                           enableCookies, enableValueCache, polling
    """
    b = HttpBinding(
        config=HttpBindingConfig(
            request=HttpRequest(
                method=HttpMethod.GET,
                url='"https://api.weather.gov/stations/KSMF/observations/latest"',
                auth=HttpAuth(),
            ),
            connectTimeout=60000,
            socketTimeout=60000,
            enableCookies=True,
            enableValueCache=True,
            polling=PollingConfig(enabled=False, rate=""),
        )
    )
    emitted = b.model_dump(exclude_none=True, mode="json")
    # Enabled/overlayOptOut/empty transforms stripped
    # (matches weather-API fixture in Bindings/view.json:1086-1107).
    assert emitted == {
        "type": "http",
        "config": {
            "request": {
                "method": "GET",
                "url": '"https://api.weather.gov/stations/KSMF/observations/latest"',
                "auth": {"type": "None", "value": ""},
            },
            "connectTimeout": 60000,
            "socketTimeout": 60000,
            "enableCookies": True,
            "enableValueCache": True,
            "polling": {"enabled": False, "rate": ""},
        },
    }


def test_binding_union_has_seven_members():
    """Binding union has all 7 members. `>= N` + membership idiom
    (avoids over-pinning exact member count)."""
    members = get_args(get_args(Binding)[0])
    assert len(members) >= 7
    assert PropertyBinding in members
    assert TagBinding in members
    assert ExpressionBinding in members
    assert ExpressionStructureBinding in members
    assert QueryBinding in members
    assert TagHistoryBinding in members
    assert HttpBinding in members


def test_binding_union_dispatches_http():
    """TypeAdapter(Binding).validate_python({'type':'http', ...})
    -> HttpBinding."""
    adapter = TypeAdapter(Binding)
    b = adapter.validate_python(
        {"type": "http", "config": {"request": {"method": "GET", "url": "x"}}}
    )
    assert isinstance(b, HttpBinding)


def test_http_binding_error_handling_opaque_dict():
    """errorHandling accepts an opaque dict (no typed sub-model yet)."""
    cfg = HttpBindingConfig(
        request=HttpRequest(url="x"),
        errorHandling={"retries": 3, "timeoutFallback": None},
    )
    assert cfg.errorHandling == {"retries": 3, "timeoutFallback": None}
    emitted = HttpBinding(config=cfg).model_dump(exclude_none=True, mode="json")
    assert emitted["config"]["errorHandling"] == {
        "retries": 3,
        "timeoutFallback": None,
    }


# ============================================================
# Component.bind_http() + fixture diff + cred-guard
# ============================================================


def test_bind_http_minimal():
    """Component(type='x').bind_http('custom.response', url='...') builds
    a binding with default method GET and only request.url populated."""
    c = Component(type="x").bind_http(
        "custom.response", url='"https://api.example.com"'
    )
    pc = c.propConfig[0]
    assert pc.binding.type == "http"
    assert pc.binding.config.request.url == '"https://api.example.com"'
    assert pc.binding.config.request.method == "GET"   # use_enum_values=True


def test_bind_http_all_request_kwargs():
    """method/body/content_type/headers (tuple form)/query_params
    populate the nested request sub-object."""
    c = Component(type="x").bind_http(
        "p",
        url="x",
        method=HttpMethod.POST,
        body='{"k":"v"}',
        content_type="application/json",
        headers=[("X-API-Key", "abc"), ("X-Other", "z")],
        query_params={"q": "foo"},
    )
    req = c.propConfig[0].binding.config.request
    assert req.method == "POST"
    assert req.body == '{"k":"v"}'
    assert req.contentType == "application/json"
    assert isinstance(req.headers, list)
    assert all(isinstance(h, HttpHeader) for h in req.headers)
    assert req.headers[0].key == "X-API-Key"
    assert req.headers[0].value == "abc"
    assert req.queryParams == {"q": "foo"}


def test_bind_http_config_level_kwargs_are_siblings_not_in_request():
    """connect_timeout/socket_timeout/enable_cookies/enable_value_cache/
    polling_* end up as config-LEVEL siblings — NOT nested under request.

    Locks the nested-vs-flat distinction (gateway shape).
    """
    c = Component(type="x").bind_http(
        "p",
        url="x",
        connect_timeout=60000,
        socket_timeout=60000,
        enable_cookies=True,
        enable_value_cache=True,
        polling_enabled=False,
        polling_rate="",
    )
    cfg = c.propConfig[0].binding.config
    # Siblings at config root
    assert cfg.connectTimeout == 60000
    assert cfg.socketTimeout == 60000
    assert cfg.enableCookies is True
    assert cfg.enableValueCache is True
    assert cfg.polling is not None
    assert cfg.polling.enabled is False
    assert cfg.polling.rate == ""
    # request sub-object holds ONLY method+url (no auth/headers/etc supplied)
    req = cfg.request
    assert req.url == "x"
    assert req.method == "GET"
    assert req.auth is None
    assert req.headers is None
    assert req.body is None
    assert req.contentType is None
    assert req.queryParams is None


def test_bind_http_auth_kwargs_build_nested_auth():
    """auth_type='Bearer' + auth_value='xyz' -> HttpAuth(type='Bearer',
    value='xyz') nested inside request.auth."""
    c = Component(type="x").bind_http(
        "p", url="x", auth_type="Bearer", auth_value="xyz"
    )
    auth = c.propConfig[0].binding.config.request.auth
    assert auth is not None
    assert auth.type == "Bearer"
    assert auth.value == "xyz"


def test_bind_http_error_handling_opaque_dict():
    """error_handling={...} -> passes through into config."""
    c = Component(type="x").bind_http(
        "p", url="x", error_handling={"retries": 3, "timeoutFallback": None}
    )
    cfg = c.propConfig[0].binding.config
    assert cfg.errorHandling == {"retries": 3, "timeoutFallback": None}


def test_bind_http_chain_with_format_transform():
    """bind_http(...).format('0.00') attaches a FormatTransform to
    the http binding (transform-chain works on every binding type)."""
    c = Component(type="x").bind_http("p", url="x").format("0.00")
    binding = c.propConfig[0].binding
    assert len(binding.transforms) == 1
    assert isinstance(binding.transforms[0], FormatTransform)


def test_bind_http_credential_guard_passes_with_bearer_value():
    """auth_value='Bearer xyz' (a string that LOOKS like an embedded
    credential token) passes the guard — HttpAuth.value is a plain string
    field; the credential guard inspects top-level dict keys, not nested
    string contents."""
    c = Component(type="x").bind_http(
        "p", url="x", auth_type="Bearer", auth_value="Bearer xyz"
    )
    auth = c.propConfig[0].binding.config.request.auth
    assert auth is not None
    assert auth.value == "Bearer xyz"


def test_credential_guard_still_fires_at_top_level_of_config():
    """The credential guard still rejects {ciphertext: ...} when
    submitted as a TOP-LEVEL key of HttpBindingConfig. This is the
    architectural confirmation that the credential-guard design is
    consistent across binding types — top-level only inspection."""
    # HttpAuth.value as plain string passes
    HttpAuth(type="Bearer", value="Bearer xyz")
    # Top-level ciphertext key on HttpBindingConfig blocks
    with pytest.raises(ValueError, match="Encrypted credential"):
        HttpBindingConfig(
            request=HttpRequest(url='"x"'),
            ciphertext="malicious",  # type: ignore[call-arg]
        )


def test_bind_http_headers_accept_pre_built_HttpHeader_objects():
    """headers kwarg accepts list[HttpHeader] directly (not just
    tuples) — escape hatch for callers who construct objects."""
    c = Component(type="x").bind_http(
        "p", url="x", headers=[HttpHeader(key="X-A", value="1")]
    )
    headers = c.propConfig[0].binding.config.request.headers
    assert headers == [HttpHeader(key="X-A", value="1")]


def test_bind_http_headers_invalid_entry_raises():
    """headers entry that is neither HttpHeader nor 2-tuple raises.

    ValidationError (TypeAdapter path) — same error family as the
    rest of the binding-construction chain so callers can wrap once.
    """
    c = Component(type="x")
    with pytest.raises(ValidationError):
        c.bind_http("p", url="x", headers=["bogus-string"])  # type: ignore[list-item]
    # 3-tuple is also rejected (tuple_schema requires exactly 2 items).
    with pytest.raises(ValidationError):
        c.bind_http("p", url="x", headers=[("a", "b", "c")])  # type: ignore[list-item]


def test_http_auth_empty_value_with_non_none_type_rejected():
    """HttpAuth(type='Bearer', value='') would emit an auth header
    with no credential and is almost certainly a programmer error. The
    cross-field validator rejects.
    """
    # type='None' + empty value is the canonical "no auth" state — allowed.
    HttpAuth(type="None", value="")
    HttpAuth()  # defaults

    # All non-"None" types with empty value reject.
    for t in ("Basic", "Bearer", "Digest"):
        with pytest.raises(ValidationError):
            HttpAuth(type=t, value="")

    # Non-empty value for any type is fine.
    HttpAuth(type="Bearer", value="abc")


def test_credential_guard_does_not_inspect_nested_dicts():
    """Architectural pin (by design). The credential guard inspects
    TOP-LEVEL Pydantic field names only. Nested dict values whose own keys
    coincide with JWE field names (ciphertext, encrypted_key, iv, protected,
    tag) MUST pass through. A legitimate HTTP API may use 'ciphertext' as a
    response field or header name and a tool-level guard cannot distinguish
    that from a JWE smuggle attempt without semantic understanding the
    gateway already provides.
    """
    cfg = HttpBindingConfig(
        request=HttpRequest(url='"x"'),
        errorHandling={
            "ciphertext": "this is a header/response field, not a JWE field",
        },
    )
    assert cfg.errorHandling == {
        "ciphertext": "this is a header/response field, not a JWE field",
    }


# ----- Fixture diff -----


def _load_view(view_relpath: str) -> dict:
    if FIXTURE_ROOT is None:
        pytest.skip("IGNITION_SAMPLE_VIEWS not set; fixture-diff test skipped.")
    p = FIXTURE_ROOT / view_relpath
    with p.open("r") as fp:
        return json.load(fp)


def _walk_find_propconfig_by_type(node, target_type, accum=None):
    """Walk a view tree; collect (prop_path, binding_dict) pairs for matching
    bindings."""
    if accum is None:
        accum = []
    if isinstance(node, dict):
        pc = node.get("propConfig")
        if isinstance(pc, dict):
            for prop, body in pc.items():
                binding = (body or {}).get("binding")
                if isinstance(binding, dict) and binding.get("type") == target_type:
                    accum.append((prop, binding))
        for v in node.values():
            _walk_find_propconfig_by_type(v, target_type, accum)
    elif isinstance(node, list):
        for v in node:
            _walk_find_propconfig_by_type(v, target_type, accum)
    return accum


def _is_superset(superset: dict, subset: dict, path: str = "") -> None:
    """Assert every key+value in `subset` is present in `superset` with same value."""
    for k, v in subset.items():
        ctx = f"{path}/{k}"
        assert k in superset, f"missing key {ctx} in superset: {superset}"
        if isinstance(v, dict):
            assert isinstance(superset[k], dict), (
                f"{ctx}: expected dict, got {type(superset[k])}"
            )
            _is_superset(superset[k], v, ctx)
        elif isinstance(v, list):
            assert isinstance(superset[k], list), (
                f"{ctx}: expected list, got {type(superset[k])}"
            )
            assert len(superset[k]) == len(v), f"{ctx}: list length mismatch"
            for i, (sup_item, sub_item) in enumerate(zip(superset[k], v)):
                if isinstance(sub_item, dict):
                    _is_superset(sup_item, sub_item, f"{ctx}[{i}]")
                else:
                    assert sup_item == sub_item, f"{ctx}[{i}]: {sup_item!r} != {sub_item!r}"
        else:
            assert superset[k] == v, f"{ctx}: {superset[k]!r} != {v!r}"


def test_fixture_diff_weather_api():
    """Fixture-diff against Bindings/view.json line 1086-1107.

    Fixture binding subtree (weather API):
        {"config": {
            "connectTimeout": 60000,
            "enableCookies": true,
            "enableValueCache": true,
            "polling": {"enabled": false, "rate": ""},
            "request": {
                "auth": {"type": "None", "value": ""},
                "method": "GET",
                "url": "\\"https://api.weather.gov/stations/KSMF/observations/latest\\""
            },
            "socketTimeout": 60000
         },
         "type": "http"}

    Locks the NESTED `request` shape against the actual gateway emit.
    """
    view = _load_view(
        "Ignition 101/Feature Views/Perspective Features/Bindings/view.json"
    )
    found = _walk_find_propconfig_by_type(view, "http")
    assert found, "no http binding found in Bindings/view.json"
    prop_path, fixture_binding = found[0]
    fixture_cfg = fixture_binding["config"]
    fixture_request = fixture_cfg["request"]
    fixture_auth = fixture_request["auth"]
    fixture_polling = fixture_cfg["polling"]

    rebuilt = Component(type="ia.container.flex").bind_http(
        prop_path,
        url=fixture_request["url"],
        method=fixture_request["method"],
        auth_type=fixture_auth["type"],
        auth_value=fixture_auth["value"],
        connect_timeout=fixture_cfg["connectTimeout"],
        socket_timeout=fixture_cfg["socketTimeout"],
        enable_cookies=fixture_cfg["enableCookies"],
        enable_value_cache=fixture_cfg["enableValueCache"],
        polling_enabled=fixture_polling["enabled"],
        polling_rate=fixture_polling["rate"],
    )
    emitted = rebuilt.model_dump(exclude_none=True, mode="json")["propConfig"][
        prop_path
    ]["binding"]
    # Verify nested-shape lock
    assert "request" in emitted["config"]
    assert "method" in emitted["config"]["request"]
    assert "url" in emitted["config"]["request"]
    assert "auth" in emitted["config"]["request"]
    # Verify siblings at config root (NOT under request)
    assert "connectTimeout" in emitted["config"]
    assert "socketTimeout" in emitted["config"]
    assert "enableCookies" in emitted["config"]
    assert "enableValueCache" in emitted["config"]
    assert "polling" in emitted["config"]
    # And these are NOT under request
    assert "connectTimeout" not in emitted["config"]["request"]
    assert "polling" not in emitted["config"]["request"]
    # Superset diff
    _is_superset(emitted, fixture_binding)


# ----- Union closure: all 7 discriminator dispatches -----


def test_all_7_binding_discriminators_dispatch():
    """Union closure: TypeAdapter(Binding) dispatches every
    discriminator string to its concrete class."""
    adapter = TypeAdapter(Binding)
    assert isinstance(
        adapter.validate_python({"type": "property", "config": {"path": "p"}}),
        PropertyBinding,
    )
    assert isinstance(
        adapter.validate_python(
            {"type": "tag", "config": {"tagPath": "t", "mode": "direct"}}
        ),
        TagBinding,
    )
    assert isinstance(
        adapter.validate_python({"type": "expr", "config": {"expression": "e"}}),
        ExpressionBinding,
    )
    assert isinstance(
        adapter.validate_python({"type": "expr-struct", "config": {"struct": {}}}),
        ExpressionStructureBinding,
    )
    assert isinstance(
        adapter.validate_python({"type": "query", "config": {"queryPath": "q"}}),
        QueryBinding,
    )
    assert isinstance(
        adapter.validate_python(
            {"type": "tag-history", "config": {"tags": "t"}}
        ),
        TagHistoryBinding,
    )
    assert isinstance(
        adapter.validate_python(
            {"type": "http", "config": {"request": {"url": "u"}}}
        ),
        HttpBinding,
    )


# ----- Chain regression: all 7 bindings + every transform -----


def test_regression_smoke_all_seven_bindings():
    """Chain every binding type and several transforms through a
    single Component — binding plumbing still works across every binding
    type (no plumbing touched)."""
    from ignition_gen_sdk.bindings.enums import TagBindingMode

    c = (
        Component(type="ia.display.label")
        .bind_property("props.a", "view.params.a")
        .expression("upper({value})")
        .bind_tag("props.b", "[default]X", mode=TagBindingMode.DIRECT)
        .map({"a": "A"}).format("0.0").script("return value")
        .bind_expression("props.c", "toBoolean({x})")
        .bind_expression_structure("props.d", struct={"k": "v"})
        .bind_query("props.e", queryPath="x", polling_enabled=True, polling_rate="5")
        .bind_tag_history("props.f", paths="[X]A", range="1h")
        .bind_http("props.g", url='"https://api.example.com"')
    )
    types = [pc.binding.type for pc in c.propConfig]
    assert types == [
        "property",
        "tag",
        "expr",
        "expr-struct",
        "query",
        "tag-history",
        "http",
    ]
