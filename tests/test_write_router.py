"""WriteRouter tests.

Covers static backend map dispatch, dry-run JSON-to-stdout, per-call
override (api/disk/auto), and the auto-fallback policy:
- GatewayError (5xx) → fall back to disk
- PayloadError (400) → surface to caller (programmer error, not transient)
- AuthMissingError / AuthScopeError → surface to caller
- Invalid backend choice → ValueError
"""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch


class TestRouterImports(unittest.TestCase):
    def test_module_importable(self) -> None:
        from ignition_gen_sdk.backends import router  # noqa: F401

    def test_class_present(self) -> None:
        from ignition_gen_sdk.backends.router import WriteRouter  # noqa: F401


def _make_tag():
    from ignition_gen_sdk.models.tags.tag import Tag

    return Tag(
        name="T1",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
    )


class TestDryRun(unittest.TestCase):
    def test_dry_run_prints_provider_root_envelope(self) -> None:
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        disk = MagicMock()
        router = WriteRouter(api, disk)

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = router.push_tags("default", "", [_make_tag()], dry_run=True)

        self.assertEqual(result, [])
        api.import_tags.assert_not_called()
        disk.write_tags.assert_not_called()

        output = captured.getvalue()
        parsed = json.loads(output)
        self.assertEqual(parsed["tagType"], "Provider")
        self.assertEqual(parsed["name"], "")
        self.assertEqual(len(parsed["tags"]), 1)
        self.assertEqual(parsed["tags"][0]["name"], "T1")


class TestExplicitBackends(unittest.TestCase):
    def test_backend_api_calls_api_only(self) -> None:
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        api.import_tags.return_value = {"successCount": 1}
        disk = MagicMock()
        router = WriteRouter(api, disk)

        result = router.push_tags("default", "Smoke", [_make_tag()], backend="api")

        api.import_tags.assert_called_once()
        disk.write_tags.assert_not_called()
        # Result is whatever api returned.
        self.assertEqual(result["successCount"], 1)

    def test_backend_disk_calls_disk_only(self) -> None:
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        disk = MagicMock()
        router = WriteRouter(api, disk)

        result = router.push_tags(
            "default", "Smoke", [_make_tag()], backend="disk"
        )

        disk.write_tags.assert_called_once()
        api.import_tags.assert_not_called()
        # Disk path returns [] (no diagnostics from disk writes).
        self.assertEqual(result, [])

    def test_backend_api_passes_collision_policy(self) -> None:
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        api.import_tags.return_value = []
        disk = MagicMock()
        router = WriteRouter(api, disk)

        router.push_tags(
            "default", "Smoke", [_make_tag()], backend="api",
            collision_policy="Abort",
        )

        # Inspect call args
        call = api.import_tags.call_args
        # signature: import_tags(provider, path, payload, collision_policy)
        self.assertEqual(call.args[0], "default")
        self.assertEqual(call.args[1], "Smoke")
        self.assertEqual(call.args[3], "Abort")


class TestAutoFallback(unittest.TestCase):
    def test_auto_gateway_error_falls_back_to_disk(self) -> None:
        """The auto fallback writes to disk AND signals
        the fallback by raising AutoFallbackToDisk (inherits from
        GatewayError). Previously this silently returned [] which made
        _print_diagnostics report "Push successful" -- hiding both the
        gateway 5xx and the on-disk state."""
        from pathlib import Path
        from ignition_gen_sdk.backends.api_client import GatewayError
        from ignition_gen_sdk.backends.router import (
            AutoFallbackToDisk, WriteRouter,
        )

        api = MagicMock()
        api.import_tags.side_effect = GatewayError("500 Internal Server Error")
        disk = MagicMock()
        disk.write_tags.return_value = Path("/tmp/dest")
        router = WriteRouter(api, disk)

        with self.assertRaises(AutoFallbackToDisk) as cm:
            router.push_tags(
                "default", "Smoke", [_make_tag()], backend="auto"
            )

        api.import_tags.assert_called_once()
        disk.write_tags.assert_called_once()
        # AutoFallbackToDisk carries the disk path + the underlying gateway error.
        self.assertEqual(cm.exception.disk_path, Path("/tmp/dest"))
        self.assertIsInstance(cm.exception.gateway_error, GatewayError)
        # And inherits from GatewayError so existing handlers still catch it.
        self.assertIsInstance(cm.exception, GatewayError)

    def test_auto_payload_error_does_not_fall_back(self) -> None:
        from ignition_gen_sdk.backends.api_client import PayloadError
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        api.import_tags.side_effect = PayloadError("400 Bad Request: bad shape")
        disk = MagicMock()
        router = WriteRouter(api, disk)

        with self.assertRaises(PayloadError):
            router.push_tags("default", "Smoke", [_make_tag()], backend="auto")

        # Disk MUST NOT have been called.
        disk.write_tags.assert_not_called()

    def test_auto_auth_missing_does_not_fall_back(self) -> None:
        from ignition_gen_sdk.backends.api_client import AuthMissingError
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        api.import_tags.side_effect = AuthMissingError("401")
        disk = MagicMock()
        router = WriteRouter(api, disk)

        with self.assertRaises(AuthMissingError):
            router.push_tags("default", "Smoke", [_make_tag()], backend="auto")
        disk.write_tags.assert_not_called()

    def test_auto_auth_scope_does_not_fall_back(self) -> None:
        from ignition_gen_sdk.backends.api_client import AuthScopeError
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        api.import_tags.side_effect = AuthScopeError("403")
        disk = MagicMock()
        router = WriteRouter(api, disk)

        with self.assertRaises(AuthScopeError):
            router.push_tags("default", "Smoke", [_make_tag()], backend="auto")
        disk.write_tags.assert_not_called()

    def test_auto_success_returns_api_result_no_disk(self) -> None:
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        api.import_tags.return_value = {"successCount": 2, "failureCount": 0}
        disk = MagicMock()
        router = WriteRouter(api, disk)

        result = router.push_tags(
            "default", "Smoke", [_make_tag()], backend="auto"
        )

        self.assertEqual(result["successCount"], 2)
        disk.write_tags.assert_not_called()


class TestInvalidBackend(unittest.TestCase):
    def test_invalid_backend_raises_value_error(self) -> None:
        from ignition_gen_sdk.backends.router import WriteRouter

        api = MagicMock()
        disk = MagicMock()
        router = WriteRouter(api, disk)

        with self.assertRaises(ValueError):
            router.push_tags(
                "default", "Smoke", [_make_tag()], backend="invalid"
            )


class TestBackendMap(unittest.TestCase):
    """The static resource-type map is part of the public contract."""

    def test_default_map_contains_tag_import(self) -> None:
        from ignition_gen_sdk.backends.router import _DEFAULT_BACKEND

        self.assertEqual(_DEFAULT_BACKEND["tag_import"], "api")

    def test_default_map_contains_tag_definition_disk(self) -> None:
        from ignition_gen_sdk.backends.router import _DEFAULT_BACKEND

        self.assertEqual(_DEFAULT_BACKEND["tag_definition_disk"], "disk")

    def test_default_map_contains_perspective_view(self) -> None:
        from ignition_gen_sdk.backends.router import _DEFAULT_BACKEND

        self.assertEqual(_DEFAULT_BACKEND["perspective_view"], "disk")


if __name__ == "__main__":
    unittest.main()
