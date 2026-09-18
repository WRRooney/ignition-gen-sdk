"""Unit tests for needs_regen() / _write_hash() / sys.path handling.

Every path comes from a Settings whose state dir is a tmp_path, so tests never
touch a real generated package or sidecar.
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import hashlib
import sys

import pytest

from ignition_gen_sdk.config import Settings
import ignition_gen_sdk.regen.engine as eng


def _settings(tmp_path):
    spec = tmp_path / "openapi.json"
    spec.write_text('{"openapi": "3.0.0", "paths": {}}', encoding="utf-8")
    return Settings(
        _env_file=None,
        ignition_api_key="test:not-a-real-token",
        ignition_state_dir=tmp_path / ".ign",
        openapi_spec_path=spec,
    )


def test_needs_regen_missing_package(tmp_path) -> None:
    assert eng.needs_regen(_settings(tmp_path)) is True


def test_needs_regen_missing_sidecar(tmp_path) -> None:
    st = _settings(tmp_path)
    st.openapi_generated_client_path.mkdir(parents=True)
    assert eng.needs_regen(st) is True


def test_needs_regen_hash_match(tmp_path) -> None:
    st = _settings(tmp_path)
    st.openapi_generated_client_path.mkdir(parents=True)
    real = hashlib.sha256(st.openapi_spec_path.read_bytes()).hexdigest()
    st.openapi_hash_sidecar_path.write_text(real + "\n", encoding="utf-8")
    assert eng.needs_regen(st) is False


def test_needs_regen_hash_mismatch(tmp_path) -> None:
    st = _settings(tmp_path)
    st.openapi_generated_client_path.mkdir(parents=True)
    st.openapi_hash_sidecar_path.write_text("a" * 64 + "\n", encoding="utf-8")
    assert eng.needs_regen(st) is True


def test_write_hash_creates_sidecar(tmp_path) -> None:
    st = _settings(tmp_path)
    eng._write_hash(st)
    content = st.openapi_hash_sidecar_path.read_text("utf-8")
    assert len(content.strip()) == 64 and content.endswith("\n")
    assert all(c in "0123456789abcdef" for c in content.strip())


def test_spec_missing_is_fetched_from_gateway(tmp_path, monkeypatch) -> None:
    import httpx

    st = _settings(tmp_path)
    st.openapi_generated_client_path.mkdir(parents=True)
    st.openapi_hash_sidecar_path.write_text("a" * 64 + "\n", encoding="utf-8")
    st.openapi_spec_path.unlink()
    calls: list[str] = []

    def fake_request(self, method, path, json=None):
        calls.append(f"{method} {path}")
        return httpx.Response(200, json={"openapi": "3.1.0", "paths": {}}, request=httpx.Request("GET", f"{GATEWAY_URL}/openapi.json"))

    monkeypatch.setattr("ignition_gen_sdk.backends.api_client.IgnitionAPIClient.request", fake_request)
    assert eng.needs_regen(st) is True
    assert calls == ["GET /openapi.json"]
    assert st.openapi_spec_path.exists()


def test_ensure_on_syspath_inserts_when_pkg_exists(tmp_path) -> None:
    st = _settings(tmp_path)
    st.openapi_generated_client_path.mkdir(parents=True)
    saved = list(sys.path)
    try:
        eng._ensure_on_syspath(st)
        assert sys.path[0] == str(st.openapi_generated_client_path)
        eng._ensure_on_syspath(st)
        assert sys.path.count(str(st.openapi_generated_client_path)) == 1
    finally:
        sys.path[:] = saved


def test_ensure_on_syspath_noop_when_pkg_missing(tmp_path) -> None:
    st = _settings(tmp_path)
    saved = list(sys.path)
    try:
        eng._ensure_on_syspath(st)
        assert sys.path == saved
    finally:
        sys.path[:] = saved


def test_ensure_generated_client_syspath_on_noregen(tmp_path, monkeypatch) -> None:
    st = _settings(tmp_path)
    st.openapi_generated_client_path.mkdir(parents=True)
    monkeypatch.setattr(eng, "needs_regen", lambda _s=None: False)
    saved = list(sys.path)
    try:
        eng.ensure_generated_client(st)
        assert sys.path[0] == str(st.openapi_generated_client_path)
    finally:
        sys.path[:] = saved


def test_codegen_python_prefers_sys_executable(monkeypatch) -> None:
    import subprocess as _sp

    captured: list[list[str]] = []

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(list(args))
        return _sp.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(eng.subprocess, "run", fake_run)
    assert eng._codegen_python() == sys.executable
    assert captured == [[sys.executable, "-c", "import openapi_python_client"]]


def test_codegen_python_raises_when_unavailable(monkeypatch) -> None:
    import subprocess as _sp

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        return _sp.CompletedProcess(args=args, returncode=1, stdout="", stderr="no mod")

    monkeypatch.setattr(eng.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="openapi-python-client.*pip install"):
        eng._codegen_python()
