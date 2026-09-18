"""Live-gateway smoke test for `ign db-conn`.

Opt-in only: runs solely under `pytest -m smoke`. The whole module is
skipped at import time when `IGNITION_URL` is not set in the
environment (`.env`-loaded settings are the
only credential source; tests must skip cleanly off-gateway).

Round-trip lifecycle:
  1. `ign db-conn names` → assert Demo_DB present (skip if absent — do
     NOT auto-create; that would leak gateway state across runs).
  2. `ign db-conn get Demo_DB` → snapshot envelope, extract `["config"]`
     (NOT the full envelope; the gateway POST body shape is the inner
     25-field ConnectionConfig only).
  3. `ign db-conn delete --name Demo_DB --yes --no-scan`.
  4. `ign db-conn create --name Demo_DB --config-file <snapshot> --no-scan`.
  5. `ign db-conn get Demo_DB` → re-extract inner config; equals original.
  6. `ign diff database-connections Demo_DB --current-file <snapshot>`
     → exit 0, "No diff".

Token-hygiene contract: every subprocess invocation runs through
`_assert_no_token_leak(result)` which scans stdout AND stderr for the
IGNITION_API_TOKEN value. Any leak fails the test loudly.

Dry-run path: a single test exercises `--dry-run` and confirms
no gateway-side state change.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

# Module-level skip: this test requires a live gateway. Skip cleanly when
# IGNITION_URL is unset (the local dev / CI default).
if not os.getenv("IGNITION_URL"):
    pytest.skip(
        "IGNITION_URL not set; live smoke disabled",
        allow_module_level=True,
    )

# Mark the whole module so it only runs under `pytest -m smoke`.
pytestmark = pytest.mark.smoke


def _assert_no_token_leak(result: subprocess.CompletedProcess) -> None:
    """Enforcement: the IGNITION_API_TOKEN value must NEVER appear in
    subprocess stdout OR stderr. Read the key from os.environ at call time
    (it is the same one the subprocess uses via .env)."""
    key = os.environ.get("IGNITION_API_TOKEN", "")
    if not key:
        # Without a key in the environment, this assertion is vacuous —
        # explicitly skip so we never report a false-green pass.
        pytest.skip("IGNITION_API_TOKEN not set; token-leak check vacuous")
    out = result.stdout or ""
    err = result.stderr or ""
    assert key not in out, "API token leaked in subprocess stdout"
    assert key not in err, "API token leaked in subprocess stderr"


def _run(*args: str, input_str: str | None = None) -> subprocess.CompletedProcess:
    """Invoke the installed `ign` entry point as a subprocess (real shell
    path the user takes). `check=False` so callers can assert on exit code."""
    return subprocess.run(
        ["ign", *args],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
        input=input_str,
    )


def _names_list(result: subprocess.CompletedProcess) -> list[str]:
    """Parse `ign db-conn names` stdout into a list of connection names.

    The CLI emits a JSON list — handle both `[{"name": "X", ...}, ...]` and
    `["X", ...]` shapes defensively."""
    items = json.loads(result.stdout)
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and "name" in item:
            out.append(item["name"])
        elif isinstance(item, str):
            out.append(item)
    return out


def test_smoke_lifecycle(tmp_path: Path) -> None:
    """Demo_DB get → snapshot → delete → recreate → diff round-trip.

    Leaves Demo_DB created on the gateway so the next run of this test
    still finds the canonical seed. Uses --no-scan throughout to keep the
    test fast and not generate scan-noise.
    """
    # (a) Names — Demo_DB must be present (gateway seed).
    r = _run("db-conn", "names")
    _assert_no_token_leak(r)
    assert r.returncode == 0, f"names failed: stderr={r.stderr!r}"
    names = _names_list(r)
    if "Demo_DB" not in names:
        pytest.skip(
            "Demo_DB connection not present on gateway; recreate via Gateway "
            "UI or raw API first."
        )

    # (b) Get full envelope; extract inner ConnectionConfig (not the envelope).
    r = _run("db-conn", "get", "Demo_DB")
    _assert_no_token_leak(r)
    assert r.returncode == 0, f"get Demo_DB failed: stderr={r.stderr!r}"
    envelope = json.loads(r.stdout)
    assert "config" in envelope, (
        "GET envelope missing 'config' key; ign db-conn get changed shape"
    )
    inner_original = envelope["config"]
    assert inner_original["driver"] == "SQLite"
    assert inner_original["translator"] == "SQLITE"

    # (c) Write inner config to a snapshot file (NOT envelope).
    snapshot = tmp_path / "demo_db_inner.json"
    snapshot.write_text(json.dumps(inner_original, indent=2, sort_keys=True))

    try:
        # (d) Delete --yes --no-scan; verify absent.
        r = _run("db-conn", "delete", "--name", "Demo_DB", "--yes", "--no-scan")
        _assert_no_token_leak(r)
        assert r.returncode == 0, f"delete failed: stderr={r.stderr!r}"

        r = _run("db-conn", "names")
        _assert_no_token_leak(r)
        assert r.returncode == 0
        assert "Demo_DB" not in _names_list(r), (
            "Demo_DB still present after delete"
        )

        # (e) Recreate from snapshot; verify present.
        r = _run(
            "db-conn",
            "create",
            "--name",
            "Demo_DB",
            "--config-file",
            str(snapshot),
            "--no-scan",
        )
        _assert_no_token_leak(r)
        assert r.returncode == 0, f"create failed: stderr={r.stderr!r}"

        r = _run("db-conn", "names")
        _assert_no_token_leak(r)
        assert r.returncode == 0
        assert "Demo_DB" in _names_list(r), "Demo_DB missing after create"

        # (f) Round-trip fidelity — get again, inner config equals original.
        r = _run("db-conn", "get", "Demo_DB")
        _assert_no_token_leak(r)
        assert r.returncode == 0
        roundtrip_envelope = json.loads(r.stdout)
        inner_after = roundtrip_envelope["config"]
        assert inner_after == inner_original, (
            "Inner ConnectionConfig drifted across delete→create round-trip"
        )

        # (g) Diff against the manifest entry written by step (e); no drift.
        r = _run(
            "diff",
            "database-connections",
            "Demo_DB",
            "--current-file",
            str(snapshot),
        )
        _assert_no_token_leak(r)
        assert r.returncode == 0, f"diff exit {r.returncode}: stderr={r.stderr!r}"
        assert "No diff" in r.stdout, (
            f"diff stdout missing 'No diff' literal: {r.stdout!r}"
        )
    finally:
        # (h) Best-effort cleanup: ensure Demo_DB is restored on the gateway.
        # Idempotent: if it already exists, delete-then-create. If absent
        # (e.g., test died between delete and create), create from snapshot.
        r = _run("db-conn", "names")
        if r.returncode == 0 and "Demo_DB" not in _names_list(r):
            _run(
                "db-conn",
                "create",
                "--name",
                "Demo_DB",
                "--config-file",
                str(snapshot),
                "--no-scan",
            )


def test_smoke_dry_run_path(tmp_path: Path) -> None:
    """--dry-run prints a JSON preview AND makes NO gateway change.

    Uses a synthetic name "SmokeDryRun" + the Demo_DB fixture content so we
    do not need Demo_DB to be present for this case.
    """
    # Snapshot a minimal SQLite config from the package fixtures (the
    # test_db_conn_model fixtures are checked in; safe to reference).
    here = Path(__file__).resolve().parent
    fixture = (
        here.parent / "fixtures" / "database-connections" / "Demo_DB.json"
    )
    assert fixture.exists(), f"missing fixture: {fixture}"
    snapshot = tmp_path / "dryrun_inner.json"
    snapshot.write_text(fixture.read_text())

    r = _run(
        "db-conn",
        "create",
        "--name",
        "SmokeDryRun",
        "--config-file",
        str(snapshot),
        "--dry-run",
        "--no-scan",
    )
    _assert_no_token_leak(r)
    assert r.returncode == 0, f"dry-run failed: stderr={r.stderr!r}"
    # Stdout must parse as JSON and reference the synthetic name + a config.
    body = json.loads(r.stdout)
    assert body.get("name") == "SmokeDryRun"
    assert "config" in body, "dry-run JSON missing 'config' key"

    # Verify no side-effect: SmokeDryRun NOT on the gateway.
    r = _run("db-conn", "names")
    _assert_no_token_leak(r)
    assert r.returncode == 0
    assert "SmokeDryRun" not in _names_list(r), (
        "dry-run leaked a connection onto the gateway — dry-run contract "
        "broken"
    )
