"""Tests for the ign view CLI subcommand."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


def _runner():
    from typer.testing import CliRunner
    # Typer 0.25.x / Click 8.2+ — CliRunner separates stdout/stderr automatically.
    # The mix_stderr kwarg was removed when Click 8.2 made stderr separate by default.
    return CliRunner()


class TestCliWiring(unittest.TestCase):
    def test_top_level_help_lists_view_subcommand(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("view", result.output)
        # Existing tag subcommand still listed (no regression)
        self.assertIn("tag", result.output)

    def test_view_help_lists_build_and_write(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["view", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("build", result.output)
        self.assertIn("write", result.output)


class TestViewBuild(unittest.TestCase):
    def test_build_emits_valid_json(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["view", "build"])
        self.assertEqual(result.exit_code, 0, msg=result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["root"]["type"], "ia.container.flex")
        self.assertEqual(len(data["root"]["children"]), 1)
        self.assertEqual(data["root"]["children"][0]["type"], "ia.display.label")


class TestViewWriteRequiredFlags(unittest.TestCase):
    def test_write_without_any_flags_fails(self):
        """--project is required."""
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["view", "write"])
        self.assertNotEqual(result.exit_code, 0)

    def test_write_without_project_fails(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["view", "write", "--view-path", "Foo"])
        self.assertNotEqual(result.exit_code, 0)
        # Typer prints missing-option error to stderr; "project" appears in the message
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("project", combined.lower())

    def test_write_without_view_path_fails(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["view", "write", "--project", "Global"])
        self.assertNotEqual(result.exit_code, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("view-path", combined.lower())


class TestViewWriteDryRun(unittest.TestCase):
    def test_dry_run_emits_three_delimited_blocks(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(
            app,
            ["view", "write", "--project", "Anything", "--view-path", "X/Y", "--dry-run"],
        )
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        self.assertIn("=== view.json ===", result.stdout)
        self.assertIn("=== resource.json ===", result.stdout)
        self.assertIn("=== target path ===", result.stdout)
        self.assertIn("projects/Anything/com.inductiveautomation.perspective/views/X/Y/", result.stdout)

    def test_dry_run_does_not_touch_filesystem(self, tmp_path: Path = None):
        """Dry run must not call ProjectDiskBackend.write_view (so the project check doesn't fire either)."""
        from ignition_gen_sdk.cli import app
        # Use a project name that definitely doesn't exist on the host:
        result = _runner().invoke(
            app,
            ["view", "write", "--project", "NonexistentProj_xyz123", "--view-path", "Z", "--dry-run"],
        )
        # Dry-run skips the skeleton check — must succeed even without project on disk
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))


class TestViewWriteFailLoud(unittest.TestCase):
    def test_write_to_missing_project_fails_loud(self):
        """ProjectNotFoundError → stderr + exit 1."""
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(
            app,
            ["view", "write", "--project", "DefinitelyNotAProj_xyz123", "--view-path", "Z", "--no-dry-run"],
        )
        self.assertEqual(result.exit_code, 1)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("Designer first", combined)


class TestViewWriteRejectsEmptyOnDryRun(unittest.TestCase):
    """Empty --view-path must be rejected BEFORE dry-run branch.

    If validation runs after the `if dry_run:` early return, a user
    could pass `--view-path "" --dry-run` and get a printed payload
    with an invalid target path. Validation MUST be first.
    """

    def test_write_rejects_empty_view_path_even_on_dry_run(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(
            app,
            ["view", "write", "--project", "SmokeProj", "--view-path", "", "--dry-run"],
        )
        self.assertNotEqual(
            result.exit_code,
            0,
            msg=(
                "empty --view-path must be rejected even on dry-run; got exit_code=0 "
                "with output: " + (result.output or "")
            ),
        )
        combined = (result.output or "") + (getattr(result, "stderr", "") or "")
        self.assertIn(
            "view-path",
            combined.lower(),
            msg="stderr must mention 'view-path'; got: " + combined,
        )


class TestViewWriteDryRunRejectsTraversal(unittest.TestCase):
    """Traversal segments must be rejected on dry-run, not just
    on no-dry-run.

    Pre-fix behavior: ``--view-path '../../escape' --dry-run`` exited 0
    and printed a misleading ``target path`` line — even though the same
    command without ``--dry-run`` raised ValueError. Dry-run validation
    must match no-dry-run validation, byte-for-byte.
    """

    def _assert_rejected(self, view_path: str) -> None:
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(
            app,
            ["view", "write", "--project", "SmokeProj", "--view-path", view_path, "--dry-run"],
        )
        self.assertNotEqual(
            result.exit_code,
            0,
            msg=(
                f"dry-run must reject {view_path!r} with exit != 0; "
                f"got exit_code=0 with output: " + (result.output or "")
            ),
        )
        combined = (result.output or "") + (getattr(result, "stderr", "") or "")
        self.assertIn(
            "view-path",
            combined.lower(),
            msg=f"stderr must mention 'view-path'; got: {combined}",
        )
        # The misleading "target path" block from the pre-fix print path
        # must NOT appear when validation rejects the input.
        self.assertNotIn("=== target path ===", result.output or "")

    def test_dry_run_rejects_double_dot_segment(self):
        self._assert_rejected("../../escape")

    def test_dry_run_rejects_inner_double_dot_segment(self):
        self._assert_rejected("foo/../../escape")

    def test_dry_run_rejects_single_dot_segment(self):
        self._assert_rejected("./Hidden")

    def test_dry_run_rejects_whitespace_only_segments(self):
        self._assert_rejected("/   / ")


# ----------------------------------------------------------------------------
# Post-write scan wiring: ign view write -> POST /scan/projects, with --no-scan
# ----------------------------------------------------------------------------


def _make_full_project_skeleton(root: Path, name: str = "Global") -> Path:
    """Build a project skeleton including the perspective views/ subtree."""
    proj = root / "projects" / name
    (proj / "com.inductiveautomation.perspective" / "views").mkdir(parents=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


class _RecordingScanClient:
    """Stand-in for ScanClient. Records every scan_*() call and any kwargs the
    CLI used to construct it. ``instances`` is a class-level reset point that
    each test must clear before invoking the runner."""

    instances: "list[_RecordingScanClient]" = []

    def __init__(self, settings, *, timeout: float = 5.0, **_kwargs):  # noqa: D401
        self.calls: list[str] = []
        self._settings = settings
        self._timeout = timeout
        _RecordingScanClient.instances.append(self)

    def scan_projects(self) -> None:
        self.calls.append("scan_projects")

    def scan_config(self) -> None:
        self.calls.append("scan_config")

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _RaisingScanClient(_RecordingScanClient):
    """ScanClient stand-in that raises ScanWarning on every scan_projects()."""

    def scan_projects(self) -> None:
        from ignition_gen_sdk.backends.scan_client import ScanWarning
        self.calls.append("scan_projects")
        raise ScanWarning(
            "scan POST /data/api/v1/scan/projects failed: ConnectError: refused"
        )


class TestViewWriteScanIntegration(unittest.TestCase):
    """Post-write POST /scan/projects, suppressed by --no-scan, never
    on --dry-run, WARNING-on-failure with exit code 0."""

    def setUp(self):  # noqa: D401
        _RecordingScanClient.instances = []

    def _patch(self, monkeypatch, cls):
        import ignition_gen_sdk.cli.cmd_view as cmd_view
        monkeypatch.setattr(cmd_view, "ScanClient", cls)

    def test_write_invokes_scan_projects_after_successful_disk_write(self):
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            self._patch(mp, _RecordingScanClient)
            import tempfile
            from ignition_gen_sdk.cli import app
            with tempfile.TemporaryDirectory() as tdir:
                tdir_path = Path(tdir)
                _make_full_project_skeleton(tdir_path, "Global")
                mp.setenv("IGNITION_DATA_DIR", str(tdir_path))
                result = _runner().invoke(
                    app,
                    ["view", "write", "--project", "Global",
                     "--view-path", "Main/Overview", "--no-dry-run"],
                )
                self.assertEqual(
                    result.exit_code, 0,
                    msg=(result.stdout or "") + (result.stderr or ""),
                )
                # File on disk
                dest = (tdir_path / "projects" / "Global"
                        / "com.inductiveautomation.perspective"
                        / "views" / "Main" / "Overview")
                self.assertTrue((dest / "view.json").is_file())
                # scan_projects called exactly once
                self.assertEqual(len(_RecordingScanClient.instances), 1)
                self.assertEqual(
                    _RecordingScanClient.instances[0].calls,
                    ["scan_projects"],
                )

    def test_write_no_scan_flag_suppresses_scan_call(self):
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            self._patch(mp, _RecordingScanClient)
            import tempfile
            from ignition_gen_sdk.cli import app
            with tempfile.TemporaryDirectory() as tdir:
                tdir_path = Path(tdir)
                _make_full_project_skeleton(tdir_path, "Global")
                mp.setenv("IGNITION_DATA_DIR", str(tdir_path))
                result = _runner().invoke(
                    app,
                    ["view", "write", "--project", "Global",
                     "--view-path", "Main/Overview", "--no-dry-run", "--no-scan"],
                )
                self.assertEqual(
                    result.exit_code, 0,
                    msg=(result.stdout or "") + (result.stderr or ""),
                )
                dest = (tdir_path / "projects" / "Global"
                        / "com.inductiveautomation.perspective"
                        / "views" / "Main" / "Overview")
                self.assertTrue((dest / "view.json").is_file())
                # zero instances OR no scan_projects call
                total_calls = sum(
                    len(i.calls) for i in _RecordingScanClient.instances
                )
                self.assertEqual(total_calls, 0)

    def test_write_dry_run_never_scans_regardless_of_flag(self):
        import pytest
        from ignition_gen_sdk.cli import app
        for flag in ["--scan", "--no-scan"]:
            with pytest.MonkeyPatch.context() as mp:
                _RecordingScanClient.instances = []
                self._patch(mp, _RecordingScanClient)
                result = _runner().invoke(
                    app,
                    ["view", "write", "--project", "Global",
                     "--view-path", "Main/Overview", "--dry-run", flag],
                )
                self.assertEqual(
                    result.exit_code, 0,
                    msg=f"dry-run + {flag} should exit 0: "
                        + (result.stdout or "") + (result.stderr or ""),
                )
                total_calls = sum(
                    len(i.calls) for i in _RecordingScanClient.instances
                )
                self.assertEqual(total_calls, 0,
                                 msg=f"dry-run + {flag} must not scan")

    def test_write_scan_warning_emits_warning_stderr_and_exit_zero(self):
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            self._patch(mp, _RaisingScanClient)
            import tempfile
            from ignition_gen_sdk.cli import app
            with tempfile.TemporaryDirectory() as tdir:
                tdir_path = Path(tdir)
                _make_full_project_skeleton(tdir_path, "Global")
                mp.setenv("IGNITION_DATA_DIR", str(tdir_path))
                result = _runner().invoke(
                    app,
                    ["view", "write", "--project", "Global",
                     "--view-path", "Main/Overview", "--no-dry-run"],
                )
                self.assertEqual(
                    result.exit_code, 0,
                    msg="Disk write succeeded; scan-fail is best-effort -> exit 0",
                )
                combined = (result.stdout or "") + (result.stderr or "")
                self.assertIn("WARNING:", combined)
                # The dest file path appears in the warning line
                dest = (tdir_path / "projects" / "Global"
                        / "com.inductiveautomation.perspective"
                        / "views" / "Main" / "Overview")
                self.assertIn(str(dest), combined)
                # Files still on disk
                self.assertTrue((dest / "view.json").is_file())
                self.assertTrue((dest / "resource.json").is_file())

    def test_write_does_not_double_prefix_token_when_settings_token_already_prefixed(self):
        """Smoke test: settings.ignition_api_key flows through unchanged when
        already test:-prefixed (no surprise prefix-doubling in the CLI)."""
        import pytest
        captured_keys: list[str] = []

        class _CaptureClient(_RecordingScanClient):
            def __init__(self, settings, *, timeout: float = 5.0, **kw):
                captured_keys.append(settings.ignition_api_key)
                super().__init__(settings, timeout=timeout, **kw)

        with pytest.MonkeyPatch.context() as mp:
            self._patch(mp, _CaptureClient)
            mp.setenv("IGNITION_API_TOKEN", "test:tok-xyz")
            import tempfile
            from ignition_gen_sdk.cli import app
            with tempfile.TemporaryDirectory() as tdir:
                tdir_path = Path(tdir)
                _make_full_project_skeleton(tdir_path, "Global")
                mp.setenv("IGNITION_DATA_DIR", str(tdir_path))
                result = _runner().invoke(
                    app,
                    ["view", "write", "--project", "Global",
                     "--view-path", "Main/Overview", "--no-dry-run"],
                )
                self.assertEqual(
                    result.exit_code, 0,
                    msg=(result.stdout or "") + (result.stderr or ""),
                )
                self.assertEqual(captured_keys, ["test:tok-xyz"])

    def test_write_post_scan_failure_does_not_remove_written_files(self):
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            self._patch(mp, _RaisingScanClient)
            import tempfile
            from ignition_gen_sdk.cli import app
            with tempfile.TemporaryDirectory() as tdir:
                tdir_path = Path(tdir)
                _make_full_project_skeleton(tdir_path, "Global")
                mp.setenv("IGNITION_DATA_DIR", str(tdir_path))
                result = _runner().invoke(
                    app,
                    ["view", "write", "--project", "Global",
                     "--view-path", "Main/Overview", "--no-dry-run"],
                )
                self.assertEqual(result.exit_code, 0)
                dest = (tdir_path / "projects" / "Global"
                        / "com.inductiveautomation.perspective"
                        / "views" / "Main" / "Overview")
                self.assertTrue((dest / "view.json").is_file())
                self.assertTrue((dest / "resource.json").is_file())


if __name__ == "__main__":
    unittest.main()
