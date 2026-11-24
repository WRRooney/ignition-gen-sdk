"""ign device — OPC UA device connections (com.inductiveautomation.opcua/device).

Verbs:

- list      — GET  resources/list/com.inductiveautomation.opcua/device
- get       — GET  resources/find/com.inductiveautomation.opcua/device/<name>
- describe  — GET  resources/type/com.inductiveautomation.opcua/device
              (settings schema for every installed driver type)
- create    — POST resources/com.inductiveautomation.opcua/device (one-element
              JSON array), optionally followed by --program
- program   — PUT  resources/datafile/com.inductiveautomation.opcua/device/<name>/instructions.csv
              (load or replace a Programmable Device Simulator program)
- program-get — GET the same data file
- delete    — DELETE resources/com.inductiveautomation.opcua/device/<name>/<signature>

Data-file writes and deletes need the resource's current signature; each verb
fetches it with `find` first. All calls go through IgnitionAPIClient.request(),
so the token never enters argv. Mutations scan config afterwards (best effort,
WARNING on stderr).
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from ..backends.api_client import (
    AuthMissingError,
    IgnitionAPIClient,
    IgnitionAPIError,
    PayloadError,
)
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ._errors import render_error

device_app = typer.Typer(
    name="device",
    help="OPC UA device connections, including simulator programs.",
    no_args_is_help=True,
)

_MODULE = "com.inductiveautomation.opcua/device"
_BASE = "/data/api/v1/resources"
PROGRAM_FILE = "instructions.csv"
PROGRAM_HEADER = ["Time Interval", "Browse Path", "Value Source", "Data Type"]
SIM_TYPE = "ProgrammableSimulatorDevice"
SIM_DEFAULT_SETTINGS = {"legacyMode": False, "repeat": True, "timeIntervalRate": 1000}


def _get_api() -> tuple[Settings, IgnitionAPIClient]:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as e:  # noqa: BLE001
        render_error(AuthMissingError(f"check IGNITION_API_TOKEN (env or .env) ({e})"), no_color=False)
        raise typer.Exit(code=1) from None
    return settings, IgnitionAPIClient(settings)


def _run(name: str | None, fn: Callable[[IgnitionAPIClient], Any]) -> tuple[Settings, Any]:
    """Run fn(client), render any API error as Error:/Hint: and exit 1."""
    settings, client = _get_api()
    try:
        return settings, fn(client)
    except (IgnitionAPIError, ValueError) as e:
        if name and isinstance(e, PayloadError) and ("404" in str(e) or "not found" in str(e).lower()):
            e = PayloadError(f"device '{name}' not found.")
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    finally:
        client.close()


def _scan(settings: Settings, scan: bool) -> None:
    if not scan:
        return
    try:
        with ScanClient(settings) as sc:
            sc.scan_config()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed; the change may not be picked up. Reason: {e}", err=True)


def _json(r: Any) -> Any:
    return r.json() if r.text else {}


def _signature(client: IgnitionAPIClient, name: str) -> str:
    found = _json(client.request("GET", f"{_BASE}/find/{_MODULE}/{name}"))
    sig = found.get("signature") if isinstance(found, dict) else None
    if not sig:
        raise ValueError(f"gateway returned no signature for device '{name}'.")
    return sig


def check_program(text: str) -> None:
    """Reject a simulator program whose header is not the 4-column 8.3 format."""
    first = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    cols = [c.strip().strip('"') for c in first.split(",")]
    if cols != PROGRAM_HEADER:
        raise ValueError(
            f"program header must be '{', '.join(PROGRAM_HEADER)}'; got '{first}'. "
            "Export one from the gateway (ign device program-get) to see the format."
        )


def _put_program(client: IgnitionAPIClient, name: str, data: bytes) -> Any:
    sig = _signature(client, name)
    path = f"{_BASE}/datafile/{_MODULE}/{name}/{PROGRAM_FILE}?signature={sig}"
    return _json(client.request("PUT", path, content=data, content_type="text/csv"))


def _read_program(path: Path) -> bytes:
    data = path.read_bytes()
    check_program(data.decode("utf-8"))
    return data


def _confirm(confirm: bool, prompt: str) -> None:
    if not confirm and sys.stdin.isatty():
        typer.confirm(prompt, abort=True)


@device_app.command("list")
def list_cmd() -> None:
    """List all device connections."""
    _, out = _run(None, lambda c: _json(c.request("GET", f"{_BASE}/list/{_MODULE}")))
    typer.echo(json.dumps(out, indent=2))


@device_app.command("get")
def get_cmd(name: Annotated[str, typer.Option("--name", help="Device name.")]) -> None:
    """Get one device connection (config and signature)."""
    _, out = _run(name, lambda c: _json(c.request("GET", f"{_BASE}/find/{_MODULE}/{name}")))
    typer.echo(json.dumps(out, indent=2))


@device_app.command("describe")
def describe_cmd() -> None:
    """Describe the device resource type: driver types and their settings schemas."""
    _, out = _run(None, lambda c: _json(c.request("GET", f"{_BASE}/type/{_MODULE}")))
    typer.echo(json.dumps(out, indent=2))


@device_app.command("create")
def create_cmd(
    name: Annotated[str, typer.Option("--name", help="Device name.")],
    type_: Annotated[str, typer.Option("--type", help=f"Driver type code, e.g. {SIM_TYPE}, ModbusTcp. See `ign device describe`.")] = SIM_TYPE,
    settings_file: Annotated[
        str | None,
        typer.Option("--settings-file", help="JSON file (or '-') with the type-specific settings object. "
                     f"Defaults to {SIM_DEFAULT_SETTINGS} for {SIM_TYPE}, else {{}}."),
    ] = None,
    description: Annotated[str, typer.Option("--description")] = "",
    disabled: Annotated[bool, typer.Option("--disabled", help="Create the device disabled.")] = False,
    program: Annotated[
        Path | None,
        typer.Option("--program", help=f"Simulator program CSV to load as {PROGRAM_FILE} after create.", exists=True, dir_okay=False),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the payload; no API call.")] = False,
    confirm: Annotated[bool, typer.Option("--confirm", help="Skip the confirmation prompt.")] = False,
    scan: Annotated[bool, typer.Option("--scan/--no-scan", help="POST scan/config afterwards. Default: scan.")] = True,
) -> None:
    """Create a device connection; with --program, also load the simulator program."""
    try:
        if settings_file is None:
            dev_settings: dict[str, Any] = dict(SIM_DEFAULT_SETTINGS) if type_ == SIM_TYPE else {}
        else:
            text = sys.stdin.read() if settings_file == "-" else Path(settings_file).read_text(encoding="utf-8")
            dev_settings = json.loads(text)
        data = _read_program(program) if program else None
    except (OSError, ValueError) as e:  # JSONDecodeError and bad CSV header are ValueErrors
        render_error(ValueError(str(e)), no_color=False)
        raise typer.Exit(code=1) from None

    payload = [{
        "name": name,
        "collection": "core",
        "enabled": not disabled,
        "description": description,
        "config": {"profile": {"type": type_}, "settings": dev_settings},
    }]
    if dry_run:
        typer.echo(json.dumps(payload, indent=2))
        if program:
            typer.echo(f"then PUT {_BASE}/datafile/{_MODULE}/{name}/{PROGRAM_FILE} ({len(data or b'')} bytes)")
        return

    _confirm(confirm, f"Create device '{name}' ({type_})?")

    def go(c: IgnitionAPIClient) -> Any:
        out = {"create": _json(c.request("POST", f"{_BASE}/{_MODULE}", json=payload))}
        if data is not None:
            out["program"] = _put_program(c, name, data)
        return out

    settings, out = _run(None, go)
    typer.echo(json.dumps(out, indent=2))
    _scan(settings, scan)


@device_app.command("program")
def program_cmd(
    name: Annotated[str, typer.Option("--name", help="Device name.")],
    file: Annotated[Path, typer.Option("--file", help="Program CSV (Time Interval, Browse Path, Value Source, Data Type).", exists=True, dir_okay=False)],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate the CSV and print the target; no API call.")] = False,
    confirm: Annotated[bool, typer.Option("--confirm", help="Skip the confirmation prompt.")] = False,
    scan: Annotated[bool, typer.Option("--scan/--no-scan", help="POST scan/config afterwards. Default: scan.")] = True,
) -> None:
    """Load or replace a Programmable Device Simulator program (instructions.csv)."""
    try:
        data = _read_program(file)
    except (OSError, ValueError) as e:
        render_error(ValueError(str(e)), no_color=False)
        raise typer.Exit(code=1) from None
    if dry_run:
        rows = max(len(data.decode("utf-8").strip().splitlines()) - 1, 0)
        typer.echo(f"PUT {_BASE}/datafile/{_MODULE}/{name}/{PROGRAM_FILE} ({rows} instruction rows)")
        return
    _confirm(confirm, f"Replace the program of device '{name}'?")
    settings, out = _run(name, lambda c: _put_program(c, name, data))
    typer.echo(json.dumps(out, indent=2))
    _scan(settings, scan)


@device_app.command("program-get")
def program_get_cmd(name: Annotated[str, typer.Option("--name", help="Device name.")]) -> None:
    """Print a simulator device's program CSV."""
    _, r = _run(name, lambda c: c.request("GET", f"{_BASE}/datafile/{_MODULE}/{name}/{PROGRAM_FILE}"))
    typer.echo(r.text, nl=False)


@device_app.command("delete")
def delete_cmd(
    name: Annotated[str, typer.Option("--name", help="Device name.")],
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
    scan: Annotated[bool, typer.Option("--scan/--no-scan", help="POST scan/config afterwards. Default: scan.")] = True,
) -> None:
    """Delete a device connection."""
    if not yes:
        typer.confirm(f"Delete device '{name}'?", abort=True)
    settings, out = _run(name, lambda c: _json(c.request("DELETE", f"{_BASE}/{_MODULE}/{name}/{_signature(c, name)}")))
    typer.echo(json.dumps(out, indent=2))
    _scan(settings, scan)
