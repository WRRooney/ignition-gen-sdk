"""Tests for ProjectDiskBackend.write_script and ign script write CLI.

Backend tests first, then CLI tests (marked with 'cli').

All tests are self-contained; filesystem writes go to tmp_path only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ignition_gen_sdk.backends.project_disk import (
    ProjectDiskBackend,
    ProjectNotFoundError,
    ScriptTabError,
)
from ignition_gen_sdk.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TAB_CODE = "def buildNavTree(provider='default'):\n\treturn []\n"
SPACE_CODE = "def buildNavTree(provider='default'):\n    return []\n"
SYNTAX_BAD = "def broken(\n"


def _settings_with_root(root: Path) -> Settings:
    return Settings(ignition_data_root=root)


def _make_project_skeleton(root: Path, name: str) -> Path:
    proj = root / "projects" / name
    (proj / "ignition" / "script-python").mkdir(parents=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


# ---------------------------------------------------------------------------
# Backend tests
# ---------------------------------------------------------------------------

def test_write_script_creates_code_py(tmp_path: Path):
    """write_script creates code.py at the correct path."""
    _make_project_skeleton(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_script("Proj", "app/nav", TAB_CODE)
    assert (dest / "code.py").is_file()
    assert (dest / "code.py").read_text() == TAB_CODE


def test_write_script_creates_resource_json_with_scope_a(tmp_path: Path):
    """write_script creates resource.json with scope='A' (not 'G')."""
    _make_project_skeleton(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_script("Proj", "app/nav", TAB_CODE)
    resource = json.loads((dest / "resource.json").read_text())
    assert resource["scope"] == "A"
    assert resource["version"] == 1
    assert resource["restricted"] is False
    assert resource["overridable"] is True
    assert resource["files"] == ["code.py"]
    # hintScope is REQUIRED for the gateway to register the script module
    # (without it project modules never load). Matches a working live example. Signature omitted (gateway computes it on scan).
    assert resource["attributes"]["hintScope"] == 2
    assert resource["attributes"]["lastModification"]["actor"] == "ign"


def test_write_script_correct_path_layout(tmp_path: Path):
    """write_script places code.py under ignition/script-python/<path>/."""
    _make_project_skeleton(tmp_path, "Demo")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_script("Demo", "app/nav", TAB_CODE)
    expected = (
        tmp_path
        / "projects"
        / "Demo"
        / "ignition"
        / "script-python"
        / "app"        / "nav"
    )
    assert dest == expected


def test_write_script_missing_project_raises_project_not_found(tmp_path: Path):
    """ProjectNotFoundError raised when project.json absent (fail-loud rule)."""
    (tmp_path / "projects").mkdir()
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    with pytest.raises(ProjectNotFoundError):
        backend.write_script("Bogus", "app/nav", TAB_CODE)


def test_write_script_layer_guard_raises_on_traversal(tmp_path: Path):
    """ValueError raised if script_path resolves outside _projects_root.

    _split_view_path_segments catches '..' segments first (directory-traversal
    marker check) — the layer guard fires second as defense-in-depth. Both raise
    ValueError; the test accepts either.
    """
    _make_project_skeleton(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    with pytest.raises(ValueError):
        backend.write_script("Proj", "../../../etc/cron.d/evil", TAB_CODE)


def test_write_script_rejects_space_indented_code(tmp_path: Path):
    """ScriptTabError raised for code with any space-indented line."""
    _make_project_skeleton(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    with pytest.raises(ScriptTabError) as exc_info:
        backend.write_script("Proj", "app/nav", SPACE_CODE)
    assert "TAB" in str(exc_info.value)


def test_write_script_accepts_tab_indented_code(tmp_path: Path):
    """TAB-indented code passes validation and is written."""
    _make_project_skeleton(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_script("Proj", "app/nav", TAB_CODE)
    assert (dest / "code.py").read_text() == TAB_CODE


def test_write_script_rejects_syntax_invalid_code(tmp_path: Path):
    """SyntaxError raised for code that fails ast.parse."""
    _make_project_skeleton(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    with pytest.raises(SyntaxError):
        backend.write_script("Proj", "app/nav", SYNTAX_BAD)


def test_write_script_no_disk_write_on_validation_failure(tmp_path: Path):
    """No files written when space-indented code is rejected."""
    _make_project_skeleton(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    with pytest.raises(ScriptTabError):
        backend.write_script("Proj", "app/nav", SPACE_CODE)
    dest = (
        tmp_path / "projects" / "Proj" / "ignition" / "script-python" / "app" / "nav"
    )
    assert not (dest / "code.py").exists()


def test_write_script_non_indented_code_passes_tab_check(tmp_path: Path):
    """Single-line function with no indentation passes TAB check."""
    _make_project_skeleton(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_script("Proj", "app/util", "def hello():\n\tpass\n")
    assert (dest / "code.py").is_file()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def test_cli_dry_run_prints_code_and_target_path(tmp_path: Path):
    """--dry-run prints code.py content and target path without touching disk."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    code_file = tmp_path / "nav.py"
    code_file.write_text(TAB_CODE)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["script", "write", "--project", "Demo", "--script-path", "app/nav",
         "--file", str(code_file), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "=== code.py ===" in result.output
    assert TAB_CODE.strip() in result.output
    assert "=== target path ===" in result.output
    assert "app/nav" in result.output


def test_cli_dry_run_shows_resource_json_with_hintscope(tmp_path: Path):
    """--dry-run must also preview the resource.json — its hintScope:2 is
    what makes the module load. Hiding it defeats the preview."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    code_file = tmp_path / "nav.py"
    code_file.write_text(TAB_CODE)
    result = CliRunner().invoke(
        app,
        ["script", "write", "--project", "Demo", "--script-path", "app/nav",
         "--file", str(code_file), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "=== resource.json ===" in result.output
    assert '"hintScope": 2' in result.output
    assert '"files": [' in result.output and "code.py" in result.output


def test_cli_dry_run_rejects_space_indented_code(tmp_path: Path):
    """--dry-run runs the SAME acceptance gate as a real write — it must
    REJECT space-indented code (previously it silently 'passed')."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    code_file = tmp_path / "spacey.py"
    code_file.write_text("def f(x):\n    return x\n")  # 4-space indent
    result = CliRunner().invoke(
        app,
        ["script", "write", "--project", "Demo", "--script-path", "app/nav",
         "--file", str(code_file), "--dry-run"],
    )
    assert result.exit_code == 1, result.output
    assert "TAB indentation" in result.output


def test_cli_dry_run_no_settings_needed(tmp_path: Path):
    """--dry-run must not require IGNITION_API_TOKEN / Settings()."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    code_file = tmp_path / "nav.py"
    code_file.write_text(TAB_CODE)

    runner = CliRunner(env={})
    # Run with completely empty env — no IGNITION_API_TOKEN
    old_env = {k: os.environ.pop(k) for k in list(os.environ) if k == "IGNITION_API_TOKEN"}
    try:
        result = runner.invoke(
            app,
            ["script", "write", "--project", "Demo", "--script-path", "app/nav",
             "--file", str(code_file), "--dry-run"],
            catch_exceptions=False,
        )
    finally:
        os.environ.update(old_env)
    assert result.exit_code == 0, result.output


def test_cli_space_indented_file_exits_1(tmp_path: Path):
    """Space-indented --file exits code 1 with Error: on stderr."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    _make_project_skeleton(tmp_path, "Demo")
    code_file = tmp_path / "bad.py"
    code_file.write_text(SPACE_CODE)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["script", "write", "--project", "Demo", "--script-path", "app/nav",
         "--file", str(code_file), "--no-scan"],
        env={
            "IGNITION_API_TOKEN": "test:test",
            "IGNITION_DATA_DIR": str(tmp_path),
        },
    )
    assert result.exit_code == 1
    combined = (result.output or "") + (result.stderr or "")
    assert "Error" in combined or "error" in combined.lower()


def test_cli_syntax_invalid_file_exits_1(tmp_path: Path):
    """Syntax-invalid --file exits code 1 with Error: on stderr."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    _make_project_skeleton(tmp_path, "Demo")
    code_file = tmp_path / "bad.py"
    code_file.write_text(SYNTAX_BAD)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["script", "write", "--project", "Demo", "--script-path", "app/nav",
         "--file", str(code_file), "--no-scan"],
        env={
            "IGNITION_API_TOKEN": "test:test",
            "IGNITION_DATA_DIR": str(tmp_path),
        },
    )
    assert result.exit_code == 1
    combined = (result.output or "") + (result.stderr or "")
    assert "Error" in combined or "error" in combined.lower()


def test_cli_successful_write_prints_written_paths(tmp_path: Path):
    """Successful write prints 'Written: .../code.py' and 'Written: .../resource.json'."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    _make_project_skeleton(tmp_path, "Demo")
    code_file = tmp_path / "nav.py"
    code_file.write_text(TAB_CODE)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["script", "write", "--project", "Demo", "--script-path", "app/nav",
         "--file", str(code_file), "--no-scan"],
        env={
            "IGNITION_API_TOKEN": "test:test",
            "IGNITION_DATA_DIR": str(tmp_path),
        },
    )
    assert result.exit_code == 0, result.output
    assert "Written:" in result.output
    assert "code.py" in result.output
    assert "resource.json" in result.output


def test_cli_help_shows_write_subcommand(tmp_path: Path):
    """ign script --help lists the write subcommand."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["script", "--help"])
    assert result.exit_code == 0
    assert "write" in result.output


def test_cli_scan_called_after_successful_write(tmp_path: Path):
    """After successful write, scan_projects is called (mocked)."""
    from unittest.mock import patch, MagicMock
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    _make_project_skeleton(tmp_path, "Demo")
    code_file = tmp_path / "nav.py"
    code_file.write_text(TAB_CODE)

    mock_scan = MagicMock()
    mock_scan.__enter__ = MagicMock(return_value=mock_scan)
    mock_scan.__exit__ = MagicMock(return_value=False)

    runner = CliRunner()
    with patch("ignition_gen_sdk.cli.cmd_script.ScanClient", return_value=mock_scan):
        result = runner.invoke(
            app,
            ["script", "write", "--project", "Demo", "--script-path", "app/nav",
             "--file", str(code_file)],
            env={
                "IGNITION_API_TOKEN": "test:test",
                "IGNITION_DATA_DIR": str(tmp_path),
            },
        )
    assert result.exit_code == 0, result.output
    mock_scan.scan_projects.assert_called_once()
