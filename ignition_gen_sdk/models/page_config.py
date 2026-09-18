"""PageConfig — Perspective page-config model (mounts views at URLs).

A Perspective project's navigable pages live in a single per-project resource
``projects/<P>/com.inductiveautomation.perspective/page-config/config.json``:

    {"pages": {"/": {"title": "Overview", "viewPath": "Pages/Overview"},
               "/pid": {"title": "P&ID", "viewPath": "Pages/PID"}},
     "sharedDocks": {"cornerPriority": "top-bottom"}}

Without a page-config the client renders "No view configured for this page" —
i.e. the app has no entry URL. This model is the sanctioned (ign-only) way to
write that config; never hand-write it (the disk-write ban).

Shape verified against an on-disk Designer-written page-config.
"""
from __future__ import annotations

from pydantic import ConfigDict, Field

from .base import IgnitionBaseModel


class PageEntry(IgnitionBaseModel):
    """One mounted page: a URL maps to a project view path."""

    # extra="allow": tolerate richer existing entries (per-page docks, etc.)
    # when round-tripping an existing page-config; the credential guard stays.
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    viewPath: str
    title: str | None = None


class PageConfig(IgnitionBaseModel):
    """A project's full Perspective page-config: url -> page entry + shared docks."""

    pages: dict[str, PageEntry] = Field(default_factory=dict)
    sharedDocks: dict = Field(default_factory=lambda: {"cornerPriority": "top-bottom"})

    def with_page(self, url: str, view_path: str, title: str | None = None,
                  docks: dict | None = None) -> "PageConfig":
        """Return a copy with ``url`` mounted to ``view_path`` (add or replace).

        Other pages are preserved — the basis for incremental mounting. Any
        OTHER keys already on this page entry (docks, per-page settings) are
        preserved too: re-mounting a URL must not silently drop its docked
        chrome. Pass ``docks`` to set/replace them ({} clears).
        """
        pages = dict(self.pages)
        extra = {}
        existing = pages.get(url)
        if existing is not None:
            extra = {k: v for k, v in existing.model_dump(exclude_none=True).items()
                     if k not in ("viewPath", "title")}
        if docks is not None:
            extra["docks"] = docks
        pages[url] = PageEntry(viewPath=view_path, title=title, **extra)
        return PageConfig(pages=pages, sharedDocks=dict(self.sharedDocks))

    def without_page(self, url: str) -> "PageConfig":
        """Return a copy with ``url`` removed. KeyError if not mounted."""
        pages = dict(self.pages)
        del pages[url]
        return PageConfig(pages=pages, sharedDocks=dict(self.sharedDocks))

    def with_shared_docks(self, docks: dict) -> "PageConfig":
        """Return a copy whose SHARED docks carry ``docks`` (one key per side).

        Shared docks are the chrome every page in the project gets — the app
        header, and now the phone footer. Only the sides named in ``docks`` are
        replaced; the other sides and ``cornerPriority`` survive, so setting a
        bottom dock can never silently drop the top one. Pages are untouched.
        """
        shared = dict(self.sharedDocks)
        shared.update(docks)
        return PageConfig(pages=dict(self.pages), sharedDocks=shared)

    def without_shared_dock(self, side: str) -> "PageConfig":
        """Return a copy with the shared dock on ``side`` removed (no-op if absent)."""
        shared = {k: v for k, v in self.sharedDocks.items() if k != side}
        return PageConfig(pages=dict(self.pages), sharedDocks=shared)

    def config_json(self) -> dict:
        """The config.json payload (drops None title via emit)."""
        return {
            "pages": {url: entry.emit() for url, entry in self.pages.items()},
            "sharedDocks": self.sharedDocks,
        }
