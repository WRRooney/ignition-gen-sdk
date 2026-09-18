"""Perspective RUNTIME validation (Playwright + system Chrome).

Drives a real headless browser against the gateway's Perspective client so a
view can be checked for RUNTIME render — the gap that made "open it in Designer"
a human-only gate. Captures: HTTP reachability, browser console/page
errors, Perspective component-error-boundary crashes (real bugs) vs
ia_qualityOverlay--error overlays (bad bound-data quality = a data signal),
login-wall detection, and a screenshot.

This module is the package home for the harness that began as
``scripts/perspective_validate.py`` (now a thin wrapper). It powers
``ign view validate``.

Playwright is an OPTIONAL dependency (``pip install -e '.[runtime]'`` +
``playwright install chrome``); the import is lazy so the rest of ign stays
usable without it. A missing dependency raises :class:`RuntimeValidationError`
with the install hint, never an opaque ImportError.
"""
from __future__ import annotations

DEFAULT_BASE = "http://localhost:8088"


def default_base() -> str:
    """Gateway base URL from ``Settings().ignition_base_url`` (env/.env).

    Falls back to :data:`DEFAULT_BASE` when Settings cannot load (e.g. no API
    token configured) — the runtime harness is read-only and needs no token.
    """
    try:
        from ..config import Settings

        return Settings().ignition_base_url  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001 - any Settings failure means "use default"
        return DEFAULT_BASE

# Real Perspective error DOM (verified live):
#   .component-error-boundary  — a component CRASHED (React error boundary). A BUG.
#   .ia_qualityOverlay--error  — bound DATA has bad/error quality. A data signal,
#                                not necessarily a view defect.
# (The old guess-y selectors .component-error/.view-error never matched — they
# produced a false "0 overlays" while the screenshot showed errors.)
_CRASH_SELECTOR = ".component-error-boundary"
_QUALITY_ERROR_SELECTOR = ".ia_qualityOverlay--error"
# Perspective replaces an unresolvable view with its own placeholder card
# ("View Not Found" / "No view configured for this page") and still serves
# HTTP 200 with zero crashes — so a bad ROUTE used to validate as OK (T-nav
# blind spot: a 5-segment URL against a 2-segment mount printed "OK:").
_VIEW_STATE_SELECTOR = ".ia_viewStateDisplay__primaryMessage"
# An IA symbol (ia.symbol.valve seen, 8.3.8) that never received its SVG layers:
# a normally sized component whose <svg> is empty and still visibility:hidden.
# Happens when the symbol requests its layers while the session is settling
# (cold session ~80%, warm ~30%); not a view defect.
_SYMBOL_EMPTY_JS = (
    "() => [...document.querySelectorAll('[data-component^=\"ia.symbol.\"] svg')]"
    ".filter(s => s.querySelectorAll('path,rect,polygon,circle').length === 0).length"
)
_VIEW_STATE_FAILURES = ("not found", "no view configured")

# Matched against the page's VISIBLE TEXT, never against page.content(): the
# Perspective client bundle ships the strings "username" and "password" inside
# its own JavaScript, so scanning the raw HTML reported a login wall on every
# healthy page and failed the whole validation with it.
_LOGIN_MARKERS = ("sign in", "log in to")
_EULA_LABELS = ("AGREE & CLOSE", "Agree & Close", "AGREE")


class RuntimeValidationError(Exception):
    """Raised when the runtime harness cannot run (e.g. Playwright not installed)."""


def client_url(
    base: str | None = None,
    *,
    project: str | None = None,
    page: str | None = None,
    client_path: str | None = None,
    url: str | None = None,
) -> str:
    """Resolve a Perspective client URL from one of three target forms (pure).

    Precedence: ``url`` (absolute) > ``client_path`` (path under base) >
    ``project`` (+ optional ``page``) → ``/data/perspective/client/<project>[/<page>]``.

    Raises :class:`ValueError` if no target is given (so the CLI can surface a
    clean message instead of rendering the gateway's default landing page).
    ``base`` defaults to :func:`default_base` (Settings/env) when omitted.
    """
    base = (base or default_base()).rstrip("/")
    if url:
        return url
    if client_path:
        return base + ("" if client_path.startswith("/") else "/") + client_path
    if project:
        path = f"/data/perspective/client/{project}"
        if page:
            path += "/" + page.lstrip("/")
        return base + path
    raise ValueError(
        "no validation target — pass one of --url, --client-path, or --project (+ optional --page)."
    )


def _is_view_state_failure(message: str) -> bool:
    """True when a Perspective view-state placeholder means the view did NOT render (pure)."""
    text = (message or "").strip().lower()
    return any(marker in text for marker in _VIEW_STATE_FAILURES)


def verdict(result: dict) -> tuple[bool, list[str]]:
    """Classify a :func:`validate` result into (ok, reasons) (pure).

    A view FAILS validation (ok=False) on a real defect: a component crash
    (error boundary), a view-state placeholder, or an HTTP error. Bad data QUALITY
    overlays are reported as a non-fatal WARNING (a data signal, not a view
    defect — they may reflect a tag's live quality, not the view). An HTTP
    status >= 400 also fails. A NEGATIVE crash count (the harness set -1 because
    the crash-boundary selector threw) is treated as a FAILURE, not a pass — an
    inconclusive crash check must never read as "clean" (the silent false
    negative this guard exists to prevent).
    """
    reasons: list[str] = []
    status = result.get("http_status")
    if status is not None and status >= 400:
        reasons.append(f"http_status={status}")
    # PRESENT-and-None means the probe threw; ABSENT means a caller built the
    # result dict without that key at all, which is not evidence of anything.
    states = result.get("view_state_messages", [])
    if "view_state_messages" in result and states is None:
        reasons.append(
            "view-state probe errored (inconclusive — could not read the "
            "view-state placeholder; treat as not-validated)"
        )
        states = []
    msgs = [m for m in states if _is_view_state_failure(m)]
    if msgs:
        reasons.append(
            "Perspective rendered a view-state placeholder instead of the view "
            f"({'; '.join(sorted(set(msgs)))}) — the route or view path did not resolve"
        )
    crashes = result.get("component_crashes", 0)
    if isinstance(crashes, int) and crashes < 0:
        reasons.append(
            "crash detector errored (inconclusive — could not count "
            "component-error boundaries; treat as not-validated)"
        )
    elif isinstance(crashes, int) and crashes > 0:
        comps = result.get("crashed_components") or []
        detail = f" ({', '.join(c for c in comps if c)})" if any(comps) else ""
        reasons.append(f"{crashes} component crash(es){detail}")
    return (len(reasons) == 0, reasons)


def warnings(result: dict) -> list[str]:
    """Non-fatal signals worth surfacing (pure) — distinct from :func:`verdict` failures."""
    out: list[str] = []
    q = result.get("quality_error_overlays", 0)
    if isinstance(q, int) and q < 0:
        out.append("quality-overlay detector errored (could not count .ia_qualityOverlay--error)")
    elif isinstance(q, int) and q > 0:
        out.append(
            f"{q} data-quality error overlay(s) — bound tag(s) report bad quality "
            f"(a DATA signal, not necessarily a view defect)"
        )
    ce = result.get("console_errors") or []
    if ce:
        out.append(f"{len(ce)} browser console error(s)")
    se = result.get("symbol_svg_empty", 0)
    if isinstance(se, int) and se > 0:
        out.append(
            f"{se} IA symbol(s) rendered EMPTY (ia.symbol.* svg with no shapes) — the "
            f"8.3 symbol-library race on a settling session, not a view defect; the same "
            f"view renders on a warm session (memory reference-ia-symbol-valve-cold-session)"
        )
    if result.get("login_wall"):
        # A WARNING, never a failure. An anonymous Perspective session offers a
        # "Sign in" affordance of its own, and any page that edits credentials
        # has a password box on it, so the pair is not evidence of a wall. A
        # real one renders no view at all, which view_state_messages catches
        # unambiguously.
        out.append(
            "possible login wall (a password field and sign-in text are both "
            "present) — check the screenshot if the view looks empty"
        )
    return out


def validate(
    target_url: str,
    out_png: str = "/tmp/perspective.png",
    *,
    timeout_ms: int = 30000,
    hydrate_ms: int = 3000,
    connect_timeout_ms: int = 15000,
) -> dict:
    """Render ``target_url`` in headless Chrome and report runtime health.

    Returns a dict with: url, http_status, console_errors, page_errors,
    eula_dismissed, login_wall, component_crashes, quality_error_overlays,
    crashed_components, visible_text_sample, screenshot.

    Raises :class:`RuntimeValidationError` if Playwright is not installed.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # optional dep not installed
        raise RuntimeValidationError(
            "Playwright is required for runtime validation but is not installed. "
            "Install it with: pip install -e '.[runtime]' && playwright install chrome"
        ) from e

    result: dict = {"url": target_url, "console_errors": [], "page_errors": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on(
            "console",
            lambda m: result["console_errors"].append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: result["page_errors"].append(str(e)))
        resp = page.goto(target_url, wait_until="networkidle", timeout=timeout_ms)
        result["http_status"] = resp.status if resp else None
        page.wait_for_timeout(hydrate_ms)
        # Dismiss the Maker "Personal Use Only" EULA modal (overlays every Maker
        # client load and would otherwise occlude the view).
        result["eula_dismissed"] = False
        for label in _EULA_LABELS:
            try:
                btn = page.get_by_text(label, exact=False).first
                if btn.count() > 0:
                    btn.click(timeout=2000)
                    result["eula_dismissed"] = True
                    break
            except Exception:
                pass
        # Wait (briefly) for the Perspective session to report CONNECTED
        # ("Connected: <gateway>" appears once the WebSocket session establishes;
        # note a "No Connection to Gateway" string can co-exist as a default/
        # status element, so detect the POSITIVE "connected:" signal). NOTE
        # even a connected headless session does NOT fire view onStartup
        # — onStartup-driven view.custom.* (nav menu, KPI tiles) never populate
        # headlessly. So `connected` is informational; it does NOT imply
        # onStartup ran. Verify onStartup-driven views in a real browser.
        result["connected"] = False
        for _ in range(max(1, int(connect_timeout_ms / 500))):
            try:
                txt = page.inner_text("body").lower()
            except Exception:
                txt = ""
            if "connected:" in txt:
                result["connected"] = True
                break
            page.wait_for_timeout(500)
        # Let bindings settle.
        page.wait_for_timeout(hydrate_ms)
        try:
            visible = page.inner_text("body").lower()
        except Exception:
            visible = ""
        # A real login wall also puts a password box on the page; requiring
        # both keeps a view that merely says "Sign in to continue" in a label
        # from being read as one.
        try:
            password_box = page.locator("input[type=password]").count()
        except Exception:
            password_box = 0
        # Reported, never fatal. An anonymous Perspective session legitimately
        # offers a "Sign in" affordance, and any page that EDITS credentials
        # has a password box on it, so the two together are not evidence of a
        # wall. A real one shows up as an absent view or a view-state message,
        # which are checked separately and are unambiguous.
        result["login_wall"] = bool(password_box) and any(
            m in visible for m in _LOGIN_MARKERS)
        try:
            result["component_crashes"] = page.locator(_CRASH_SELECTOR).count()
        except Exception:
            result["component_crashes"] = -1
        try:
            result["quality_error_overlays"] = page.locator(_QUALITY_ERROR_SELECTOR).count()
        except Exception:
            result["quality_error_overlays"] = -1
        try:
            result["view_state_messages"] = [
                t.strip() for t in page.locator(_VIEW_STATE_SELECTOR).all_inner_texts() if t.strip()
            ]
        except Exception:
            # None, not [] — an empty list means "checked, nothing wrong",
            # which would print OK: for a page that may have rendered a "View
            # Not Found" placeholder. The crash and quality probes above use -1
            # for the same reason, and verdict() already fails on those.
            result["view_state_messages"] = None
        try:
            result["crashed_components"] = sorted(set(page.eval_on_selector_all(
                _CRASH_SELECTOR,
                "els => els.map(e => e.getAttribute('data-component'))",
            )))
        except Exception:
            result["crashed_components"] = []
        try:
            result["visible_text_sample"] = page.inner_text("body")[:400]
        except Exception:
            result["visible_text_sample"] = ""
        # IA symbol race (ia.symbol.valve, 8.3.8): a symbol that requested its
        # SVG layers while the session was still settling keeps an EMPTY,
        # visibility:hidden <svg> forever. Not a view defect -- the same view
        # renders on a warm session -- so it is reported by name, not folded
        # into the verdict. See memory reference-ia-symbol-valve-cold-session.
        try:
            result["symbol_svg_empty"] = page.evaluate(_SYMBOL_EMPTY_JS)
        except Exception:
            result["symbol_svg_empty"] = -1
        page.screenshot(path=out_png, full_page=True)
        result["screenshot"] = out_png
        browser.close()
    return result
