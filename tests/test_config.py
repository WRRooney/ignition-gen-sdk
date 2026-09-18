"""Tests for Settings — locks the token-redaction security invariant.

The api_key is read from IGNITION_API_TOKEN but must NEVER appear in repr/str
output (those land in logs and tracebacks). Confirmed live;
this test locks it against regression. Hermetic — never reads the real .env
token (passes _env_file=None + an explicit fake key).
"""
from __future__ import annotations

from ignition_gen_sdk.config import Settings

_FAKE_KEY = "test:FAKE_SECRET_DO_NOT_LOG_0123456789"


def _settings() -> Settings:
    # _env_file=None skips .env; env overrides are cleared so defaults are
    # observable regardless of the developer's shell.
    import os
    from unittest.mock import patch
    cleared = {k: v for k, v in os.environ.items() if not k.startswith("IGNITION_")}
    with patch.dict(os.environ, cleared, clear=True):
        return Settings(_env_file=None, ignition_api_key=_FAKE_KEY)


def test_api_key_loads() -> None:
    assert _settings().ignition_api_key == _FAKE_KEY


def test_repr_redacts_token() -> None:
    s = _settings()
    assert _FAKE_KEY not in repr(s)
    assert "[REDACTED]" in repr(s)


def test_str_redacts_token() -> None:
    s = _settings()
    assert _FAKE_KEY not in str(s)
    assert "[REDACTED]" in str(s)


def test_defaults_present() -> None:
    s = _settings()
    # Explicit defaults must survive (Ignition distinguishes absent vs default).
    assert s.ignition_default_tag_provider == "default"
    assert s.ignition_default_project == "Global"
    assert s.openapi_spec_path == s.ignition_state_dir / "openapi.json"
