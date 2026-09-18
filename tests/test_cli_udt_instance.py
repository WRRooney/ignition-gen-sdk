"""Tests for `ign tag udt-instance` + the scan-lock / collision-policy
plumbing added alongside it.

No network: Settings is pointed at a tempdir and ScanClient is monkeypatched.
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _runner():
    from typer.testing import CliRunner

    return CliRunner()


_INSTANCES = [
    {
        "name": "Flow1",
        "tagType": "UdtInstance",
        "typeId": "Equipment/Analog",
        "parameters": {"meta.area": {"dataType": "String", "value": "Area1"}},
    },
    {"name": "Pump1", "tagType": "UdtInstance", "typeId": "Equipment/Motor"},
]


def _settings_for(root: Path):
    from ignition_gen_sdk.config import Settings

    return Settings(
        ignition_api_key="test:test",
        ignition_base_url=GATEWAY_URL,
        ignition_data_root=str(root),
    )


class TestCliUdtInstance(unittest.TestCase):
    def test_help_lists_udt_instance(self):
        from ignition_gen_sdk.cli import app

        r = _runner().invoke(app, ["tag", "--help"])
        self.assertEqual(r.exit_code, 0, msg=r.output)
        self.assertIn("udt-instance", r.output)

    def test_dry_run_emits_flat_udts_payload(self):
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "i.json"
            p.write_text(json.dumps(_INSTANCES))
            r = _runner().invoke(
                app,
                ["tag", "udt-instance", "--provider", "default", "--path",
                 "Area1/Pump01", "--file", str(p), "--dry-run"],
            )
        self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
        out = json.loads(r.stdout)
        # Flat list, no 'usr' wrapper.
        self.assertIsInstance(out, list)
        self.assertEqual(out[0]["tagType"], "UdtInstance")
        self.assertEqual(out[0]["typeId"], "Equipment/Analog")

    def test_writes_udts_json_and_sidecar(self):
        from ignition_gen_sdk.cli import app
        import ignition_gen_sdk.cli.cmd_tag as cmd_tag

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "i.json"
            src.write_text(json.dumps(_INSTANCES))
            with mock.patch.object(cmd_tag, "Settings", lambda: _settings_for(root)):
                r = _runner().invoke(
                    app,
                    ["tag", "udt-instance", "--provider", "default", "--path",
                     "Area1/Pump01", "--file", str(src), "--no-scan"],
                )
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            dest = (root / "config/resources/core/ignition/tag-definition"
                    / "default" / "Area1" / "Pump01")
            udts = json.loads((dest / "udts.json").read_text())
            self.assertEqual([u["name"] for u in udts],
                             ["Flow1", "Pump1"])
            sidecar = json.loads((dest / "unary-resource.json").read_text())
            self.assertEqual(sidecar["files"], ["udts.json"])
            self.assertEqual(sidecar["scope"], "G")
            self.assertEqual(sidecar["attributes"], {"config": {}})
            self.assertIs(sidecar["overridable"], True)

    def test_bad_payload_rejected(self):
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.json"
            # Valid JSON, invalid UdtInstance (no typeId, bogus extra key).
            p.write_text(json.dumps([{"name": "X", "tagType": "UdtInstance", "nope": 1}]))
            r = _runner().invoke(app, ["tag", "udt-instance", "--file", str(p)])
        self.assertEqual(r.exit_code, 1, msg=r.stdout + r.stderr)
        self.assertIn("UDT instance", r.stderr)

    def test_bad_json_rejected(self):
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.json"
            p.write_text("{nope")
            r = _runner().invoke(app, ["tag", "udt-instance", "--file", str(p)])
        self.assertEqual(r.exit_code, 1)
        self.assertIn("--file", r.stderr)


class TestScanLock(unittest.TestCase):
    def test_acquire_config_lock_posts_body(self):
        import httpx
        from ignition_gen_sdk.backends.scan_client import ScanClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={})

        with tempfile.TemporaryDirectory() as d:
            with ScanClient(_settings_for(Path(d)),
                            _transport=httpx.MockTransport(handler)) as c:
                c.acquire_config_lock()
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/data/api/v1/scan-lock/config")
        self.assertEqual(captured["body"], {"acquireTimeout": 10, "holdTimeout": 60})

    def test_acquire_failure_is_warning_not_fatal(self):
        """A 409/500 on the lock must NOT stop the disk write."""
        from ignition_gen_sdk.cli import app
        import ignition_gen_sdk.cli.cmd_tag as cmd_tag
        from ignition_gen_sdk.backends.scan_client import ScanWarning

        calls: list[str] = []

        class FakeScanClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

            def acquire_config_lock(self, **kw):
                calls.append("lock")
                raise ScanWarning("HTTP 409")

            def scan_config(self):
                calls.append("scan")

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "i.json"
            src.write_text(json.dumps(_INSTANCES))
            with mock.patch.object(cmd_tag, "Settings", lambda: _settings_for(root)), \
                    mock.patch.object(cmd_tag, "ScanClient", FakeScanClient):
                r = _runner().invoke(
                    app,
                    ["tag", "udt-instance", "--provider", "default",
                     "--path", "F", "--file", str(src)],
                )
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            self.assertIn("WARNING", r.stderr)
            # Write still happened; scan still ran (lock, then write, then scan).
            self.assertEqual(calls, ["lock", "scan"])
            self.assertTrue((root / "config/resources/core/ignition/tag-definition"
                             / "default" / "F" / "udts.json").exists())

    def test_no_scan_skips_lock(self):
        """--no-scan must not take a lock nobody will release."""
        from ignition_gen_sdk.cli import app
        import ignition_gen_sdk.cli.cmd_tag as cmd_tag

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "i.json"
            src.write_text(json.dumps(_INSTANCES))
            with mock.patch.object(cmd_tag, "Settings", lambda: _settings_for(root)), \
                    mock.patch.object(cmd_tag, "ScanClient") as sc:
                r = _runner().invoke(
                    app,
                    ["tag", "udt-instance", "--path", "F", "--file", str(src), "--no-scan"],
                )
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            sc.assert_not_called()

    def test_udt_type_takes_lock_before_write(self):
        from ignition_gen_sdk.cli import app
        import ignition_gen_sdk.cli.cmd_tag as cmd_tag

        udt = {"name": "WaterTank", "tagType": "UdtType"}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "t.json"
            src.write_text(json.dumps(udt))
            with mock.patch.object(cmd_tag, "Settings", lambda: _settings_for(root)), \
                    mock.patch.object(cmd_tag, "ScanClient") as sc:
                r = _runner().invoke(
                    app, ["tag", "udt-type", "--provider", "default", "--path", "F",
                          "--file", str(src)]
                )
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            inst = sc.return_value.__enter__.return_value
            inst.acquire_config_lock.assert_called_once()
            inst.scan_config.assert_called_once()


class TestCollisionPolicy(unittest.TestCase):
    def test_router_default_is_overwrite(self):
        from ignition_gen_sdk.backends.router import WriteRouter

        api = mock.Mock()
        router = WriteRouter(api, mock.Mock())
        router.push_tags("default", "P", [], backend="api")
        self.assertEqual(api.import_tags.call_args[0][3], "Overwrite")

    def test_push_cli_forwards_collision_policy(self):
        from ignition_gen_sdk.cli import app
        import ignition_gen_sdk.cli.cmd_tag as cmd_tag

        router = mock.Mock()
        router.push_tags.return_value = {"successCount": 1, "failureCount": 0}
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(cmd_tag, "Settings", lambda: _settings_for(Path(d))), \
                    mock.patch.object(cmd_tag, "_make_router", lambda s: router):
                r = _runner().invoke(
                    app, ["tag", "push", "--backend", "api", "--collision-policy", "Ignore"]
                )
        self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
        self.assertEqual(router.push_tags.call_args.kwargs["collision_policy"], "Ignore")

    def test_push_cli_default_collision_policy_is_overwrite(self):
        from ignition_gen_sdk.cli import app
        import ignition_gen_sdk.cli.cmd_tag as cmd_tag

        router = mock.Mock()
        router.push_tags.return_value = {"successCount": 1, "failureCount": 0}
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(cmd_tag, "Settings", lambda: _settings_for(Path(d))), \
                    mock.patch.object(cmd_tag, "_make_router", lambda s: router):
                r = _runner().invoke(app, ["tag", "push", "--backend", "api"])
        self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
        self.assertEqual(router.push_tags.call_args.kwargs["collision_policy"], "Overwrite")

    def test_push_cli_rejects_bad_collision_policy(self):
        from ignition_gen_sdk.cli import app

        r = _runner().invoke(app, ["tag", "push", "--collision-policy", "Clobber"])
        self.assertEqual(r.exit_code, 1, msg=r.stdout + r.stderr)
        self.assertIn("MergeOverwrite", r.stderr)

    def test_import_cli_accepts_ignore(self):
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.json"
            p.write_text(json.dumps({"tags": []}))
            r = _runner().invoke(
                app,
                ["tag", "import", "--file", str(p), "--collision-policy", "Ignore",
                 "--dry-run"],
            )
        self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
        self.assertIn("collisionPolicy=Ignore", r.stdout)


if __name__ == "__main__":
    unittest.main()
