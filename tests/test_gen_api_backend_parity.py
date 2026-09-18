"""ApiBackend generated-client parity tests.

Verify ApiBackend return types are unchanged when it is backed by the
generated client. Uses unittest.mock to mock the generated client
functions; tests that the public API returns list[dict] or dict — never
attrs objects.

Coverage:
- list_providers(): returns list[dict] when mock resp.parsed has items
- list_connections(): returns list[dict] when mock resp.parsed has items
- list_drivers(): returns list[dict] when mock resp.parsed has items
- _parse_response raises AuthMissingError on status_code=401
- _parse_response raises PayloadError on status_code=400
- _parse_response returns empty list when resp.parsed is None (no raw content)
- Full non-smoke suite passes (regression gate)
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import unittest
from unittest.mock import MagicMock, patch

import attrs


# ---------------------------------------------------------------------------
# Minimal attrs models to stand in for generated response objects
# ---------------------------------------------------------------------------

@attrs.define
class _FakeItem:
    name: str
    config: dict = attrs.Factory(dict)


@attrs.define
class _FakeListResponse:
    items: list[_FakeItem] = attrs.Factory(list)
    metadata: dict = attrs.Factory(dict)

    def to_dict(self) -> dict:
        return {
            "items": [{"name": i.name, "config": i.config} for i in self.items],
            "metadata": self.metadata,
        }


@attrs.define
class _FakeFindResponse:
    name: str
    signature: str = ""
    config: dict = attrs.Factory(dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "signature": self.signature, "config": self.config}


# ---------------------------------------------------------------------------
# Helper to build an ApiBackend with a mock generated client
# ---------------------------------------------------------------------------

def _make_backend_with_mock_gen():
    """Build ApiBackend with a MagicMock injected as the generated client."""
    from ignition_gen_sdk.backends.api_backend import ApiBackend
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
    from ignition_gen_sdk.config import Settings

    settings = Settings(
        ignition_api_key="test:test-parity-key",
        ignition_base_url=GATEWAY_URL,
    )
    client = IgnitionAPIClient(settings)
    mock_gen = MagicMock()
    client._generated = mock_gen
    backend = ApiBackend(client)
    return backend, client, mock_gen


def _make_mock_resp(status_code: int, parsed=None, content: bytes = b"{}"):
    """Build a MagicMock that looks like a generated sync_detailed() Response."""
    resp = MagicMock()
    # Generated Response wraps status_code in HTTPStatus enum.
    resp.status_code = status_code
    resp.parsed = parsed
    resp.content = content
    return resp


# ---------------------------------------------------------------------------
# list_providers() returns list[dict]
# ---------------------------------------------------------------------------

class TestListProvidersReturnType(unittest.TestCase):
    def test_list_providers_returns_list_of_dicts(self) -> None:
        """list_providers() returns list[dict] — never attrs objects."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
        from ignition_gen_sdk.config import Settings
        import httpx

        # Use MockTransport returning items envelope to exercise real path.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"name": "default", "enabled": True},
                        {"name": "System", "enabled": True},
                    ],
                    "metadata": {"total": 2},
                },
            )

        settings = Settings(
            ignition_api_key="test:test-parity-key",
            ignition_base_url=GATEWAY_URL,
        )
        client = IgnitionAPIClient(settings)
        client._client.close()
        transport = httpx.MockTransport(handler)
        client._client = httpx.Client(
            base_url=settings.ignition_base_url,
            headers={"X-Ignition-API-Token": "test:test-parity-key", "Content-Type": "application/json"},
            transport=transport,
        )
        backend = ApiBackend(client)
        try:
            result = backend.list_providers()
        finally:
            client.close()

        self.assertIsInstance(result, list, "list_providers() must return list")
        for item in result:
            self.assertIsInstance(item, dict, f"Each item must be dict, got {type(item)}")

    def test_list_providers_via_typed_path_returns_list_of_dicts(self) -> None:
        """list_providers() via mock resp.parsed returns list[dict]."""
        backend, client, mock_gen = _make_backend_with_mock_gen()

        # Mock sync_detailed to return a proper Response-like with parsed set.
        fake_parsed = _FakeListResponse(
            items=[_FakeItem(name="default"), _FakeItem(name="System")]
        )
        mock_resp = _make_mock_resp(200, parsed=fake_parsed)

        with patch(
            "ignition_api_client.api.config_tag_provider.get_data_api_v1_resources_list_ignition_tag_provider.sync_detailed",
            return_value=mock_resp,
        ):
            result = backend.list_providers()

        self.assertIsInstance(result, list, "list_providers() must return list")
        for item in result:
            self.assertIsInstance(item, dict, f"Each item must be dict, got {type(item)}")
        names = [item.get("name") for item in result]
        self.assertIn("default", names)
        self.assertIn("System", names)


# ---------------------------------------------------------------------------
# list_connections() returns list[dict]
# ---------------------------------------------------------------------------

class TestListConnectionsReturnType(unittest.TestCase):
    def test_list_connections_returns_list_of_dicts(self) -> None:
        """list_connections() returns list[dict] — never attrs objects."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
        from ignition_gen_sdk.config import Settings
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"name": "Demo_DB", "enabled": True},
                    ],
                    "metadata": {"total": 1},
                },
            )

        settings = Settings(
            ignition_api_key="test:test-parity-key",
            ignition_base_url=GATEWAY_URL,
        )
        client = IgnitionAPIClient(settings)
        client._client.close()
        transport = httpx.MockTransport(handler)
        client._client = httpx.Client(
            base_url=settings.ignition_base_url,
            headers={"X-Ignition-API-Token": "test:test-parity-key", "Content-Type": "application/json"},
            transport=transport,
        )
        backend = ApiBackend(client)
        try:
            result = backend.list_connections()
        finally:
            client.close()

        self.assertIsInstance(result, list, "list_connections() must return list")
        for item in result:
            self.assertIsInstance(item, dict, f"Each item must be dict, got {type(item)}")


# ---------------------------------------------------------------------------
# list_drivers() returns list[dict]
# ---------------------------------------------------------------------------

class TestListDriversReturnType(unittest.TestCase):
    def test_list_drivers_returns_list_of_dicts(self) -> None:
        """list_drivers() returns list[dict]."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
        from ignition_gen_sdk.config import Settings
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"name": "MySQL", "enabled": True},
                    ],
                    "metadata": {"total": 1},
                },
            )

        settings = Settings(
            ignition_api_key="test:test-parity-key",
            ignition_base_url=GATEWAY_URL,
        )
        client = IgnitionAPIClient(settings)
        client._client.close()
        transport = httpx.MockTransport(handler)
        client._client = httpx.Client(
            base_url=settings.ignition_base_url,
            headers={"X-Ignition-API-Token": "test:test-parity-key", "Content-Type": "application/json"},
            transport=transport,
        )
        backend = ApiBackend(client)
        try:
            result = backend.list_drivers()
        finally:
            client.close()

        self.assertIsInstance(result, list, "list_drivers() must return list")
        for item in result:
            self.assertIsInstance(item, dict, f"Each item must be dict, got {type(item)}")


# ---------------------------------------------------------------------------
# _parse_response raises AuthMissingError on 401
# ---------------------------------------------------------------------------

class TestParseResponseErrors(unittest.TestCase):
    def test_parse_response_raises_auth_missing_on_401(self) -> None:
        """_parse_response raises AuthMissingError for status 401."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient, AuthMissingError
        from ignition_gen_sdk.config import Settings

        settings = Settings(
            ignition_api_key="test:test-parity-key",
            ignition_base_url=GATEWAY_URL,
        )
        client = IgnitionAPIClient(settings)
        backend = ApiBackend(client)

        mock_resp = _make_mock_resp(401, content=b"Unauthorized")

        with self.assertRaises(AuthMissingError):
            backend._parse_response(mock_resp)

    # ---------------------------------------------------------------------------
    # _parse_response raises PayloadError on 400
    # ---------------------------------------------------------------------------

    def test_parse_response_raises_payload_error_on_400(self) -> None:
        """_parse_response raises PayloadError for status 400."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient, PayloadError
        from ignition_gen_sdk.config import Settings

        settings = Settings(
            ignition_api_key="test:test-parity-key",
            ignition_base_url=GATEWAY_URL,
        )
        client = IgnitionAPIClient(settings)
        backend = ApiBackend(client)

        mock_resp = _make_mock_resp(400, content=b"Bad params")

        with self.assertRaises(PayloadError):
            backend._parse_response(mock_resp)

    # ---------------------------------------------------------------------------
    # _parse_response returns empty list when parsed is None + no content
    # ---------------------------------------------------------------------------

    def test_parse_response_returns_empty_list_when_parsed_none(self) -> None:
        """_parse_response returns empty_default when resp.parsed is None."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
        from ignition_gen_sdk.config import Settings

        settings = Settings(
            ignition_api_key="test:test-parity-key",
            ignition_base_url=GATEWAY_URL,
        )
        client = IgnitionAPIClient(settings)
        backend = ApiBackend(client)

        # parsed is None AND no JSON-parseable content
        mock_resp = _make_mock_resp(200, parsed=None, content=b"")

        result = backend._parse_response(mock_resp, envelope_key="items", empty_default=[])
        self.assertEqual(result, [], f"Expected [], got {result!r}")


# ---------------------------------------------------------------------------
# _gen_client property exists and re-syncs transport
# ---------------------------------------------------------------------------

class TestGenClientProperty(unittest.TestCase):
    def test_gen_client_property_returns_generated_client(self) -> None:
        """_gen_client property returns the generated Client instance."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
        from ignition_gen_sdk.config import Settings

        settings = Settings(
            ignition_api_key="test:test-parity-key",
            ignition_base_url=GATEWAY_URL,
        )
        client = IgnitionAPIClient(settings)
        backend = ApiBackend(client)

        gen = backend._gen_client
        self.assertIsNotNone(gen, "_gen_client must not be None")

    def test_gen_client_shares_httpx_client_with_api_client(self) -> None:
        """_gen_client.get_httpx_client() IS the same object as client._client."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
        from ignition_gen_sdk.config import Settings

        settings = Settings(
            ignition_api_key="test:test-parity-key",
            ignition_base_url=GATEWAY_URL,
        )
        client = IgnitionAPIClient(settings)
        backend = ApiBackend(client)

        gen = backend._gen_client
        self.assertIs(
            gen.get_httpx_client(),
            client._client,
            "generated client does not share the auth transport",
        )


# ---------------------------------------------------------------------------
# No top-level ignition_api_client imports in api_backend.py
# ---------------------------------------------------------------------------

class TestLazyImports(unittest.TestCase):
    def test_no_top_level_ignition_api_client_import(self) -> None:
        """api_backend.py must not import ignition_api_client at module level."""
        from pathlib import Path
        api_backend_path = (
            Path(__file__).resolve().parents[1]
            / "ignition_gen_sdk"
            / "backends"
            / "api_backend.py"
        )
        source = api_backend_path.read_text(encoding="utf-8")
        # Check no top-level (outside function body) import of the generated package.
        # Lines starting with "from ignition_api_client" or "import ignition_api_client"
        # at the module level (not indented) are forbidden.
        for line in source.splitlines():
            if line.startswith("from ignition_api_client") or line.startswith("import ignition_api_client"):
                self.fail(
                    f"Top-level import of ignition_api_client found in api_backend.py:\n  {line}"
                )


if __name__ == "__main__":
    unittest.main()
