"""``ign security``: get / set-permissions / update against a fake gateway."""
from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from ignition_gen_sdk.cli import app

runner = CliRunner()
SIG = "0c2eb8843e46e198bfcecccda387c4c1"
CONFIG = {
    "accessPermissions": {"type": "AnyOf", "securityLevels": [{"name": "Authenticated", "children": []}]},
    "readPermissions": {"type": "AnyOf", "securityLevels": []},
    "writePermissions": {"type": "AnyOf", "securityLevels": [{"name": "Authenticated", "children": [
        {"name": "Roles", "children": [{"name": "Administrator", "children": []}]}]}]},
    "designerPermissions": {"type": "AnyOf", "securityLevels": []},
    "createProjectPermissions": {"type": "AnyOf", "securityLevels": []},
    "forceIdpAuth": True,
    "systemAuthProfile": "default",
    "someNewerField": 7,
}


@pytest.fixture
def gateway(monkeypatch):
    calls: list[tuple[str, str, object]] = []

    def fake_request(self, method, path, json=None):
        calls.append((method, path, json))
        req = httpx.Request(method, "http://gw" + path)
        if method == "GET":
            return httpx.Response(200, json={"signature": SIG, "config": json_copy(CONFIG), "enabled": True}, request=req)
        return httpx.Response(200, json={"success": True}, request=req)

    monkeypatch.setattr("ignition_gen_sdk.backends.api_client.IgnitionAPIClient.request", fake_request)
    return calls


def json_copy(o):
    return json.loads(json.dumps(o))


def test_get_prints_config_and_paths(gateway):
    r = runner.invoke(app, ["security", "get"])
    assert r.exit_code == 0 and json.loads(r.output)["someNewerField"] == 7
    r = runner.invoke(app, ["security", "get", "--key", "writePermissions", "--paths"])
    assert r.exit_code == 0 and json.loads(r.output) == {"type": "AnyOf", "paths": ["Authenticated/Roles/Administrator"]}


def test_set_permissions_gets_patches_puts(gateway):
    r = runner.invoke(app, ["security", "set-permissions", "--key", "writePermissions",
                            "--any-of", "Authenticated/Roles/Administrator", "--any-of", "APIKey/Write"])
    assert r.exit_code == 0, r.output
    put = [c for c in gateway if c[0] == "PUT"][0]
    assert put[1].endswith("/resources/ignition/security-properties")
    body = put[2][0]
    assert body["signature"] == SIG
    assert body["config"]["writePermissions"]["securityLevels"][1] == {"name": "APIKey", "children": [{"name": "Write", "children": []}]}
    assert body["config"]["someNewerField"] == 7  # untouched keys survive the round trip
    assert body["config"]["accessPermissions"] == CONFIG["accessPermissions"]


def test_set_permissions_open_and_dry_run(gateway):
    r = runner.invoke(app, ["security", "set-permissions", "--key", "designerPermissions", "--open", "--dry-run"])
    assert r.exit_code == 0 and json.loads(r.output)["designerPermissions"] == {"type": "AnyOf", "securityLevels": []}
    assert not [c for c in gateway if c[0] == "PUT"]
    assert runner.invoke(app, ["security", "set-permissions", "--key", "bogus", "--open"]).exit_code == 1
    assert runner.invoke(app, ["security", "set-permissions", "--key", "readPermissions"]).exit_code == 1


def test_update_validates_file(gateway, tmp_path):
    f = tmp_path / "sec.json"
    bad = json_copy(CONFIG); bad["writePermissions"]["type"] = "Some"
    f.write_text(json.dumps(bad))
    r = runner.invoke(app, ["security", "update", "--file", str(f)])
    assert r.exit_code == 1 and not [c for c in gateway if c[0] == "PUT"]
    f.write_text(json.dumps(CONFIG))
    r = runner.invoke(app, ["security", "update", "--file", str(f)])
    assert r.exit_code == 0 and [c for c in gateway if c[0] == "PUT"][0][2][0]["config"] == CONFIG
