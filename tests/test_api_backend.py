"""ApiBackend tests.

Covers:
- import_tags delegation to IgnitionAPIClient
- Tag provider CRUD (9 endpoints)
- Signature-required guards on update_provider / delete_provider
- Response unwrapping for endpoints that return ``{items, metadata}``
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import unittest
from unittest.mock import MagicMock

import httpx


class TestApiBackendImports(unittest.TestCase):
    def test_module_importable(self) -> None:
        from ignition_gen_sdk.backends import api_backend  # noqa: F401

    def test_class_present(self) -> None:
        from ignition_gen_sdk.backends.api_backend import ApiBackend  # noqa: F401


class TestApiBackendTagImport(unittest.TestCase):
    def test_import_tags_delegates_to_client(self) -> None:
        from ignition_gen_sdk.backends.api_backend import ApiBackend

        client = MagicMock()
        client.import_tags.return_value = {"successCount": 1, "failureCount": 0, "failures": []}
        backend = ApiBackend(client)

        result = backend.import_tags("default", "Smoke", {"tags": []})

        client.import_tags.assert_called_once_with(
            "default", "Smoke", {"tags": []}, "MergeOverwrite"
        )
        self.assertEqual(result["successCount"], 1)

    def test_import_tags_collision_policy_passed_through(self) -> None:
        from ignition_gen_sdk.backends.api_backend import ApiBackend

        client = MagicMock()
        client.import_tags.return_value = []
        backend = ApiBackend(client)

        backend.import_tags("default", "P", {"tags": []}, collision_policy="Abort")

        client.import_tags.assert_called_once_with(
            "default", "P", {"tags": []}, "Abort"
        )


def _make_backend_with_transport(handler):
    """Build an ApiBackend whose IgnitionAPIClient hits an httpx MockTransport."""
    from ignition_gen_sdk.backends.api_backend import ApiBackend
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
    from ignition_gen_sdk.config import Settings

    settings = Settings(
        ignition_api_key="test:test-secret",
        ignition_base_url=GATEWAY_URL,
    )
    client = IgnitionAPIClient(settings)
    # Swap the underlying httpx.Client for one that uses our handler.
    client._client.close()
    transport = httpx.MockTransport(handler)
    client._client = httpx.Client(
        base_url=settings.ignition_base_url,
        headers={
            "X-Ignition-API-Token": "test:test-secret",
            "Content-Type": "application/json",
        },
        transport=transport,
    )
    return ApiBackend(client), client


class TestProviderListAndNames(unittest.TestCase):
    def test_list_providers_unwraps_items(self) -> None:
        """``/list`` returns ``{items, metadata}`` — backend should return the items list."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"name": "default", "signature": "abc", "config": {}},
                        {"name": "Plant", "signature": "def", "config": {}},
                    ],
                    "metadata": {"total": 2},
                },
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            providers = backend.list_providers()
        finally:
            client.close()

        self.assertIsInstance(providers, list)
        self.assertEqual(len(providers), 2)
        self.assertEqual(providers[0]["name"], "default")
        self.assertIn("/data/api/v1/resources/list/ignition/tag-provider", captured["url"])
        self.assertEqual(captured["method"], "GET")

    def test_get_provider_names_returns_list_of_names(self) -> None:
        """``/names`` returns ``{items: [{name, enabled, modes}], metadata}``.

        Backend extracts a plain list of names — the plan's verify script
        asserts ``isinstance(names, list)`` and ``'default' in names``.
        """
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"name": "default", "enabled": True, "modes": ["core"]},
                        {"name": "Plant", "enabled": True, "modes": ["core"]},
                    ],
                    "metadata": {"total": 2},
                },
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            names = backend.get_provider_names()
        finally:
            client.close()

        self.assertIsInstance(names, list)
        self.assertIn("default", names)
        self.assertIn("Plant", names)


class TestGetProvider(unittest.TestCase):
    def test_get_provider_returns_dict_with_signature(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(
                200,
                json={
                    "type": "ignition/tag-provider",
                    "name": "default",
                    "signature": "5a176959",
                    "config": {"profile": {"type": "STANDARD"}},
                    "enabled": True,
                },
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            provider = backend.get_provider("default")
        finally:
            client.close()

        self.assertEqual(provider["name"], "default")
        self.assertEqual(provider["signature"], "5a176959")
        self.assertIn(
            "/data/api/v1/resources/find/ignition/tag-provider/default",
            captured["url"],
        )


class TestProviderModifyDeleteGuards(unittest.TestCase):
    def test_update_provider_blank_signature_raises_before_http(self) -> None:
        """Plan guarantees: blank signature raises ValueError without any HTTP call."""
        from ignition_gen_sdk.backends.api_backend import ApiBackend

        client = MagicMock()
        backend = ApiBackend(client)

        with self.assertRaises(ValueError) as ctx:
            backend.update_provider("default", signature="", config={})
        self.assertIn("signature", str(ctx.exception).lower())
        # Must NOT have called the underlying httpx client.
        client._client.put.assert_not_called()
        client._client.post.assert_not_called()

    def test_delete_provider_blank_signature_raises_before_http(self) -> None:
        from ignition_gen_sdk.backends.api_backend import ApiBackend

        client = MagicMock()
        backend = ApiBackend(client)

        with self.assertRaises(ValueError) as ctx:
            backend.delete_provider("default", signature="")
        self.assertIn("signature", str(ctx.exception).lower())
        client._client.delete.assert_not_called()


class TestCreateProvider(unittest.TestCase):
    def test_create_provider_posts_list_envelope(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            captured["body"] = request.read()
            return httpx.Response(200, json={"success": True, "changes": []})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.create_provider(
                "newprov",
                config={"profile": {"type": "STANDARD"}},
                description="Test",
            )
        finally:
            client.close()

        import json as _json
        body = _json.loads(captured["body"])
        self.assertIsInstance(body, list)
        self.assertEqual(body[0]["name"], "newprov")
        self.assertTrue(body[0]["enabled"])
        self.assertEqual(body[0]["description"], "Test")
        self.assertEqual(captured["method"], "POST")
        self.assertIn("/data/api/v1/resources/ignition/tag-provider", captured["url"])


class TestUpdateProviderHttp(unittest.TestCase):
    def test_update_provider_puts_with_signature(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = request.read()
            return httpx.Response(200, json={"success": True, "changes": []})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.update_provider(
                "default",
                signature="abc123",
                config={"profile": {"type": "STANDARD"}},
            )
        finally:
            client.close()

        import json as _json
        body = _json.loads(captured["body"])
        self.assertEqual(captured["method"], "PUT")
        self.assertEqual(body[0]["signature"], "abc123")
        self.assertEqual(body[0]["name"], "default")


class TestDeleteProviderHttp(unittest.TestCase):
    def test_delete_provider_uses_path_signature(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"success": True})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.delete_provider("default", signature="sig123")
        finally:
            client.close()

        self.assertEqual(captured["method"], "DELETE")
        self.assertIn("/ignition/tag-provider/default/sig123", captured["url"])


class TestRenameAndDescribeAndDeleteMany(unittest.TestCase):
    def test_rename_provider_post(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = request.read()
            return httpx.Response(200, json={"success": True})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.rename_provider("old", "new")
        finally:
            client.close()

        import json as _json
        body = _json.loads(captured["body"])
        self.assertEqual(captured["method"], "POST")
        self.assertIn("/rename/ignition/tag-provider/old", captured["url"])
        self.assertEqual(body["name"], "new")

    def test_describe_provider_type(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"module": "ignition", "typeId": "tag-provider", "total": 5},
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            info = backend.describe_provider_type()
        finally:
            client.close()

        self.assertEqual(info["typeId"], "tag-provider")

    def test_delete_providers_posts_array(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = request.read()
            return httpx.Response(200, json={"success": True})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.delete_providers(
                [{"name": "a", "signature": "s1"}, {"name": "b", "signature": "s2"}]
            )
        finally:
            client.close()

        import json as _json
        body = _json.loads(captured["body"])
        self.assertEqual(captured["method"], "POST")
        self.assertIn("/delete/ignition/tag-provider", captured["url"])
        self.assertEqual(len(body), 2)


if __name__ == "__main__":
    unittest.main()
