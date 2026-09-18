"""Settings.openapi_spec_path + new exception classes.

Behavior contracts:
- Settings exposes `openapi_spec_path: Path` with default
  `<state-dir>/openapi.json` (state dir defaults to ./.ign).
- Env override via IGNITION_OPENAPI_SPEC_PATH works.
- Settings __repr__ still masks api_key as [REDACTED] (unchanged behavior).
- UnknownPathError + MethodNotAllowedError importable from api_client.
- Both inherit from IgnitionAPIError (so existing taxonomy catch blocks see them).
- Default str(exc) is the message passed in.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _add_pkg_path() -> None:
    here = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(here))


_add_pkg_path()


class TestSettingsOpenAPISpecPath(unittest.TestCase):
    def test_default_path_points_at_workspace_spec(self) -> None:
        with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:test-secret-token-DO-NOT-LEAK"}, clear=False):
            os.environ.pop("IGNITION_OPENAPI_SPEC_PATH", None)
            from ignition_gen_sdk.config import Settings

            s = Settings()
            self.assertEqual(s.openapi_spec_path, s.ignition_state_dir / "openapi.json")
            self.assertEqual(s.ignition_state_dir.name, ".ign")

    def test_env_override_via_IGNITION_OPENAPI_SPEC_PATH(self) -> None:
        with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:test-secret-token-DO-NOT-LEAK", "IGNITION_OPENAPI_SPEC_PATH": "/tmp/some/custom/spec.json"}, clear=False):
            from ignition_gen_sdk.config import Settings

            s = Settings()
            self.assertEqual(
                str(s.openapi_spec_path), "/tmp/some/custom/spec.json"
            )

    def test_repr_still_redacts_token_unchanged(self) -> None:
        with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:test-secret-token-DO-NOT-LEAK"}, clear=False):
            os.environ.pop("IGNITION_OPENAPI_SPEC_PATH", None)
            from ignition_gen_sdk.config import Settings

            s = Settings()
            r = repr(s)
            self.assertIn("REDACTED", r)
            self.assertNotIn("test-secret-token-DO-NOT-LEAK", r)


class TestNewExceptionClasses(unittest.TestCase):
    def test_UnknownPathError_subclass_of_IgnitionAPIError(self) -> None:
        from ignition_gen_sdk.backends.api_client import (
            IgnitionAPIError,
            UnknownPathError,
        )

        self.assertTrue(issubclass(UnknownPathError, IgnitionAPIError))
        self.assertTrue(issubclass(UnknownPathError, Exception))

    def test_MethodNotAllowedError_subclass_of_IgnitionAPIError(self) -> None:
        from ignition_gen_sdk.backends.api_client import (
            IgnitionAPIError,
            MethodNotAllowedError,
        )

        self.assertTrue(issubclass(MethodNotAllowedError, IgnitionAPIError))
        self.assertTrue(issubclass(MethodNotAllowedError, Exception))

    def test_UnknownPathError_message_default_behavior(self) -> None:
        from ignition_gen_sdk.backends.api_client import UnknownPathError

        exc = UnknownPathError("path '/foo' not in openapi.json")
        self.assertEqual(str(exc), "path '/foo' not in openapi.json")

    def test_MethodNotAllowedError_message_default_behavior(self) -> None:
        from ignition_gen_sdk.backends.api_client import MethodNotAllowedError

        exc = MethodNotAllowedError("DELETE not allowed on /foo")
        self.assertEqual(str(exc), "DELETE not allowed on /foo")


if __name__ == "__main__":
    unittest.main()
