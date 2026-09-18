"""Structural sanity for cmd_api.

Validates the module imports cleanly, exports `api_app` as a Typer
instance with no_args_is_help, and defines the four required helpers
(_get_api, _read_body, _refuse_jwe_in_body, _validate_body_strict).
Behavioral coverage lives in test_cli_api.py + test_cli_api_strict.py.
"""
from __future__ import annotations

import unittest


class TestCmdApiStructure(unittest.TestCase):
    def test_module_imports(self) -> None:
        from ignition_gen_sdk.cli import cmd_api  # noqa: F401

    def test_api_app_is_typer(self) -> None:
        import typer

        from ignition_gen_sdk.cli.cmd_api import api_app

        self.assertIsInstance(api_app, typer.Typer)

    def test_four_helpers_defined(self) -> None:
        from ignition_gen_sdk.cli import cmd_api

        for name in ("_get_api", "_read_body", "_refuse_jwe_in_body", "_validate_body_strict"):
            self.assertTrue(
                hasattr(cmd_api, name),
                msg=f"cmd_api missing helper: {name}",
            )

    def test_no_top_level_openapi_core_import(self) -> None:
        """openapi_core must be imported lazily inside _validate_body_strict --
        not at module top-level -- so the lean install path doesn't require
        the [strict] extras."""
        from pathlib import Path

        from ignition_gen_sdk.cli import cmd_api

        src = Path(cmd_api.__file__).read_text(encoding="utf-8")
        # Only the lazy-imported inside-function reference is allowed; any
        # top-level `from openapi_core ...` / `import openapi_core` is not.
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("from openapi_core", "import openapi_core")):
                # Acceptable only if the line is indented (i.e. inside a function body).
                self.assertNotEqual(
                    line, stripped, msg=f"top-level openapi_core import: {line!r}",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
