"""``ign device`` CLI tests. IgnitionAPIClient and ScanClient are patched; no gateway."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ignition_gen_sdk.backends.api_client import PayloadError
from ignition_gen_sdk.cli import app

PROGRAM = (
    "Time Interval, Browse Path, Value Source, Data Type\n"
    '"0","Line/Flow","0.0","Double"\n'
    '"1000","Line/Flow","ramp(0,100)","Double"\n'
)


@pytest.fixture
def client():
    with patch("ignition_gen_sdk.cli.cmd_device.IgnitionAPIClient") as cls, \
         patch("ignition_gen_sdk.cli.cmd_device.ScanClient") as scan_cls, \
         patch("ignition_gen_sdk.cli.cmd_device.Settings"):
        inst = MagicMock()

        def request(method, path, **kw):
            r = MagicMock()
            r.text = "x"
            r.json.return_value = {"name": "Sim1", "signature": "abc123"} if "/find/" in path else {"success": True}
            return r

        inst.request.side_effect = request
        cls.return_value = inst
        inst.scan = scan_cls.return_value.__enter__.return_value
        yield inst


@pytest.fixture
def program(tmp_path: Path) -> Path:
    p = tmp_path / "prog.csv"
    p.write_text(PROGRAM)
    return p


def run(*args: str):
    return CliRunner().invoke(app, ["device", *args])


def test_help_lists_verbs():
    out = run("--help").output
    for verb in ("list", "get", "describe", "create", "program", "program-get", "delete"):
        assert verb in out


def test_create_dry_run_defaults_to_simulator(client):
    r = run("create", "--name", "Sim1", "--dry-run")
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload[0]["config"]["profile"]["type"] == "ProgrammableSimulatorDevice"
    assert payload[0]["config"]["settings"]["timeIntervalRate"] == 1000
    client.request.assert_not_called()


def test_create_with_program_posts_then_puts_csv_with_signature(client, program):
    r = run("create", "--name", "Sim1", "--program", str(program), "--confirm")
    assert r.exit_code == 0, r.output
    calls = client.request.call_args_list
    assert calls[0].args == ("POST", "/data/api/v1/resources/com.inductiveautomation.opcua/device")
    assert isinstance(calls[0].kwargs["json"], list)
    assert calls[1].args[1].endswith("/find/com.inductiveautomation.opcua/device/Sim1")
    method, path = calls[2].args
    assert method == "PUT"
    assert path.endswith("/datafile/com.inductiveautomation.opcua/device/Sim1/instructions.csv?signature=abc123")
    assert calls[2].kwargs["content"] == PROGRAM.encode()
    assert calls[2].kwargs["content_type"] == "text/csv"
    client.scan.scan_config.assert_called_once()


def test_program_rejects_wrong_header(client, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Time,Path,Value\n0,a,1\n")
    r = run("program", "--name", "Sim1", "--file", str(bad), "--confirm")
    assert r.exit_code == 1
    assert "program header must be" in r.output
    client.request.assert_not_called()


def test_program_not_found(client, program):
    client.request.side_effect = PayloadError("404 Not Found: ")
    r = run("program", "--name", "Nope", "--file", str(program), "--confirm")
    assert r.exit_code == 1
    assert "device 'Nope' not found." in r.output


def test_delete_uses_signature(client):
    r = run("delete", "--name", "Sim1", "--yes", "--no-scan")
    assert r.exit_code == 0, r.output
    assert client.request.call_args_list[-1].args == (
        "DELETE", "/data/api/v1/resources/com.inductiveautomation.opcua/device/Sim1/abc123")
    client.scan.scan_config.assert_not_called()
