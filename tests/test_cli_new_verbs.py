"""Smallest checks for the ``openapi``, ``tools``, ``builtins`` and ``icons`` verbs."""
from __future__ import annotations

from conftest import GATEWAY_URL

import io
import json
import zipfile

import httpx
from typer.testing import CliRunner

from ignition_gen_sdk.cli import app

runner = CliRunner()


def test_openapi_fetch_writes_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IGNITION_STATE_DIR", str(tmp_path / ".ign"))
    monkeypatch.delenv("IGNITION_OPENAPI_SPEC_PATH", raising=False)  # never write a real spec
    spec = {"openapi": "3.1.0", "info": {"version": "9"}, "paths": {"/data/api/v1/x": {}}}

    def fake_request(self, method, path, json=None):
        assert (method, path) == ("GET", "/openapi.json")
        return httpx.Response(200, json=spec, request=httpx.Request("GET", f"{GATEWAY_URL}/openapi.json"))

    monkeypatch.setattr("ignition_gen_sdk.backends.api_client.IgnitionAPIClient.request", fake_request)
    result = runner.invoke(app, ["openapi", "fetch"])
    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / ".ign" / "openapi.json").read_text())["paths"]
    assert "1 paths" in result.output


def test_tools_list_and_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tools = tmp_path / ".ign_tools"
    tools.mkdir()
    (tools / "_helper.py").write_text("X = 1\n")
    (tools / "hello.py").write_text('"""Say hello.\n\nMore."""\nimport sys\nimport _helper\nprint("hi", sys.argv[1:], _helper.X)\n')
    result = runner.invoke(app, ["tools", "list"])
    assert result.exit_code == 0 and result.output.strip() == "hello  Say hello."
    result = runner.invoke(app, ["tools", "run", "hello", "--force", "a"])
    assert result.exit_code == 0 and "hi ['--force', 'a'] 1" in result.output
    assert runner.invoke(app, ["tools", "run", "missing"]).exit_code == 1


def test_builtins_audit_flags_unknown_calls(tmp_path):
    lib = tmp_path / "projects" / "P" / "ignition" / "script-python" / "lib"
    lib.mkdir(parents=True)
    (lib / "code.py").write_text("system.tag.readBlocking(['x'])\nsystem.perspective.setSessionProperty('a', 1)\n")
    result = runner.invoke(app, ["builtins", "audit", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "system.perspective.setSessionProperty" in result.output
    assert "readBlocking" not in result.output
    assert runner.invoke(app, ["builtins", "audit", "--data-dir", str(tmp_path), "-p", "Other"]).exit_code == 0


def test_icons_list_from_modl(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("icons/material.svg", '<svg><g class="icon" id="home"/><g class="icon" id="alarm"/></svg>')
    modl = tmp_path / "Perspective-module.modl"
    with zipfile.ZipFile(modl, "w") as z:
        z.writestr("perspective-icons-1.jar", inner.getvalue())
    result = runner.invoke(app, ["icons", "list", "--modl", str(modl), "--json"])
    assert result.exit_code == 0 and json.loads(result.output) == ["alarm", "home"]
    assert runner.invoke(app, ["icons", "list"]).exit_code == 1
