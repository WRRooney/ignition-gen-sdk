"""Gateway + session event scripts (ign event). Fixtures are Designer-saved 8.3
examples of every kind (fixtures/event_scripts), so shape checks are against
real Designer output."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ignition_gen_sdk.backends.event_scripts import (
    KINDS,
    EventNotFoundError,
    EventScriptBackend,
    EventScriptError,
)
from ignition_gen_sdk.cli import app
from ignition_gen_sdk.config import Settings

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "event_scripts"


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    proj = tmp_path / "projects" / "Demo"
    proj.mkdir(parents=True)
    (proj / "project.json").write_text('{"title": "Demo"}')
    for module in ("ignition", "com.inductiveautomation.perspective"):
        shutil.copytree(FIXTURES / module, proj / module)
    return tmp_path


@pytest.fixture()
def backend(root: Path) -> EventScriptBackend:
    return EventScriptBackend(Settings(ignition_data_root=root))


def _attrs(path: Path) -> dict:
    a = json.loads((path / "resource.json").read_text())["attributes"]
    return {k: v for k, v in a.items() if k not in ("lastModification", "lastModificationSignature")}


def test_every_kind_reads_its_designer_fixture(backend):
    found = {(k, n) for k, n, _ in backend.list("Demo")}
    assert {k for k, _ in found} == set(KINDS)
    assert ("gateway.timer", "Example") in found and ("gateway.update", None) in found


def test_rewrite_reproduces_designer_resource(backend, root):
    for key, name, attrs in backend.list("Demo"):
        code = backend.code_path("Demo", key, name).read_text()
        dest = backend.write("Demo", key, name, code)
        assert _attrs(dest) == attrs, key
        res = json.loads((dest / "resource.json").read_text())
        assert res["scope"] == "G" and res["files"] == [f"{KINDS[key].function}.py"]


def test_new_named_event_gets_defaults(backend):
    dest = backend.write("Demo", "gateway.timer", "Poll", "def handleTimerEvent():\n\tpass\n")
    assert _attrs(dest) == {"delay": 1000, "fixedDelay": True, "sharedThread": True, "enabled": True}


def test_rewrite_keeps_settings_and_overrides_merge(backend):
    dest = backend.write("Demo", "gateway.timer", "Example", "def handleTimerEvent():\n\tpass\n",
                         attrs={"delay": 250}, enabled=False)
    assert _attrs(dest) == {"sharedThread": True, "delay": 250, "fixedDelay": True, "enabled": False}


@pytest.mark.parametrize("key,name,code,attrs,msg", [
    ("gateway.update", None, "def onUpdate(actor):\n\tpass\n", None, "must take"),
    ("gateway.update", None, "def other():\n\tpass\n", None, "must define"),
    ("gateway.timer", None, "def handleTimerEvent():\n\tpass\n", None, "--name"),
    ("gateway.startup", "X", "def onStartup():\n\tpass\n", None, "drop --name"),
    ("gateway.timer", "T", "def handleTimerEvent():\n\tpass\n", {"dealy": 5}, "unknown attribute"),
    ("gateway.timer", "T", "def handleTimerEvent():\n\tpass\n", {"delay": "5"}, "must be int"),
    ("gateway.tag-change", "New",
     "def onTagChange(initialChange, newValue, previousValue, event, executionCount):\n\tpass\n",
     None, "paths"),
    ("gateway.nope", None, "", None, "unknown event kind"),
])
def test_rejects(backend, key, name, code, attrs, msg):
    with pytest.raises(EventScriptError, match=msg):
        backend.write("Demo", key, name, code, attrs=attrs)


def test_delete_prunes_empty_named_folder(backend, root):
    backend.delete("Demo", "gateway.scheduled", "Example")
    assert not (root / "projects/Demo/ignition/scheduled").exists()
    with pytest.raises(EventNotFoundError):
        backend.delete("Demo", "gateway.scheduled", "Example")


def test_cli_replace_text_keeps_attributes(root, monkeypatch):
    monkeypatch.setenv("IGNITION_DATA_DIR", str(root))
    before = _attrs(root / "projects/Demo/ignition/tag-change/Example")
    r = CliRunner().invoke(app, ["event", "replace-text", "--project", "Demo", "--kind", "gateway.tag-change",
                                 "--name", "Example", "--old", "pass", "--new", "return", "--expect", "1",
                                 "--no-scan"])
    assert r.exit_code == 0, r.output
    d = root / "projects/Demo/ignition/tag-change/Example"
    assert "\treturn" in (d / "onTagChange.py").read_text()
    assert _attrs(d) == before


def test_cli_write_attr_parsing(root, tmp_path, monkeypatch):
    monkeypatch.setenv("IGNITION_DATA_DIR", str(root))
    src = tmp_path / "s.py"
    src.write_text("def handleScheduleEvent():\n\tpass\n")
    r = CliRunner().invoke(app, ["event", "write", "--project", "Demo", "--kind", "gateway.scheduled",
                                 "--name", "Nightly", "--file", str(src), "--attr", "cronExpression=0 2 * * *",
                                 "--no-scan"])
    assert r.exit_code == 0, r.output
    assert _attrs(root / "projects/Demo/ignition/scheduled/Nightly")["cronExpression"] == "0 2 * * *"
