"""Live-gateway smoke test — regen engine end-to-end.

Opt-in only: runs solely under ``pytest -m smoke``. The whole module is
skipped at import time when ``IGNITION_URL`` is not set.

Validates that the regen engine produces an importable
generated client, maintains a valid hash sidecar, and that the auto-generated
``api_reference/`` output is safe (no literal token, env-var placeholder only).

Four test cases:

  1. ``test_regen_engine_package_importable`` — ``from ignition_api_client import
     Client`` succeeds after ``needs_regen()`` returns False.
  2. ``test_regen_engine_hash_sidecar_exists`` — ``.openapi_hash`` sidecar exists
     and contains a valid 64-char SHA256 hex string.
  3. ``test_regen_doc_output_auth_no_literal_token`` — ``AUTH.md`` contains the
     ``${IGNITION_API_TOKEN}`` placeholder and does NOT contain any literal token
     matching ``test:[A-Za-z0-9_-]{4,}``.
  4. ``test_regen_doc_output_index_exists`` — ``INDEX.md`` exists and is non-trivial
     (> 100 bytes; means the generator ran and produced output).
"""
from __future__ import annotations

import os
import re

import pytest

# ---------------------------------------------------------------------------
# Module-level skip + smoke marker
# ---------------------------------------------------------------------------

if not os.getenv("IGNITION_URL"):
    pytest.skip(
        "IGNITION_URL not set; live smoke disabled",
        allow_module_level=True,
    )

pytestmark = pytest.mark.smoke

# ---------------------------------------------------------------------------
# Path constants (derived from engine.py topology to stay in sync)
# ---------------------------------------------------------------------------

from ignition_gen_sdk.config import Settings
from ignition_gen_sdk.regen.doc_gen import api_reference_dir

_SETTINGS = Settings()
_HASH_SIDECAR = _SETTINGS.openapi_hash_sidecar_path
_API_REF_DIR = api_reference_dir(_SETTINGS)
_AUTH_MD = _API_REF_DIR / "AUTH.md"
_INDEX_MD = _API_REF_DIR / "INDEX.md"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_regen_engine_package_importable() -> None:
    """Generated package is importable and needs_regen() returns False.

    Verifies that after the regen engine has run, the
    ``ignition_api_client`` package is available for import and the spec hash
    matches the sidecar (no drift since last regen).
    """
    from ignition_gen_sdk.regen.engine import needs_regen

    assert not needs_regen(), (
        "needs_regen() returned True — spec drifted or generated package missing. "
        "Run `ign provider list` (or any typed verb) to trigger regen, then "
        "re-run smoke tests."
    )

    # The Client class must be importable after regen.
    from ignition_api_client import Client  # noqa: PLC0415

    assert Client is not None, "ignition_api_client.Client imported as None"


def test_regen_engine_hash_sidecar_exists() -> None:
    """.openapi_hash sidecar exists and contains a valid SHA256 hex string.

    The sidecar must contain exactly 64 hex characters (optionally followed
    by a newline). This validates that needs_regen() has a valid baseline to
    compare against on subsequent invocations.
    """
    assert _HASH_SIDECAR.exists(), (
        f".openapi_hash sidecar missing at {_HASH_SIDECAR}. "
        "Run any typed ign verb to trigger regen and recreate it."
    )

    content = _HASH_SIDECAR.read_text(encoding="utf-8")
    stripped = content.strip()
    assert len(stripped) == 64, (
        f"Expected 64-char SHA256 hex, got {len(stripped)} chars: {stripped!r}"
    )
    # Validate it is a valid hex string.
    assert re.fullmatch(r"[0-9a-f]{64}", stripped), (
        f".openapi_hash content is not a valid lowercase hex SHA256: {stripped!r}"
    )


def test_regen_doc_output_auth_no_literal_token() -> None:
    """AUTH.md has env-var placeholder and no literal token.

    Two assertions:
    - "${IGNITION_API_TOKEN}" is present (env-var placeholder).
    - The regex ``test:[A-Za-z0-9_-]{4,}`` does NOT match anywhere in the
      file (no literal token value ever committed to disk).
    """
    assert _AUTH_MD.exists(), (
        f"AUTH.md missing at {_AUTH_MD}. "
        "Run doc_gen (or any regen trigger) to regenerate api_reference/."
    )

    content = _AUTH_MD.read_text(encoding="utf-8")

    # Must contain the env-var placeholder.
    assert "${IGNITION_API_TOKEN}" in content, (
        "AUTH.md does not contain '${IGNITION_API_TOKEN}' placeholder — "
        "doc generator may have changed the AUTH template"
    )

    # Must NOT contain a literal token value.
    literal_token_match = re.search(r"test:[A-Za-z0-9_-]{4,}", content)
    assert literal_token_match is None, (
        f"Literal API token found in AUTH.md at position "
        f"{literal_token_match.start()}: {literal_token_match.group()!r}. "
        "Token must never be written to disk."
    )


def test_regen_doc_output_index_exists() -> None:
    """INDEX.md exists and has substantial content (generator ran).

    A minimal INDEX.md of > 100 bytes confirms the doc generator produced
    real output, not an empty stub.
    """
    assert _INDEX_MD.exists(), (
        f"INDEX.md missing at {_INDEX_MD}. "
        "Run doc_gen (or any regen trigger) to regenerate api_reference/."
    )

    content = _INDEX_MD.read_text(encoding="utf-8")
    assert len(content) > 100, (
        f"INDEX.md has only {len(content)} bytes — expected > 100 bytes of "
        "generated content. Generator may have produced an empty output."
    )
