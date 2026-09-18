"""Tests for ScanClient — POST /scan/projects and /scan/config.

All tests use httpx.MockTransport stubs — no live gateway, no network.
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import httpx
import pytest

from ignition_gen_sdk.backends.scan_client import ScanClient, ScanWarning
from ignition_gen_sdk.config import Settings


def _settings(*, key: str = "test:abc123", base: str = GATEWAY_URL) -> Settings:
    """Build a Settings with a non-default api_key + base url (and a tempdir-irrelevant data root)."""
    return Settings(
        ignition_api_key=key,
        ignition_base_url=base,
        ignition_data_root="/tmp/does-not-matter",
    )


def _ok_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "scanActive": False,
            "lastScanTimestamp": 1,
            "lastScanDuration": 5,
        },
    )


def test_scan_projects_posts_to_correct_path_with_auth_header():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url_path"] = request.url.path
        captured["auth"] = request.headers.get("X-Ignition-API-Token")
        return _ok_response(request)

    transport = httpx.MockTransport(handler)
    with ScanClient(_settings(), _transport=transport) as c:
        c.scan_projects()

    assert captured == {
        "method": "POST",
        "url_path": "/data/api/v1/scan/projects",
        "auth": "test:abc123",
    }


def test_scan_projects_with_prefixed_token_does_not_double_prefix():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("X-Ignition-API-Token")
        return _ok_response(request)

    transport = httpx.MockTransport(handler)
    with ScanClient(_settings(key="test:tok-xyz"), _transport=transport) as c:
        c.scan_projects()

    assert captured["auth"] == "test:tok-xyz"


def test_scan_projects_raises_scan_warning_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    with ScanClient(_settings(), _transport=transport) as c:
        with pytest.raises(ScanWarning) as exc_info:
            c.scan_projects()
    msg = str(exc_info.value)
    assert "500" in msg
    assert "/data/api/v1/scan/projects" in msg


def test_scan_projects_raises_scan_warning_on_connect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(handler)
    with ScanClient(_settings(), _transport=transport) as c:
        with pytest.raises(ScanWarning) as exc_info:
            c.scan_projects()
    msg = str(exc_info.value)
    # The underlying class name or message must surface
    assert "ConnectError" in msg or "refused" in msg


def test_scan_projects_raises_scan_warning_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(handler)
    with ScanClient(_settings(), _transport=transport) as c:
        with pytest.raises(ScanWarning):
            c.scan_projects()


def test_scan_config_posts_to_scan_config_path():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url_path"] = request.url.path
        return _ok_response(request)

    transport = httpx.MockTransport(handler)
    with ScanClient(_settings(), _transport=transport) as c:
        c.scan_config()

    assert captured == {
        "method": "POST",
        "url_path": "/data/api/v1/scan/config",
    }


def test_scan_client_context_manager_closes_underlying_client():
    transport = httpx.MockTransport(_ok_response)
    with ScanClient(_settings(), _transport=transport) as client:
        underlying = client._client
    assert underlying.is_closed is True
