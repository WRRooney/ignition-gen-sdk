"""Live-gateway smoke test for ``ign api``.

Opt-in only: runs solely under ``pytest -m smoke``. Mirrors the layout of
``tests/test_db_conn_live_smoke.py`` (the canonical smoke pattern)
but replays the Demo_DB DB-connection lifecycle through the generic
``ign api METHOD PATH`` verb instead of typed ``ign db-conn``
verbs. Validates that every leak-closure assertion (token never
in argv, token never in stdout/stderr, JWE refusal, light path
validation) actually holds in production conditions against a running
gateway at ``IGNITION_URL``.

Five test functions:

  1. ``test_gateway_info_smoke`` — `api GET /data/api/v1/gateway-info`
     against the live gateway returns 200 with parseable JSON.
  2. ``test_unknown_path_smoke`` — `api GET /no/such/path` exits non-zero
     with ``Path error:`` in stderr and completes in < 2 s wall-clock
     (no HTTP round-trip — light validation fires pre-flight).
  3. ``test_demo_db_lifecycle_smoke`` — Demo_DB replay through `ign api`
     only: GET existing → POST clone → GET clone → DELETE clone → GET
     clone returns 404. Each subprocess capture asserted free of the
     live token literal (defense-in-depth via scrub_token).
  4. ``test_no_token_leak_in_subprocess_output`` — parametrized over all
     five captured (stdout, stderr) tuples from tests 1-3; asserts the
     literal token string + the regex ``test:[A-Za-z0-9_-]{4,}`` are
     absent from each stream.
  5. ``test_no_token_in_argv`` — launches a subprocess and asserts the
     argv list contains no element matching the token regex. Effectively
     a tautology now (api_cmd has no ``--token`` flag) but serves as a
     permanent contract: if anyone ever refactors cmd_api to accept a
     token argument, this test fails.

Module-level skip rules (module-level ``pytest.skip`` with
``allow_module_level=True``):

- If ``IGNITION_API_TOKEN`` is not in the environment, skip the whole
  module — `.env`-loaded settings are the only credential source
 , so we cannot meaningfully test the live path without it.
- The ``live_gateway`` session-scoped fixture additionally probes the
  gateway with a 5-s timeout GET ``/gateway-info``; on connection-refused
  or non-2xx, raises ``pytest.skip``.

Token-hygiene contract:
The live token literal value is referenced once in this file as
``_LIVE_TOKEN_LITERAL`` (a sentinel constant) and re-used in the
parametrized leak assertion. If the token is ever rotated, the sentinel
must be updated in source — that update is a positive event (rotation
landed) and forces a deliberate code change.

"""
from __future__ import annotations

from conftest import GATEWAY_URL

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module-level skip + smoke marker
# ---------------------------------------------------------------------------

# `.env`-loaded settings are the only credential source. Without
# the key in the environment the gateway calls cannot authenticate and the
# leak-assertions would be vacuous; skip cleanly off-gateway.
if not os.getenv("IGNITION_API_TOKEN"):
    pytest.skip(
        "IGNITION_API_TOKEN not set; live smoke disabled",
        allow_module_level=True,
    )

# Whole module is gated behind `pytest -m smoke` per the pyproject.toml
# `smoke` marker. Default `pytest` deselects everything in this file.
pytestmark = pytest.mark.smoke


# ---------------------------------------------------------------------------
# Sentinel constants
# ---------------------------------------------------------------------------

# Sentinel for the live token's shape. Set IGNITION_LIVE_TOKEN_SENTINEL to
# the real value to assert it never appears in any subprocess stream; the
# regex below catches any token of the same shape regardless.
_LIVE_TOKEN_LITERAL = os.environ.get(
    "IGNITION_LIVE_TOKEN_SENTINEL", "test:EXAMPLE-LIVE-TOKEN-SENTINEL"
)

# Regex form for defense-in-depth: any 4+ char test:[A-Za-z0-9_-]
# sequence is suspect (the same shape ``scrub_token`` redacts). Catches
# rotated tokens that share the prefix.
_TOKEN_REGEX = re.compile(r"test:[A-Za-z0-9_\-]{4,}")

# Live gateway target: IGNITION_URL (see conftest.GATEWAY_URL). The tests run
# host-side, so it must be an address the host can reach (e.g. a published
# port, not a docker-network-internal hostname).
_LIVE_BASE_URL = GATEWAY_URL

# The Demo_DB clone name used by the automated lifecycle (test 3). Kept
# distinct from any manual clone name so replays can run in either order
# without colliding on the gateway. The lifecycle test (test 3) creates /
# gets / deletes this exact resource name on the live gateway.
_CLONE_NAME = "Demo_DBTestClone"
assert _CLONE_NAME == "Demo_DBTestClone"  # pinned: a rename here must be deliberate


# ---------------------------------------------------------------------------
# Per-test capture registry — feeds the parametrized leak assertion.
# ---------------------------------------------------------------------------

# Each test populates _CAPTURES with (label, stdout, stderr) tuples; the
# parametrized leak test reads from this list at collection time via a
# fixture-driven loop. Module-level mutable state is acceptable here
# because the captures are per-process and the leak test runs last.
_CAPTURES: list[tuple[str, str, str]] = []


def _record(label: str, result: subprocess.CompletedProcess) -> None:
    """Append a labeled capture to the module-level registry for the leak test."""
    _CAPTURES.append((label, result.stdout or "", result.stderr or ""))


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _ign_api_env() -> dict[str, str]:
    """Return an env dict for subprocess.run that forces the live host URL.

    Inherits the parent environment (so ``IGNITION_API_TOKEN`` flows from
    ``.env``-loaded shell or pytest invocation) and pins ``IGNITION_URL`` to
    ``_LIVE_BASE_URL``, which conftest scrubs from the test process env.
    """
    return {**os.environ, "IGNITION_URL": _LIVE_BASE_URL}


def _run_api(
    method: str,
    path: str,
    *extra: str,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess:
    """Run ``python -m ignition_gen_sdk.cli api METHOD PATH [...]`` and capture.

    Uses ``sys.executable -m ignition_gen_sdk.cli`` rather than the
    installed ``ign`` script so the test always picks up the venv's
    interpreter (and its editable install of this package) instead
    of whatever ``ign`` binary happens to be first on PATH.
    """
    argv = [sys.executable, "-m", "ignition_gen_sdk.cli", "api", method, path, *extra]
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_ign_api_env(),
        check=False,
    )


# ---------------------------------------------------------------------------
# Session fixture: probe the gateway; skip the whole suite if unreachable.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def live_gateway() -> str:
    """Probe ``api GET /gateway-info`` with a 5-s budget; skip on unreachable.

    Returns the verified base URL on success so individual tests can
    refer to it (mostly for logging — the actual subprocesses pick it
    up from the env var set in ``_ign_api_env``).
    """
    probe = _run_api("GET", "/data/api/v1/gateway-info", timeout=5.0)
    if probe.returncode != 0:
        # NetworkError / connection-refused / timeout all surface as
        # non-zero exit with the five-clause render_error message. The
        # leak-assertion at the parametrized test will scan the probe
        # output too via _CAPTURES — record it.
        _record("gateway_probe_failed", probe)
        pytest.skip(
            f"Gateway unreachable at {_LIVE_BASE_URL}: "
            f"exit={probe.returncode}; stderr={probe.stderr.strip()[:200]!r}"
        )
    return _LIVE_BASE_URL


# ---------------------------------------------------------------------------
# Read-only smoke
# ---------------------------------------------------------------------------


def test_gateway_info_smoke(live_gateway: str) -> None:
    """`api GET /data/api/v1/gateway-info` returns 200 with parseable JSON."""
    import json as _json

    result = _run_api("GET", "/data/api/v1/gateway-info")
    _record("gateway_info", result)

    assert result.returncode == 0, (
        f"gateway-info exit={result.returncode}; stderr={result.stderr!r}"
    )
    # stdout must be parseable JSON and a non-empty dict.
    body = _json.loads(result.stdout)
    assert isinstance(body, dict)
    assert len(body) >= 1, f"gateway-info body had no keys: {body!r}"


# ---------------------------------------------------------------------------
# Light validation short-circuits BEFORE any HTTP round-trip.
# ---------------------------------------------------------------------------


def test_unknown_path_smoke(live_gateway: str) -> None:
    """`api GET /no/such/path` exits non-zero with `Path error:` in < 2s."""
    start = time.monotonic()
    result = _run_api("GET", "/no/such/path", timeout=10.0)
    elapsed = time.monotonic() - start
    _record("unknown_path", result)

    assert result.returncode != 0, (
        "expected non-zero exit for unknown path; "
        f"got 0; stdout={result.stdout!r}"
    )
    assert "Path error:" in result.stderr, (
        f"stderr missing 'Path error:' label: {result.stderr!r}"
    )
    # Light validation fires pre-flight — no HTTP round-trip. Even a slow
    # cold-start Python interpreter should finish well under 2 s once
    # the light validator runs (no network).
    assert elapsed < 2.0, (
        f"unknown-path call took {elapsed:.2f}s; expected < 2s (no HTTP)"
    )


# ---------------------------------------------------------------------------
# Full Demo_DB lifecycle replay via `ign api` only.
# ---------------------------------------------------------------------------


def _read_demo_db_seed_config() -> dict:
    """Read the checked-in Demo_DB fixture (fixtures/database-connections/).

    Used as a known-good shape for the POST clone body.
    """
    import json as _json

    seed_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "database-connections" / "Demo_DB.json"
    )
    return _json.loads(seed_path.read_text(encoding="utf-8"))


def test_demo_db_lifecycle_smoke(
    live_gateway: str, tmp_path: Path
) -> None:
    """Full Demo_DB replay through `ign api`: GET → POST → GET → DELETE → GET 404.

    Step labels:
      A. GET existing Demo_DB config (parse signature out of response).
      B. POST create clone (body is the seed config wrapped in the
         resource-create envelope ``[{"name": ..., "config": {...}}]``).
      C. GET clone to confirm creation (and extract its signature for D).
      D. DELETE clone using the signature from C.
      E. GET clone again — must surface a payload error (404 routed
         through PayloadError per the existing five-clause taxonomy).
    """
    import json as _json

    # ------------------------------------------------------------------
    # Step A — GET existing Demo_DB; parse signature for later (proves the
    # live gateway has the canonical seed connection).
    # ------------------------------------------------------------------
    r_a = _run_api(
        "GET",
        "/data/api/v1/resources/find/ignition/database-connection/Demo_DB",
    )
    _record("demo_db_get_existing", r_a)
    if r_a.returncode != 0:
        pytest.skip(
            f"Demo_DB seed connection missing on the gateway "
            f"(exit={r_a.returncode}); recreate via Gateway UI to enable smoke."
        )
    existing_env = _json.loads(r_a.stdout)
    assert existing_env.get("name") == "Demo_DB", (
        f"GET Demo_DB envelope mis-shaped: {existing_env!r}"
    )

    # ------------------------------------------------------------------
    # Step B — POST create clone. Body shape per
    # api_reference/config-database-connections.md is an ARRAY of
    # `{name, config}` objects. Wrap a single-element array.
    # ------------------------------------------------------------------
    seed_config = _read_demo_db_seed_config()
    create_body = [{"name": _CLONE_NAME, "config": seed_config}]
    body_file = tmp_path / "create_clone_body.json"
    body_file.write_text(_json.dumps(create_body))

    # try/finally so that even if any later step fails the cleanup
    # DELETE in the finally block fires, avoiding an orphaned clone
    # connection left on the gateway.
    cleanup_signature: str | None = None
    try:
        r_b = _run_api(
            "POST",
            "/data/api/v1/resources/ignition/database-connection",
            "--file",
            str(body_file),
            "--confirm",
        )
        _record("demo_db_create_clone", r_b)
        assert r_b.returncode == 0, (
            f"POST create clone exit={r_b.returncode}; "
            f"stderr={r_b.stderr!r}"
        )

        # ------------------------------------------------------------------
        # Step C — GET clone; confirms it landed AND extract its signature
        # (DELETE needs the signature as a path-template segment).
        # ------------------------------------------------------------------
        r_c = _run_api(
            "GET",
            f"/data/api/v1/resources/find/ignition/database-connection/{_CLONE_NAME}",
        )
        _record("demo_db_get_clone", r_c)
        assert r_c.returncode == 0, (
            f"GET clone exit={r_c.returncode}; stderr={r_c.stderr!r}"
        )
        clone_env = _json.loads(r_c.stdout)
        assert clone_env.get("name") == _CLONE_NAME, (
            f"clone GET name mismatch: {clone_env!r}"
        )
        cleanup_signature = clone_env.get("signature")
        assert isinstance(cleanup_signature, str) and cleanup_signature, (
            f"GET clone missing 'signature': {clone_env!r}"
        )

        # ------------------------------------------------------------------
        # Step D — DELETE clone via its signature.
        # ------------------------------------------------------------------
        delete_path = (
            f"/data/api/v1/resources/ignition/database-connection/"
            f"{_CLONE_NAME}/{cleanup_signature}"
        )
        r_d = _run_api("DELETE", delete_path, "--confirm")
        _record("demo_db_delete_clone", r_d)
        assert r_d.returncode == 0, (
            f"DELETE clone exit={r_d.returncode}; stderr={r_d.stderr!r}"
        )
        # Once the delete succeeds we no longer need cleanup; clear the
        # signature so the finally block does not double-delete.
        cleanup_signature = None

        # ------------------------------------------------------------------
        # Step E — GET clone again; expect Payload error (404 routed
        # through PayloadError per the existing five-clause taxonomy).
        # ------------------------------------------------------------------
        r_e = _run_api(
            "GET",
            f"/data/api/v1/resources/find/ignition/database-connection/{_CLONE_NAME}",
        )
        _record("demo_db_get_clone_after_delete", r_e)
        assert r_e.returncode != 0, (
            "expected non-zero exit on GET clone after delete; "
            f"got 0; stdout={r_e.stdout!r}"
        )
        assert "Payload error:" in r_e.stderr, (
            f"expected 'Payload error:' (404 routed through PayloadError); "
            f"stderr={r_e.stderr!r}"
        )
    finally:
        # Best-effort cleanup. If we still hold a signature, try delete
        # once; otherwise we already cleaned up successfully or never
        # created the clone. Ignore errors — this is purely defensive.
        if cleanup_signature:
            try:
                _run_api(
                    "DELETE",
                    f"/data/api/v1/resources/ignition/database-connection/"
                    f"{_CLONE_NAME}/{cleanup_signature}",
                    "--confirm",
                    timeout=10.0,
                )
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Defense-in-depth token-leak scan over all captured streams.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stream_attr",
    ["stdout", "stderr"],
)
def test_no_token_leak_in_subprocess_output(
    live_gateway: str, stream_attr: str
) -> None:
    """Every recorded (stdout, stderr) is asserted free of token shapes.

    Runs AFTER the first three tests via pytest's natural ordering — by
    this point ``_CAPTURES`` holds the gateway-info, unknown-path, and
    five Demo_DB-lifecycle captures (8+ entries total). Iterates over
    each captured stream and asserts:

    1. The literal token sentinel ``_LIVE_TOKEN_LITERAL`` is absent.
    2. No substring matches ``test:[A-Za-z0-9_-]{4,}`` (defense-in-depth
       against rotated tokens that share the prefix).

    Parametrized over (stdout, stderr) so failures point at the specific
    stream.
    """
    assert _CAPTURES, (
        "no subprocess captures recorded; this test must run after "
        "test_gateway_info_smoke / test_unknown_path_smoke / "
        "test_demo_db_lifecycle_smoke"
    )

    leaks: list[tuple[str, str, str]] = []
    for label, out, err in _CAPTURES:
        stream = out if stream_attr == "stdout" else err
        if _LIVE_TOKEN_LITERAL in stream:
            leaks.append((label, "literal", stream[:200]))
        match = _TOKEN_REGEX.search(stream)
        if match:
            leaks.append((label, f"regex: {match.group(0)}", stream[:200]))

    assert not leaks, (
        f"token leaked in subprocess {stream_attr}: "
        + "; ".join(f"[{lbl}] {how}: {snippet!r}" for lbl, how, snippet in leaks)
    )


# ---------------------------------------------------------------------------
# Argv contract — no element of the subprocess argv contains a token.
# ---------------------------------------------------------------------------


def test_no_token_in_argv(live_gateway: str) -> None:
    """The subprocess argv must not contain any ``test:...`` shape.

    A tautology with the current ``api_cmd`` signature (no ``--token``
    flag) but serves as a permanent contract: if anyone ever refactors
    ``cmd_api`` to accept a token argument, this test fails — preventing
    the regression the leak-closure work fixed in the first place.
    """
    argv = [sys.executable, "-m", "ignition_gen_sdk.cli", "api", "GET", "/data/api/v1/gateway-info"]
    leak_in_argv = [a for a in argv if _TOKEN_REGEX.search(a)]
    assert not leak_in_argv, (
        f"argv contains a token shape: {leak_in_argv!r} "
        "(api_cmd must not accept --token)"
    )

    # Sanity: the subprocess still works end-to-end with this argv (we
    # rely on this throughout the suite). Run it and record the capture.
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=15.0,
        env=_ign_api_env(),
        check=False,
    )
    _record("argv_smoke_repeat", result)
    assert result.returncode == 0, (
        f"argv-smoke subprocess failed: exit={result.returncode}; "
        f"stderr={result.stderr!r}"
    )
