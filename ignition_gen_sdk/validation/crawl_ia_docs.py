"""Re-runnable crawler for the Inductive Automation 8.3 appendix references.

Extracts the authoritative set of Ignition 8.3 **system.* scripting functions**
and **expression functions** straight from the official docs and regenerates
ignition_gen_sdk/validation/_ia_8_3_builtins.py (the data the whitelists use).

Why: the whitelists were originally sourced from the 8.1 appendix and had
gaps/version drift. This pulls 8.3 ground truth and is re-runnable to
re-document when IA updates the docs.

robots.txt at docs.inductiveautomation.com is `allow: /` — crawling these
public reference pages is permitted. Pages are server-rendered
(SSG), so plain httpx suffices (no browser needed). Functions are discovered
from the per-function subpage links the index/category pages contain.

Run:  ign builtins refresh
Writes: ignition_gen_sdk/validation/_ia_8_3_builtins.py  (+ prints a summary)
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import httpx

_BASE = "https://docs.inductiveautomation.com/docs/8.3/appendix"
_SYS_INDEX = _BASE + "/scripting-functions"
_EXPR_INDEX = _BASE + "/expression-functions"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; ign-docs-extractor/1.0)"}
DEFAULT_OUT = Path(__file__).resolve().parent / "_ia_8_3_builtins.py"


def _get(client: httpx.Client, url: str) -> str:
    r = client.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text


def crawl_system(client: httpx.Client) -> set[str]:
    """system.<pkg>.<fn> from the scripting-functions index subpage links."""
    html = _get(client, _SYS_INDEX)
    out: set[str] = set()
    for pkg, leaf in re.findall(
        r"/docs/8\.3/appendix/scripting-functions/(system-[a-z0-9]+)/(system-[a-z0-9]+-[A-Za-z0-9_]+)",
        html,
    ):
        m = re.match(r"system-([a-z0-9]+)-(.+)", leaf)
        if m:
            out.add("system.%s.%s" % (m.group(1), m.group(2)))
    return out


def crawl_expression(client: httpx.Client) -> set[str]:
    """Expression function names from each category page's per-function links."""
    idx = _get(client, _EXPR_INDEX)
    categories = sorted(set(re.findall(r"/docs/8\.3/appendix/expression-functions/([a-z0-9-]+)\"", idx)))
    out: set[str] = set()
    for cat in categories:
        time.sleep(0.3)  # be polite
        html = _get(client, _EXPR_INDEX + "/" + cat)
        names = re.findall(
            r"/docs/8\.3/appendix/expression-functions/" + re.escape(cat) + r"/([A-Za-z0-9_]+)",
            html,
        )
        out.update(names)
    return out


def _emit_module(system_fns: set[str], expr_fns: set[str]) -> str:
    subpkgs = sorted({f.split(".")[1] for f in system_fns})
    L = ['"""GENERATED — do not edit by hand. Re-run `ign builtins refresh`.',
         "",
         "Authoritative Ignition 8.3 system.* scripting functions + expression",
         "functions, crawled from the official appendix:",
         "  %s" % _SYS_INDEX,
         "  %s" % _EXPR_INDEX,
         '"""',
         "from __future__ import annotations",
         "",
         "SYSTEM_SUBPACKAGES_8_3: frozenset[str] = frozenset({"]
    L += ["    %r," % s for s in subpkgs]
    L += ["})", "", "SYSTEM_FUNCTIONS_8_3: frozenset[str] = frozenset({"]
    L += ["    %r," % s for s in sorted(system_fns)]
    L += ["})", "", "EXPRESSION_FUNCTIONS_8_3: frozenset[str] = frozenset({"]
    L += ["    %r," % e for e in sorted(expr_fns)]
    L += ["})", ""]
    return "\n".join(L)


def main(out: Path = DEFAULT_OUT) -> int:
    with httpx.Client(headers=_UA) as client:
        system_fns = crawl_system(client)
        expr_fns = crawl_expression(client)
    if len(system_fns) < 300 or len(expr_fns) < 100:
        print("REFUSING to write — suspiciously few results "
              "(system=%d expr=%d); docs layout may have changed." % (len(system_fns), len(expr_fns)),
              file=sys.stderr)
        return 1
    out.write_text(_emit_module(system_fns, expr_fns), encoding="utf-8")
    print("system functions: %d (%d subpackages)" % (
        len(system_fns), len({f.split('.')[1] for f in system_fns})))
    print("expression functions: %d" % len(expr_fns))
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
