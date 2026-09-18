"""OpenAPI path resolver + _errors.py extension.

Behavior contracts:
- load_spec(settings) reads + parses settings.openapi_spec_path once;
  subsequent calls with same settings return identical dict object (cache).
- resolve_path_against_spec(settings, "GET", "/data/api/v1/gateway-info")
  returns None.
- resolve_path_against_spec(settings, "POST", "/data/api/v1/scan/config")
  returns None.
- DELETE /gateway-info → MethodNotAllowedError.
- GET /no/such/path → UnknownPathError.
- GET /data/api/v1/resources/find/ignition/tag-provider/default → None
  (matches template /...{name}).
- GET literal /foo/{name} (unsubstituted template) → UnknownPathError.
- Method comparison case-insensitive.
- render_error(UnknownPathError("x")) prints "Path error:" label + hint.
- render_error(MethodNotAllowedError("y")) prints "Method error:" + hint.

Light validation runs against the LIVE openapi.json (551 paths) -- the
spec is the source of truth being validated, do NOT mock it.
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


def _settings():
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:sentinel-not-used-in-resolver"}, clear=False):
        from ignition_gen_sdk.config import Settings

        return Settings()


class TestLoadSpec(unittest.TestCase):
    def test_returns_dict_with_paths_key(self) -> None:
        from ignition_gen_sdk.cli._openapi_resolver import load_spec

        s = _settings()
        spec = load_spec(s)
        self.assertIsInstance(spec, dict)
        self.assertIn("paths", spec)
        # Sanity: the live spec has many paths.
        self.assertGreater(len(spec["paths"]), 100)

    def test_cache_identity_same_settings(self) -> None:
        from ignition_gen_sdk.cli._openapi_resolver import load_spec

        s = _settings()
        spec1 = load_spec(s)
        spec2 = load_spec(s)
        # Module-level cache keyed by resolved Path -- same dict object.
        self.assertIs(spec1, spec2)


class TestResolvePathAgainstSpec(unittest.TestCase):
    def test_GET_gateway_info_passes(self) -> None:
        from ignition_gen_sdk.cli._openapi_resolver import (
            resolve_path_against_spec,
        )

        s = _settings()
        # Sanity: present path; this MUST exist in the live spec.
        result = resolve_path_against_spec(
            s, "GET", "/data/api/v1/gateway-info"
        )
        self.assertIsNone(result)

    def test_POST_scan_config_passes(self) -> None:
        from ignition_gen_sdk.cli._openapi_resolver import (
            resolve_path_against_spec,
        )

        s = _settings()
        result = resolve_path_against_spec(
            s, "POST", "/data/api/v1/scan/config"
        )
        self.assertIsNone(result)

    def test_unknown_path_raises_UnknownPathError(self) -> None:
        from ignition_gen_sdk.backends.api_client import UnknownPathError
        from ignition_gen_sdk.cli._openapi_resolver import (
            resolve_path_against_spec,
        )

        s = _settings()
        with self.assertRaises(UnknownPathError):
            resolve_path_against_spec(s, "GET", "/no/such/path")

    def test_method_not_allowed_raises_MethodNotAllowedError(self) -> None:
        from ignition_gen_sdk.backends.api_client import MethodNotAllowedError
        from ignition_gen_sdk.cli._openapi_resolver import (
            resolve_path_against_spec,
        )

        s = _settings()
        # /gateway-info is GET-only in the live spec.
        with self.assertRaises(MethodNotAllowedError):
            resolve_path_against_spec(
                s, "DELETE", "/data/api/v1/gateway-info"
            )

    def test_template_substitution_matches_provider_resource(self) -> None:
        from ignition_gen_sdk.cli._openapi_resolver import (
            resolve_path_against_spec,
        )

        s = _settings()
        # Spec key is /data/api/v1/resources/find/ignition/tag-provider/{name}
        # User passes a concrete value; resolver must match the template.
        result = resolve_path_against_spec(
            s,
            "GET",
            "/data/api/v1/resources/find/ignition/tag-provider/default",
        )
        self.assertIsNone(result)

    def test_unsubstituted_template_literal_rejected(self) -> None:
        from ignition_gen_sdk.backends.api_client import UnknownPathError
        from ignition_gen_sdk.cli._openapi_resolver import (
            resolve_path_against_spec,
        )

        s = _settings()
        # User passes the literal template -- this must be rejected so they
        # supply the concrete value.
        with self.assertRaises(UnknownPathError):
            resolve_path_against_spec(
                s,
                "GET",
                "/data/api/v1/resources/find/ignition/tag-provider/{name}",
            )

    def test_method_case_insensitive(self) -> None:
        from ignition_gen_sdk.cli._openapi_resolver import (
            resolve_path_against_spec,
        )

        s = _settings()
        # Lowercase "get" should match the same operation as "GET".
        result_lower = resolve_path_against_spec(
            s, "get", "/data/api/v1/gateway-info"
        )
        result_upper = resolve_path_against_spec(
            s, "GET", "/data/api/v1/gateway-info"
        )
        self.assertIsNone(result_lower)
        self.assertIsNone(result_upper)


class TestRenderErrorPath(unittest.TestCase):
    def test_render_UnknownPathError_label_and_hint(self) -> None:
        import io
        import contextlib

        from ignition_gen_sdk.backends.api_client import UnknownPathError
        from ignition_gen_sdk.cli._errors import render_error

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            render_error(UnknownPathError("not in spec"), no_color=True)
        out = buf.getvalue()
        self.assertIn("Path error:", out)
        self.assertIn("not in spec", out)
        self.assertIn("Hint:", out)
        self.assertIn("openapi.json", out)

    def test_render_MethodNotAllowedError_label_and_hint(self) -> None:
        import io
        import contextlib

        from ignition_gen_sdk.backends.api_client import MethodNotAllowedError
        from ignition_gen_sdk.cli._errors import render_error

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            render_error(
                MethodNotAllowedError("DELETE on /gateway-info"),
                no_color=True,
            )
        out = buf.getvalue()
        self.assertIn("Method error:", out)
        self.assertIn("DELETE on /gateway-info", out)
        self.assertIn("Hint:", out)


if __name__ == "__main__":
    unittest.main()
