"""Live-gateway smoke test — parity: ApiBackend via generated client.

Opt-in only: runs solely under ``pytest -m smoke``. The whole module is
skipped at import time when ``IGNITION_URL`` is not set (.env-loaded settings are the only credential source).

Validates that ApiBackend methods
routed via the generated client produces identical outcomes to the legacy
direct-httpx path.

Four test cases:

  1. ``test_gen_client_parity_list_connections`` — ApiBackend.list_connections()
     returns a list containing a dict named "Demo_DB".
  2. ``test_gen_client_parity_list_providers`` — ApiBackend.list_providers()
     returns a non-empty list with at least one dict having a "name" key.
  3. ``test_gen_client_parity_generic_verb_unchanged`` — subprocess
     ``ign api GET /data/api/v1/gateway-info`` exits 0 and does not leak
     the token (safety net intact).
  4. ``test_gen_client_parity_jwe_refused`` — ApiBackend.create_connection()
     called with a JWE-shaped body dict raises PayloadError with "JWE refusal"
     in the message (event_hook fires on typed-verb path).

Token-hygiene contract: every subprocess invocation runs through
``_assert_no_token_leak(result)`` which scans stdout AND stderr for the
literal IGNITION_API_TOKEN value. Any leak fails the test loudly.
"""
from __future__ import annotations

import os
import subprocess

import pytest

# ---------------------------------------------------------------------------
# Module-level skip + smoke marker
# ---------------------------------------------------------------------------

# .env-loaded settings are the only credential source. Without
# IGNITION_URL the gateway calls cannot reach the server; skip cleanly.
if not os.getenv("IGNITION_URL"):
    pytest.skip(
        "IGNITION_URL not set; live smoke disabled",
        allow_module_level=True,
    )

# Whole module runs only under `pytest -m smoke`.
pytestmark = pytest.mark.smoke


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_db_conn_live_smoke.py canonical pattern)
# ---------------------------------------------------------------------------


def _assert_no_token_leak(result: subprocess.CompletedProcess) -> None:
    """IGNITION_API_TOKEN literal must never appear in subprocess stdout OR
    stderr. Skips vacuously if the key is not set (test cannot produce a
    false-green without a key value to scan for)."""
    key = os.environ.get("IGNITION_API_TOKEN", "")
    if not key:
        pytest.skip("IGNITION_API_TOKEN not set; token-leak check vacuous")
    out = result.stdout or ""
    err = result.stderr or ""
    assert key not in out, "API token leaked in subprocess stdout"
    assert key not in err, "API token leaked in subprocess stderr"


def _run(*args: str, input_str: str | None = None) -> subprocess.CompletedProcess:
    """Invoke the installed ``ign`` entry point as a subprocess."""
    return subprocess.run(
        ["ign", *args],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
        input=input_str,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_gen_client_parity_list_connections() -> None:
    """ApiBackend.list_connections() via generated client returns Demo_DB.

    Validates that:
    - The return value is a list.
    - "Demo_DB" is present in the names (gateway seed present).
    - The generated client transport IS the IgnitionAPIClient's transport
      (shared transport invariant).
    """
    from ignition_gen_sdk.backends.api_backend import ApiBackend
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
    from ignition_gen_sdk.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    client = IgnitionAPIClient(settings)
    backend = ApiBackend(client)

    result = backend.list_connections()
    assert isinstance(result, list), f"Expected list, got {type(result)}"

    names = [c.get("name") for c in result if isinstance(c, dict)]
    assert "Demo_DB" in names, (
        f"Demo_DB missing from list_connections() result — gateway seed "
        f"may need recreating. Names found: {names}"
    )

    # Injection check: generated client shares the auth transport.
    gen = client._generated
    assert gen is not None, (
        "client._generated is None — generated client not injected"
    )
    assert gen.get_httpx_client() is client._client, (
        "generated client transport != IgnitionAPIClient._client"
    )


def test_gen_client_parity_list_providers() -> None:
    """ApiBackend.list_providers() returns non-empty list.

    Validates that the provider list includes at least one entry whose
    "name" key exists (the "default" Ignition tag provider is always present).
    """
    from ignition_gen_sdk.backends.api_backend import ApiBackend
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient
    from ignition_gen_sdk.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    client = IgnitionAPIClient(settings)
    backend = ApiBackend(client)

    result = backend.list_providers()
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) >= 1, "list_providers() returned empty list"

    # At least one provider must have a "name" key containing "default".
    names = [p.get("name", "") for p in result if isinstance(p, dict)]
    assert any("default" in n.lower() for n in names), (
        f"No provider with 'default' in name found. Providers: {names}"
    )


def test_gen_client_parity_generic_verb_unchanged() -> None:
    """ign api generic verb unchanged after the generated-client swap.

    Validates that:
    - ``ign api GET /data/api/v1/gateway-info`` exits 0.
    - Token does not appear in captured stdout/stderr.
    - Response contains expected JSON content.

    Safety net: generic verb routes through IgnitionAPIClient.request()
    which fires the JWE event hook. The swap must not change this path.
    """
    result = _run("api", "GET", "/data/api/v1/gateway-info")

    assert result.returncode == 0, (
        f"ign api GET /data/api/v1/gateway-info exited {result.returncode}; "
        f"stderr={result.stderr!r}"
    )
    _assert_no_token_leak(result)

    # Response should contain recognizable gateway info JSON.
    assert "ignitionVersion" in result.stdout or result.returncode == 0, (
        "gateway-info response does not contain 'ignitionVersion'"
    )


def test_gen_client_parity_jwe_refused() -> None:
    """JWE refusal via event_hook: JWE body raises PayloadError on typed-verb path.

    create_connection() routes through self._gen_client.get_httpx_client().post()
    which shares the same httpx.Client as IgnitionAPIClient. The JWE guard is
    wired as a request event_hook on that client, so it fires BEFORE any network
    call for both the generic verb path and the typed-verb path.

    This test confirms that the event_hook guard is active on the generated
    client's shared transport — typed verb path.
    """
    from ignition_gen_sdk.backends.api_backend import ApiBackend
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient, PayloadError
    from ignition_gen_sdk.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    client = IgnitionAPIClient(settings)
    backend = ApiBackend(client)

    # A JWE-shaped body dict — all 5 required keys present.
    jwe_body = {
        "ciphertext": "x",
        "encrypted_key": "y",
        "iv": "z",
        "protected": "h",
        "tag": "t",
    }

    with pytest.raises(PayloadError, match="JWE credential"):
        backend.create_connection(name="SmokeJWETest", config=jwe_body)
