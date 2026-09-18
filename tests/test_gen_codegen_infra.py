"""Tests for the codegen infra — Settings fields, .gitignore, pyproject extras."""
from __future__ import annotations

from pathlib import Path

import pytest

# Path from test file:
#   tests/test_gen_codegen_infra.py
#   parents[0] = tests/
#   parents[1] = tools/ignition_gen_sdk/   <-- package root / TOOLS_DIR
#   parents[2] = tools/
#   parents[3] = data/                    <-- REPO_ROOT
#   parents[4] = ignition/
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOLS_DIR = _REPO_ROOT
_GITIGNORE = _REPO_ROOT / ".gitignore"
_PYPROJECT = _TOOLS_DIR / "pyproject.toml"
_OPC_YAML = _TOOLS_DIR / "ignition_gen_sdk" / "regen" / "openapi-python-client.yaml"


class TestSettingsFields:
    """Settings gains two new Path fields for generated client + hash sidecar."""

    def test_settings_has_openapi_generated_client_path_field(self) -> None:
        from ignition_gen_sdk.config import Settings

        fields = Settings.model_fields
        assert "openapi_generated_client_path" in fields, (
            "Settings missing openapi_generated_client_path field"
        )

    def test_settings_has_openapi_hash_sidecar_path_field(self) -> None:
        from ignition_gen_sdk.config import Settings

        fields = Settings.model_fields
        assert "openapi_hash_sidecar_path" in fields, (
            "Settings missing openapi_hash_sidecar_path field"
        )

    def test_generated_client_path_default_points_to_tools_dir(
        self, tmp_path: Path
    ) -> None:
        """Default path is tools/ignition_gen_sdk/_ignition_api_client."""
        from ignition_gen_sdk.config import Settings

        s = Settings(ignition_api_key="test:testkey")  # type: ignore[call-arg]
        assert s.openapi_generated_client_path == s.ignition_state_dir / "client"

    def test_hash_sidecar_path_default_points_to_tools_dir(self) -> None:
        """Default path is tools/ignition_gen_sdk/.openapi_hash."""
        from ignition_gen_sdk.config import Settings

        s = Settings(ignition_api_key="test:testkey")  # type: ignore[call-arg]
        assert s.openapi_hash_sidecar_path == s.ignition_state_dir / "openapi.hash"

    def test_generated_client_path_overridable_via_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """IGNITION_OPENAPI_GENERATED_CLIENT_PATH env var overrides default."""
        monkeypatch.setenv(
            "IGNITION_OPENAPI_GENERATED_CLIENT_PATH", str(tmp_path / "custom_client")
        )
        from importlib import reload
        import ignition_gen_sdk.config as cfg_mod
        reload(cfg_mod)
        from ignition_gen_sdk.config import Settings as S
        s = S(ignition_api_key="test:testkey")  # type: ignore[call-arg]
        assert s.openapi_generated_client_path == tmp_path / "custom_client"
        reload(cfg_mod)  # restore

    def test_hash_sidecar_path_overridable_via_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """IGNITION_OPENAPI_HASH_SIDECAR_PATH env var overrides default."""
        monkeypatch.setenv(
            "IGNITION_OPENAPI_HASH_SIDECAR_PATH", str(tmp_path / ".custom_hash")
        )
        from importlib import reload
        import ignition_gen_sdk.config as cfg_mod
        reload(cfg_mod)
        from ignition_gen_sdk.config import Settings as S
        s = S(ignition_api_key="test:testkey")  # type: ignore[call-arg]
        assert s.openapi_hash_sidecar_path == tmp_path / ".custom_hash"
        reload(cfg_mod)  # restore


class TestGitignoreEntries:
    """Generated dir + hash sidecar are gitignored."""

    def test_gitignore_contains_generated_client_dir(self) -> None:
        content = _GITIGNORE.read_text(encoding="utf-8")
        assert ".ign/" in content, ".gitignore missing .ign/"

    def test_gitignore_contains_hash_sidecar(self) -> None:
        content = _GITIGNORE.read_text(encoding="utf-8")
        assert ".ign/" in content, ".gitignore missing .ign/"


class TestPyprojectToml:
    """pyproject.toml declares openapi-python-client as a core dependency."""

    def test_pyproject_has_codegen_core_dep(self) -> None:
        content = _PYPROJECT.read_text(encoding="utf-8")
        assert '"openapi-python-client>=0.28.4",' in content, (
            "pyproject.toml missing the openapi-python-client core dependency"
        )


class TestOpenapiYaml:
    """openapi-python-client.yaml exists with correct package name."""

    def test_opc_yaml_exists(self) -> None:
        assert _OPC_YAML.exists(), "openapi-python-client.yaml not found"

    def test_opc_yaml_has_package_name_override(self) -> None:
        content = _OPC_YAML.read_text(encoding="utf-8")
        assert 'package_name_override: "ignition_api_client"' in content, (
            "openapi-python-client.yaml missing package_name_override"
        )
