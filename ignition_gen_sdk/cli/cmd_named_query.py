"""ign named-query — Perspective/gateway named-query CLI subcommand.

Named queries had no ign verb at all, which meant the only way to author
one was by hand — and hand-writing under projects/** is banned. This is the
sanctioned path.

Caching is a first-class option here because it is the lever that stops an
N-session dashboard from running N copies of the same aggregate:
``--cache-seconds`` makes the GATEWAY hold one result set for every caller.
It only pays off when all sessions send IDENTICAL parameters, so quantize
any now()-derived window to the poll bucket before binding.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from ..backends.api_client import AuthMissingError
from ..backends.project_disk import ProjectDiskBackend, ProjectNotFoundError
from ..backends.scan_client import ScanClient, ScanWarning
from ..config import Settings
from ..models.named_query import NamedQuery, NamedQueryParameter
from ._errors import render_error

named_query_app = typer.Typer(help="Named query operations: write, list, delete.")


def _parse_params(raw: list[str]) -> list[NamedQueryParameter]:
    """``["startDate:DateTime", "area:String"]`` -> parameter models."""
    out: list[NamedQueryParameter] = []
    for item in raw:
        if item.count(":") != 1:
            raise ValueError(
                f"--param {item!r} must be exactly 'identifier:DataType', "
                "e.g. 'startDate:DateTime'."
            )
        identifier, sql_type = item.split(":")
        out.append(
            NamedQueryParameter(identifier=identifier.strip(), sqlType=sql_type.strip())
        )
    return out


@named_query_app.command("write")
def write_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
    query_path: Annotated[
        str,
        typer.Option(
            "--query-path",
            help="Slash-separated query path, e.g. Alarm/MySQL/RateTimeline. "
            "This is also the name passed to system.db.runNamedQuery().",
        ),
    ],
    file: Annotated[
        Path, typer.Option("--file", help="Path to the .sql file to write as query.sql.")
    ],
    database: Annotated[
        str, typer.Option("--database", help="Datasource name the query runs against.")
    ],
    param: Annotated[
        Optional[list[str]],
        typer.Option(
            "--param",
            help="Repeatable bind parameter as 'identifier:DataType' "
            "(DataType is an Ignition tag data type: String, Int4, Float8, DateTime, ...).",
        ),
    ] = None,
    cache_seconds: Annotated[
        int,
        typer.Option(
            "--cache-seconds",
            help="Gateway-side result cache lifetime in seconds. 0 disables caching "
            "(the Designer default). Shared across ALL sessions, keyed on the "
            "parameter values.",
        ),
    ] = 0,
    max_return_size: Annotated[
        int, typer.Option("--max-return-size", help="Row cap written to the resource.")
    ] = 100,
    enforce_max_return_size: Annotated[
        bool,
        typer.Option(
            "--enforce-max-return-size/--no-enforce-max-return-size",
            help="Whether the gateway actually enforces --max-return-size.",
        ),
    ] = False,
    query_type: Annotated[
        str, typer.Option("--type", help="Query | Update | Scalar Query.")
    ] = "Query",
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print payload; no write.")
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After write, POST /scan/projects.")
    ] = True,
) -> None:
    """Write query.sql + resource.json for a named query.

    Writes to projects/<name>/ignition/named-query/<query-path>/.

    Every ``:name`` in the SQL must be declared with --param and vice versa;
    a mismatch fails before anything is written. Ignition scans SQL COMMENTS
    for parameters too, so keep ``:word`` tokens out of them.
    """
    try:
        sql = file.read_text(encoding="utf-8")
    except OSError as e:
        render_error(ValueError(f"--file could not be read: {e}"), no_color=False)
        raise typer.Exit(code=1) from None

    try:
        config = NamedQuery(
            database=database,
            parameters=_parse_params(param or []),
            type=query_type,
            cacheEnabled=cache_seconds > 0,
            cacheAmount=max(1, cache_seconds),
            cacheUnit="SEC",
            maxReturnSize=max_return_size,
            useMaxReturnSize=enforce_max_return_size,
        )
    except ValueError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    if dry_run:
        import json

        from ..backends.project_disk import sql_bind_parameters
        from ..serializers.resource_metadata import named_query_resource_json

        declared = {p.identifier for p in config.parameters}
        used = sql_bind_parameters(sql)
        if used != declared:
            render_error(
                ValueError(
                    f"parameter mismatch — in SQL but undeclared: "
                    f"{sorted(used - declared) or 'none'}; declared but absent "
                    f"from SQL: {sorted(declared - used) or 'none'}."
                ),
                no_color=False,
            )
            raise typer.Exit(code=1)
        typer.echo("=== query.sql ===")
        typer.echo(sql)
        typer.echo("=== resource.json ===")
        typer.echo(json.dumps(named_query_resource_json(config.attributes()), indent=2))
        typer.echo("=== target path ===")
        typer.echo(f"projects/{project}/ignition/named-query/{query_path}/")
        return

    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None

    try:
        backend = ProjectDiskBackend(settings)
        dest = backend.write_named_query(project, query_path, sql, config)
    except (ProjectNotFoundError, ValueError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Written: {dest}/query.sql")
    typer.echo(f"Written: {dest}/resource.json")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(
            f"WARNING: gateway scan failed for {dest}; the change is on disk "
            f"but the gateway may not see it until the next scan tick. Reason: {e}",
            err=True,
        )


@named_query_app.command("list")
def list_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
) -> None:
    """List the named queries defined in ``--project`` (read-only)."""
    import json

    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None
    backend = ProjectDiskBackend(settings)
    try:
        root = backend._project_named_query_root(project)
    except ProjectNotFoundError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    if not root.is_dir():
        typer.echo(f"No named queries in {project!r}.")
        return
    rows = sorted(
        p.parent.relative_to(root).as_posix() for p in root.rglob("query.sql")
    )
    typer.echo(f"{len(rows)} named query(ies) in {project!r}:")
    for name in rows:
        meta = root / name / "resource.json"
        detail = ""
        try:
            attrs = json.loads(meta.read_text())["attributes"]
            cache = (
                f", cache {attrs['cacheAmount']}{attrs['cacheUnit'].lower()}"
                if attrs.get("cacheEnabled")
                else ""
            )
            detail = f"  [{attrs.get('database', '?')}{cache}]"
        except (OSError, ValueError, KeyError):
            pass
        typer.echo(f"  {name}{detail}")


@named_query_app.command("delete")
def delete_cmd(
    project: Annotated[str, typer.Option("--project", help="Project name (REQUIRED).")],
    query_path: Annotated[
        str,
        typer.Option("--query-path", help="Query path, e.g. Alarm/MySQL/JournalPage."),
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print the target; no write.")
    ] = False,
    scan: Annotated[
        bool, typer.Option("--scan/--no-scan", help="After delete, POST /scan/projects.")
    ] = True,
) -> None:
    """Delete named query ``--query-path`` from ``--project``."""
    try:
        settings = Settings()  # type: ignore[call-arg]
    except (FileNotFoundError, ValueError):
        render_error(
            AuthMissingError("check that IGNITION_API_TOKEN is set"),
            no_color=False,
        )
        raise typer.Exit(code=1) from None
    backend = ProjectDiskBackend(settings)
    if dry_run:
        try:
            root = backend._project_named_query_root(project)
        except ProjectNotFoundError as e:
            render_error(e, no_color=False)
            raise typer.Exit(code=1) from None
        typer.echo(f"Would remove: {root / query_path}")
        return
    try:
        dest = backend.delete_named_query(project, query_path)
    except (ProjectNotFoundError, FileNotFoundError, ValueError) as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None

    typer.echo(f"Deleted named query {query_path!r} from {project}")
    typer.echo(f"Removed: {dest}")

    if not scan:
        return
    try:
        with ScanClient(settings) as scan_client:
            scan_client.scan_projects()
    except ScanWarning as e:
        typer.echo(f"WARNING: gateway scan failed ({e})", err=True)
