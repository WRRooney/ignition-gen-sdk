"""Tag model fix, TagApiSerializer, IgnitionAPIClient.

Behavior contracts:
- Tag(opcServer not set).emit() does NOT contain "opcServer".
- Tag with opcServer set explicitly emits opcServer.
- tags_to_import_body([tag]) wraps in Provider envelope: name="", tagType="Provider".
- IgnitionAPIClient maps 401→AuthMissingError, 403→AuthScopeError,
  400→PayloadError (with response body), 5xx→GatewayError. Token
  never appears in exception messages.
"""
from __future__ import annotations

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


def _settings():
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:secret-token-VALUE-xyz"}, clear=False):
        from ignition_gen_sdk.config import Settings

        return Settings()


class TestTagModel(unittest.TestCase):
    def test_emit_no_opcServer_when_unset(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag

        tag = Tag(
            name="T1",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.DOUBLE,
            valueSource=TagValueSource.MEMORY,
        )
        flat = tag.emit()
        self.assertNotIn("opcServer", flat, f"opcServer leaked: {flat}")

    def test_emit_keeps_explicit_opcServer(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag

        tag = Tag(
            name="T2",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.DOUBLE,
            valueSource=TagValueSource.OPC,
            opcItemPath="ns=1;s=test",
            opcServer="Ignition OPC UA Server",
        )
        flat = tag.emit()
        self.assertEqual(flat["opcServer"], "Ignition OPC UA Server")
        self.assertEqual(flat["opcItemPath"], "ns=1;s=test")
        self.assertEqual(flat["dataType"], "Float8")
        self.assertEqual(flat["tagType"], "AtomicTag")
        self.assertEqual(flat["valueSource"], "opc")

    def test_emit_drops_none_fields(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag

        tag = Tag(
            name="T3",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.DOUBLE,
            valueSource=TagValueSource.MEMORY,
        )
        flat = tag.emit()
        for k, v in flat.items():
            self.assertIsNotNone(v, f"None value in emit at key {k}")

    def test_credential_guard_inherits_to_tag(self) -> None:
        from ignition_gen_sdk.models.tags.tag import Tag

        with self.assertRaises(ValueError):
            Tag.model_validate({"ciphertext": "x", "name": "T"})


class TestTagApiSerializer(unittest.TestCase):
    def test_import_body_provider_envelope(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.serializers.tag_api import tags_to_import_body

        tag = Tag(
            name="T",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.DOUBLE,
            valueSource=TagValueSource.OPC,
            opcItemPath="ns=1;s=x",
            opcServer="Ignition OPC UA Server",
        )
        body = tags_to_import_body([tag])
        self.assertEqual(body["name"], "")
        self.assertEqual(body["tagType"], "Provider")
        self.assertEqual(len(body["tags"]), 1)
        self.assertEqual(body["tags"][0]["name"], "T")
        self.assertEqual(body["tags"][0]["dataType"], "Float8")


class _MockTransport(httpx.MockTransport):
    pass


class TestIgnitionAPIClient(unittest.TestCase):
    def _client_with_status(self, status: int, body: str = ""):
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

        settings = _settings()

        def handler(request: httpx.Request) -> httpx.Response:
            # Verify header is composed correctly
            self.assertEqual(
                request.headers.get("X-Ignition-API-Token"),
                settings.ignition_api_key,
            )
            return httpx.Response(status_code=status, text=body)

        client = IgnitionAPIClient(settings)
        # Replace transport on the underlying httpx.Client.
        client._client._transport = httpx.MockTransport(handler)
        return client, settings

    def test_error_classes_distinct_subclasses(self) -> None:
        from ignition_gen_sdk.backends.api_client import (
            AuthMissingError,
            AuthScopeError,
            GatewayError,
            IgnitionAPIError,
            PayloadError,
        )

        for cls in (AuthMissingError, AuthScopeError, PayloadError, GatewayError):
            self.assertTrue(issubclass(cls, IgnitionAPIError))
            self.assertTrue(issubclass(cls, Exception))

    def test_raises_AuthMissingError_on_401(self) -> None:
        from ignition_gen_sdk.backends.api_client import AuthMissingError

        client, settings = self._client_with_status(401, "unauthorized")
        with self.assertRaises(AuthMissingError) as cm:
            client.import_tags("default", "Smoke", {"tags": []})
        self.assertNotIn(settings.ignition_api_key, str(cm.exception))

    def test_raises_AuthScopeError_on_403(self) -> None:
        from ignition_gen_sdk.backends.api_client import AuthScopeError

        client, settings = self._client_with_status(403)
        with self.assertRaises(AuthScopeError) as cm:
            client.import_tags("default", "Smoke", {"tags": []})
        self.assertNotIn(settings.ignition_api_key, str(cm.exception))

    def test_raises_PayloadError_on_400_with_body(self) -> None:
        from ignition_gen_sdk.backends.api_client import PayloadError

        client, settings = self._client_with_status(400, "bad provider")
        with self.assertRaises(PayloadError) as cm:
            client.import_tags("default", "Smoke", {"tags": []})
        self.assertIn("bad provider", str(cm.exception))
        self.assertNotIn(settings.ignition_api_key, str(cm.exception))

    def test_raises_GatewayError_on_500(self) -> None:
        from ignition_gen_sdk.backends.api_client import GatewayError

        client, settings = self._client_with_status(503, "down")
        with self.assertRaises(GatewayError) as cm:
            client.import_tags("default", "Smoke", {"tags": []})
        self.assertNotIn(settings.ignition_api_key, str(cm.exception))

    def test_returns_diagnostics_on_200(self) -> None:
        from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

        settings = _settings()

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/data/api/v1/tags/import")
            params = dict(request.url.params)
            self.assertEqual(params["provider"], "default")
            self.assertEqual(params["type"], "json")
            self.assertEqual(params["collisionPolicy"], "MergeOverwrite")
            self.assertEqual(params["path"], "Smoke")
            return httpx.Response(200, json=[])

        client = IgnitionAPIClient(settings)
        client._client._transport = httpx.MockTransport(handler)
        result = client.import_tags("default", "Smoke", {"tags": []})
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
