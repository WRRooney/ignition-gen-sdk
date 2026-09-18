"""Tests for ``ign theme`` — the sanctioned writer for Perspective themes.

Themes were the last Perspective resource with no ign verb, so a new theme
could not be created without a banned hand-write under ``config/resources/**``.

The load-bearing behaviour under test:
  - the resource lands at the layered config path the gateway reads, with a
    generated ``config.json`` (entrypoint) and ``resource.json`` (scope "G",
    every file manifested — an unlisted file is a file the gateway never loads);
  - an ``--entrypoint`` that is not among the supplied files is refused, because
    the gateway would otherwise serve a theme that renders nothing;
  - ``light`` / ``dark`` are refused: ``copy-base`` materializes them so they can
    be read, but the gateway ignores edits to a copied base theme, so a write
    there is a silent no-op — exactly the failure a loud error prevents;
  - a traversal name cannot escape the themes directory.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_THEMES = "config/resources/core/com.inductiveautomation.perspective/themes"


def _runner():
    from typer.testing import CliRunner

    return CliRunner()


def _invoke(root: Path, args: list[str]):
    with patch.dict(
        os.environ,
        {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)},
        clear=False,
    ):
        from ignition_gen_sdk.cli import app

        return _runner().invoke(app, args)


def _src(root: Path, **files: str) -> Path:
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in (files or {"index.css": "@import '../dark/index.css';"}).items():
        (src / name).write_text(text, encoding="utf-8")
    return src


class TestThemeWrite(unittest.TestCase):
    def test_writes_files_config_and_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _src(
                root,
                **{
                    "index.css": '@import "./variables.css";\n',
                    "variables.css": ":root { --symbolFill--running: #FFF; }\n",
                },
            )
            res = _invoke(
                root,
                ["theme", "write", "--name", "dark-signal", "--dir", str(src), "--no-scan"],
            )
            self.assertEqual(res.exit_code, 0, res.output)

            dest = root / _THEMES / "dark-signal"
            self.assertTrue((dest / "index.css").is_file())
            self.assertIn("--symbolFill--running", (dest / "variables.css").read_text())

            cfg = json.loads((dest / "config.json").read_text())
            self.assertEqual(cfg, {"entrypoint": "index.css", "isPrivate": False})

            meta = json.loads((dest / "resource.json").read_text())
            self.assertEqual(meta["scope"], "G")
            self.assertEqual(
                meta["files"], ["config.json", "index.css", "variables.css"]
            )

    def test_rewrite_restamps_lastmodification(self):
        """A rewrite MUST change resource.json's lastModification stamp.

        Perspective compiles a theme on first use and keys the result on the
        theme NAME. Without a changed stamp the config layer does not treat the
        rewrite as a change, the cached CSS keeps being served, and the new
        colors never reach a client — a silent no-op that looks exactly like a
        broken stylesheet. Verified live: the identical CSS under a fresh theme
        name rendered correctly while the rewritten name did not.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _src(root, **{"index.css": ":root { --a: red; }\n"})
            args = ["theme", "write", "--name", "r-signal", "--dir", str(src), "--no-scan"]
            self.assertEqual(_invoke(root, args).exit_code, 0)
            meta = json.loads((root / _THEMES / "r-signal" / "resource.json").read_text())
            first = meta["attributes"]["lastModification"]
            self.assertEqual(first["actor"], "ign")

            (src / "index.css").write_text(":root { --a: blue; }\n", encoding="utf-8")
            self.assertEqual(_invoke(root, args).exit_code, 0)
            dest = root / _THEMES / "r-signal"
            self.assertIn("blue", (dest / "index.css").read_text())
            second = json.loads((dest / "resource.json").read_text())["attributes"]
            self.assertEqual(second["lastModification"]["actor"], "ign")
            self.assertRegex(
                second["lastModification"]["timestamp"],
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            )

    def test_entrypoint_must_be_among_the_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _src(root, **{"variables.css": ":root {}\n"})
            res = _invoke(
                root,
                ["theme", "write", "--name", "x-signal", "--dir", str(src), "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1, res.output)
            self.assertIn("entrypoint", res.output)
            self.assertFalse((root / _THEMES / "x-signal").exists())

    def test_base_theme_names_are_refused(self):
        for name in ("light", "dark"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src = _src(root, **{"index.css": "/* x */\n"})
                res = _invoke(
                    root,
                    ["theme", "write", "--name", name, "--dir", str(src), "--no-scan"],
                )
                self.assertEqual(res.exit_code, 1, res.output)
                self.assertIn("BASE theme", res.output)

    def test_traversal_name_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _src(root, **{"index.css": "/* x */\n"})
            res = _invoke(
                root,
                ["theme", "write", "--name", "..", "--dir", str(src), "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1, res.output)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _src(root, **{"index.css": "/* x */\n"})
            res = _invoke(
                root,
                ["theme", "write", "--name", "y-signal", "--dir", str(src), "--dry-run"],
            )
            self.assertEqual(res.exit_code, 0, res.output)
            self.assertFalse((root / _THEMES / "y-signal").exists())


class TestThemeListDelete(unittest.TestCase):
    def test_list_then_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _src(root, **{"index.css": "/* x */\n"})
            _invoke(root, ["theme", "write", "--name", "z-signal", "--dir", str(src), "--no-scan"])

            res = _invoke(root, ["theme", "list"])
            self.assertEqual(res.exit_code, 0, res.output)
            self.assertIn("z-signal", res.output)

            res = _invoke(root, ["theme", "delete", "--name", "z-signal", "--no-scan"])
            self.assertEqual(res.exit_code, 0, res.output)
            self.assertFalse((root / _THEMES / "z-signal").exists())

    def test_delete_missing_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            res = _invoke(root, ["theme", "delete", "--name", "nope", "--no-scan"])
            self.assertEqual(res.exit_code, 1, res.output)

    def test_list_flags_base_copies_as_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / _THEMES / "dark"
            base.mkdir(parents=True)
            (base / "config.json").write_text("{}")
            res = _invoke(root, ["theme", "list"])
            self.assertEqual(res.exit_code, 0, res.output)
            self.assertIn("edits ignored", res.output)


class TestThemeScan(unittest.TestCase):
    def test_write_scans_config_not_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _src(root, **{"index.css": "/* x */\n"})
            with patch("ignition_gen_sdk.cli.cmd_theme.ScanClient") as scan_cls:
                inst = scan_cls.return_value.__enter__.return_value
                res = _invoke(
                    root,
                    ["theme", "write", "--name", "s-signal", "--dir", str(src)],
                )
            self.assertEqual(res.exit_code, 0, res.output)
            inst.scan_config.assert_called_once()


if __name__ == "__main__":
    unittest.main()
