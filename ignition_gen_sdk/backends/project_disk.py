"""ProjectDiskBackend — writes Perspective views under projects/<name>/.

Sibling of DiskBackend. Different write root (projects/ vs
config/resources/core/), different guard (fail-loud project-skeleton
check vs the layer-guard for tags).

When projects/<name>/project.json is missing, ``write_view`` raises
ProjectNotFoundError. The perspective views/ subdirectory is auto-created
when missing. The project itself is NOT auto-scaffolded.

view_path is split-then-each-segment-validated. ``.`` and
``..`` segments raise ValueError. Empty / whitespace-only
``view_path`` raises ValueError. Inner empty segments (e.g.
``"//foo//"``) are skipped — preserves
``test_write_view_path_split_then_encoded_pitfall_5``. After dest is
computed, ``dest.resolve()`` is asserted to be ``views_root.resolve()``
or a descendant — defense-in-depth containment check.

Empty-segment filtering lives in one place, the module-private helper
``_split_view_path_segments``; ``write_view`` has exactly one call site
for segment parsing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import ast
import json
import re
import shutil
from pathlib import Path

from ..config import Settings
from ..models.named_query import NamedQuery
from ..models.views.view import View
from ..serializers.resource_metadata import view_resource_json
from ..serializers.view_disk import view_to_disk
from ._fs_utils import _atomic_write, _encode_segment

if TYPE_CHECKING:  # pragma: no cover
    from ..models.page_config import PageConfig
    from ..models.session_props import SessionProps

# ign-owned stylesheet block delimiters (see write_stylesheet_block).
_BLOCK_DELIM_RE = re.compile(r"/\*\s*(>>>|<<<)\s*ign:")

# A named-query bind parameter. The lookbehind rejects Postgres's ``::`` cast
# operator and any ``word:word`` run, so only a real ``:name`` token matches.
_SQL_PARAM_RE = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
# Single-quoted SQL string literals, doubled-quote escapes included. Stripped
# before the parameter scan so a LIKE pattern such as ':/tag:' is not read as
# a parameter.
_SQL_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")

# Gson writes HTML-safe JSON by default, which is what the Designer saves: the
# five characters below are emitted as \u escapes inside string values. Plain
# json.dumps leaves them literal, so every Designer round-trip rewrote whole
# expressions ("a = b" <-> "a = b") as phantom diff noise. Escaping after
# json.dumps is safe because none of these characters ever appear in JSON
# SYNTAX — only inside string literals.
_HTML_SAFE_ESCAPES = {
    "&": "\\u0026",
    "<": "\\u003c",
    ">": "\\u003e",
    "=": "\\u003d",
    "'": "\\u0027",
}


def dumps_designer(payload: object, indent: int = 2) -> str:
    """json.dumps with Gson's HTML-safe escaping — byte-comparable to a
    Designer save, so ign writes do not churn on round-trip. Non-ASCII stays
    LITERAL (``m³``, ``—``) — Gson never \\u-escapes it; json.dumps' default did,
    churning every such line of a Designer-authored udts.json."""
    text = json.dumps(payload, indent=indent, ensure_ascii=False)
    for raw, escaped in _HTML_SAFE_ESCAPES.items():
        text = text.replace(raw, escaped)
    return text


def sql_bind_parameters(sql: str) -> set[str]:
    """Every ``:name`` Ignition will treat as a bind parameter in ``sql``.

    Two rules, and they pull in opposite directions:

    * String literals do NOT contribute parameters — a LIKE pattern like
      ``'%:/tag:'`` is data, not a bind.
    * Comments DO. Ignition scans the raw text, so a ``:word`` in a comment
      becomes a phantom parameter that fails the query at runtime.

    So each line is split at its ``--`` marker: literals are stripped from the
    code half only, and the comment half is scanned verbatim. Scanning for
    literals across comments too is what makes an ordinary apostrophe (as in
    "the chart's width") swallow the rest of the file and hide every real
    parameter after it.
    """
    found: set[str] = set()
    for line in sql.splitlines():
        code, marker, comment = line.partition("--")
        found |= set(_SQL_PARAM_RE.findall(_SQL_LITERAL_RE.sub("''", code)))
        if marker:
            found |= set(_SQL_PARAM_RE.findall(comment))
    return found


def _split_view_path_segments(view_path: str) -> list[str]:
    """Split, filter, validate, and encode a slash-separated view path.

    Rejects:
        - whole string empty / whitespace-only -> ValueError
        - per-segment '.', '..', or whitespace-only via _encode_segment
        - net-empty result (e.g. '/', '//') -> ValueError

    Permits:
        - inner empty segments ('//foo//' -> ['foo']) preserving the
          existing skip-empty-inner behavior tested in
          test_write_view_path_split_then_encoded_pitfall_5.

    Replaces the parallel ``s.strip()`` vs ``not seg`` filters that
    previously lived in ``write_view``.
    """
    if not view_path or not view_path.strip():
        raise ValueError(
            f"view_path is empty or whitespace-only: {view_path!r}; "
            f"a view must live under a named subdirectory of views/"
        )
    encoded: list[str] = []
    for seg in view_path.split("/"):
        if not seg:  # skip empty inner segments
            continue
        encoded.append(_encode_segment(seg))  # raises on '.', '..', whitespace
    if not encoded:
        raise ValueError(
            f"view_path has no non-empty segments: {view_path!r}; "
            f"a view must live under a named subdirectory of views/"
        )
    return encoded


class ProjectNotFoundError(ValueError):
    """Raised when --project name doesn't exist on disk under projects/."""


class ViewNotFoundError(FileNotFoundError):
    """Raised when the target view directory does not exist on disk."""


class ScriptNotFoundError(FileNotFoundError):
    """Raised when the target library script directory does not exist on disk."""


class ViewScriptError(ValueError):
    """A view carries an embedded script that does not parse."""


class ScriptTabError(ValueError):
    """Raised when project library script code contains space-indented lines.

    Ignition project library scripts run on Jython 2.7 inside the gateway.
    Project library scripts use TAB indentation throughout (Designer convention).

    This check uses CPython-3 ast.parse semantics as a compile proxy.
    It will catch CPython-3 SyntaxErrors (e.g. invalid syntax, undefined
    tokens). It may NOT catch all Jython-2.7-specific constructs (e.g.
    print-as-statement), since Jython 2.7 grammar ≈ Python 2.7 and differs
    from CPython 3.

    If any non-empty line starts with a space character, this error is raised.
    Auto-conversion is intentionally NOT performed — mixed indentation could
    silently change semantics. Supply TAB-indented code explicitly.
    """


class UnknownSystemCallError(ValueError):
    """Raised when a project library script references a system.* function that
    is not a known Ignition scripting function — an unknown namespace (any
    namespace is checked) or, for fully-sourced namespaces, an unknown leaf.

    Such a call passes ast.parse but throws AttributeError live in the gateway.
    Whitelist source/extension: ignition_gen_sdk.validation.ignition_builtins.
    """


def validate_script_code(code: str) -> None:
    """Run the project-library-script acceptance checks WITHOUT writing.

    Same gate `write_script` applies before any disk write, factored out so the
    CLI dry-run can preview faithfully (a dry-run that skipped these
    would "pass" on code a real write rejects). Raises:
      - ScriptTabError   — any non-empty line starts with a space (TAB rule).
      - SyntaxError      — CPython-3 ast.parse proxy for a compile error.
      - UnknownSystemCallError — a system.* call to an unknown namespace/leaf.
    """
    for line in code.splitlines():
        if line and line[0] == " ":
            raise ScriptTabError(
                "Project library scripts require TAB indentation. "
                "Code contains space-indented line. "
                "Note: this check uses CPython-3 compile semantics and may not catch "
                "all Jython-2.7-only constructs like print-as-statement."
            )
    ast.parse(code, filename="<script>")
    from ..validation import unknown_system_calls

    bad_calls = unknown_system_calls(code)
    if bad_calls:
        raise UnknownSystemCallError(
            f"script references unknown system.* function(s): {bad_calls}. "
            f"Check the namespace/spelling (e.g. system.tag not system.tags); if "
            f"this is a real function add it to "
            f"ignition_gen_sdk.validation.ignition_builtins.SYSTEM_FUNCTIONS."
        )


def script_resource_json() -> dict:
    """The resource.json a project-library script write emits.

    Single source for both `write_script` and the CLI dry-run preview.
    `hintScope: 2` is REQUIRED — without it the gateway silently skips the
    module (it never loads, so anything calling it fails silently). The
    signature is omitted; the gateway computes lastModificationSignature on scan.
    """
    from datetime import datetime, timezone

    return {
        "scope": "A",
        "version": 1,
        "restricted": False,
        "overridable": True,
        "files": ["code.py"],
        "attributes": {
            "hintScope": 2,
            "lastModification": {
                "actor": "ign",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        },
    }


def _iter_view_scripts(node, path=""):
    """Yield (jsonPath, source) for every embedded script in a view payload."""
    if isinstance(node, dict):
        for key, value in node.items():
            where = "%s.%s" % (path, key) if path else key
            if key in ("code", "script") and isinstance(value, str):
                yield where, value
            else:
                for found in _iter_view_scripts(value, where):
                    yield found
    elif isinstance(node, list):
        for index, item in enumerate(node):
            for found in _iter_view_scripts(item, "%s[%d]" % (path, index)):
                yield found


def validate_view_scripts(payload) -> None:
    """Raise ViewScriptError if any embedded script fails to parse.

    Perspective stores binding transforms, event handlers, message handlers and
    custom methods as the BODY of a function it wraps at runtime, so a broken
    one is not a load error -- the view saves, renders, and the binding simply
    never produces a value. The visible symptom is an empty list or a default,
    with a stack trace only in the gateway log.

    That is how a comment line that lost its leading '#' shipped a user-
    management page that reported "No users match." against a populated user
    source, and did it convincingly enough to pass a hand-written check for the
    data leak the same edit was fixing.

    Bodies are indented one level because of the wrapper, so they are compiled
    inside a throwaway def. The signature does not matter: names resolve at
    runtime, and this only asks whether the source parses.
    """
    broken = []
    for where, source in _iter_view_scripts(payload):
        if not source.strip():
            continue
        # Probe the first line that carries CODE: blank lines and comment
        # lines are invisible to the parser's indentation rules, so a
        # column-0 comment above a tab-indented body must not suppress the
        # wrapper (real case: ExcelReports' Excel Query onActionPerformed).
        first = next((ln for ln in source.splitlines()
                      if ln.strip() and not ln.lstrip().startswith("#")), "")
        candidate = ("def _f(*a, **k):\n" + source
                     if first[:1] in (" ", "\t") else source)
        try:
            ast.parse(candidate)
        except SyntaxError as exc:
            broken.append("%s: %s (line %s: %r)"
                          % (where, exc.msg, exc.lineno, (exc.text or "").rstrip()))
    if broken:
        raise ViewScriptError(
            "view contains %d script(s) that do not parse; Perspective would "
            "save this and silently produce nothing:\n  %s"
            % (len(broken), "\n  ".join(broken)))


class ProjectDiskBackend:
    """Writes Perspective views under projects/<name>/com.inductiveautomation.perspective/views/<path>/."""

    def __init__(self, settings: Settings) -> None:
        self._projects_root = settings.ignition_data_root / "projects"

    def _project_views_root(self, project: str) -> Path:
        """Fail loud ONLY if project.json is missing.

        The perspective views/ subdirectory is auto-created when
        missing under an existing project.
        """
        proj_dir = self._projects_root / _encode_segment(project)
        if not (proj_dir / "project.json").is_file():
            raise ProjectNotFoundError(
                f"Project {project!r} not found at {proj_dir}. "
                f"Create the project in the Ignition Designer first; "
                f"this tool does not auto-scaffold projects."
            )
        views_root = proj_dir / "com.inductiveautomation.perspective" / "views"
        # Auto-create the perspective
        # subtree when project.json is present but views/ has not been
        # touched in Designer yet.
        views_root.mkdir(parents=True, exist_ok=True)
        return views_root

    def write_view(
        self, project: str, view_path: str, view: View, documentation: str | None = None
    ) -> Path:
        """Write view.json + resource.json. Returns the leaf directory path.

        ``documentation`` → resource.json ``documentation``; ``None`` keeps an
        existing manifest's text (a rewrite must not drop a Designer-authored
        notice)."""
        segments = _split_view_path_segments(view_path)  # single source of truth
        views_root = self._project_views_root(project)   # project guard + mkdir
        dest = views_root
        for seg in segments:
            dest = dest / seg
        # Defense-in-depth: containment check on the resolved path.
        views_root_resolved = views_root.resolve()
        dest_resolved = Path(str(dest)).resolve(strict=False)
        if (
            dest_resolved != views_root_resolved
            and views_root_resolved not in dest_resolved.parents
        ):
            raise ValueError(
                f"resolved view-path containment violation: {dest_resolved} "
                f"is not inside views root {views_root_resolved}"
            )
        payload = view_to_disk(view)
        # Before anything touches disk: a view whose embedded Python does not
        # parse renders as silence, not as an error.
        validate_view_scripts(payload)
        dest.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            dest / "view.json",
            dumps_designer(payload, indent=2),
        )
        # When OVERWRITING a Designer-authored view, keep any extra
        # manifest entries (thumbnail.png) whose files actually exist on disk —
        # a fresh files:["view.json"] would orphan the Designer thumbnail and
        # desync the resource manifest from the directory contents.
        existing_manifest: dict = {}
        existing = dest / "resource.json"
        if existing.is_file():
            try:
                existing_manifest = json.loads(existing.read_text())
            except (ValueError, OSError):
                existing_manifest = {}  # unreadable manifest: fall back to the fresh default
        if documentation is None:
            documentation = existing_manifest.get("documentation")
        resource = view_resource_json(documentation)
        for f in existing_manifest.get("files", []):
            if f not in resource["files"] and (dest / f).is_file():
                resource["files"].append(f)
        # Heal a previously-orphaned Designer thumbnail: on disk but unlisted.
        if "thumbnail.png" not in resource["files"] and (dest / "thumbnail.png").is_file():
            resource["files"].append("thumbnail.png")
        _atomic_write(
            dest / "resource.json",
            dumps_designer(resource, indent=2),
        )
        return dest

    def write_style_class(self, project: str, name: str, style: dict) -> Path:
        """Write style-classes/<name>/{style.json, resource.json}.

        ``style`` is the raw style.json payload — top-level keys limited to
        ``base`` and ``variants`` (verified against Designer-written files;
        anything else is a typo and fails loud). ``name`` may be a nested
        path (slash-separated), mirroring view paths.
        """
        unknown = set(style) - {"base", "variants"}
        if unknown:
            raise ValueError(
                f"style class {name!r}: unknown top-level key(s) {sorted(unknown)!r} "
                "— style.json carries only 'base' and 'variants'."
            )
        from ..serializers.resource_metadata import style_class_resource_json

        segments = _split_view_path_segments(name)
        # _project_views_root validates project.json exists; style-classes is
        # its sibling directory.
        root = self._project_views_root(project).parent / "style-classes"
        dest = root
        for seg in segments:
            dest = dest / seg
        # Defense-in-depth: containment check on the resolved path (mirrors
        # write_view; guarantee #3 in _fs_utils).
        root_resolved = root.resolve()
        dest_resolved = Path(str(dest)).resolve(strict=False)
        if dest_resolved != root_resolved and root_resolved not in dest_resolved.parents:
            raise ValueError(
                f"resolved style-class path containment violation: {dest_resolved} "
                f"is not inside style-classes root {root_resolved}"
            )
        dest.mkdir(parents=True, exist_ok=True)
        _atomic_write(dest / "style.json", dumps_designer(style, indent=2))
        _atomic_write(dest / "resource.json", dumps_designer(style_class_resource_json(), indent=2))
        return dest

    def _project_stylesheet_dir(self, project: str) -> Path:
        """projects/<name>/com.inductiveautomation.perspective/stylesheet."""
        dest = self._project_views_root(project).parent / "stylesheet"
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    def read_stylesheet(self, project: str) -> str:
        """Current stylesheet.css text ('' when the project has none yet)."""
        css = self._project_stylesheet_dir(project) / "stylesheet.css"
        return css.read_text(encoding="utf-8") if css.is_file() else ""

    def write_stylesheet_block(self, project: str, marker: str, css: str) -> Path:
        """Upsert an ign-owned block inside the project's stylesheet.css.

        The block is delimited by ``/* >>> ign:<marker> */`` … ``/* <<<
        ign:<marker> */``. Re-running REPLACES only that block, so
        hand-authored CSS around it (the Designer stylesheet is user
        territory) is preserved byte-for-byte. A new marker appends at the end.

        The Perspective option overlays (dropdown lists, modals) render in a
        portal outside the component subtree, so a style class cannot reach
        them — the project stylesheet is the only channel.
        """
        if not marker or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", marker):
            raise ValueError(
                f"stylesheet marker {marker!r} must be 1-64 chars of "
                "letters/digits/dot/dash/underscore (it is embedded in a CSS comment)."
            )
        if _BLOCK_DELIM_RE.search(css):
            # a stray delimiter inside the payload would corrupt future upserts
            raise ValueError("css payload must not contain ign block delimiters.")
        begin, end = f"/* >>> ign:{marker} */", f"/* <<< ign:{marker} */"
        block = f"{begin}\n{css.strip()}\n{end}\n"

        existing = self.read_stylesheet(project)
        if begin in existing and end in existing:
            head, rest = existing.split(begin, 1)
            _, tail = rest.split(end, 1)
            updated = head + block + tail.lstrip("\n")
        else:
            sep = "" if not existing or existing.endswith("\n\n") else (
                "\n" if existing.endswith("\n") else "\n\n")
            updated = existing + sep + block

        from ..serializers.resource_metadata import stylesheet_resource_json

        dest = self._project_stylesheet_dir(project)
        _atomic_write(dest / "stylesheet.css", updated)
        _atomic_write(dest / "resource.json", dumps_designer(stylesheet_resource_json(), indent=2))
        return dest

    def remove_stylesheet_block(self, project: str, marker: str) -> bool:
        """Delete one ign-owned block from the project's stylesheet.css.

        The inverse of :meth:`write_stylesheet_block`, and the only way to
        RENAME a marker (upsert under the new name, remove the old) — an
        upsert with empty content is refused, and would leave an empty block
        behind anyway. Hand-authored CSS around the block is untouched.

        Returns True when a block was removed, False when the marker was not
        present (so callers can be idempotent without pre-checking).
        """
        if not marker or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", marker):
            raise ValueError(
                f"stylesheet marker {marker!r} must be 1-64 chars of "
                "letters/digits/dot/dash/underscore."
            )
        begin, end = f"/* >>> ign:{marker} */", f"/* <<< ign:{marker} */"
        existing = self.read_stylesheet(project)
        if begin not in existing or end not in existing:
            return False
        head, rest = existing.split(begin, 1)
        _, tail = rest.split(end, 1)
        updated = head.rstrip("\n")
        tail = tail.lstrip("\n")
        if updated and tail:
            updated += "\n\n"
        elif updated:
            updated += "\n"
        updated += tail

        from ..serializers.resource_metadata import stylesheet_resource_json

        dest = self._project_stylesheet_dir(project)
        _atomic_write(dest / "stylesheet.css", updated)
        _atomic_write(dest / "resource.json", dumps_designer(stylesheet_resource_json(), indent=2))
        return True

    def delete_style_class(self, project: str, name: str) -> Path:
        """Remove a style-classes/<name>/ directory.

        Generated style classes go stale when a view stops using them (the
        generator simply stops emitting one), and a stale class silently keeps
        applying to anything that still names it. Mirrors delete_view: same
        containment guard, FileNotFoundError when absent.
        """
        segments = _split_view_path_segments(name)
        root = self._project_views_root(project).parent / "style-classes"
        dest = root.joinpath(*segments)
        root_resolved = root.resolve()
        dest_resolved = Path(str(dest)).resolve(strict=False)
        if dest_resolved != root_resolved and root_resolved not in dest_resolved.parents:
            raise ValueError(
                f"resolved style-class path containment violation: {dest_resolved}"
            )
        if not dest.is_dir():
            raise FileNotFoundError(
                f"style class {name!r} not found in project {project!r}."
            )
        shutil.rmtree(dest)
        return dest

    def _project_page_config_dir(self, project: str, create: bool = True) -> Path:
        """projects/<name>/com.inductiveautomation.perspective/page-config.

        Raises ProjectNotFoundError if project.json is absent.

        ``create`` MUST be False on a read path. Perspective treats the
        DIRECTORY as the resource: a child project holding an empty
        page-config/ shadows its parent's routes completely, so every route
        added to the parent 404s. `page list` auto-creating this directory is
        exactly how that happened once — a read-only command silently broke
        route inheritance, and the symptom (a route that will not resolve, that
        no scan fixes) looks nothing like its cause.
        """
        proj_dir = self._projects_root / _encode_segment(project)
        if not (proj_dir / "project.json").is_file():
            raise ProjectNotFoundError(
                f"Project {project!r} not found at {proj_dir}. "
                f"Create the project in the Ignition Designer first; "
                f"this tool does not auto-scaffold projects."
            )
        pc_dir = proj_dir / "com.inductiveautomation.perspective" / "page-config"
        if create:
            pc_dir.mkdir(parents=True, exist_ok=True)
        return pc_dir

    def read_page_config(self, project: str) -> "PageConfig":
        """Load the project's existing page-config (empty PageConfig if none).

        Basis for incremental mounting — add a page without dropping existing ones.
        """
        from ..models.page_config import PageConfig

        pc_dir = self._project_page_config_dir(project, create=False)
        cfg = pc_dir / "config.json"
        if not cfg.is_file():
            return PageConfig()
        return PageConfig.model_validate(json.loads(cfg.read_text(encoding="utf-8")))

    def write_page_config(self, project: str, page_config: "PageConfig") -> Path:
        """Write page-config/{config.json,resource.json}. Returns the directory."""
        from ..serializers.resource_metadata import page_config_resource_json

        pc_dir = self._project_page_config_dir(project)
        if not pc_dir.is_relative_to(self._projects_root):  # layer guard
            raise ValueError(
                f"layer guard: resolved page-config dir {pc_dir} is outside "
                f"projects/ root {self._projects_root}; refusing to write"
            )
        _atomic_write(pc_dir / "config.json", dumps_designer(page_config.config_json(), indent=2))
        _atomic_write(pc_dir / "resource.json", dumps_designer(page_config_resource_json(), indent=2))
        return pc_dir

    def _project_session_props_dir(self, project: str, create: bool = True) -> Path:
        """projects/<name>/com.inductiveautomation.perspective/session-props.

        Raises ProjectNotFoundError if project.json is absent.

        ``create`` MUST be False on a read path, for the same reason as
        page-config: these resources inherit per RESOURCE, and Perspective
        treats the DIRECTORY as the resource. A child left holding an empty
        session-props/ stops inheriting its parent's custom properties
        entirely — and an auto-mkdir on a read is a silent way to cause that.
        """
        proj_dir = self._projects_root / _encode_segment(project)
        if not (proj_dir / "project.json").is_file():
            raise ProjectNotFoundError(
                f"Project {project!r} not found at {proj_dir}. "
                f"Create the project in the Ignition Designer first; "
                f"this tool does not auto-scaffold projects."
            )
        sp_dir = proj_dir / "com.inductiveautomation.perspective" / "session-props"
        if create:
            sp_dir.mkdir(parents=True, exist_ok=True)
        return sp_dir

    def read_session_props(self, project: str) -> "SessionProps":
        """Load the project's existing session-props (empty SessionProps if none)."""
        from ..models.session_props import SessionProps

        sp_dir = self._project_session_props_dir(project, create=False)
        pj = sp_dir / "props.json"
        if not pj.is_file():
            return SessionProps()
        return SessionProps.model_validate(json.loads(pj.read_text(encoding="utf-8")))

    def write_session_props(self, project: str, session_props: "SessionProps") -> Path:
        """Write session-props/{props.json,resource.json}. Returns the directory."""
        from ..serializers.resource_metadata import session_props_resource_json

        sp_dir = self._project_session_props_dir(project)
        if not sp_dir.is_relative_to(self._projects_root):  # layer guard
            raise ValueError(
                f"layer guard: resolved session-props dir {sp_dir} is outside "
                f"projects/ root {self._projects_root}; refusing to write"
            )
        _atomic_write(sp_dir / "props.json", dumps_designer(session_props.props_json(), indent=2))
        _atomic_write(sp_dir / "resource.json", dumps_designer(session_props_resource_json(), indent=2))
        return sp_dir

    def _project_scripts_root(self, project: str) -> Path:
        """Return projects/<name>/ignition/script-python (project-exists guard).

        Raises ProjectNotFoundError if project.json is absent — same guard as
        _project_views_root. Does NOT auto-mkdir the scripts root; write_script
        creates directories at the leaf.
        """
        proj_dir = self._projects_root / _encode_segment(project)
        if not (proj_dir / "project.json").is_file():
            raise ProjectNotFoundError(
                f"Project {project!r} not found at {proj_dir}. "
                f"Create the project in the Ignition Designer first; "
                f"this tool does not auto-scaffold projects."
            )
        return proj_dir / "ignition" / "script-python"

    def write_script(self, project: str, script_path: str, code: str) -> Path:
        """Write code.py + resource.json for a project library script.

        Parameters
        ----------
        project:
            Ignition project name (must have project.json on disk).
        script_path:
            Slash-separated package path, e.g. "plant/nav". The final segment is
            the package directory that receives code.py + resource.json.
        code:
            Python source code. Must be TAB-indented (ScriptTabError on any
            space-indented non-empty line) and parse-clean under CPython 3
            ast.parse (SyntaxError otherwise).

        Returns
        -------
        Path
            The leaf directory that received code.py + resource.json.

        Raises
        ------
        ProjectNotFoundError
            project.json absent.
        ValueError
            Empty/invalid script_path segments, or resolved path outside
            _projects_root (layer guard).
        ScriptTabError
            Any non-empty line starts with a space character.
        SyntaxError
            Code fails ast.parse (CPython-3 compile proxy; note: Jython 2.7
            grammar ≈ Python 2.7 — this check may not catch all
            Jython-2.7-only constructs such as print-as-statement).
        """
        # 1. Project-exists guard
        scripts_root = self._project_scripts_root(project)
        # 2. Validate and encode path segments (reuse existing helper)
        segments = _split_view_path_segments(script_path)
        # 3. Build destination
        dest = scripts_root
        for seg in segments:
            dest = dest / seg
        # 4. Layer guard: resolved path must be inside _projects_root
        if not dest.is_relative_to(self._projects_root):
            raise ValueError(
                f"layer guard: resolved path {dest} is outside projects/ root "
                f"{self._projects_root}; refusing to write"
            )
        # 5-6.5. Acceptance gate (TAB-indent + ast.parse + system.* whitelist).
        # Factored into validate_script_code() so the CLI dry-run runs the SAME
        # checks — a preview must reflect what a real write accepts.
        validate_script_code(code)
        # 7. Create leaf directory (parents=True for nested packages)
        dest.mkdir(parents=True, exist_ok=True)
        # 8 & 9. Atomic writes for both files
        _atomic_write(dest / "code.py", code)
        _atomic_write(
            dest / "resource.json",
            dumps_designer(script_resource_json(), indent=2),
        )
        return dest

    def _project_named_query_root(self, project: str) -> Path:
        """projects/<name>/ignition/named-query (project-exists guard)."""
        proj_dir = self._projects_root / _encode_segment(project)
        if not (proj_dir / "project.json").is_file():
            raise ProjectNotFoundError(
                f"Project {project!r} not found at {proj_dir}. "
                f"Create the project in the Ignition Designer first; "
                f"this tool does not auto-scaffold projects."
            )
        return proj_dir / "ignition" / "named-query"

    def delete_named_query(self, project: str, query_path: str) -> Path:
        """Remove a named-query directory.

        A named query outlives the script that called it: nothing references
        it by import, so a retired query just sits there looking live. Mirrors
        delete_style_class — same containment guard, FileNotFoundError when
        absent.
        """
        segments = _split_view_path_segments(query_path)
        root = self._project_named_query_root(project)
        dest = root.joinpath(*segments)
        root_resolved = root.resolve()
        dest_resolved = Path(str(dest)).resolve(strict=False)
        if dest_resolved != root_resolved and root_resolved not in dest_resolved.parents:
            raise ValueError(
                f"resolved named-query path containment violation: {dest_resolved}"
            )
        if not dest.is_dir():
            raise FileNotFoundError(
                f"named query {query_path!r} not found in project {project!r}."
            )
        shutil.rmtree(dest)
        return dest

    def write_named_query(
        self, project: str, query_path: str, sql: str, config: NamedQuery
    ) -> Path:
        """Write query.sql + resource.json for a named query.

        Every ``:name`` token in the SQL must be declared in ``config``, and
        every declared parameter must appear in the SQL. Ignition's parser
        finds parameters by scanning the raw text — INCLUDING inside comments —
        so a stray ``:word`` in a comment becomes a phantom bind parameter and
        the query fails at runtime with a missing-parameter error. That is why
        the check runs over the whole file rather than a comment-stripped copy.
        """
        from ..serializers.resource_metadata import named_query_resource_json

        declared = {p.identifier for p in config.parameters}
        used = sql_bind_parameters(sql)
        if used != declared:
            missing = sorted(used - declared)
            unused = sorted(declared - used)
            raise ValueError(
                f"named query {query_path!r}: parameter mismatch — "
                f"in SQL but undeclared: {missing or 'none'}; "
                f"declared but absent from SQL: {unused or 'none'}. "
                "Note Ignition scans COMMENTS for parameters too, so a ':word' "
                "in a comment counts as a use."
            )

        root = self._project_named_query_root(project)
        segments = _split_view_path_segments(query_path)
        dest = root
        for seg in segments:
            dest = dest / seg
        if not dest.is_relative_to(self._projects_root):
            raise ValueError(
                f"layer guard: resolved path {dest} is outside projects/ root "
                f"{self._projects_root}; refusing to write"
            )
        dest.mkdir(parents=True, exist_ok=True)
        _atomic_write(dest / "query.sql", sql)
        _atomic_write(
            dest / "resource.json",
            dumps_designer(named_query_resource_json(config.attributes()), indent=2),
        )
        return dest

    def delete_session_props(self, project: str) -> Path:
        """Remove a project's ENTIRE session-props resource.

        Session-props inherit per RESOURCE, not per property: a child project
        that carries any session-props of its own overrides the parent's
        completely, so a prop declared only on the parent is invisible to the
        child. Deleting the child's resource is how it goes back to inheriting.
        """
        # NOT _project_session_props_dir: that helper auto-creates the
        # directory, so asking it for the path would conjure the very resource
        # this is meant to remove and then report success at deleting it.
        proj_dir = self._projects_root / _encode_segment(project)
        if not (proj_dir / "project.json").is_file():
            raise ProjectNotFoundError(
                f"Project {project!r} not found at {proj_dir}."
            )
        dest = proj_dir / "com.inductiveautomation.perspective" / "session-props"
        if not dest.exists():
            raise FileNotFoundError(
                f"Project {project!r} has no session-props resource at {dest}; "
                f"it already inherits its parent's."
            )
        shutil.rmtree(dest)
        return dest

    def delete_page_config(self, project: str) -> Path:
        """Remove a project's ENTIRE page-config resource.

        A child project that carries its own page-config OVERRIDES the parent's
        outright — inheritance is per-resource, not merged — so the only way to
        make a child fall back to the template's routes is to delete the child's
        resource. Deleting it is therefore a normal operation, not a repair.

        Returns the directory removed. Raises FileNotFoundError when the project
        has no page-config (nothing to inherit-ify), ProjectNotFoundError when
        the project itself is absent.
        """
        dest = self._project_page_config_dir(project)
        if not (dest / "config.json").is_file():
            raise FileNotFoundError(
                f"Project {project!r} has no page-config to delete "
                f"(it already inherits its parent's)."
            )
        if not dest.resolve().is_relative_to(self._projects_root.resolve()):
            raise ValueError(f"page-config path escapes projects/: {dest}")
        shutil.rmtree(dest)
        return dest

    def delete_view(self, project: str, view_path: str) -> None:
        """Remove the view directory (view.json + resource.json + dir) from disk.

        Uses the same path helpers as write_view so the project-exists guard
        is inherited automatically.

        Layer guard: the resolved directory must be under self._projects_root.
        Raises ViewNotFoundError if the view directory does not exist.
        Raises ValueError if the layer guard trips (path traversal / outside projects/).
        """
        views_root = self._project_views_root(project)  # raises ProjectNotFoundError if absent
        segments = _split_view_path_segments(view_path)  # raises ValueError on bad path
        resolved_dir = views_root.joinpath(*segments)

        # Layer guard: path traversal mitigation
        if not resolved_dir.is_relative_to(self._projects_root):
            raise ValueError(
                f"layer guard: resolved path {resolved_dir} is outside projects/ root "
                f"{self._projects_root}; refusing to delete"
            )

        if not resolved_dir.exists():
            raise ViewNotFoundError(
                f"View not found at {resolved_dir}; "
                f"check --project ({project!r}) and --view-path ({view_path!r}) are correct."
            )

        shutil.rmtree(resolved_dir)

        # Prune the folders the view leaves behind. Perspective shows any
        # directory under views/ as a folder in the resource tree, so deleting
        # Probe/AlarmLib without this leaves an empty "Probe" folder in the
        # Designer forever. Stops at the first non-empty parent and never
        # touches views_root itself.
        parent = resolved_dir.parent
        while parent != views_root and views_root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break  # not empty (or gone): every parent above it is in use
            parent = parent.parent

    def delete_script(self, project: str, script_path: str) -> None:
        """Remove a library script package dir (code.py + resource.json) from disk.

        Mirror of delete_view for projects/<name>/ignition/script-python/<path>/.
        Raises ProjectNotFoundError / ScriptNotFoundError / ValueError (layer
        guard) with the same contracts.
        """
        scripts_root = self._project_scripts_root(project)
        segments = _split_view_path_segments(script_path)
        resolved_dir = scripts_root.joinpath(*segments)

        if not resolved_dir.is_relative_to(self._projects_root):
            raise ValueError(
                f"layer guard: resolved path {resolved_dir} is outside projects/ root "
                f"{self._projects_root}; refusing to delete"
            )

        if not resolved_dir.exists():
            raise ScriptNotFoundError(
                f"Script not found at {resolved_dir}; "
                f"check --project ({project!r}) and --script-path ({script_path!r}) are correct."
            )

        shutil.rmtree(resolved_dir)

        # Prune empty parent packages, same as delete_view does for view folders.
        parent = resolved_dir.parent
        while parent != scripts_root and scripts_root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
