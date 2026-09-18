"""Unit tests for _make_jwe_guard event hook.

Tests the factory-returned hook in isolation:
- Fires and raises PayloadError for a flat JWE body
- Fires for a nested JWE body (recursive _walk_jwe)
- Passes (no exception) for non-JWE JSON, empty body, and non-JSON binary body
- Verifies the hook is registered on IgnitionAPIClient._client.event_hooks

These are distinct from test_gen_transport_shared.py which tests the broader
transport injection and shared httpx.Client contract. This file focuses on
the guard factory itself and the recursive walk logic.
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import json

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jwe_payload(**overrides) -> bytes:
    """Return a minimal JWE-shaped JSON body as bytes."""
    payload = {
        "ciphertext": "abc123",
        "encrypted_key": "def456",
        "iv": "ghi789",
        "protected": "jkl012",
        "tag": "mno345",
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def _req(content: bytes) -> httpx.Request:
    return httpx.Request("POST", f"{GATEWAY_URL}/test", content=content)


# ---------------------------------------------------------------------------
# flat JWE body raises PayloadError with "JWE refusal" in message
# ---------------------------------------------------------------------------

def test_jwe_guard_fires_for_jwe_body() -> None:
    """_make_jwe_guard raises PayloadError containing 'JWE refusal' for a JWE body."""
    from ignition_gen_sdk.backends.api_client import _make_jwe_guard, PayloadError
    from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

    guard = _make_jwe_guard(JWE_KEYS_REQUIRED)
    req = _req(_jwe_payload())

    with pytest.raises(PayloadError, match="JWE credential"):
        guard(req)


# ---------------------------------------------------------------------------
# ordinary non-JWE body passes silently
# ---------------------------------------------------------------------------

def test_jwe_guard_passes_non_jwe_body() -> None:
    """_make_jwe_guard does not raise for an ordinary JSON body."""
    from ignition_gen_sdk.backends.api_client import _make_jwe_guard
    from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

    guard = _make_jwe_guard(JWE_KEYS_REQUIRED)
    req = _req(json.dumps({"name": "Demo_DB"}).encode())
    guard(req)  # must not raise


# ---------------------------------------------------------------------------
# empty body passes silently (< 20 bytes short-circuit)
# ---------------------------------------------------------------------------

def test_jwe_guard_passes_empty_body() -> None:
    """_make_jwe_guard silently skips an empty request body."""
    from ignition_gen_sdk.backends.api_client import _make_jwe_guard
    from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

    guard = _make_jwe_guard(JWE_KEYS_REQUIRED)
    req = _req(b"")
    guard(req)  # must not raise


# ---------------------------------------------------------------------------
# binary / non-JSON body passes silently
# ---------------------------------------------------------------------------

def test_jwe_guard_passes_non_json_body() -> None:
    """_make_jwe_guard silently skips non-JSON binary body (UnicodeDecodeError / JSONDecodeError path)."""
    from ignition_gen_sdk.backends.api_client import _make_jwe_guard
    from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

    guard = _make_jwe_guard(JWE_KEYS_REQUIRED)
    req = _req(b"\x80\xff binary data here xyz")
    guard(req)  # must not raise


# ---------------------------------------------------------------------------
# JWE nested inside a list raises PayloadError (recursive _walk_jwe)
# ---------------------------------------------------------------------------

def test_jwe_guard_fires_for_nested_jwe() -> None:
    """_make_jwe_guard catches a JWE dict nested inside a list (recursive walk)."""
    from ignition_gen_sdk.backends.api_client import _make_jwe_guard, PayloadError
    from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

    guard = _make_jwe_guard(JWE_KEYS_REQUIRED)

    nested = {
        "connections": [
            {"name": "safe"},
            {
                "ciphertext": "x",
                "encrypted_key": "y",
                "iv": "z",
                "protected": "h",
                "tag": "t",
            },
        ]
    }
    req = _req(json.dumps(nested).encode())

    with pytest.raises(PayloadError, match="JWE credential"):
        guard(req)


# ---------------------------------------------------------------------------
# event_hooks["request"] on IgnitionAPIClient._client contains the guard
# ---------------------------------------------------------------------------

def test_jwe_guard_fires_both_paths() -> None:
    """IgnitionAPIClient._client.event_hooks['request'] is non-empty (guard registered)."""
    from ignition_gen_sdk.config import Settings
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

    settings = Settings(
        ignition_api_key="test:testkey1234",
        ignition_base_url=GATEWAY_URL,
    )
    client = IgnitionAPIClient(settings)
    try:
        hooks = client._client.event_hooks
        assert "request" in hooks, "event_hooks has no 'request' key"
        assert len(hooks["request"]) > 0, (
            "event_hooks['request'] is empty — JWE guard not registered"
        )
    finally:
        client.close()
