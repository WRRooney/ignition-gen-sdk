"""Gateway and Perspective session event scripts on disk (Ignition 8.3).

Every event is one directory holding ``<function>.py`` plus a ``resource.json``
whose ``attributes`` carry the event's settings (timer delay, tag-change paths,
cron expression, ...). Nothing is binary; 8.1's gzipped ``event-scripts/data.bin``
is gone.

    projects/<p>/ignition/<folder>[/<name>]/<function>.py                gateway events
    projects/<p>/com.inductiveautomation.perspective/<folder>[/<name>]/  session events

Singleton kinds (startup, update, ...) live directly in ``<folder>``; named kinds
(timer, tag-change, message, ...) hold one subdirectory per event. Shapes were
taken from Designer-saved examples of every kind.
"""
from __future__ import annotations

import ast
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..config import Settings
from ._fs_utils import _atomic_write, _encode_segment
from .project_disk import ProjectNotFoundError, dumps_designer, validate_script_code

GATEWAY = "ignition"
SESSION = "com.inductiveautomation.perspective"


@dataclass(frozen=True)
class EventKind:
    module: str
    folder: str
    function: str
    params: tuple[str, ...]
    named: bool = False
    defaults: dict = field(default_factory=dict)
    # keys with no safe default: must be supplied when the event is created
    required: frozenset = frozenset()


_KEY_EVENT_KEYS = frozenset({
    "eventBound", "eventBoundKey", "eventBoundCode", "eventMode", "regexPattern", "regexWindow",
    "altEventModifier", "controlEventModifier", "metaEventModifier", "shiftEventModifier",
    "capturePhaseEventOption", "preventDefaultEventOption", "stopPropagationEventOption",
})

KINDS: dict[str, EventKind] = {
    "gateway.startup": EventKind(GATEWAY, "startup", "onStartup", ()),
    "gateway.shutdown": EventKind(GATEWAY, "shutdown", "onShutdown", ()),
    "gateway.update": EventKind(GATEWAY, "update", "onUpdate", ("actor", "resources")),
    "gateway.timer": EventKind(GATEWAY, "timer", "handleTimerEvent", (), named=True,
                               defaults={"delay": 1000, "fixedDelay": True, "sharedThread": True}),
    "gateway.tag-change": EventKind(
        GATEWAY, "tag-change", "onTagChange",
        ("initialChange", "newValue", "previousValue", "event", "executionCount"), named=True,
        defaults={"changeTypes": ["ValueChange", "QualityChange", "TimestampChange"]},
        required=frozenset({"paths"})),
    "gateway.scheduled": EventKind(GATEWAY, "scheduled", "handleScheduleEvent", (), named=True,
                                   required=frozenset({"cronExpression"})),
    "gateway.message": EventKind(GATEWAY, "message", "handleMessage", ("payload",), named=True,
                                 defaults={"threadType": "Shared"}),
    "session.startup": EventKind(SESSION, "startup", "onStartup", ("session",)),
    "session.shutdown": EventKind(SESSION, "shutdown", "onShutdown", ("session",)),
    "session.page-startup": EventKind(SESSION, "page-startup", "onPageStartup", ("page",)),
    "session.accelerometer": EventKind(SESSION, "accelerometer", "onAccelerometerDataReceived",
                                       ("session", "data", "context")),
    "session.auth-challenge": EventKind(SESSION, "auth-challenge", "onAuthChallengeCompleted",
                                        ("session", "payload", "result")),
    "session.barcode": EventKind(SESSION, "barcode", "onBarcodeDataReceived", ("session", "data", "context")),
    "session.bluetooth": EventKind(SESSION, "bluetooth", "onBluetoothReceived", ("session", "data")),
    "session.nfc-scan": EventKind(SESSION, "nfc-scan", "onNdefDataReceived", ("session", "data", "context")),
    "session.form-submission": EventKind(
        SESSION, "form-submission-handler", "handleSubmission",
        ("session", "name", "data", "files", "formContext", "sessionContext", "retry"), named=True),
    # ponytail: every key-event setting is required on create; the modifier flags'
    # Designer defaults are unverified, so copy them from an existing key event
    "session.key-event": EventKind(SESSION, "key-event", "onKeyEvent", ("page", "event"), named=True,
                                   required=_KEY_EVENT_KEYS),
    "session.message": EventKind(SESSION, "message", "handleMessage", ("session", "payload"), named=True,
                                 defaults={"threadType": "Shared"}),
}

# resource.json attributes the gateway/Designer own; never user settings
_META_KEYS = {"lastModification", "lastModificationSignature", "enabled"}


class EventScriptError(ValueError):
    """Bad kind, name, attributes or function signature for an event script."""


class EventNotFoundError(FileNotFoundError):
    """The event directory does not exist."""


def kind_of(key: str) -> EventKind:
    try:
        return KINDS[key]
    except KeyError:
        raise EventScriptError(f"unknown event kind {key!r}; one of: {', '.join(KINDS)}") from None


def validate_event_code(kind: EventKind, code: str) -> None:
    """Library-script gate (TAB, syntax, system.*) plus the Designer's signature.

    The gateway calls ``<function>(<params>)`` by position, so a renamed or
    reordered parameter list is a silent runtime bug; require the exact one.
    """
    validate_script_code(code)
    for node in ast.parse(code).body:
        if isinstance(node, ast.FunctionDef) and node.name == kind.function:
            got = tuple(a.arg for a in node.args.args)
            if got != kind.params:
                raise EventScriptError(
                    f"{kind.function} must take ({', '.join(kind.params)}), got ({', '.join(got)})")
            return
    raise EventScriptError(f"code must define {kind.function}({', '.join(kind.params)})")


def _check_attrs(key: str, kind: EventKind, attrs: dict) -> None:
    known = set(kind.defaults) | set(kind.required)
    unknown = set(attrs) - known
    if unknown:
        allowed = ", ".join(sorted(known)) or "none"
        raise EventScriptError(f"{key}: unknown attribute(s) {sorted(unknown)}; allowed: {allowed}")
    for k, v in attrs.items():
        if k in kind.defaults and type(v) is not type(kind.defaults[k]):
            raise EventScriptError(
                f"{key}: attribute {k!r} must be {type(kind.defaults[k]).__name__}, got {type(v).__name__}")


class EventScriptBackend:
    def __init__(self, settings: Settings) -> None:
        self._projects_root = settings.ignition_data_root / "projects"

    def _dir(self, project: str, kind: EventKind, name: str | None) -> Path:
        proj = self._projects_root / _encode_segment(project)
        if not (proj / "project.json").is_file():
            raise ProjectNotFoundError(
                f"Project {project!r} not found at {proj}. Create the project in the Designer first.")
        if kind.named and not name:
            raise EventScriptError(f"{kind.folder} events are named: pass --name")
        if not kind.named and name:
            raise EventScriptError(f"{kind.folder} is a single event per project: drop --name")
        dest = proj / kind.module / kind.folder
        if name:
            dest = dest / _encode_segment(name)
        if not dest.resolve().is_relative_to(self._projects_root.resolve()):
            raise ValueError(f"layer guard: {dest} is outside {self._projects_root}")
        return dest

    def read_attributes(self, project: str, key: str, name: str | None = None) -> dict:
        res = self._dir(project, kind_of(key), name) / "resource.json"
        if not res.is_file():
            return {}
        return json.loads(res.read_text(encoding="utf-8")).get("attributes", {})

    def resource_json(self, key: str, attrs: dict, enabled: bool) -> dict:
        kind = kind_of(key)
        return {
            "scope": "G",
            "version": 1,
            "restricted": False,
            "overridable": True,
            "files": [f"{kind.function}.py"],
            "attributes": {
                **attrs,
                "enabled": enabled,
                "lastModification": {
                    "actor": "ign",
                    "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            },
        }

    def plan(self, project: str, key: str, name: str | None, code: str,
             attrs: dict | None = None, enabled: bool | None = None) -> tuple[Path, dict]:
        """Validate and merge; return (directory, resource.json) without writing.

        Settings merge over the existing event's (a rewrite keeps what the
        Designer set), then over the kind's defaults for a new event.
        """
        kind = kind_of(key)
        attrs = attrs or {}
        _check_attrs(key, kind, attrs)
        validate_event_code(kind, code)
        dest = self._dir(project, kind, name)
        existing = self.read_attributes(project, key, name)
        base = {k: v for k, v in existing.items() if k not in _META_KEYS} if existing else dict(kind.defaults)
        merged = {**base, **attrs}
        missing = sorted(kind.required - set(merged))
        if missing:
            raise EventScriptError(f"{key}: new event needs attribute(s) {missing} (--attr key=JSON)")
        if enabled is None:
            enabled = existing.get("enabled", True)
        return dest, self.resource_json(key, merged, enabled)

    def write(self, project: str, key: str, name: str | None, code: str,
              attrs: dict | None = None, enabled: bool | None = None) -> Path:
        dest, resource = self.plan(project, key, name, code, attrs, enabled)
        dest.mkdir(parents=True, exist_ok=True)
        _atomic_write(dest / f"{kind_of(key).function}.py", code)
        _atomic_write(dest / "resource.json", dumps_designer(resource, indent=2))
        return dest

    def code_path(self, project: str, key: str, name: str | None = None) -> Path:
        path = self._dir(project, kind_of(key), name) / f"{kind_of(key).function}.py"
        if not path.is_file():
            raise EventNotFoundError(f"no {key} event at {path.parent}")
        return path

    def delete(self, project: str, key: str, name: str | None = None) -> Path:
        dest = self._dir(project, kind_of(key), name)
        if not dest.is_dir():
            raise EventNotFoundError(f"no {key} event at {dest}")
        shutil.rmtree(dest)
        parent = dest.parent
        if name and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
        return dest

    def list(self, project: str) -> list[tuple[str, str | None, dict]]:
        """(kind, name, attributes) for every event script in the project."""
        proj = self._projects_root / _encode_segment(project)
        if not (proj / "project.json").is_file():
            raise ProjectNotFoundError(f"Project {project!r} not found at {proj}.")
        out = []
        for key, kind in KINDS.items():
            base = proj / kind.module / kind.folder
            dirs = sorted(p for p in base.iterdir() if p.is_dir()) if kind.named and base.is_dir() else [base]
            for d in dirs:
                res = d / "resource.json"
                if (d / f"{kind.function}.py").is_file() and res.is_file():
                    attrs = json.loads(res.read_text(encoding="utf-8")).get("attributes", {})
                    out.append((key, d.name if kind.named else None,
                                {k: v for k, v in attrs.items() if k not in _META_KEYS - {"enabled"}}))
        return out
