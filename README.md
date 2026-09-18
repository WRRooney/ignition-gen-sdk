# ignition-gen-sdk

Agent SDK and `ign` CLI for Inductive Automation **Ignition 8.3**.

Author tags, UDTs, Perspective views, pages, scripts, themes and other project
resources as typed Python (Pydantic), emit the exact JSON the gateway accepts,
and write it through one of two backends: the gateway HTTP API or the gateway's
on-disk `config/resources` and `projects` trees (followed by a scan). Every
write goes through the models, so an agent never hand-edits `view.json`.

Built for AI coding agents (Claude Code, Codex, Gemini CLI, Cursor, OpenCode, …)
that run with access to a gateway API token and, optionally, its data directory.
The companion [ignition-skills](../ignition-skills) repo teaches agents how to
use it. Ignition 8.3 only.

## Install

```bash
uv tool install git+https://github.com/WRRooney/ignition-gen-sdk   # or: pip install git+https://github.com/WRRooney/ignition-gen-sdk
# extras: [strict] deep OpenAPI validation, [runtime] headless view validation, e.g.
#   uv tool install 'ignition-gen-sdk[strict,runtime] @ git+https://github.com/WRRooney/ignition-gen-sdk'
```

## Configure

Environment variables, or a `.env` in the working directory (see `.env.example`):

| Variable | Required | Meaning |
|---|---|---|
| `IGNITION_URL` | yes | Gateway base URL, e.g. `http://localhost:8088` |
| `IGNITION_API_TOKEN` | yes | Full `<name>:<secret>` value shown once when you create the key under Platform > Security > API Keys |
| `IGNITION_DATA_DIR` | for disk writes | The gateway data directory (holds `config/resources/`, `projects/`) |
| `IGNITION_PROJECT` | no | Default Perspective project (`Global`) |
| `IGNITION_TAG_PROVIDER` | no | Default tag provider (`default`) |
| `IGNITION_STATE_DIR` | no | SDK state dir (`./.ign`), gitignore it |

The token is never printed, logged or placed in argv. Use `ign api` instead of
`curl` for the same reason.

## Ten-minute quickstart

```bash
ign provider names          # first call fetches the gateway spec to .ign/ and generates the typed client

ign tag build                                       # print a demo tag JSON
ign tag push --provider default --path Tanks/T01 --dry-run
ign tag push --provider default --path Tanks/T01    # via API, records a manifest entry

ign view write --project Demo --view-path Demo/Hello --dry-run
ign view write --project Demo --view-path Demo/Hello   # disk write + POST /scan/projects
ign page mount --project Demo --view-path Demo/Hello --url /hello
ign view validate --project Demo --page /hello      # headless render; needs [runtime]

ign logs --min-level ERROR --limit 20               # read the gateway log
```

`--dry-run` prints the JSON that would be written. Disk writes trigger a
gateway scan unless `--no-scan` is given. The project must already exist
(`projects/<name>/project.json`); create projects through the gateway.

## Library

```python
from ignition_gen_sdk import Settings, ViewBuilder, Tag, ProjectDiskBackend

vb = ViewBuilder(name="Hello")
vb.flex_root()
vb.label(text="Hello, Perspective").bind_text("[default]Tanks/T01/Level")
view = vb.build()                       # full Pydantic validation happens here

backend = ProjectDiskBackend(Settings())
backend.write_view("Demo", "Demo/Hello", view)
```

`ignition_gen_sdk` re-exports the stable surface: `Settings`, models (`Tag`,
`UdtType`, `UdtInstance`, `Alarm`, `View`, `Component`), `ViewBuilder`,
`TagBuilder`, the backends (`IgnitionAPIClient`, `ApiBackend`, `DiskBackend`,
`ProjectDiskBackend`, `WriteRouter`, `ScanClient`) and `seed_guard`. Deeper
module paths work but may move between minor versions.

## Verbs

| Group | Verbs | Writes |
|---|---|---|
| `tag` | build, push, import, udt-type, udt-instance, set-udt-member-prop, set-udt-type-prop, delete | API or disk |
| `view` | build, write, set-prop, replace-text, delete, validate | disk |
| `page`, `session-props`, `script`, `named-query`, `style-class`, `stylesheet`, `theme` | write/list/delete per resource | disk |
| `provider`, `db-conn`, `alarm-journal`, `driver` | list, get, create, update, delete, rename, describe | API |
| `alarm-pipeline` | list, show, replace-text, copy | disk |
| `api` | any `/data/api/v1/*` call, `--strict` validates against the spec | API |
| `openapi` | fetch (refresh the spec), gen, docs | `.ign/` |
| `diff`, `logs`, `component` | read-only | — |
| `tools` | list, run — your own generators in `.ign_tools/` | whatever they do |
| `builtins` | audit (unknown `system.*`/expression calls), refresh | — |
| `icons` | list glyphs a Perspective module actually ships | — |

`ign <group> --help` documents each verb.

## Your own tools

Put generator scripts in `.ign_tools/` at your project root. `ign tools list`
shows them; `ign tools run NAME [ARGS]` executes one. They import
`ignition_gen_sdk` like any script. Generators are seeds: import
`ignition_gen_sdk.tools.seed_guard` and refuse to overwrite views someone has since
edited in the Designer.

## Development

```bash
uv venv && uv pip install -e '.[dev,strict]'
pytest                                   # unit + fixture tests
IGNITION_OPENAPI_SPEC_PATH=.ign/openapi.json pytest   # also the spec-dependent modules (after any ign call fetched it)
IGNITION_SAMPLE_VIEWS=/path/to/samplequickstart/.../views pytest   # fixture-diff vs the sample project
```

Tests never need a live gateway except `pytest -m smoke`.

## License

Apache-2.0.
