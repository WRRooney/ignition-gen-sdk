"""``ign tools`` — discover and run the project's own generator scripts.

User-owned tools live in ``.ign_tools/`` at the working directory root, one
Python file per tool. They import ``ignition_gen_sdk`` like any script and are the
place agents accumulate reusable, project-specific generators (view families,
tag seeds, migrations). The SDK never writes into this directory.

    .ign_tools/
        build_pump_views.py     # docstring first line = description
        _shared.py              # underscore-prefixed files are helpers, not tools

``ign tools run NAME [ARGS...]`` executes the file as ``__main__`` with
``sys.argv = [NAME, *ARGS]``. Generators are SEEDS: guard against clobbering
hand-edited views with :mod:`ignition_gen_sdk.tools.seed_guard`.
"""
from __future__ import annotations

import ast
import runpy
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

tools_app = typer.Typer(no_args_is_help=True, help="Project tools in .ign_tools/: list, run.")

TOOLS_DIR = Path(".ign_tools")


def discover(root: Path = TOOLS_DIR) -> list[tuple[str, str]]:
    """(name, one-line description) for every ``<name>.py`` in ``root`` not starting with ``_``."""
    out: list[tuple[str, str]] = []
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.py")):
        if path.name.startswith("_"):
            continue
        desc = ""
        try:
            doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
            desc = (doc or "").strip().splitlines()[0] if doc else ""
        except SyntaxError:
            desc = "(syntax error)"
        out.append((path.stem, desc))
    return out


@tools_app.command("list")
def list_cmd() -> None:
    """List tools in .ign_tools/."""
    tools = discover()
    if not tools:
        typer.echo(f"No tools in {TOOLS_DIR}/ (create <name>.py files there).")
        return
    width = max(len(n) for n, _ in tools)
    for name, desc in tools:
        typer.echo(f"{name:<{width}}  {desc}")


@tools_app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Tool name (file stem in .ign_tools/).")],
    args: Annotated[Optional[list[str]], typer.Argument(help="Arguments passed to the tool.")] = None,
) -> None:
    """Run .ign_tools/NAME.py as __main__ with the given arguments."""
    path = TOOLS_DIR / f"{name}.py"
    if not path.is_file():
        typer.echo(f"Error: no tool {path}. `ign tools list` shows what exists.", err=True)
        raise typer.Exit(code=1)
    argv = [str(path), *(args or []), *ctx.args]
    saved_argv, saved_path = sys.argv, list(sys.path)
    sys.argv = argv
    sys.path.insert(0, str(TOOLS_DIR.resolve()))  # like `python .ign_tools/NAME.py`: siblings importable
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as e:
        raise typer.Exit(code=int(e.code or 0)) from None
    finally:
        sys.argv, sys.path[:] = saved_argv, saved_path
