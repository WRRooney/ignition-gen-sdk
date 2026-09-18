"""ign diff — compare a current JSON payload with the last manifest entry.

Exit codes:
    0 — no diff (current file matches last pushed manifest entry by sha256)
    1 — diff exists (current file differs from manifest entry)
    2 — no manifest entry for this resource-id (push first)

Usage:
    ign diff tags default/Tanks/T01 --current-file ./tag_output.json
    ign diff views MyProject/Main/Overview --from-stdin < current.json
    ign diff tags default/Tanks/T01 --current-file payload.json --json
    ign diff tags default/Tanks/T01 --current-file payload.json --no-color
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from ..manifest.manifest import read as _manifest_read, _sha256


# Payloads may be dict OR list (disk backend
# stores the bare tags.json list to match the on-disk shape). Diff
# helpers accept Any JSON-serializable value.


def _unified_diff(old: Any, new: Any) -> list[str]:
    return list(difflib.unified_diff(
        json.dumps(old, indent=2, sort_keys=True).splitlines(keepends=True),
        json.dumps(new, indent=2, sort_keys=True).splitlines(keepends=True),
        fromfile="manifest (last pushed)",
        tofile="current payload",
        n=3,
    ))


def _diff_to_json(old: Any, new: Any) -> dict:
    """Top-level key diff only (not a recursive deep-diff).

    When payloads are lists (disk-backend tag manifests), fall
    back to a single "changed" entry comparing the two lists wholesale
    — top-level-keys diff doesn't apply to lists.
    """
    if not (isinstance(old, dict) and isinstance(new, dict)):
        if old == new:
            return {"added": {}, "removed": {}, "changed": {}}
        return {"added": {}, "removed": {}, "changed": {"<root>": [old, new]}}
    added = {k: v for k, v in new.items() if k not in old}
    removed = {k: v for k, v in old.items() if k not in new}
    changed = {
        k: [old[k], new[k]]
        for k in old
        if k in new and old[k] != new[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


def _load_current_payload(current_file: Optional[str], from_stdin: bool) -> Any:
    """Load current payload from file path or stdin.

    Returns Any because tags.json on disk is a JSON list (bare),
    not a dict. The manifest payload mirrors that shape so the sha256
    short-circuit succeeds when the file is unchanged.
    """
    if from_stdin:
        return json.load(sys.stdin)
    if current_file:
        return json.loads(Path(current_file).read_text(encoding="utf-8"))
    raise typer.BadParameter(
        "Provide --current-file PATH or --from-stdin to supply the current payload."
    )


def diff_cmd(
    resource_type: Annotated[str, typer.Argument(help="Resource type: tags, views, providers, database-connections")],
    resource_id: Annotated[str, typer.Argument(help="Resource ID: e.g. default/Tanks/T01")],
    current_file: Annotated[
        Optional[str],
        typer.Option("--current-file", help="Path to JSON file containing current payload to diff."),
    ] = None,
    from_stdin: Annotated[
        bool,
        typer.Option("--from-stdin", help="Read current payload JSON from stdin."),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON diff instead of unified diff."),
    ] = False,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Suppress Rich color output."),
    ] = False,
) -> None:
    """Show diff between a current JSON payload and the last manifest entry.

    Requires --current-file PATH or --from-stdin to provide the current payload.

    Exit 0: no diff (sha256 match). Exit 1: diff exists. Exit 2: no manifest entry.
    """
    entry = _manifest_read(resource_type, resource_id)
    if entry is None:
        typer.echo(
            f"No manifest entry for {resource_type}/{resource_id}. "
            "Push first to record a baseline.",
            err=True,
        )
        raise typer.Exit(code=2)

    # Payload may be dict (api backend / view backend) or list
    # (disk backend tag manifest, matching the bare tags.json on disk).
    manifest_payload: Any = entry.get("payload", {})

    # Load the current payload from file or stdin
    try:
        current_payload = _load_current_payload(current_file, from_stdin)
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"Error loading current payload: {e}", err=True)
        raise typer.Exit(code=1)

    # sha256 short-circuit: if hashes match, no diff
    current_sha = _sha256(current_payload)
    stored_sha = entry.get("sha256", "")

    if current_sha == stored_sha:
        if json_out:
            typer.echo(json.dumps({"diff": False, "sha256": current_sha}))
        else:
            typer.echo(f"No diff for {resource_type}/{resource_id} (sha256 match).")
        raise typer.Exit(code=0)

    # sha256 mismatch — produce diff
    if json_out:
        result = _diff_to_json(manifest_payload, current_payload)
        typer.echo(json.dumps(result))
        raise typer.Exit(code=1)

    lines = _unified_diff(manifest_payload, current_payload)

    if lines:
        _should_color = not no_color and sys.stdout.isatty()
        if _should_color:
            try:
                from rich.console import Console
                console = Console(highlight=False, no_color=no_color)
                for line in lines:
                    if line.startswith("+"):
                        console.print(f"[green]{line}[/green]", end="")
                    elif line.startswith("-"):
                        console.print(f"[red]{line}[/red]", end="")
                    elif line.startswith("@"):
                        console.print(f"[cyan]{line}[/cyan]", end="")
                    else:
                        console.print(line, end="")
            except ImportError:
                typer.echo("".join(lines))
        else:
            typer.echo("".join(lines))
        raise typer.Exit(code=1)

    raise typer.Exit(code=0)
