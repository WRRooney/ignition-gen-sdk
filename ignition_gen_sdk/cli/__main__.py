"""Enable ``python -m ignition_gen_sdk.cli`` as a subprocess entry point.

The live-gateway smoke test invokes the CLI via
``subprocess.run([sys.executable, "-m", "ignition_gen_sdk.cli", "api", ...])``
to guarantee the venv-correct interpreter (rather than depending on
``ign`` being first on PATH). Python requires a ``__main__.py`` inside
a package for the ``-m package`` form to dispatch; without this file the
interpreter errors with "'ignition_gen_sdk.cli' is a package and cannot
be directly executed".

This file is a no-op shim: it imports the existing Typer ``app`` from
``__init__.py`` and calls it. All command wiring + behavior lives in
``__init__.py`` and the ``cmd_*.py`` modules; this entry point exists
only so the ``-m`` invocation works.
"""
from __future__ import annotations

from . import app


if __name__ == "__main__":
    app()
