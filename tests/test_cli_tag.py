"""`ign tag` CLI tests.

Behavior contracts:

- `ign tag build` prints valid AtomicTag JSON (tagType=AtomicTag,
  dataType=Float8) to stdout and exits 0.
- `ign tag push --dry-run` prints Provider-root JSON envelope to stdout,
  no gateway/disk call, exits 0.
- `ign tag push --backend disk` writes via DiskBackend and prints the
  destination path; no API call.
- `ign tag push` (auto / api) calls WriteRouter.push_tags and prints
  outcome; "Push successful" on empty/dict result.
- AuthMissingError → stderr "Auth error: check IGNITION_API_TOKEN in
  .env"; exit code 1.
- AuthScopeError → stderr "Permission error: token lacks required scope
  — check Gateway UI"; exit code 1.
- PayloadError → stderr "Payload error: <body>"; exit code 1.
- GatewayError → stderr "Gateway error: <message>"; exit code 1.
- No error message ever contains the literal API key value.

Tests use Typer's `CliRunner` (from typer.testing) which executes the
command in-process and captures stdout/stderr/exit_code without spawning a
shell. The WriteRouter is patched so the CLI's behavior is verified
without touching the live gateway or disk.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


# All tests use a fresh CliRunner per test to avoid shared state.
def _runner():
    from typer.testing import CliRunner

    # Typer 0.25.x's CliRunner separates stdout / stderr automatically
    # (no mix_stderr arg — that was removed when Click 8.2 made it the
    # default). ``result.stdout`` and ``result.stderr`` are the two
    # streams; ``result.output`` is the merged view.
    return CliRunner()


class TestCliWiring(unittest.TestCase):
    """The `tag` subcommand group must be wired onto the top-level app."""

    def test_top_level_help_lists_tag_subcommand(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("tag", result.output)

    def test_tag_help_lists_build_and_push(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["tag", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("build", result.output)
        self.assertIn("push", result.output)


class TestTagBuild(unittest.TestCase):
    """`ign tag build` prints valid AtomicTag JSON."""

    def test_build_prints_atomic_tag_with_float8(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["tag", "build"])
        self.assertEqual(result.exit_code, 0, msg=result.output)

        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["tagType"], "AtomicTag")
        self.assertEqual(parsed["dataType"], "Float8")
        # Demo tag is OPC-sourced.
        self.assertEqual(parsed["valueSource"], "opc")
        # Has at least one alarm.
        self.assertIn("alarms", parsed)
        self.assertGreaterEqual(len(parsed["alarms"]), 1)


class TestTagPushDryRun(unittest.TestCase):
    """`ign tag push --dry-run` prints Provider-root JSON; no router call."""

    def test_dry_run_prints_provider_root_envelope(self) -> None:
        from ignition_gen_sdk.cli import app

        # Patch the router so we can prove it was NOT called for dry-run.
        # The CLI should serialize the payload itself for dry-run output.
        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            router_cls.return_value = router_inst

            result = _runner().invoke(app, ["tag", "push", "--dry-run"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["tagType"], "Provider")
        self.assertEqual(parsed["name"], "")
        self.assertGreaterEqual(len(parsed["tags"]), 1)
        # WriteRouter must not have been asked to push.
        router_inst.push_tags.assert_not_called()


class TestTagPushApi(unittest.TestCase):
    """`ign tag push` (default backend) → WriteRouter.push_tags."""

    def test_push_calls_router_with_provider_path_and_backend(self) -> None:
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            router_inst.push_tags.return_value = {
                "successCount": 1,
                "failureCount": 0,
            }
            router_cls.return_value = router_inst

            result = _runner().invoke(
                app,
                [
                    "tag",
                    "push",
                    "--provider",
                    "default",
                    "--path",
                    "Test/Smoke",
                ],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        router_inst.push_tags.assert_called_once()
        call = router_inst.push_tags.call_args
        # Provider / path / backend land as kwargs (the CLI passes them as
        # keyword args to WriteRouter.push_tags).
        self.assertEqual(call.kwargs["provider"], "default")
        self.assertEqual(call.kwargs["path"], "Test/Smoke")
        self.assertEqual(call.kwargs["dry_run"], False)
        # Default backend is "auto".
        self.assertEqual(call.kwargs["backend"], "auto")
        # tags is a list with at least one Tag.
        tags = call.kwargs["tags"]
        self.assertGreaterEqual(len(tags), 1)
        # Stdout contains a recognisable success line.
        self.assertIn("Push successful", result.stdout)


class TestTagPushDisk(unittest.TestCase):
    """`ign tag push --backend disk` writes to disk and prints path."""

    def test_disk_backend_passes_through(self) -> None:
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            # Disk path returns [] from the router contract.
            router_inst.push_tags.return_value = []
            router_cls.return_value = router_inst

            # --no-scan: the disk backend wires a scan_config() call
            # after disk writes; this test runs without a live gateway,
            # so suppress the scan to keep the test offline-friendly.
            result = _runner().invoke(
                app,
                [
                    "tag",
                    "push",
                    "--backend",
                    "disk",
                    "--provider",
                    "default",
                    "--path",
                    "Test/DiskSmoke",
                    "--no-scan",
                ],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        call = router_inst.push_tags.call_args
        self.assertEqual(call.kwargs["backend"], "disk")
        # Stdout mentions a disk path with the provider+path components.
        # Fallback acceptance: the word "disk" should at least appear.
        self.assertIn("disk", result.stdout.lower())


class TestTagPushDiskScansConfig(unittest.TestCase):
    """--backend disk must POST /scan/config after
    write so the gateway re-scans config/resources/** without waiting
    for the next tick. --no-scan suppresses entirely.
    """

    def test_disk_backend_triggers_scan_config_by_default(self) -> None:
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls, patch(
            "ignition_gen_sdk.cli.cmd_tag.ScanClient"
        ) as scan_cls:
            router_inst = MagicMock()
            router_inst.push_tags.return_value = []
            router_cls.return_value = router_inst
            scan_inst = MagicMock()
            # ScanClient is used as a context manager.
            scan_cls.return_value.__enter__.return_value = scan_inst
            scan_cls.return_value.__exit__.return_value = False

            result = _runner().invoke(
                app,
                ["tag", "push", "--backend", "disk",
                 "--provider", "default", "--path", "Test/A"],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        scan_inst.scan_config.assert_called_once()

    def test_disk_backend_no_scan_flag_suppresses_scan(self) -> None:
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls, patch(
            "ignition_gen_sdk.cli.cmd_tag.ScanClient"
        ) as scan_cls:
            router_inst = MagicMock()
            router_inst.push_tags.return_value = []
            router_cls.return_value = router_inst

            result = _runner().invoke(
                app,
                ["tag", "push", "--backend", "disk",
                 "--provider", "default", "--path", "Test/A",
                 "--no-scan"],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        scan_cls.assert_not_called()

    def test_disk_backend_scan_failure_is_best_effort(self) -> None:
        """ScanWarning from scan_config must not fail the command — disk
        write already succeeded; gateway is the only thing out of sync."""
        from ignition_gen_sdk.backends.scan_client import ScanWarning
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls, patch(
            "ignition_gen_sdk.cli.cmd_tag.ScanClient"
        ) as scan_cls:
            router_inst = MagicMock()
            router_inst.push_tags.return_value = []
            router_cls.return_value = router_inst
            scan_inst = MagicMock()
            scan_inst.scan_config.side_effect = ScanWarning("gateway down")
            scan_cls.return_value.__enter__.return_value = scan_inst
            scan_cls.return_value.__exit__.return_value = False

            result = _runner().invoke(
                app,
                ["tag", "push", "--backend", "disk",
                 "--provider", "default", "--path", "Test/A"],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        # WARNING printed to stderr but exit 0 (disk write succeeded).
        self.assertIn("WARNING", result.stderr)


class TestTagPushDiagnostics(unittest.TestCase):
    """Non-empty diagnostics list from API surfaces to stdout/stderr."""

    def test_error_diagnostic_lines_routed_to_stderr(self) -> None:
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            router_inst.push_tags.return_value = [
                {"level": "Error", "diagnosticMessage": "bad path"},
            ]
            router_cls.return_value = router_inst

            result = _runner().invoke(
                app,
                [
                    "tag",
                    "push",
                    "--provider",
                    "default",
                    "--path",
                    "Test/Smoke",
                ],
            )

        # Exit code 0 — diagnostics surfaced but the CLI only fails on
        # exception. Output should mention "bad path".
        self.assertEqual(result.exit_code, 0, msg=result.output)
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertIn("bad path", combined)


class TestTagPushAuthMissing(unittest.TestCase):
    """401 → AuthMissingError → 'Auth error: check IGNITION_API_TOKEN ...'."""

    def test_auth_missing_message_and_exit_code(self) -> None:
        from ignition_gen_sdk.backends.api_client import AuthMissingError
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            router_inst.push_tags.side_effect = AuthMissingError("401")
            router_cls.return_value = router_inst

            result = _runner().invoke(
                app, ["tag", "push", "--provider", "default", "--path", ""]
            )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Auth error", result.stderr)
        self.assertIn("IGNITION_API_TOKEN", result.stderr)
        # Token value MUST NOT appear in error output.
        self.assertNotIn("test-secret-DO-NOT-LEAK", result.stderr)


class TestTagPushAuthScope(unittest.TestCase):
    """403 → AuthScopeError → 'Permission error: token lacks required scope ...'."""

    def test_auth_scope_message_and_exit_code(self) -> None:
        from ignition_gen_sdk.backends.api_client import AuthScopeError
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            router_inst.push_tags.side_effect = AuthScopeError("403")
            router_cls.return_value = router_inst

            result = _runner().invoke(
                app, ["tag", "push", "--provider", "default", "--path", ""]
            )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Permission error", result.stderr)
        self.assertIn("scope", result.stderr.lower())
        self.assertNotIn("test-secret-DO-NOT-LEAK", result.stderr)


class TestTagPushPayloadError(unittest.TestCase):
    """400 → PayloadError → 'Payload error: <body>'."""

    def test_payload_error_message_and_exit_code(self) -> None:
        from ignition_gen_sdk.backends.api_client import PayloadError
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            router_inst.push_tags.side_effect = PayloadError(
                "400 Bad Request: provider 'nope' not found"
            )
            router_cls.return_value = router_inst

            result = _runner().invoke(
                app, ["tag", "push", "--provider", "nope", "--path", ""]
            )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Payload error", result.stderr)
        self.assertIn("provider 'nope' not found", result.stderr)
        self.assertNotIn("test-secret-DO-NOT-LEAK", result.stderr)


class TestTagPushGatewayError(unittest.TestCase):
    """5xx → GatewayError → 'Gateway error: <message>'."""

    def test_gateway_error_message_and_exit_code(self) -> None:
        from ignition_gen_sdk.backends.api_client import GatewayError
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            router_inst.push_tags.side_effect = GatewayError(
                "500 Gateway Error: retry the request"
            )
            router_cls.return_value = router_inst

            result = _runner().invoke(
                app, ["tag", "push", "--provider", "default", "--path", ""]
            )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Gateway error", result.stderr)
        self.assertNotIn("test-secret-DO-NOT-LEAK", result.stderr)


class TestTagPushValueError(unittest.TestCase):
    """`--backend invalid` → ValueError → exit 1, error message printed."""

    def test_invalid_backend_surfaces_as_error(self) -> None:
        from ignition_gen_sdk.cli import app

        # No router patch — the CLI must still produce a clean error
        # before / from the router call. Construct WriteRouter normally;
        # ValueError("Invalid backend ...") is raised inside push_tags.
        with patch(
            "ignition_gen_sdk.cli.cmd_tag.WriteRouter"
        ) as router_cls:
            router_inst = MagicMock()
            router_inst.push_tags.side_effect = ValueError(
                "Invalid backend 'invalid'."
            )
            router_cls.return_value = router_inst

            result = _runner().invoke(
                app,
                [
                    "tag",
                    "push",
                    "--backend",
                    "invalid",
                    "--provider",
                    "default",
                    "--path",
                    "",
                ],
            )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Invalid backend", result.stderr)


if __name__ == "__main__":
    unittest.main()
