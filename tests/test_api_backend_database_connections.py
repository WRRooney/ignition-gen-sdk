"""ApiBackend database-connection CRUD tests.

Mirrors tests/test_task5_api_backend.py (provider CRUD) for the nine
``ignition/database-connection`` endpoints. Uses httpx.MockTransport
through the same ``_make_backend_with_transport`` pattern.

Coverage:
- list_connections: items envelope unwrap + bare-list passthrough
- get_connection_names: items envelope name extraction
- get_connection: URL-quoting of the name path segment
- create_connection: POST body shape (one-element array, description optional)
- update_connection: signature-empty ValueError before HTTP + PUT body shape
- delete_connection: signature-empty ValueError before HTTP + both path
  segments URL-quoted
- delete_connections: bulk POST body passthrough
- rename_connection: POST body + URL-quoted name + default references="UPDATE"
- describe_connection_type: raw dict echo
- NetworkError wrap on httpx.RequestError
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import json
import unittest

import httpx


def _make_backend_with_transport(handler):
    """Build an ApiBackend whose IgnitionAPIClient hits an httpx MockTransport."""
    from ignition_gen_sdk.backends.api_backend import ApiBackend
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
    from ignition_gen_sdk.config import Settings

    settings = Settings(
        ignition_api_key="test:test-secret-DO-NOT-LEAK",
        ignition_base_url=GATEWAY_URL,
    )
    client = IgnitionAPIClient(settings)
    client._client.close()
    transport = httpx.MockTransport(handler)
    client._client = httpx.Client(
        base_url=settings.ignition_base_url,
        headers={
            "X-Ignition-API-Token": "test:test-secret-DO-NOT-LEAK",
            "Content-Type": "application/json",
        },
        transport=transport,
    )
    return ApiBackend(client), client


class TestListAndDescribe(unittest.TestCase):
    def test_list_connections_unwraps_items(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"name": "Demo_DB", "config": {"driver": "SQLite"}},
                        {"name": "Sensors_DB", "config": {"driver": "MySQL"}},
                    ],
                    "metadata": {"total": 2},
                },
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            connections = backend.list_connections()
        finally:
            client.close()

        self.assertIsInstance(connections, list)
        self.assertEqual(len(connections), 2)
        self.assertEqual(connections[0]["name"], "Demo_DB")
        self.assertIn(
            "/data/api/v1/resources/list/ignition/database-connection",
            captured["url"],
        )
        self.assertEqual(captured["method"], "GET")

    def test_list_connections_passes_through_bare_list(self) -> None:
        """Defensive: future gateway might drop the envelope. Bare list OK."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=[{"name": "Demo_DB"}, {"name": "Sensors_DB"}]
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            connections = backend.list_connections()
        finally:
            client.close()

        self.assertEqual(connections, [{"name": "Demo_DB"}, {"name": "Sensors_DB"}])

    def test_get_connection_names_extracts_names(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"name": "Demo_DB", "enabled": True},
                        {"name": "Sensors_DB", "enabled": True},
                    ],
                    "metadata": {"total": 2},
                },
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            names = backend.get_connection_names()
        finally:
            client.close()

        self.assertIsInstance(names, list)
        self.assertEqual(names, ["Demo_DB", "Sensors_DB"])

    def test_describe_connection_type_returns_raw_dict(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(
                200,
                json={
                    "module": "ignition",
                    "typeId": "database-connection",
                    "total": 2,
                },
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            info = backend.describe_connection_type()
        finally:
            client.close()

        self.assertEqual(info["typeId"], "database-connection")
        self.assertEqual(info["total"], 2)
        self.assertEqual(captured["method"], "GET")
        self.assertIn(
            "/data/api/v1/resources/type/ignition/database-connection",
            captured["url"],
        )

    def test_network_error_wrapped(self) -> None:
        """httpx transport errors must surface as NetworkError, not raw httpx."""
        from ignition_gen_sdk.backends.api_client import NetworkError

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated connection refused")

        backend, client = _make_backend_with_transport(handler)
        try:
            with self.assertRaises(NetworkError):
                backend.list_connections()
        finally:
            client.close()


class TestGet(unittest.TestCase):
    def test_get_connection_url_quotes_name(self) -> None:
        """A name containing spaces + parentheses must be percent-encoded.

        ``request.url.path`` is the *decoded* path. Use ``raw_path`` (bytes)
        to assert the wire-shape literal segment after percent-encoding.
        """
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["raw_path"] = request.url.raw_path
            return httpx.Response(
                200,
                json={
                    "name": "My DB (Prod)",
                    "signature": "abc123",
                    "config": {"driver": "MySQL"},
                },
            )

        backend, client = _make_backend_with_transport(handler)
        try:
            result = backend.get_connection("My DB (Prod)")
        finally:
            client.close()

        # Name path segment must be percent-encoded.
        self.assertEqual(
            captured["raw_path"],
            b"/data/api/v1/resources/find/ignition/database-connection/My%20DB%20%28Prod%29",
        )
        self.assertEqual(result["signature"], "abc123")


class TestCreateUpdate(unittest.TestCase):
    def test_create_connection_post_body_shape(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = request.read()
            return httpx.Response(200, json={"success": True, "changes": []})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.create_connection(
                "Demo_DB",
                config={"driver": "SQLite", "translator": "SQLITE"},
            )
        finally:
            client.close()

        body = json.loads(captured["body"])
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["path"],
            "/data/api/v1/resources/ignition/database-connection",
        )
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["name"], "Demo_DB")
        self.assertTrue(body[0]["enabled"])
        self.assertEqual(body[0]["config"], {"driver": "SQLite", "translator": "SQLITE"})
        # description omitted when None
        self.assertNotIn("description", body[0])

    def test_update_connection_requires_signature(self) -> None:
        """Empty signature must raise ValueError BEFORE any HTTP call."""
        def must_not_be_called(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                "HTTP call must not happen when signature is empty"
            )

        backend, client = _make_backend_with_transport(must_not_be_called)
        try:
            with self.assertRaises(ValueError) as ctx:
                backend.update_connection("Demo_DB", "", config={})
            self.assertIn("non-empty signature", str(ctx.exception))
            self.assertIn("get_connection", str(ctx.exception))
        finally:
            client.close()

    def test_update_connection_put_body_shape(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = request.read()
            return httpx.Response(200, json={"success": True, "changes": []})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.update_connection(
                "Demo_DB",
                signature="abc123",
                config={"driver": "SQLite", "translator": "SQLITE"},
            )
        finally:
            client.close()

        body = json.loads(captured["body"])
        self.assertEqual(captured["method"], "PUT")
        self.assertEqual(
            captured["path"],
            "/data/api/v1/resources/ignition/database-connection",
        )
        self.assertIsInstance(body, list)
        self.assertEqual(body[0]["name"], "Demo_DB")
        self.assertEqual(body[0]["signature"], "abc123")
        self.assertEqual(body[0]["config"]["driver"], "SQLite")


class TestDeleteAndRename(unittest.TestCase):
    def test_delete_connection_requires_signature(self) -> None:
        def must_not_be_called(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                "HTTP call must not happen when signature is empty"
            )

        backend, client = _make_backend_with_transport(must_not_be_called)
        try:
            with self.assertRaises(ValueError) as ctx:
                backend.delete_connection("Demo_DB", "")
            self.assertIn("non-empty signature", str(ctx.exception))
        finally:
            client.close()

    def test_delete_connection_url_quotes_both_segments(self) -> None:
        """Name with space + signature with '/' both percent-encoded.

        Use ``raw_path`` (bytes) — the decoded ``path`` would collapse
        ``abc%2Fdef`` to ``abc/def`` and look like a wider URL.
        """
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["raw_path"] = request.url.raw_path
            return httpx.Response(200, json={"success": True})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.delete_connection("My DB", "abc/def")
        finally:
            client.close()

        self.assertEqual(captured["method"], "DELETE")
        self.assertEqual(
            captured["raw_path"],
            b"/data/api/v1/resources/ignition/database-connection/My%20DB/abc%2Fdef",
        )

    def test_delete_connections_bulk_post_body(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = request.read()
            return httpx.Response(200, json={"success": True})

        backend, client = _make_backend_with_transport(handler)
        try:
            entries = [
                {"name": "Demo_DB", "signature": "s1"},
                {"name": "Sensors_DB", "signature": "s2"},
            ]
            backend.delete_connections(entries)
        finally:
            client.close()

        body = json.loads(captured["body"])
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["path"],
            "/data/api/v1/resources/delete/ignition/database-connection",
        )
        self.assertEqual(body, [
            {"name": "Demo_DB", "signature": "s1"},
            {"name": "Sensors_DB", "signature": "s2"},
        ])

    def test_rename_connection_post_body_and_path(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = request.read()
            return httpx.Response(200, json={"success": True})

        backend, client = _make_backend_with_transport(handler)
        try:
            backend.rename_connection("Demo_DB", "Demo_DBRenamed")
        finally:
            client.close()

        body = json.loads(captured["body"])
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["path"],
            "/data/api/v1/resources/rename/ignition/database-connection/Demo_DB",
        )
        self.assertEqual(body, {"name": "Demo_DBRenamed", "references": "UPDATE"})


if __name__ == "__main__":
    unittest.main()
