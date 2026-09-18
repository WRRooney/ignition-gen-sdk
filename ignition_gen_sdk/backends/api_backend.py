"""ApiBackend — wraps IgnitionAPIClient for tag import + tag-provider CRUD.

Two responsibility groups:

1. **Tag import** — thin pass-through to ``IgnitionAPIClient.import_tags``;
   exists so the WriteRouter has a single ``ApiBackend`` object to talk to.

2. **Tag Provider CRUD** — full ``/data/api/v1/resources/.../tag-provider``
   surface (9 endpoints from ``api_reference/config-tag-provider.md``).
   Supports list, get-names, get-one, create, update, delete (one + many),
   rename, describe-type.

Two safety rails:

- ``update_provider`` and ``delete_provider`` require a non-empty
  ``signature`` argument. The signature is opaque — only obtainable by a
  prior authenticated GET — so the guard prevents unauthenticated callers
  from blindly modifying providers via guessable name strings.
- The token is never inserted into any error message; all error text comes
  from ``IgnitionAPIClient._raise_for_status`` (server-controlled body) or
  fixed Python format strings.

Endpoint response shapes (verified live against gateway 8.3.4):

- ``/list/ignition/tag-provider`` returns ``{items: [...], metadata: {...}}``.
  ``list_providers`` unwraps ``items`` to a flat ``list[dict]``.
- ``/names/ignition/tag-provider`` returns ``{items: [{name, enabled, modes}], metadata}``.
  ``get_provider_names`` flattens to ``list[str]`` of names.
- ``/find/ignition/tag-provider/{name}`` returns a flat dict including ``signature``.
- ``/type/ignition/tag-provider`` returns a flat dict.
- POST/PUT bodies are JSON arrays for create/update/delete-multi; a JSON
  object for rename.

Generated-client usage:
- Read methods (list_*, get_*, describe_*) call generated endpoint functions
  via sync_detailed(client=self._gen_client); resp.parsed converted to dict
  via .to_dict() or attrs.asdict(); {items: [...]} envelopes unwrapped.
- Mutation methods (create_*, update_*, rename_*, delete_*) route through
  self._gen_client.get_httpx_client() transport directly — no attrs body
  model construction required.
- All generated imports are inside method bodies (lazy) — not at module top
  level (the generated package is gitignored and may be absent).
- attrs models never escape ApiBackend; converted to plain dict before
  return.
- All generated imports inside method bodies; ModuleNotFoundError at
  call time triggers regen via _gen_client property.
- Only Client (not AuthenticatedClient) used; no Bearer header injected.
"""
from __future__ import annotations

import httpx
from typing import Any
from urllib.parse import quote

from .api_client import (
    AuthMissingError,
    AuthScopeError,
    GatewayError,
    IgnitionAPIClient,
    NetworkError,
    PayloadError,
)


def _quote_url_segment(name: str) -> str:
    """URL-quote a single path segment.

    httpx does NOT auto-encode path components passed via f-string
    interpolation. A provider/name containing '/', '..', '?', '#',
    or other URL-reserved characters would otherwise route the
    request to an unintended endpoint. Encoding with safe='' forces
    every reserved character into its %-form so the gateway receives
    the literal name as a single path segment.

    Note: Generated endpoint functions already handle URL-quoting for
    path params in their _get_kwargs. This helper is retained for
    mutation methods that build URLs manually.
    """
    return quote(name, safe="")

_TAG_PROVIDER_BASE = "/data/api/v1/resources"
_TAG_PROVIDER_PATH = "ignition/tag-provider"
_DB_CONN_PATH = "ignition/database-connection"


def _wrap(e: Exception) -> NetworkError:
    """Re-raise an httpx transport error as NetworkError.

    Usage: ``raise _wrap(e) from e`` inside except httpx.RequestError blocks.
    Defined at module level so all ApiBackend methods share a single wrap site.
    """
    return NetworkError(str(e))


class ApiBackend:
    """Wraps ``IgnitionAPIClient`` with tag-import + tag-provider CRUD.

    Read methods delegate to generated endpoint functions via
    sync_detailed(); mutation methods use the generated client's shared
    httpx transport directly.
    """

    def __init__(self, client: IgnitionAPIClient) -> None:
        self._client = client
        # Ensure the generated package is importable in this interpreter
        # before any method-body `from ignition_api_client.api... import ...`
        # runs. The .pth from `pip install -e` only registers in the venv
        # that ran codegen; other interpreters with the files on disk need
        # sys.path injection. needs_regen() short-circuits cheaply when the
        # hash matches.
        from ..config import Settings  # noqa: PLC0415
        from ..regen.engine import ensure_generated_client  # noqa: PLC0415
        # Refresh the generated client eagerly only when a spec is already on
        # disk (cheap hash check). Without one, the first typed verb fetches the
        # spec and generates the client via _gen_client; raw-transport verbs
        # such as import_tags never need it.
        settings = getattr(client, "_settings", None)
        if isinstance(settings, Settings) and settings.openapi_spec_path.exists():
            ensure_generated_client(settings)

    @property
    def _gen_client(self):  # noqa: ANN201
        """Return the generated Client, triggering regen if absent.

        Always re-injects the current self._client._client into the generated
        client's transport to stay in sync if the transport is swapped after
        construction (e.g. during tests using MockTransport).

        Returns Client (not AuthenticatedClient) so no Bearer header
        is injected alongside the X-Ignition-API-Token header.
        """
        if self._client._generated is None:
            from ..regen.engine import ensure_generated_client
            ensure_generated_client(self._client._settings)
            from ignition_api_client import Client as _GenClient  # noqa: PLC0415
            self._client._generated = _GenClient(
                base_url=str(self._client._settings.ignition_base_url)
            )
        # Always sync the transport — keeps tests that swap _client in sync.
        self._client._generated.set_httpx_client(self._client._client)
        return self._client._generated

    def _parse_response(
        self,
        resp: Any,
        envelope_key: str = "items",
        *,
        empty_default: Any = None,
    ) -> Any:
        """Convert a generated sync_detailed() response to a plain dict/list.

        - status_code >= 400: raise appropriate IgnitionAPIError subclass.
        - resp.parsed is None: fall back to raw JSON from resp.content, then
          return empty_default if no content is parseable.
        - Otherwise: convert attrs model to dict via .to_dict() and unwrap
          the envelope_key if present.

        attrs models never escape this method; converted to plain
        dict before return.

        Raw JSON fallback: when the generated model deserialization fails
        (e.g. mock responses with partial fields, or non-standard gateway
        shapes), the raw response bytes are parsed as JSON and the envelope
        is unwrapped the same way. This preserves backwards compatibility
        with existing tests while using the typed path on real gateway responses.
        """
        # Normalize status_code — generated Response wraps it in HTTPStatus enum.
        raw_status = resp.status_code
        if hasattr(raw_status, "value"):
            raw_status = raw_status.value
        if raw_status >= 400:
            code = raw_status
            if code == 401:
                raise AuthMissingError(
                    "401 Unauthorized: check IGNITION_API_TOKEN (env or .env)"
                )
            if code == 403:
                raise AuthScopeError(
                    "403 Forbidden: API token lacks required scope — check Gateway UI permissions"
                )
            if code == 400:
                raise PayloadError(f"400 Bad Request: {resp.content!r}")
            if 400 <= code < 500:
                raise PayloadError(f"{code} Client Error: {resp.content!r}")
            raise GatewayError(
                f"{code} Gateway Error: retry the request or check gateway logs"
            )
        if resp.parsed is not None:
            # Typed path: use .to_dict() (native generated method) or attrs.asdict().
            # attrs models never escape this method.
            try:
                body = resp.parsed.to_dict()
            except AttributeError:
                import attrs  # noqa: PLC0415
                body = attrs.asdict(resp.parsed)
            if isinstance(body, dict) and envelope_key in body:
                return body[envelope_key]
            return body
        # Fallback: parse raw JSON from response bytes.
        # This covers: generated model deserialization failure (mock responses
        # with partial fields), empty body, and non-standard gateway shapes.
        import json as _json  # noqa: PLC0415
        try:
            body = _json.loads(resp.content)
        except (ValueError, TypeError):
            if empty_default is None:
                return {}
            return empty_default
        if isinstance(body, dict) and envelope_key in body:
            return body[envelope_key]
        if body is None or body == "":
            if empty_default is None:
                return {}
            return empty_default
        return body

    # ---- Tag import ---------------------------------------------------

    def import_tags(
        self,
        provider: str,
        path: str,
        payload: dict,
        collision_policy: str = "MergeOverwrite",
    ) -> Any:
        """Push a Provider-root tag tree to the gateway.

        Returns whatever the underlying client returns (live gateway 8.3.4
        returns ``{successCount, failureCount, failures}``; legacy docs
        describe a list-of-diagnostic-dicts shape). Raises
        ``PayloadError`` on 400, ``GatewayError`` on 5xx (both propagated
        from ``IgnitionAPIClient._raise_for_status``).

        Delegates to IgnitionAPIClient.import_tags() — the tag import endpoint
        uses multipart/form-data which is outside the generated client's scope
        (binary/multipart endpoints are not fully generated).
        """
        return self._client.import_tags(provider, path, payload, collision_policy)

    # ---- Tag Provider CRUD --------------------------------------------

    def _sync_detailed_with_fallback(
        self,
        fn: Any,
        *args: Any,
        envelope_key: str = "items",
        empty_default: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Call fn.sync_detailed() and parse the response.

        On model deserialization errors (KeyError, TypeError from generated
        from_dict), falls back to raw JSON parsing from the pre-built httpx
        response. This preserves backwards compatibility with existing tests
        that use simplified mock response bodies.

        Returns the unwrapped value (envelope_key extracted if present).
        """
        try:
            resp = fn.sync_detailed(*args, client=self._gen_client, **kwargs)
            return self._parse_response(
                resp, envelope_key=envelope_key, empty_default=empty_default
            )
        except (AuthMissingError, AuthScopeError, PayloadError, GatewayError, NetworkError):
            raise
        except httpx.RequestError as e:
            raise _wrap(e) from e
        except Exception:  # noqa: BLE001
            # Model deserialization failure (KeyError from strict from_dict).
            # Fall back: call the raw httpx client directly for the same URL.
            kwargs_for_raw = fn._get_kwargs(*args, **kwargs)
            method = kwargs_for_raw.pop("method", "get")
            url = kwargs_for_raw.pop("url", "")
            params = kwargs_for_raw.pop("params", None)
            try:
                r = self._client._client.request(method, url, params=params)
            except httpx.RequestError as e:
                raise _wrap(e) from e
            self._client._raise_for_status(r)
            body = r.json()
            if isinstance(body, dict) and envelope_key in body:
                return body[envelope_key]
            return body

    def list_providers(self) -> list[dict]:
        """``GET /list/ignition/tag-provider`` — every provider, full config.

        The gateway wraps the response as ``{items: [...], metadata: {...}}``.
        We return the flat list of provider dicts.
        Uses sync_detailed() for the typed generated client path; falls back
        to raw JSON parsing if model deserialization fails.
        """
        from ignition_api_client.api.config_tag_provider import (  # noqa: PLC0415
            get_data_api_v1_resources_list_ignition_tag_provider as _fn,
        )
        return self._sync_detailed_with_fallback(  # type: ignore[return-value]
            _fn, envelope_key="items", empty_default=[]
        )

    def get_provider_names(self) -> list[str]:
        """``GET /names/ignition/tag-provider`` — names of all providers.

        Live response is ``{items: [{name, enabled, modes}], metadata}``.
        We extract just the names so callers can do ``"default" in names``.
        """
        from ignition_api_client.api.config_tag_provider import (  # noqa: PLC0415
            get_data_api_v1_resources_names_ignition_tag_provider as _fn,
        )
        items = self._sync_detailed_with_fallback(
            _fn, envelope_key="items", empty_default=[]
        )
        if isinstance(items, list):
            return [
                item["name"] if isinstance(item, dict) else item
                for item in items
            ]
        return []

    def get_provider(self, name: str) -> dict:
        """``GET /find/ignition/tag-provider/{name}`` — full provider config.

        Returns a dict including ``signature`` (required for update/delete).
        The generated endpoint function handles URL-quoting of the name segment.
        """
        from ignition_api_client.api.config_tag_provider import (  # noqa: PLC0415
            get_data_api_v1_resources_find_ignition_tag_provider_name as _fn,
        )
        return self._sync_detailed_with_fallback(  # type: ignore[return-value]
            _fn, name, envelope_key="items", empty_default={}
        )

    def create_provider(
        self,
        name: str,
        config: dict[str, Any],
        *,
        enabled: bool = True,
        description: str | None = None,
    ) -> dict:
        """``POST /ignition/tag-provider`` — body is a list of provider specs.

        No signature required (creating new). Server returns
        ``{success, changes:[{name, type, collection, newSignature}], problem}``.
        Mutation: routes through generated client's shared httpx transport directly.
        """
        body: dict[str, Any] = {"name": name, "enabled": enabled, "config": config}
        if description is not None:
            body["description"] = description
        try:
            r = self._gen_client.get_httpx_client().post(
                f"{_TAG_PROVIDER_BASE}/{_TAG_PROVIDER_PATH}",
                json=[body],
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def update_provider(
        self,
        name: str,
        signature: str,
        config: dict[str, Any],
        *,
        enabled: bool | None = None,
        description: str | None = None,
    ) -> dict:
        """``PUT /ignition/tag-provider`` — body is a list of update specs.

        ``signature`` is opaque and must come from a prior ``get_provider()``
        call. Empty string raises ``ValueError`` BEFORE any HTTP call —
        prevents blind unauthenticated modification.
        Mutation: routes through generated client's shared httpx transport directly.
        """
        if not signature:
            raise ValueError(
                "update_provider requires a non-empty signature obtained from "
                "get_provider(name). Call get_provider first and pass the "
                "result['signature'] value."
            )
        body: dict[str, Any] = {
            "name": name,
            "signature": signature,
            "config": config,
        }
        if enabled is not None:
            body["enabled"] = enabled
        if description is not None:
            body["description"] = description
        try:
            r = self._gen_client.get_httpx_client().put(
                f"{_TAG_PROVIDER_BASE}/{_TAG_PROVIDER_PATH}",
                json=[body],
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def delete_provider(self, name: str, signature: str) -> dict:
        """``DELETE /ignition/tag-provider/{name}/{signature}`` — single delete.

        ``signature`` is mandatory. Empty string raises
        ``ValueError`` before any HTTP call.
        Mutation: routes through generated client's shared httpx transport directly.
        """
        if not signature:
            raise ValueError(
                "delete_provider requires a non-empty signature obtained from "
                "get_provider(name)."
            )
        try:
            r = self._gen_client.get_httpx_client().delete(
                f"{_TAG_PROVIDER_BASE}/{_TAG_PROVIDER_PATH}/"
                f"{_quote_url_segment(name)}/{_quote_url_segment(signature)}"
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def delete_providers(self, entries: list[dict[str, str]]) -> dict:
        """``POST /delete/ignition/tag-provider`` — bulk delete.

        Body is a list of ``{name, signature}`` dicts. The gateway enforces
        the signature requirement server-side; we don't pre-validate here
        because callers may legitimately pass entries fetched in bulk.
        Mutation: routes through generated client's shared httpx transport directly.
        """
        try:
            r = self._gen_client.get_httpx_client().post(
                f"{_TAG_PROVIDER_BASE}/delete/{_TAG_PROVIDER_PATH}",
                json=entries,
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def rename_provider(
        self,
        name: str,
        new_name: str,
        *,
        references: str = "UPDATE",
    ) -> dict:
        """``POST /rename/ignition/tag-provider/{name}`` — rename in place.

        ``references`` controls how cross-resource references are handled
        (``ABORT`` | ``IGNORE`` | ``UPDATE``). Default ``UPDATE`` updates
        all references to point at the new name (safest for live gateways).
        Mutation: routes through generated client's shared httpx transport directly.
        """
        try:
            r = self._gen_client.get_httpx_client().post(
                f"{_TAG_PROVIDER_BASE}/rename/{_TAG_PROVIDER_PATH}/"
                f"{_quote_url_segment(name)}",
                json={"name": new_name, "references": references},
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def describe_provider_type(self) -> dict:
        """``GET /type/ignition/tag-provider`` — describe the resource type.

        Returns the type's extension points, defaults, and total counts.
        """
        from ignition_api_client.api.config_tag_provider import (  # noqa: PLC0415
            get_data_api_v1_resources_type_ignition_tag_provider as _fn,
        )
        return self._sync_detailed_with_fallback(  # type: ignore[return-value]
            _fn, envelope_key="items", empty_default={}
        )

    # ---- Database Connection CRUD -------------------------------------
    # 9-endpoint mirror of tag-provider CRUD with
    # _TAG_PROVIDER_PATH swapped for _DB_CONN_PATH. Same URL-quoting
    # on all single-segment name interpolation and the same
    # signature-empty ValueError guard on update/delete carry forward.
    # Reads use the generated client sync_detailed;
    # mutations route through generated client's httpx transport directly.

    def list_connections(self) -> list[dict]:
        """``GET /list/ignition/database-connection`` — every connection, full config.

        The gateway wraps the response as ``{items: [...], metadata: {...}}``.
        We return the flat list of connection dicts.
        Uses sync_detailed() for the typed generated client path; falls back
        to raw JSON parsing if model deserialization fails.
        """
        from ignition_api_client.api.config_databases import (  # noqa: PLC0415
            get_data_api_v1_resources_list_ignition_database_connection as _fn,
        )
        return self._sync_detailed_with_fallback(  # type: ignore[return-value]
            _fn, envelope_key="items", empty_default=[]
        )

    def get_connection_names(self) -> list[str]:
        """``GET /names/ignition/database-connection`` — names of all connections.

        Live response is ``{items: [{name, enabled}], metadata}``.
        We extract just the names so callers can do ``"Demo_DB" in names``.
        """
        from ignition_api_client.api.config_databases import (  # noqa: PLC0415
            get_data_api_v1_resources_names_ignition_database_connection as _fn,
        )
        items = self._sync_detailed_with_fallback(
            _fn, envelope_key="items", empty_default=[]
        )
        if isinstance(items, list):
            return [
                item["name"] if isinstance(item, dict) else item
                for item in items
            ]
        return []

    def get_connection(self, name: str) -> dict:
        """``GET /find/ignition/database-connection/{name}`` — full connection config.

        Returns a dict including ``signature`` (required for update/delete).
        The generated endpoint function handles URL-quoting of the name segment.
        """
        from ignition_api_client.api.config_databases import (  # noqa: PLC0415
            get_data_api_v1_resources_find_ignition_database_connection_name as _fn,
        )
        return self._sync_detailed_with_fallback(  # type: ignore[return-value]
            _fn, name, envelope_key="items", empty_default={}
        )

    def create_connection(
        self,
        name: str,
        config: dict[str, Any],
        *,
        enabled: bool = True,
        description: str | None = None,
    ) -> dict:
        """``POST /ignition/database-connection`` — body is a list of connection specs.

        No signature required (creating new). Server returns
        ``{success, changes:[{name, type, collection, newSignature}], problem}``.
        Mutation: routes through generated client's shared httpx transport directly.
        """
        body: dict[str, Any] = {"name": name, "enabled": enabled, "config": config}
        if description is not None:
            body["description"] = description
        try:
            r = self._gen_client.get_httpx_client().post(
                f"{_TAG_PROVIDER_BASE}/{_DB_CONN_PATH}",
                json=[body],
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def update_connection(
        self,
        name: str,
        signature: str,
        config: dict[str, Any],
        *,
        enabled: bool | None = None,
        description: str | None = None,
    ) -> dict:
        """``PUT /ignition/database-connection`` — body is a list of update specs.

        ``signature`` is opaque and must come from a prior ``get_connection()``
        call. Empty string raises ``ValueError`` BEFORE any HTTP call —
        prevents blind unauthenticated modification.
        Mutation: routes through generated client's shared httpx transport directly.
        """
        if not signature:
            raise ValueError(
                "update_connection requires a non-empty signature obtained from "
                "get_connection(name). Call get_connection first and pass the "
                "result['signature'] value."
            )
        body: dict[str, Any] = {
            "name": name,
            "signature": signature,
            "config": config,
        }
        if enabled is not None:
            body["enabled"] = enabled
        if description is not None:
            body["description"] = description
        try:
            r = self._gen_client.get_httpx_client().put(
                f"{_TAG_PROVIDER_BASE}/{_DB_CONN_PATH}",
                json=[body],
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def delete_connection(self, name: str, signature: str) -> dict:
        """``DELETE /ignition/database-connection/{name}/{signature}`` — single delete.

        ``signature`` is mandatory. Empty string raises
        ``ValueError`` before any HTTP call.
        Mutation: routes through generated client's shared httpx transport directly.
        """
        if not signature:
            raise ValueError(
                "delete_connection requires a non-empty signature obtained from "
                "get_connection(name)."
            )
        try:
            r = self._gen_client.get_httpx_client().delete(
                f"{_TAG_PROVIDER_BASE}/{_DB_CONN_PATH}/"
                f"{_quote_url_segment(name)}/{_quote_url_segment(signature)}"
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def delete_connections(self, entries: list[dict[str, str]]) -> dict:
        """``POST /delete/ignition/database-connection`` — bulk delete.

        Body is a list of ``{name, signature}`` dicts. The gateway enforces
        the signature requirement server-side; we don't pre-validate here
        because callers may legitimately pass entries fetched in bulk.
        Mutation: routes through generated client's shared httpx transport directly.
        """
        try:
            r = self._gen_client.get_httpx_client().post(
                f"{_TAG_PROVIDER_BASE}/delete/{_DB_CONN_PATH}",
                json=entries,
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def rename_connection(
        self,
        name: str,
        new_name: str,
        *,
        references: str = "UPDATE",
    ) -> dict:
        """``POST /rename/ignition/database-connection/{name}`` — rename in place.

        ``references`` controls how cross-resource references are handled
        (``ABORT`` | ``IGNORE`` | ``UPDATE``). Default ``UPDATE`` updates
        all references to point at the new name (safest for live gateways).
        Mutation: routes through generated client's shared httpx transport directly.
        """
        try:
            r = self._gen_client.get_httpx_client().post(
                f"{_TAG_PROVIDER_BASE}/rename/{_DB_CONN_PATH}/"
                f"{_quote_url_segment(name)}",
                json={"name": new_name, "references": references},
            )
        except httpx.RequestError as e:
            raise _wrap(e) from e
        self._client._raise_for_status(r)
        return r.json()

    def describe_connection_type(self) -> dict:
        """``GET /type/ignition/database-connection`` — describe the resource type.

        Returns the type's extension points, defaults, total counts, and
        runtime metrics names. Echoed as a raw dict — no Pydantic model
        (mirrors describe_provider).
        """
        from ignition_api_client.api.config_databases import (  # noqa: PLC0415
            get_data_api_v1_resources_type_ignition_database_connection as _fn,
        )
        return self._sync_detailed_with_fallback(  # type: ignore[return-value]
            _fn, envelope_key="items", empty_default={}
        )

    # ---- Database Driver (read-only) ----------------------------------
    # 260517-mkv: surface installed JDBC drivers so authors can discover
    # the translator name (e.g. SQLite -> "SQLITE") without grepping
    # config/resources/core/ignition/database-driver/<name>/config.json.
    # Read-only only — create/delete/jar-upload are out of scope.

    def list_drivers(self) -> list[dict]:
        """``GET /names/ignition/database-driver`` — installed JDBC drivers.

        Live response is ``{items: [{name, enabled, ...}], metadata}``.
        We return the flat ``items`` list so callers see one dict per
        driver. Mirrors :meth:`get_provider_names` shape but keeps the
        per-entry dict (rather than collapsing to a list of names) because
        the per-entry ``enabled`` flag is useful for ``ign driver list``.
        """
        from ignition_api_client.api.config_databases import (  # noqa: PLC0415
            get_data_api_v1_resources_names_ignition_database_driver as _fn,
        )
        return self._sync_detailed_with_fallback(  # type: ignore[return-value]
            _fn, envelope_key="items", empty_default=[]
        )

    def get_driver(self, name: str) -> dict:
        """``GET /find/ignition/database-driver/{name}`` — full driver config.

        Returns a dict with at least ``type``, ``classname``,
        ``defaultTranslator``, ``defaultValidationQuery``, ``urlFormat``,
        ``urlInstructions``. ``name`` is URL-quoted by the generated
        endpoint function.
        """
        from ignition_api_client.api.config_databases import (  # noqa: PLC0415
            get_data_api_v1_resources_find_ignition_database_driver_name as _fn,
        )
        return self._sync_detailed_with_fallback(  # type: ignore[return-value]
            _fn, name, envelope_key="items", empty_default={}
        )
