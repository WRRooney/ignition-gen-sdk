"""doc_gen.py — OpenAPI spec JSON → api_reference/*.md generator.

Reads the parsed spec dict (via the module-level cached load_spec() from
cli._openapi_resolver) and writes the api_reference/ directory:
  - AUTH.md     : hard-coded auth template (spec has zero securitySchemes)
  - INDEX.md    : table of tags → file links + endpoint counts
  - <tag-slug>.md : one file per spec tag; per-endpoint docs in path order

AUTH.md (and every per-endpoint auth note) uses ${IGNITION_API_TOKEN}
env-var placeholder — NEVER the literal token value.

Output lands in <state-dir>/api_reference/ (see api_reference_dir()).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import Settings
from ..cli._openapi_resolver import load_spec

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AUTH.md template — hard-coded because spec has zero securitySchemes
# env-var placeholder, NEVER the literal token value.
# Must be >= 25 lines when rendered (AUTH.md length guard).
# ---------------------------------------------------------------------------

_AUTH_TEMPLATE = """\
# Authentication

The Ignition Gateway HTTP API uses a custom header token for all requests.

## Header

**Header name:** `X-Ignition-API-Token`

**Format:** `<name>:<secret>`, exactly as the gateway shows it when the API key is created.

Set `IGNITION_API_TOKEN` to that full value (env or `.env`). The header sent is:

```
X-Ignition-API-Token: ${IGNITION_API_TOKEN}
```

Never pass the literal token value in any argument, log, or documentation.
Use the `${IGNITION_API_TOKEN}` placeholder in docs; load from `.env` at runtime.

## Error Semantics

| HTTP Status | Error Class | Meaning |
|-------------|-------------|---------|
| 401 | AuthMissingError | API key missing or invalid — check IGNITION_API_TOKEN (env or .env) |
| 403 | AuthScopeError | Token authenticated but lacks required scope — review token permissions in Gateway UI |
| 400 | PayloadError | Auth OK but request payload rejected — server response body included for diagnosis |
| 422 | PayloadError | Unprocessable entity (e.g. invalid provider name) — check request body |
| 5xx | GatewayError | Gateway-side failure — retry after ensuring the gateway is up |

## Usage with ign

```bash
# Set token in .env (never pass on command line):
echo "IGNITION_API_TOKEN=your_token_here" >> .env

# Then invoke ign subcommands normally:
ign api GET /data/api/v1/gateway-info
ign db-conn list
ign tag list
```

The `ign api` verb reads `X-Ignition-API-Token` from `.env`
automatically. The header is set once at client construction and never echoed
to stdout, stderr, or exception messages.

## Security Notes

- The token is set as an HTTP header (`X-Ignition-API-Token`), NOT as a Bearer token.
- Do NOT use `AuthenticatedClient` from the generated package — it adds an
  `Authorization: Bearer` header that conflicts with `X-Ignition-API-Token`.
- The JWE guard refuses requests that contain AES-256-GCM credential
  payloads in the request body. Set encrypted values via the Gateway UI instead.
"""


# ---------------------------------------------------------------------------
# Tag slug helper
# ---------------------------------------------------------------------------

def _tag_slug(tag: str) -> str:
    """Lowercase tag name with spaces/slashes replaced by hyphens."""
    return re.sub(r"[\s/]+", "-", tag.lower())


# ---------------------------------------------------------------------------
# Per-endpoint renderer
# ---------------------------------------------------------------------------

def render_endpoint_doc(method: str, path: str, op: dict[str, Any]) -> str:
    """Render one endpoint as Markdown.

    The auth example uses the ${IGNITION_API_TOKEN} placeholder, never a literal token.
    """
    lines: list[str] = [
        f"## {method.upper()} {path}",
        "",
        f"**Summary:** {op.get('summary', '(no summary)')}",
        f"**Tag:** {op.get('tags', ['(untagged)'])[0]}",
    ]

    params = op.get("parameters", [])
    if params:
        lines += [
            "",
            "### Parameters",
            "| Name | In | Type | Required | Description |",
            "|------|----|------|----------|-------------|",
        ]
        for p in params:
            schema = p.get("schema", {})
            desc = p.get("description", "").replace("\n", " ")[:80]
            lines.append(
                f"| `{p.get('name', '')}` | {p.get('in', '')} | "
                f"{schema.get('type', 'any')} | "
                f"{'yes' if p.get('required') else 'no'} | "
                f"{desc} |"
            )

    # Check for non-JSON body (binary upload endpoints)
    request_body = op.get("requestBody", {})
    content_types = set((request_body.get("content") or {}).keys())
    binary_types = {"multipart/form-data", "application/octet-stream", "application/zip"}
    is_binary = bool(content_types & binary_types) or any(
        ct.startswith("*") for ct in content_types
    )

    lines += [
        "",
        "### Example",
        "```bash",
        f"ign api {method.upper()} {path}",
        "```",
        "",
    ]

    if is_binary:
        lines += [
            "**Note:** Binary upload — use `ign api` with `--file <file>` for this endpoint.",
            "The `--json` flag is not applicable.",
            "",
        ]

    lines += [
        "**Auth:** Set `IGNITION_API_TOKEN` in `.env`. "
        "Header: `X-Ignition-API-Token: ${IGNITION_API_TOKEN}`",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tag-file writer
# ---------------------------------------------------------------------------

def _write_tag_files(spec: dict[str, Any], out_dir: Path) -> None:
    """Group operations by first tag; write one <tag-slug>.md per tag."""
    # Build groups: tag_name -> list of (method, path, op_dict)
    groups: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}

    http_verbs = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
    paths_obj = spec.get("paths") or {}

    for path, path_item in paths_obj.items():
        for verb, op in path_item.items():
            if verb.lower() not in http_verbs:
                continue
            if not isinstance(op, dict):
                continue
            tag = (op.get("tags") or ["default"])[0]
            if tag not in groups:
                groups[tag] = []
            groups[tag].append((verb.upper(), path, op))

    for tag, endpoints in groups.items():
        slug = _tag_slug(tag)
        lines = [f"# {tag} API Reference", ""]
        for i, (method, path, op) in enumerate(endpoints):
            lines.append(render_endpoint_doc(method, path, op))
            if i < len(endpoints) - 1:
                lines.append("\n---\n")
        (out_dir / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# INDEX.md writer
# ---------------------------------------------------------------------------

def _write_index(spec: dict[str, Any], out_dir: Path) -> None:
    """Write INDEX.md — tag table with file links and endpoint counts."""
    http_verbs = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
    paths_obj = spec.get("paths") or {}

    # Count endpoints per tag
    tag_counts: dict[str, int] = {}
    for path_item in paths_obj.values():
        for verb, op in path_item.items():
            if verb.lower() not in http_verbs:
                continue
            if not isinstance(op, dict):
                continue
            tag = (op.get("tags") or ["default"])[0]
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Determine tag groups from x-tagGroups or fallback to flat tags list
    tag_groups: list[dict[str, Any]] = spec.get("x-tagGroups") or []
    if not tag_groups:
        # Fallback: single group containing all tags
        all_tags = list(tag_counts.keys())
        tag_groups = [{"name": "API Reference", "tags": all_tags}]

    total_tags = sum(len(g.get("tags", [])) for g in tag_groups)
    total_ops = sum(tag_counts.values())

    lines: list[str] = [
        "# Ignition HTTP API — Reference Index",
        "",
        f"**Total tags:** {total_tags} | **Total operations:** {total_ops}",
        "",
        "See [AUTH.md](AUTH.md) for authentication details.",
        "",
    ]

    for group in tag_groups:
        group_name = group.get("name", "API")
        group_tags = group.get("tags", [])
        lines += [f"## {group_name}", ""]
        lines += [
            "| Tag | File | Endpoints |",
            "|-----|------|-----------|",
        ]
        for tag in group_tags:
            slug = _tag_slug(tag)
            count = tag_counts.get(tag, 0)
            lines.append(f"| {tag} | [{slug}.md]({slug}.md) | {count} |")
        lines.append("")

    (out_dir / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def api_reference_dir(settings: Settings) -> Path:
    """Where generated endpoint docs land: <state-dir>/api_reference/."""
    return settings.ignition_state_dir / "api_reference"


def generate_docs(settings: Settings | None = None) -> None:
    """Generate api_reference/*.md from spec JSON.

    Writes:
      - AUTH.md   : hard-coded auth template with env-var placeholder
      - INDEX.md  : x-tagGroups-based table with file links + endpoint counts
      - <tag-slug>.md : per-endpoint docs for each spec tag

    Args:
        settings: Optional Settings instance. Constructed from env if None.
    """
    if settings is None:
        settings = Settings()  # type: ignore[call-arg]
    spec = load_spec(settings)
    out_dir = api_reference_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    # AUTH.md is a fixed template: the spec declares no securitySchemes.
    (out_dir / "AUTH.md").write_text(_AUTH_TEMPLATE, encoding="utf-8")
    _write_tag_files(spec, out_dir)
    _write_index(spec, out_dir)
