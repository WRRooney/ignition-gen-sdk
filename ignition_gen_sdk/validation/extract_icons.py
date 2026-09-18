"""Extract the icon names `ia.display.icon` actually supports, from the gateway.

WHERE THEY WENT IN 8.3. Under 8.1 the sprites sat on disk at
`webserver/webapps/main/res/perspective/icons/*.svg` and you could just read
them. In 8.3 nothing under `webserver/` carries them: the Perspective module
ships its own jar, and the sprites live inside it.

    user-lib/modules/Perspective-module.modl      (a zip)
      └── perspective-icons-<version>.jar         (a zip)
            └── icons/material.svg                (<symbol id="..."> per glyph)
                     ignition.svg
                     symbol_{simple,p&id,mimic}.svg

The gateway serves them at /res/perspective/icons/ but that path is not in the
OpenAPI spec, so `ign api` will not fetch it; reading the module file (or
`docker cp` from the container) is the reliable route.

WHY THIS IS NOT OPTIONAL. A name that is not in the sprite renders as NOTHING
and logs `React.cloneElement(...): The argument must be a React element, but
you passed null` to the browser console. When this was written the Nav Builder
offered 968 names of which 55 did not exist, and omitted 404 that did.

Run:  ign icons list --container <docker-name> [--set material] [--json]
      ign icons list --modl /path/to/Perspective-module.modl
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import zipfile

MODULE_PATH = "/usr/local/bin/ignition/user-lib/modules/Perspective-module.modl"

# material.svg and ignition.svg are :target sprites -- one `<g class="icon"
# id="NAME">` per glyph, shown by a CSS rule, NOT the `<symbol>` sheet 8.1
# used. Matching <symbol> here silently yields zero icons, which reads as
# "this version ships none".
_ICON_ID = re.compile(r"<g[^>]*\bclass=\"icon\"[^>]*\bid=\"([^\"]+)\"")

# The symbol_* sheets are the artwork behind ia.symbol.* (pump bodies, valve
# halves) and are addressed by those components, not by ia.display.icon. They
# use nested <svg id="...">, so they are reported separately.
_SYMBOL_ID = re.compile(r"<svg[^>]*\bid=\"([^\"]+)\"")

# Sets an `ia.display.icon` path can name: "<set>/<glyph>".
ICON_SETS = ("material", "ignition")


def read_module(modl: str | None, container: str | None) -> bytes:
    """The .modl bytes, from a local path or out of the running container.

    `docker cp`, not `docker exec cat`: exec mangles a binary stream, and the
    damage is quiet -- both zips still open and every sprite reads back empty,
    which looks exactly like "this version ships no icons".
    """
    if modl:
        with open(modl, "rb") as fh:
            return fh.read()
    if not container:
        raise ValueError("pass --modl <file> or --container <docker container name>")
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, "perspective.modl")
        subprocess.check_call(
            ["docker", "cp", "%s:%s" % (container, MODULE_PATH), local],
            stdout=subprocess.DEVNULL)
        with open(local, "rb") as fh:
            return fh.read()


def icon_sets(module: bytes) -> dict[str, list[str]]:
    """{set name: sorted glyph names} for every sprite in the module."""
    outer = zipfile.ZipFile(io.BytesIO(module))
    jars = [n for n in outer.namelist() if "perspective-icons" in n]
    if not jars:
        raise SystemExit("no perspective-icons jar in the module: %s"
                         % outer.namelist())
    inner = zipfile.ZipFile(io.BytesIO(outer.read(jars[0])))
    sets = {}
    for entry in inner.namelist():
        if not entry.endswith(".svg"):
            continue
        svg = inner.read(entry).decode("utf-8", "replace")
        names = _ICON_ID.findall(svg) or _SYMBOL_ID.findall(svg)
        sets[entry.split("/")[-1][:-4]] = sorted(set(names))
    return sets


def as_jython_list(names: list[str], per_line: int = 4) -> str:
    """The names as a tab-indented Jython list literal, ready to paste."""
    lines = []
    for i in range(0, len(names), per_line):
        chunk = ", ".join('"%s"' % n for n in names[i:i + per_line])
        lines.append("\t%s," % chunk)
    return "\n".join(lines)

