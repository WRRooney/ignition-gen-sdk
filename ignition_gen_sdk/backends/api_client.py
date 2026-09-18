"""IgnitionAPIClient — httpx sync client for the gateway HTTP API.

Header format:
    X-Ignition-API-Token: <username>:<token>
The full ``<name>:<secret>`` header value is the IGNITION_API_TOKEN from
.env.

Error taxonomy:
- 401 → AuthMissingError
- 403 → AuthScopeError
- 400 → PayloadError (carries server response body for diagnosis)
- 5xx → GatewayError (retry may help)

Token VALUE is never inserted into exception messages — error strings are
fixed format; only response bodies (which are server-controlled and never
echo the token in observed responses) get included for 400.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from ..config import Settings
from ..models.databases import JWE_KEYS_REQUIRED

if TYPE_CHECKING:
    from ignition_api_client import Client as GeneratedClient


def _walk_jwe(node: Any, jwe_keys: frozenset[str]) -> None:
    """Recursively walk a parsed JSON node; raise PayloadError if JWE shape found."""
    if isinstance(node, dict):
        if jwe_keys.issubset(node.keys()):
            raise PayloadError(
                "JWE credential payload refused: request body contains an AES-256-GCM "
                "JWE credential payload. Set encrypted values via the Gateway UI."
            )
        for v in node.values():
            _walk_jwe(v, jwe_keys)
    elif isinstance(node, list):
        for item in node:
            _walk_jwe(item, jwe_keys)


def _make_jwe_guard(jwe_keys: frozenset[str]):  # noqa: ANN201
    """Return an httpx request event hook that refuses JWE payloads.

    The returned hook fires before any network call via the httpx.Client
    event_hooks mechanism. Short bodies (< 20 bytes) and non-JSON bodies
    are silently skipped.
    """
    def _guard(request: httpx.Request) -> None:
        if len(request.content) < 20:
            return
        try:
            body = json.loads(request.content)
            _walk_jwe(body, jwe_keys)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return _guard


class IgnitionAPIError(Exception):
    """Base class for all Ignition API errors."""


class AuthMissingError(IgnitionAPIError):
    """401: API key missing or invalid."""


class AuthScopeError(IgnitionAPIError):
    """403: Token authenticated but lacks required scope."""


class PayloadError(IgnitionAPIError):
    """400: Auth OK but request payload rejected. Includes response body."""


class GatewayError(IgnitionAPIError):
    """5xx: Gateway-side failure. Retry may help."""


class NetworkError(IgnitionAPIError):
    """Transport-layer failure — DNS resolution, connection refused, timeout.

    Raised by IgnitionAPIClient and ApiBackend when httpx raises a transport
    error (ConnectError, ConnectTimeout, ReadTimeout, RequestError) before
    the gateway responds. The HTTP error taxonomy (AuthMissingError,
    PayloadError, etc.) only applies to gateway HTTP responses; this
    class covers the case where no response arrives at all.

    The CLI routes this through render_error() with a polished Hint.
    """


class UnknownPathError(IgnitionAPIError):
    """Path not present in openapi.json. Raised by cli._openapi_resolver.resolve_path_against_spec."""


class MethodNotAllowedError(IgnitionAPIError):
    """Method not in the path's OpenAPI operations list. Raised by cli._openapi_resolver.resolve_path_against_spec."""


class IgnitionAPIClient:
    """Sync httpx client for the gateway HTTP API.

    Use as a context manager to ensure the underlying TCP connection
    pool is closed:

        with IgnitionAPIClient(Settings()) as client:
            client.import_tags(provider="default", path="Smoke", payload=body)
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Full `<name>:<secret>` header value; Settings validates the shape.
        token_header = settings.ignition_api_key
        self._client = httpx.Client(
            base_url=settings.ignition_base_url,
            headers={
                "X-Ignition-API-Token": token_header,
                "Content-Type": "application/json",
            },
            timeout=30.0,
            event_hooks={
                "request": [_make_jwe_guard(JWE_KEYS_REQUIRED)],
                "response": [],
            },
        )
        # Inject shared transport into generated client so both paths
        # share auth + JWE guard. Import is deferred (generated pkg may be absent
        # on fresh clone — the generated package is gitignored).
        self._generated: "GeneratedClient | None"
        try:
            from ignition_api_client import Client as _GenClient  # noqa: PLC0415
            self._generated = _GenClient(base_url=str(settings.ignition_base_url))
            self._generated.set_httpx_client(self._client)
        except ModuleNotFoundError:
            self._generated = None  # triggers regen on first ApiBackend typed-verb call

    def _raise_for_status(self, r: httpx.Response) -> None:
        if r.status_code == 401:
            raise AuthMissingError(
                "401 Unauthorized: check IGNITION_API_TOKEN"
            )
        if r.status_code == 403:
            raise AuthScopeError(
                "403 Forbidden: API token lacks required scope — check Gateway UI permissions"
            )
        if r.status_code == 400:
            # Server response body included for diagnosis. Token is never
            # echoed back by the gateway in observed responses, so this is
            # safe; the helper does NOT format the api_key into the message.
            raise PayloadError(f"400 Bad Request: {r.text}")
        if 400 <= r.status_code < 500:
            # 422 Unprocessable Entity (e.g. invalid provider name in
            # tag-import params) and other 4xx responses are likewise
            # programmer/payload errors. Treat them as PayloadError so
            # callers can rely on a single exception class for the whole
            # 4xx family. Without this branch httpx.raise_for_status()
            # leaks an HTTPStatusError that bypasses the CLI's error
            # taxonomy.
            raise PayloadError(
                f"{r.status_code} {r.reason_phrase}: {r.text}"
            )
        if r.status_code >= 500:
            raise GatewayError(
                f"{r.status_code} Gateway Error: retry the request or check gateway logs"
            )
        r.raise_for_status()

    def request(
        self,
        method: str,
        path: str,
        json: Any = None,
    ) -> httpx.Response:
        """Generic HTTP call. Reuses the long-lived self._client.

        The X-Ignition-API-Token header was set ONCE at __init__ on
        self._client and is never touched here -- the token never enters
        the method/path arguments, the exception messages, or any other
        observable surface of this method. Callers receive the raw
        httpx.Response on 2xx and decide how to render the body.

        Args:
            method: HTTP verb (GET, POST, PUT, DELETE, PATCH). Forwarded
                verbatim to httpx; not normalized here.
            path: Path starting with "/", e.g. /data/api/v1/gateway-info.
                The base_url is prepended by httpx.
            json: Optional request body. httpx serializes dicts to JSON.

        Returns:
            httpx.Response on 2xx.

        Raises:
            AuthMissingError on 401.
            AuthScopeError on 403.
            PayloadError on 4xx (incl. 400 and 422 catch-all).
            GatewayError on 5xx.
            NetworkError on transport failure (chained via `from e`).
        """
        try:
            r = self._client.request(method, path, json=json)
        except httpx.RequestError as e:
            # Same shape as import_tags() lines above -- one catch covers
            # ConnectError, ConnectTimeout, ReadTimeout, WriteTimeout, etc.
            raise NetworkError(str(e)) from e
        self._raise_for_status(r)
        return r

    def import_tags(
        self,
        provider: str,
        path: str,
        payload: dict,
        collision_policy: str = "MergeOverwrite",
    ) -> Any:
        """POST /data/api/v1/tags/import — push tag tree to the gateway.

        Returns the parsed JSON response. Live gateway 8.3.4 returns a
        dict ``{"successCount": int, "failureCount": int, "failures": [...]}``;
        the API reference also documents a list-of-diagnostics shape.
        Callers should handle both: dict (8.3.4 observed) or list (legacy).
        """
        params: dict[str, str] = {
            "provider": provider,
            "type": "json",
            "collisionPolicy": collision_policy,
        }
        if path:
            params["path"] = path
        try:
            r = self._client.post(
                "/data/api/v1/tags/import",
                params=params,
                json=payload,
            )
        except httpx.RequestError as e:
            # RequestError is the base for ConnectError, ConnectTimeout,
            # ReadTimeout, WriteTimeout, and all other transport failures.
            raise NetworkError(str(e)) from e
        self._raise_for_status(r)
        return r.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "IgnitionAPIClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
