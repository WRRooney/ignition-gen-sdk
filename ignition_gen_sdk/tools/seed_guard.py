"""Refuse to overwrite a view a human has edited.

Every build_*.py is a SEED: it produces the first version of a view family, and
the owner then refines those views in the Designer. The rule is
"Generators are SEEDS: never re-run over user-edited views", but nothing
enforced it. A generator run with no arguments rewrote its whole
view family from the seed, and the only recovery was `git checkout`, assuming
the edits had been committed.

The guard only protects views that still EXIST. A generator whose targets have
since been DELETED will happily recreate them, which is why a generator that no
longer matches anything live belongs in `git log`, not in `scripts/` (the two
Alarm generators went that way).

That is a footgun rather than a defect: no correct invocation triggers it. But
the cost of triggering it is someone's afternoon in the Designer, and the guard
is small, so the generators ask before they clobber.

A view counts as ALREADY THERE if its view.json exists. The generator does not
try to tell a seeded view from an edited one -- it cannot, and guessing wrong
in the permissive direction is exactly the failure being prevented. Pass
--force to overwrite, which is the flag you use when you genuinely mean
"re-seed this family".
"""
from __future__ import annotations

import sys
from pathlib import Path


def existing_views(backend, project: str, view_paths) -> list[str]:
    """Which of `view_paths` already have a view.json on disk.

    Args:
        backend: A ProjectDiskBackend.
        project (str): Project name.
        view_paths (iterable[str]): Slash-separated view paths.
    Returns:
        list[str]: The paths that already exist, in the order given.
    """
    root = Path(backend._project_views_root(project))
    return [p for p in view_paths if (root.joinpath(*p.split("/")) / "view.json").is_file()]


def guard(backend, project: str, view_paths, force: bool) -> None:
    """Exit non-zero if any target view already exists and --force was not given.

    Args:
        backend: A ProjectDiskBackend.
        project (str): Project name.
        view_paths (iterable[str]): Views this run would write.
        force (bool): The generator's --force flag.
    """
    if force:
        return
    clobber = existing_views(backend, project, view_paths)
    if not clobber:
        return
    print(
        "refusing to overwrite %d existing view(s) in %s:\n  %s\n\n"
        "These may carry Designer edits, which this seed does not preserve.\n"
        "Re-seed deliberately with --force, or narrow the run with "
        "--only <path>." % (len(clobber), project, "\n  ".join(clobber)),
        file=sys.stderr,
    )
    raise SystemExit(2)
