"""Regen engine — codegen + doc-gen + spec-hash.

Single entrypoint for:
  - needs_regen(): check if generated client is absent or spec hash drifted
  - ensure_generated_client(): run codegen + install + doc-gen + write hash if stale

All paths come from Settings (state dir, default ./.ign):
  spec      settings.openapi_spec_path
  hash      settings.openapi_hash_sidecar_path
  client    settings.openapi_generated_client_path
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..config import Settings

_OPC_YAML = Path(__file__).resolve().parent / "openapi-python-client.yaml"


def _settings(settings=None) -> Settings:  # noqa: ANN001
    return settings if settings is not None else Settings()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Spec hash helpers
# ---------------------------------------------------------------------------

SPEC_URL_PATH = "/openapi.json"


def fetch_spec(settings=None) -> Path:  # noqa: ANN001
    """Download the gateway's OpenAPI document to ``settings.openapi_spec_path``.

    Called automatically the first time anything needs the spec; ``ign openapi
    fetch`` calls it explicitly to refresh. Raises the client's error classes
    (NetworkError, AuthMissingError, ...) so CLI verbs render them normally.
    """
    from ..backends.api_client import IgnitionAPIClient, PayloadError  # noqa: PLC0415

    st = _settings(settings)
    client = IgnitionAPIClient(st)
    try:
        resp = client.request("GET", SPEC_URL_PATH)
    finally:
        client.close()
    try:
        data = resp.json()
    except ValueError as e:
        raise PayloadError(f"GET {SPEC_URL_PATH} did not return JSON: {e}") from None
    if not isinstance(data, dict) or "paths" not in data:
        raise PayloadError(f"GET {SPEC_URL_PATH} is not an OpenAPI document (no 'paths')")
    st.openapi_spec_path.parent.mkdir(parents=True, exist_ok=True)
    st.openapi_spec_path.write_bytes(resp.content)
    return st.openapi_spec_path


def _spec_hash(settings=None) -> str:  # noqa: ANN001
    """SHA256 of the OpenAPI spec file. ~51ms for an 11MB spec."""
    st = _settings(settings)
    if not st.openapi_spec_path.exists():
        fetch_spec(st)
    return hashlib.sha256(st.openapi_spec_path.read_bytes()).hexdigest()


def needs_regen(settings=None) -> bool:  # noqa: ANN001
    """True if the generated package is absent OR the spec hash drifted.

    Cheap: only reads the hash sidecar file, no spec parse.
    """
    st = _settings(settings)
    if not st.openapi_generated_client_path.exists():
        return True
    if not st.openapi_hash_sidecar_path.exists():
        return True
    return st.openapi_hash_sidecar_path.read_text("utf-8").strip() != _spec_hash(st)


def _write_hash(settings=None) -> None:  # noqa: ANN001
    st = _settings(settings)
    st.openapi_hash_sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    st.openapi_hash_sidecar_path.write_text(_spec_hash(st) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _codegen_python() -> str:
    """Return the interpreter to run codegen with (must have openapi-python-client)."""
    probe = subprocess.run(
        [sys.executable, "-c", "import openapi_python_client"],
        capture_output=True, text=True, check=False,
    )
    if probe.returncode == 0:
        return sys.executable
    raise RuntimeError(
        "openapi-python-client is not installed in this interpreter. "
        "Install with `pip install 'ignition-gen-sdk[codegen]'`."
    )


def _run_codegen(settings=None) -> None:  # noqa: ANN001
    """Invoke openapi-python-client generate via a Python that has the tool.

    Uses _codegen_python() to pick an interpreter with openapi-python-client
    installed (sys.executable in the venv, or the project .venv when invoked
    from a system Python). Captures stdout+stderr; raises RuntimeError with
    the last 2000 chars of stderr on non-zero exit.
    """
    st = _settings(settings)
    py = _codegen_python()
    st.openapi_generated_client_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            py, "-m", "openapi_python_client", "generate",
            "--path", str(st.openapi_spec_path),
            "--config", str(_OPC_YAML),
            "--output-path", str(st.openapi_generated_client_path),
            "--overwrite",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"openapi-python-client failed (exit {result.returncode}):\n"
            f"{result.stderr[-2000:]}"
        )


def _install_generated(settings=None) -> None:  # noqa: ANN001
    """No-op kept for API stability: the generated package is imported via sys.path."""
    _ensure_on_syspath(settings)

def _run_docgen(settings=None) -> None:  # noqa: ANN001
    """Run doc_gen.generate_docs() to write api_reference/*.md."""
    from ..regen.doc_gen import generate_docs
    generate_docs(settings)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _ensure_on_syspath(settings=None) -> None:  # noqa: ANN001
    """Make the generated client package importable in the current interpreter.

    The pip editable install only registers in the interpreter that ran codegen.
    A different interpreter with the same on-disk files (e.g. the globally
    installed `ign` shim under system python3 vs. the project `.venv`) has
    no .pth entry, so `import ignition_api_client` fails. Prepending the
    generated-package root to sys.path makes the import work regardless of
    where codegen originally ran.
    """
    pkg = _settings(settings).openapi_generated_client_path
    pkg_root = str(pkg)
    if pkg.exists() and pkg_root not in sys.path:
        sys.path.insert(0, pkg_root)


def ensure_generated_client(settings=None) -> None:  # noqa: ANN001
    """Auto-regen the generated client if absent or spec hash drifted.

    Announces progress on stderr (non-interactive: quiet=True when stderr is not
    a tty — avoids escape code bleed in CI / pytest -m smoke).

    The function is a no-op when needs_regen() returns False (hash matches and
    generated package exists) — cheap file read, no spec parse.
    """
    st = _settings(settings)
    if not st.openapi_spec_path.exists():
        fetch_spec(st)
    if not needs_regen(st):
        _ensure_on_syspath(st)
        return

    console = Console(stderr=True, quiet=not sys.stderr.isatty())
    console.print("[yellow]Generating API client from openapi.json...[/yellow]")

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Running openapi-python-client...", total=None)

        _run_codegen(st)
        progress.update(task, description="Installing generated package...")

        _install_generated(st)
        progress.update(task, description="Generating api_reference docs...")

        _run_docgen(st)
        progress.update(task, description="Done.", completed=1, total=1)

    _write_hash(st)
    _ensure_on_syspath(st)
