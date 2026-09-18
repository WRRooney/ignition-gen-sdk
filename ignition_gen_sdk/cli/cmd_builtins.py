"""``ign builtins`` — the Ignition 8.3 system.*/expression function catalog.

``refresh`` re-crawls the official 8.3 appendix and rewrites the packaged
catalog (maintainer command). ``audit`` scans a gateway's projects for calls
that are not in the catalog: the usual symptom of an agent inventing an API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from ..config import Settings

builtins_app = typer.Typer(no_args_is_help=True, help="8.3 function catalog: refresh, audit.")


@builtins_app.command("refresh")
def refresh_cmd(
    out: Annotated[Optional[Path], typer.Option("--out", help="Write the catalog module here instead of into the package.")] = None,
) -> None:
    """Re-crawl docs.inductiveautomation.com and rewrite the 8.3 catalog."""
    from ..validation.crawl_ia_docs import DEFAULT_OUT, main  # noqa: PLC0415

    raise typer.Exit(code=main(out or DEFAULT_OUT))


@builtins_app.command("audit")
def audit_cmd(
    project: Annotated[Optional[list[str]], typer.Option("--project", "-p", help="Project(s) to scan; default all.")] = None,
    allow: Annotated[Optional[list[str]], typer.Option("--allow", help="system.<subpackage> namespaces from installed modules to accept (e.g. cirruslink).")] = None,
    data_dir: Annotated[Optional[Path], typer.Option("--data-dir", help="Gateway data dir; default IGNITION_DATA_DIR.")] = None,
) -> None:
    """Report system.* calls and expression functions that do not exist in 8.3. Exit 1 if any."""
    from ..validation.audit_builtins import main  # noqa: PLC0415

    root = data_dir or Settings().ignition_data_root  # type: ignore[call-arg]
    if not (root / "projects").is_dir():
        typer.echo(f"Error: no projects/ under {root}; set IGNITION_DATA_DIR or --data-dir.", err=True)
        raise typer.Exit(code=1)
    raise typer.Exit(code=main(root, project or None, frozenset(allow or ())))
