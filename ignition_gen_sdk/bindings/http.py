"""HttpBinding — Ignition 8.3 HTTP binding.

Discriminator: `type: Literal["http"]`. Distinct from the 6 prior binding
discriminators ("property", "tag", "expr", "expr-struct", "query",
"tag-history"). This is the last member of the Binding discriminated
union (MongoDB is not modeled; HTTP binding is stock Perspective, so no
module-availability check is needed).

Verified live shape (Ignition 101/Feature Views/Perspective Features/
Bindings/view.json line 1086-1107 — the weather-API binding subtree;
Component's @field_serializer adds the outer "binding" wrapper on emit):

    {
      "config": {
        "connectTimeout": 60000,
        "enableCookies": true,
        "enableValueCache": true,
        "polling": {"enabled": false, "rate": ""},
        "request": {
          "auth": {"type": "None", "value": ""},
          "method": "GET",
          "url": "\"https://api.weather.gov/stations/KSMF/observations/latest\""
        },
        "socketTimeout": 60000
      },
      "type": "http"
    }

NESTED-vs-FLAT shape:

    INSIDE  request: method, url, auth, headers, body, contentType, queryParams
    OUTSIDE request (config root siblings): connectTimeout, socketTimeout,
                                            polling, enableCookies,
                                            enableValueCache, errorHandling

Flattening all of these into a single dict does
NOT match the live gateway emit. The model uses the nested shape so emit
is byte-equivalent to fixture without any post-processing.

Credential-guard architecture:

    IgnitionBaseModel._block_credential_fields inspects the raw input
    `data: dict` at construction time for top-level keys ciphertext,
    encrypted_key, iv, protected, tag. It does NOT inspect nested string
    values like `HttpAuth.value="Bearer xyz"` — those are plain string
    fields whose content is the caller's responsibility.

    Practical consequence:
    * HttpAuth(type="Bearer", value="Bearer xyz")     -> ALLOWED (string content)
    * HttpAuth(ciphertext="..." )                     -> REJECTED (top-level JWE key)
    * HttpBindingConfig(request=..., ciphertext=...)  -> REJECTED
    * HttpBindingConfig(request=HttpRequest(... auth=HttpAuth(value=...)))
                                                       -> ALLOWED (nested string)

    Project policy: production auth tokens live in env vars and are bound
    in via expression-language `auth.value` referencing a Perspective
    view-param fed from a Gateway secret. The binding records what call
    to make, not the secret itself.

errorHandling: opaque dict[str, Any] | None. The gateway documents typed
sub-fields (retries, fallback strategy, etc.) but no Designer-exported
fixture exercises them. Modeled as opaque dict so the field round-trips
without forcing a typed schema we cannot verify. A typed sub-model could
replace this after pulling the 8.3 docs / live Designer export.

PollingConfig is REUSED (`from .query import PollingConfig`).
Single source of truth across query / tag-history / http bindings.

Covers the full 8.3 HTTP binding surface. No runtime module-availability
pre-flight check: HTTP binding is stock Perspective.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import Field, model_serializer, model_validator

from ..models.base import IgnitionBaseModel
from ..transforms import Transform  # noqa: F401 — Transform symbol required so HttpBinding.model_rebuild() can resolve the `list["Transform"]` forward ref
from ._emit import strip_binding_defaults
from .enums import HttpMethod
from .query import PollingConfig  # shared sub-model


class HttpAuth(IgnitionBaseModel):
    """Auth sub-object nested under HttpRequest.auth.

    Both fields default to the gateway's "no auth" state so HttpAuth()
    constructs unambiguously. The string-typed `value` is what the gateway
    appends to the configured auth header at request time (e.g. for
    type='Bearer', value='xyz' produces `Authorization: Bearer xyz`).

    Credential guard (project-wide, IgnitionBaseModel level): top-level
    JWE field names (ciphertext, encrypted_key, iv, protected, tag) are
    REJECTED at construction. The `value` field itself is a plain string;
    its content is NOT inspected.

    Cross-field invariant — a non-"None" auth `type` with empty
    `value` would emit an auth header with no credential (e.g. a Bearer
    request with no token), which the gateway would issue and the remote
    would reject with 401. Reject at construction.
    """

    type: Literal["None", "Basic", "Bearer", "Digest"] = "None"
    value: str = ""

    @model_validator(mode="after")
    def _value_required_when_type_is_set(self) -> "HttpAuth":
        if self.type != "None" and self.value == "":
            raise ValueError(
                f"HttpAuth.value is empty but type={self.type!r}. An empty "
                "value is only meaningful when type='None' (no auth). "
                "Provide a non-empty value or set type='None'."
            )
        return self


class HttpHeader(IgnitionBaseModel):
    """A single HTTP request header. Both key and value are REQUIRED — an
    empty header is a programmer error, not a valid intermediate state.

    Builder ergonomic form: `Component.bind_http(headers=[(key, value), ...])`
    converts 2-tuples to HttpHeader objects at the builder layer; direct
    `headers=[HttpHeader(...)]` passthrough is also supported.
    """

    key: str
    value: str


class HttpRequest(IgnitionBaseModel):
    """Nested request sub-object — holds method/url/auth/headers/body/
    contentType/queryParams.

    Per the nested-vs-flat correction, these fields are EXPLICITLY scoped
    to the request sub-object; a flattened shape is incorrect.
    Timeouts/polling/cookies/value-cache/errorHandling are SIBLINGS of
    request at the HttpBindingConfig root, not children of request.

    `url` is REQUIRED — every HTTP binding must target a URL. The gateway
    expects URLs as JSON-encoded strings; static URLs are typically passed
    as `url='"https://example.com"'` (note inner quotes), and expression-
    bound URLs as `url='{"http://" + view.params.host}'`.

    `method` defaults to HttpMethod.GET. `use_enum_values=True` on
    IgnitionBaseModel stores the enum's `.value` ("GET") on the instance,
    so emit is automatic.
    """

    method: HttpMethod = HttpMethod.GET
    url: str  # REQUIRED — gateway expects JSON-encoded string for static URLs
    auth: Optional[HttpAuth] = None
    headers: Optional[list[HttpHeader]] = None
    body: Optional[str] = None
    contentType: Optional[str] = None
    queryParams: Optional[dict[str, str]] = None


class HttpBindingConfig(IgnitionBaseModel):
    """Config sub-object for HttpBinding.

    REQUIRED:
    - request: HttpRequest — the nested sub-object that holds method, url,
      auth, headers, body, contentType, queryParams.

    OPTIONAL siblings (all default to None; omitted from emit by
    exclude_none — matches the fixture shape for non-polling / no-timeout
    cases):
    - connectTimeout: int — TCP connect timeout in ms
    - socketTimeout: int — read timeout in ms
    - polling: PollingConfig — re-runs the request at the configured rate.
      PollingConfig is a shared sub-model — same shape across query /
      tag-history / http bindings.
    - enableCookies: bool — whether the gateway should accept Set-Cookie
      responses and replay cookies on subsequent requests.
    - enableValueCache: bool — whether response values are cached for the
      lifetime of the view.
    - errorHandling: opaque dict[str, Any] (no fixture covers a non-empty
      value, so modeling as a typed sub-model would be speculative).
    """

    request: HttpRequest  # REQUIRED nested sub-object
    connectTimeout: Optional[int] = None
    socketTimeout: Optional[int] = None
    polling: Optional[PollingConfig] = None
    enableCookies: Optional[bool] = None
    enableValueCache: Optional[bool] = None
    errorHandling: Optional[dict[str, Any]] = None  # opaque; no typed fixture yet


class HttpBinding(IgnitionBaseModel):
    """HTTP binding — fetches data from an external URL via gateway-side
    HTTP request.

    Discriminator: type: Literal["http"]. Member of the Binding
    discriminated union (bindings/__init__.py) — the 7th and final member.
    """

    type: Literal["http"] = "http"
    enabled: bool = True
    overlayOptOut: bool = False
    config: HttpBindingConfig
    transforms: list["Transform"] = Field(default_factory=list)  # forward ref; resolved by model_rebuild() below

    @model_serializer(mode="wrap")
    def _strip_defaults(self, handler, _info):
        """Drop gateway-absent default keys. See bindings/_emit.py."""
        return strip_binding_defaults(self, handler, _info)


# Resolve the `list["Transform"]` forward ref. Same idiom as every other
# binding module.
HttpBinding.model_rebuild()
