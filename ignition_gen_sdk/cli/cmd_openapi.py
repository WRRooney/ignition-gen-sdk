"""``ign openapi`` — fetch the gateway's OpenAPI spec, generate the typed client, render docs.

The gateway publishes its spec at ``GET /openapi.json`` (linked from the
gateway's API docs page). Everything lands in the SDK state dir (``.ign/``):

    openapi.json     the spec (``fetch``)
    openapi.hash     spec hash sidecar (``gen``)
    client/          generated ``ignition_api_client`` package (``gen``)
    api_reference/   per-tag endpoint markdown + INDEX.md + AUTH.md (``docs``)

``ign api --strict``, the typed provider/db-conn verbs, and the path resolver
all read the spec from here.
"""
from __future__ import annotations

from typing import Annotated

import typer

from ..backends.api_client import IgnitionAPIError
from ..config import Settings
from ._errors import render_error

openapi_app = typer.Typer(no_args_is_help=True, help="Gateway OpenAPI spec: fetch, gen, docs.")


def _settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as e:  # noqa: BLE001
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


@openapi_app.command("fetch")
def fetch_cmd(
    gen: Annotated[bool, typer.Option("--gen/--no-gen", help="Also regenerate the typed client.")] = False,
) -> None:
    """Download (or refresh) the gateway's OpenAPI spec into <state-dir>/openapi.json."""
    import json  # noqa: PLC0415

    from ..regen.engine import fetch_spec  # noqa: PLC0415

    settings = _settings()
    try:
        out = fetch_spec(settings)
    except IgnitionAPIError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    data = json.loads(out.read_text(encoding="utf-8"))
    typer.echo(f"Wrote {out} ({len(data['paths'])} paths, {data.get('info', {}).get('version', '?')})")
    if gen:
        _gen(settings, force=True)


def _gen(settings: Settings, *, force: bool) -> None:
    from ..regen.engine import ensure_generated_client, needs_regen  # noqa: PLC0415

    if force and settings.openapi_hash_sidecar_path.exists():
        settings.openapi_hash_sidecar_path.unlink()
    if not force and not needs_regen(settings):
        typer.echo("Generated client is current.")
        return
    try:
        ensure_generated_client(settings)
    except IgnitionAPIError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Generated client at {settings.openapi_generated_client_path}")


@openapi_app.command("gen")
def gen_cmd(
    force: Annotated[bool, typer.Option("--force", help="Regenerate even if the spec hash matches.")] = False,
) -> None:
    """Generate the typed client from the fetched spec (fetches it first if missing)."""
    _gen(_settings(), force=force)


@openapi_app.command("docs")
def docs_cmd() -> None:
    """Render <state-dir>/api_reference/*.md from the fetched spec."""
    from ..regen.doc_gen import api_reference_dir, generate_docs  # noqa: PLC0415

    settings = _settings()
    try:
        generate_docs(settings)
    except IgnitionAPIError as e:
        render_error(e, no_color=False)
        raise typer.Exit(code=1) from None
    typer.echo(f"Wrote {api_reference_dir(settings)}")
