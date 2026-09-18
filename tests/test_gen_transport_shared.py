"""Tests for shared transport layer: JWE guard event hook + generated client injection.

set_httpx_client() injection shares auth between generated + raw paths.
The JWE guard event hook fires for both paths and raises PayloadError.
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import json

import httpx
import pytest


# ---------------------------------------------------------------------------
# ModuleNotFoundError fallback — _generated is None when package absent
# ---------------------------------------------------------------------------

def test_generated_is_none_when_package_missing(monkeypatch):
    """When ignition_api_client is not installed, _generated attribute is None."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ignition_api_client":
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # Re-import to get a fresh client with patched import
    from ignition_gen_sdk.config import Settings
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

    settings = Settings(
        ignition_api_key="test:testkey1234",
        ignition_base_url=GATEWAY_URL,
    )
    client = IgnitionAPIClient(settings)
    assert client._generated is None, (
        "_generated must be None when ignition_api_client is not installed"
    )
    client.close()


# ---------------------------------------------------------------------------
# When generated package IS present, injection check
# ---------------------------------------------------------------------------

def test_generated_client_shares_transport():
    """Generated client's httpx.Client IS the IgnitionAPIClient's client."""
    try:
        from ignition_api_client import Client  # noqa: F401
    except ModuleNotFoundError:
        pytest.skip("ignition_api_client not installed; skip injection check")

    from ignition_gen_sdk.config import Settings
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

    settings = Settings(
        ignition_api_key="test:testkey1234",
        ignition_base_url=GATEWAY_URL,
    )
    client = IgnitionAPIClient(settings)

    assert client._generated is not None, (
        "ignition_api_client is installed but _generated is None — injection failed"
    )
    # The critical assertion: same httpx.Client object
    assert client._generated.get_httpx_client() is client._client, (
        "generated client does not share the auth transport (set_httpx_client not called)"
    )
    client.close()


# ---------------------------------------------------------------------------
# _make_jwe_guard raises PayloadError for JWE body
# ---------------------------------------------------------------------------

def test_jwe_guard_raises_for_jwe_body():
    """_make_jwe_guard fires and raises PayloadError with 'JWE refusal' in message."""
    from ignition_gen_sdk.backends.api_client import _make_jwe_guard, PayloadError
    from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

    guard = _make_jwe_guard(JWE_KEYS_REQUIRED)

    jwe_payload = {
        "ciphertext": "abc123",
        "encrypted_key": "def456",
        "iv": "ghi789",
        "protected": "jkl012",
        "tag": "mno345",
    }
    body_bytes = json.dumps(jwe_payload).encode()
    req = httpx.Request("POST", f"{GATEWAY_URL}/test", content=body_bytes)

    with pytest.raises(PayloadError, match="JWE credential"):
        guard(req)


# ---------------------------------------------------------------------------
# _make_jwe_guard passes for non-JWE body
# ---------------------------------------------------------------------------

def test_jwe_guard_passes_for_non_jwe_body():
    """_make_jwe_guard does not raise for an ordinary JSON body."""
    from ignition_gen_sdk.backends.api_client import _make_jwe_guard
    from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

    guard = _make_jwe_guard(JWE_KEYS_REQUIRED)

    ordinary_payload = {"name": "Demo_DB", "type": "mysql", "enabled": True}
    body_bytes = json.dumps(ordinary_payload).encode()
    req = httpx.Request("POST", f"{GATEWAY_URL}/test", content=body_bytes)

    # Should not raise
    guard(req)


# ---------------------------------------------------------------------------
# _make_jwe_guard passes for short body (< 20 bytes)
# ---------------------------------------------------------------------------

def test_jwe_guard_passes_for_short_body():
    """_make_jwe_guard skips bodies shorter than 20 bytes."""
    from ignition_gen_sdk.backends.api_client import _make_jwe_guard
    from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

    guard = _make_jwe_guard(JWE_KEYS_REQUIRED)

    req = httpx.Request("POST", f"{GATEWAY_URL}/test", content=b"short")
    # Should not raise
    guard(req)


# ---------------------------------------------------------------------------
# event_hooks wired on IgnitionAPIClient._client
# ---------------------------------------------------------------------------

def test_event_hooks_present_on_client():
    """IgnitionAPIClient._client has a request event hook registered."""
    from ignition_gen_sdk.config import Settings
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

    settings = Settings(
        ignition_api_key="test:testkey1234",
        ignition_base_url=GATEWAY_URL,
    )
    client = IgnitionAPIClient(settings)

    hooks = client._client.event_hooks
    assert "request" in hooks, "request event_hooks key missing"
    assert len(hooks["request"]) >= 1, "No request hooks registered"
    client.close()


# ---------------------------------------------------------------------------
# _settings attribute set on IgnitionAPIClient
# ---------------------------------------------------------------------------

def test_settings_attribute_set():
    """IgnitionAPIClient stores self._settings for downstream use."""
    from ignition_gen_sdk.config import Settings
    from ignition_gen_sdk.backends.api_client import IgnitionAPIClient

    settings = Settings(
        ignition_api_key="test:testkey1234",
        ignition_base_url=GATEWAY_URL,
    )
    client = IgnitionAPIClient(settings)
    assert client._settings is settings
    client.close()
