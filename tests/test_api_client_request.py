"""IgnitionAPIClient.request() generic verb.

Behavior contracts:
- request("GET", "/data/api/v1/gateway-info") → httpx.Response (status 200).
- request("POST", "/path", json={}) sends method=POST + body={}.
- 401 → AuthMissingError; 403 → AuthScopeError.
- 400 → PayloadError (with body text in message).
- 422 → PayloadError (4xx catch-all).
- 500/502/503 → GatewayError.
- httpx.RequestError (ConnectError) → NetworkError chained via `from e`.
- method + path passed through verbatim to httpx.
- IGNITION_API_TOKEN value never appears in any error str(exc).
- request() signature has NO `token` parameter.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


def _add_pkg_path() -> None:
    here = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(here))


_add_pkg_path()


_SENTINEL_TOKEN = "test:sentinel-token-not-real"


def _make_client_with_transport(handler):
    """Build IgnitionAPIClient with a MockTransport handler and sentinel token."""
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": _SENTINEL_TOKEN}, clear=False):
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
        from ignition_gen_sdk.config import Settings

        settings = Settings()
        client = IgnitionAPIClient(settings)
        client._client._transport = httpx.MockTransport(handler)
        return client, settings


class TestRequestSuccess(unittest.TestCase):
    def test_200_GET_returns_response(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            return httpx.Response(200, json={"ok": True})

        client, _ = _make_client_with_transport(handler)
        r = client.request("GET", "/data/api/v1/gateway-info")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(seen["method"], "GET")
        self.assertEqual(seen["path"], "/data/api/v1/gateway-info")
        self.assertEqual(r.json(), {"ok": True})

    def test_POST_with_json_body_propagates_body(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            try:
                import json as _json

                seen["body"] = _json.loads(request.content.decode("utf-8"))
            except Exception:
                seen["body"] = None
            return httpx.Response(200, json={})

        client, _ = _make_client_with_transport(handler)
        client.request("POST", "/data/api/v1/scan/config", json={})
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["body"], {})


class TestRequestErrorMapping(unittest.TestCase):
    def _client_with_status(self, status: int, body: str = ""):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=status, text=body)

        return _make_client_with_transport(handler)

    def test_401_raises_AuthMissingError(self) -> None:
        from ignition_gen_sdk.backends.api_client import AuthMissingError

        client, settings = self._client_with_status(401, "no token")
        with self.assertRaises(AuthMissingError) as cm:
            client.request("GET", "/data/api/v1/gateway-info")
        self.assertNotIn(_SENTINEL_TOKEN, str(cm.exception))

    def test_403_raises_AuthScopeError(self) -> None:
        from ignition_gen_sdk.backends.api_client import AuthScopeError

        client, _ = self._client_with_status(403, "scope")
        with self.assertRaises(AuthScopeError) as cm:
            client.request("GET", "/data/api/v1/gateway-info")
        self.assertNotIn(_SENTINEL_TOKEN, str(cm.exception))

    def test_400_raises_PayloadError_with_body(self) -> None:
        from ignition_gen_sdk.backends.api_client import PayloadError

        client, _ = self._client_with_status(400, "bad payload here")
        with self.assertRaises(PayloadError) as cm:
            client.request("POST", "/data/api/v1/scan/config", json={})
        self.assertIn("bad payload here", str(cm.exception))
        self.assertNotIn(_SENTINEL_TOKEN, str(cm.exception))

    def test_422_raises_PayloadError(self) -> None:
        from ignition_gen_sdk.backends.api_client import PayloadError

        client, _ = self._client_with_status(422, "unprocessable")
        with self.assertRaises(PayloadError) as cm:
            client.request("POST", "/data/api/v1/scan/config", json={})
        self.assertNotIn(_SENTINEL_TOKEN, str(cm.exception))

    def test_500_raises_GatewayError(self) -> None:
        from ignition_gen_sdk.backends.api_client import GatewayError

        client, _ = self._client_with_status(500, "boom")
        with self.assertRaises(GatewayError) as cm:
            client.request("GET", "/data/api/v1/gateway-info")
        self.assertNotIn(_SENTINEL_TOKEN, str(cm.exception))

    def test_502_raises_GatewayError(self) -> None:
        from ignition_gen_sdk.backends.api_client import GatewayError

        client, _ = self._client_with_status(502, "")
        with self.assertRaises(GatewayError):
            client.request("GET", "/data/api/v1/gateway-info")

    def test_503_raises_GatewayError(self) -> None:
        from ignition_gen_sdk.backends.api_client import GatewayError

        client, _ = self._client_with_status(503, "")
        with self.assertRaises(GatewayError):
            client.request("GET", "/data/api/v1/gateway-info")


class TestRequestNetworkError(unittest.TestCase):
    def test_ConnectError_becomes_NetworkError_chained(self) -> None:
        from ignition_gen_sdk.backends.api_client import NetworkError

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated connect failure")

        client, _ = _make_client_with_transport(handler)
        with self.assertRaises(NetworkError) as cm:
            client.request("GET", "/data/api/v1/gateway-info")
        # The simulated message should be reflected in the NetworkError.
        self.assertIn("simulated", str(cm.exception))
        # Chained via `from e`.
        self.assertIsNotNone(cm.exception.__cause__)
        self.assertNotIn(_SENTINEL_TOKEN, str(cm.exception))


class TestRequestSignatureSafety(unittest.TestCase):
    def test_signature_has_no_token_parameter(self) -> None:
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

        sig = inspect.signature(IgnitionAPIClient.request)
        for name in sig.parameters:
            self.assertNotIn(
                "token",
                name.lower(),
                f"request() must not accept a token-named parameter: {name}",
            )

    def test_signature_method_path_json_only(self) -> None:
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

        sig = inspect.signature(IgnitionAPIClient.request)
        params = list(sig.parameters)
        # self, method, path, json (4 params expected)
        self.assertEqual(params[:4], ["self", "method", "path", "json"])


if __name__ == "__main__":
    unittest.main()
