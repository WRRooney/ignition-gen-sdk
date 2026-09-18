"""Whitelists of built-in Ignition expression functions and system.* scripting
functions, with checkers that flag references to names that do not exist.

WHY: an expression that calls a non-existent function, or a script that calls
`system.tags.read` (wrong namespace) or `system.tag.readBlockng` (typo), passes
JSON/Pydantic/model validation but throws at runtime in the gateway. This is the
same "validates != runtime-correct" bug class as the Python-`==` issue.

PROVENANCE (sourced 2026-06-17 from the IA 8.1 appendix — expression-functions
and scripting-functions sections):
  Augmented with the real `system.*` calls harvested from the on-disk gateway
  projects (Designer-authored and IA sample projects) — those are gateway-accepted,
  so they are authoritative for 8.3 even where the 8.1 appendix list is partial.

EXTENDING: these are whitelists — if a real Ignition function is missing, the
checker reports it as "unknown" and the fix is to add the name here (one line),
NOT to weaken the guard. Names are 8.1-appendix-stable; 8.3 is a superset.

LEAF-ENFORCEMENT SCOPE: every `system.<subpkg>` prefix is validated (catches
wrong-namespace bugs in ALL namespaces). The full leaf name (`system.x.y`) is
strictly enforced only for the namespaces in LEAF_ENFORCED_SUBPACKAGES — the
ones for which the appendix crawl returned a COMPLETE function list. For other namespaces
the known leaves below are advisory (subpackage still enforced); completing
their leaf lists (perspective/dataset/net/file/date/...) is a documented
follow-up so leaf-strictness can widen without false-positives.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Expression-language functions (expression bindings / expression tags).
# Sourced from the IA 8.1 expression-functions appendix + the stable
# long-standing core. Grouped by the appendix's own categories.
# ---------------------------------------------------------------------------
EXPRESSION_FUNCTIONS: frozenset[str] = frozenset(
    {
        # --- String (appendix-confirmed) ---
        "char", "concat", "escapeSQL", "escapeXML", "fromBinary", "fromHex",
        "fromOctal", "indexOf", "lastIndexOf", "left", "len", "length", "lower",
        "numberFormat", "ordinal", "repeat", "replace", "right", "split",
        "startsWith", "endsWith", "contains", "stringFormat", "substring",
        "substringAfter", "substringAfterLast", "substringBefore",
        "substringBeforeLast", "toBinary", "toHex", "toOctal", "trim", "upper",
        "urlEncode",
        # --- Type casting (appendix-confirmed + stable) ---
        "toBoolean", "toBorder", "toColor", "toDataSet", "toDate", "toDouble",
        "toFloat", "toFont", "toInt", "toInteger", "toLong", "toStr", "toString",
        # --- JSON ---
        "jsonFormat", "jsonGet",
        # --- Logic / general (stable core) ---
        "if", "switch", "case", "coalesce", "isNull", "isGood", "isBad",
        "isUncertain", "isError", "isAvailable", "lookup", "try", "binEnum",
        "binEnc", "getBit", "hasChanged", "runScript", "tag", "now", "typeOf",
        # --- Color (type-casting / color appendix) ---
        "color", "gradient",
        # --- Math (stable core) ---
        "abs", "acos", "asin", "atan", "ceil", "cos", "exp", "floor", "log",
        "log10", "max", "min", "pow", "round", "sin", "sqrt", "tan",
        "toDegrees", "toRadians", "sign", "hypot", "e", "pi",
        # --- Aggregate (stable core) ---
        "mean", "median", "mode", "sum", "count", "stdDev", "groupConcat",
        # --- Date (stable core) ---
        "dateArithmetic", "dateDiff", "dateExtract", "dateFormat",
        "addSeconds", "addMinutes", "addHours", "addDays", "addWeeks",
        "addMonths", "addYears", "getHour24", "getHour12", "getMinute",
        "getSecond", "getDayOfMonth", "getDayOfWeek", "getDayOfYear",
        "getMonth", "getQuarter", "getYear", "midnight", "timeBetween",
        "fromMillis", "toMillis", "secondsBetween", "minutesBetween", "hoursBetween",
        "daysBetween", "weeksBetween", "monthsBetween", "yearsBetween",
        "isDaylightSavingsTime",
        # --- Aggregate over datasets / misc (stable) ---
        "join", "isAuthorized", "forceQuality",
    }
)

# ---------------------------------------------------------------------------
# system.* scripting library.
# ---------------------------------------------------------------------------
SYSTEM_SUBPACKAGES: frozenset[str] = frozenset(
    {
        "alarm", "bacnet", "cirruslink", "dataset", "date", "db", "device",
        "dnp3", "eam", "file", "groups", "gui", "historian", "nav", "net",
        "opc", "opchda", "opcua", "perspective", "print", "project", "report",
        "security", "serial", "tag", "twilio", "user", "util",
    }
)

# Namespaces with a COMPLETE leaf list — leaf names strictly enforced.
# perspective (full appendix list ∪ on-disk) is the heaviest
# namespace, so leaf-typo coverage there is high-value.
LEAF_ENFORCED_SUBPACKAGES: frozenset[str] = frozenset(
    {"db", "util", "tag", "security", "perspective"}
)

# Full `system.<subpkg>.<leaf>` names. Complete for LEAF_ENFORCED_SUBPACKAGES;
# best-effort (partial appendix coverage + on-disk real usage) for the rest.
SYSTEM_FUNCTIONS: frozenset[str] = frozenset(
    {
        # --- system.db (appendix complete) ---
        "system.db.addDatasource", "system.db.beginNamedQueryTransaction",
        "system.db.beginTransaction", "system.db.clearAllNamedQueryCaches",
        "system.db.clearNamedQueryCache", "system.db.closeTransaction",
        "system.db.commitTransaction", "system.db.createSProcCall",
        "system.db.dateFormat", "system.db.execSProcCall",
        "system.db.getConnectionInfo", "system.db.getConnections",
        "system.db.removeDatasource", "system.db.rollbackTransaction",
        "system.db.runNamedQuery", "system.db.runPrepQuery",
        "system.db.runPrepUpdate", "system.db.runQuery",
        "system.db.runSFNamedQuery", "system.db.runSFPrepUpdate",
        "system.db.runSFUpdateQuery", "system.db.runScalarPrepQuery",
        "system.db.runScalarQuery", "system.db.runUpdateQuery",
        "system.db.setDatasourceConnectURL", "system.db.setDatasourceEnabled",
        "system.db.setDatasourceMaxConnections",
        # --- system.util (appendix complete) ---
        # audit: in _ia_8_3_builtins (crawled) and verified live via the
        # Events audit profile round-trip; was missing from this list.
        "system.util.audit",
        "system.util.getClientId", "system.util.getConnectionMode",
        "system.util.getConnectTimeout", "system.util.getEdition",
        "system.util.getGatewayAddress", "system.util.getGatewayStatus",
        "system.util.getGlobals", "system.util.getInactivitySeconds",
        "system.util.getLocale", "system.util.getLogger",
        "system.util.getModules", "system.util.getProjectName",
        "system.util.getProperty", "system.util.getReadTimeout",
        "system.util.getSessionInfo", "system.util.getSystemFlags",
        "system.util.getVersion", "system.util.invokeAsynchronous",
        "system.util.invokeLater", "system.util.jsonDecode",
        "system.util.jsonEncode", "system.util.modifyTranslation",
        "system.util.playSoundClip", "system.util.queryAuditLog",
        "system.util.retarget", "system.util.sendMessage",
        "system.util.sendRequest", "system.util.sendRequestAsync",
        "system.util.setConnectionMode", "system.util.setConnectTimeout",
        "system.util.setLocale", "system.util.setLoggingLevel",
        "system.util.setReadTimeout", "system.util.threadDump",
        "system.util.translate", "system.util.execute",
        # --- system.tag (appendix complete) ---
        "system.tag.browse", "system.tag.browseHistoricalTags",
        "system.tag.configure", "system.tag.copy",
        "system.tag.deleteAnnotations", "system.tag.deleteTags",
        "system.tag.exists", "system.tag.exportTags",
        "system.tag.getConfiguration", "system.tag.importTags",
        "system.tag.move", "system.tag.queryAnnotations",
        "system.tag.queryTagCalculations", "system.tag.queryTagDensity",
        "system.tag.queryTagHistory", "system.tag.readAsync",
        "system.tag.readBlocking", "system.tag.rename",
        "system.tag.requestGroupExecution", "system.tag.storeAnnotations",
        "system.tag.storeTagHistory", "system.tag.writeAsync",
        "system.tag.writeBlocking",
        # legacy aliases still accepted by 8.3 (on-disk usage). NOTE:
        # system.tag.browseTags is 7.x/Vision and was REMOVED in 8.x — it throws
        # at runtime (silently returns nothing to callers). Deliberately NOT
        # whitelisted; use system.tag.browse(path, filter).getResults().
        "system.tag.read", "system.tag.write", "system.tag.query",
        # --- system.security (appendix complete) ---
        "system.security.getRoles", "system.security.getUsername",
        "system.security.getUserRoles", "system.security.isScreenLocked",
        "system.security.lockScreen", "system.security.logout",
        "system.security.switchUser", "system.security.unlockScreen",
        "system.security.validateUser",
        # --- system.perspective (LEAF-ENFORCED; appendix complete list ∪ on-disk) ---
        # The appendix omitted set/getSessionProperty but the framework uses them and
        # the gateway accepts them — union both sources. For leaf-enforcement
        # over-inclusion is safe (under-catches a rare fake); under-inclusion
        # would false-block a valid call.
        "system.perspective.navigate", "system.perspective.navigateBack",
        "system.perspective.navigateForward", "system.perspective.sendMessage",
        "system.perspective.openPopup", "system.perspective.closePopup",
        "system.perspective.togglePopup", "system.perspective.openDock",
        "system.perspective.closeDock", "system.perspective.toggleDock",
        "system.perspective.alterDock", "system.perspective.closePage",
        "system.perspective.setTheme", "system.perspective.alterLogging",
        "system.perspective.authenticationChallenge",
        "system.perspective.getProjectInfo", "system.perspective.getSessionInfo",
        "system.perspective.isAuthorized", "system.perspective.login",
        "system.perspective.logout", "system.perspective.print",
        "system.perspective.refresh", "system.perspective.download",
        "system.perspective.vibrateDevice", "system.perspective.closeSession",
        "system.perspective.setSessionProperty",
        "system.perspective.getSessionProperty",
        # --- system.dataset (advisory) ---
        "system.dataset.addColumn", "system.dataset.deleteRows",
        "system.dataset.filterColumns", "system.dataset.toDataSet",
        "system.dataset.toPyDataSet", "system.dataset.fromCSV",
        "system.dataset.toCSV", "system.dataset.dataSetToHTML",
        "system.dataset.addRow", "system.dataset.deleteRow",
        "system.dataset.getColumnHeaders", "system.dataset.setValue",
        "system.dataset.updateRow", "system.dataset.sort",
        "system.dataset.clearDataset", "system.dataset.appendDataset",
        "system.dataset.formatDates", "system.dataset.insertColumn",
        "system.dataset.insertRow",
        # --- system.historian (advisory: 8.3 crawl `_ia_8_3_builtins` + on-disk) ---
        "system.historian.browse", "system.historian.deleteAnnotations",
        "system.historian.queryAggregatedPoints",
        "system.historian.queryAnnotations", "system.historian.queryMetadata",
        "system.historian.queryRawPoints", "system.historian.queryValues",
        "system.historian.storeAnnotations", "system.historian.storeDataPoints",
        "system.historian.storeMetadata",
        "system.historian.updateRegisteredNodePath",
        # --- system.date (advisory: on-disk + documented) ---
        "system.date.now", "system.date.format", "system.date.parse",
        "system.date.fromMillis", "system.date.toMillis", "system.date.midnight",
        "system.date.getTimezoneOffset", "system.date.getTimezone",
        "system.date.getTimezoneRawOffset", "system.date.isAfter",
        "system.date.isBefore", "system.date.isBetween",
        "system.date.isDaylightTime", "system.date.setTime", "system.date.getDate",
        "system.date.addMillis", "system.date.addSeconds",
        "system.date.addMinutes", "system.date.addHours", "system.date.addDays",
        "system.date.addWeeks", "system.date.addMonths", "system.date.addYears",
        "system.date.secondsBetween", "system.date.minutesBetween",
        "system.date.hoursBetween", "system.date.daysBetween",
        "system.date.weeksBetween", "system.date.monthsBetween",
        "system.date.yearsBetween", "system.date.millisBetween",
        "system.date.getSecond", "system.date.getMinute", "system.date.getHour24",
        "system.date.getHour12", "system.date.getDayOfMonth",
        "system.date.getDayOfWeek", "system.date.getDayOfYear",
        "system.date.getMonth", "system.date.getQuarter", "system.date.getYear",
        # --- system.net (advisory) ---
        "system.net.httpGet", "system.net.httpPost", "system.net.httpPut",
        "system.net.httpDelete", "system.net.httpClient", "system.net.sendEmail",
        "system.net.getHostName", "system.net.getIpAddress",
        "system.net.getExternalIpAddress",
        # --- system.file (advisory) ---
        "system.file.fileExists", "system.file.getTempFile",
        "system.file.readFileAsBytes", "system.file.readFileAsString",
        "system.file.writeFile", "system.file.openFile", "system.file.saveFile",
        "system.file.getFileSize",
        # --- system.project (advisory) ---
        "system.project.getProjectName", "system.project.requestScan",
        # --- system.cirruslink (advisory: sub-namespace 'engine') ---
        "system.cirruslink.engine",
    }
)

# A function-call token in an Ignition expression: an identifier immediately
# followed by '('. Excludes the property-reference braces and string literals
# (callers strip those first).
_EXPR_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
# A system.* call: system.<subpkg>.<leaf> (leaf is the first identifier after subpkg).
_SYSTEM_CALL = re.compile(r"\bsystem\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)")


# Ignition expression FUNCTION NAMES ARE CASE-INSENSITIVE (e.g. COALESCE, isnull,
# tostr are all valid — verified against IA-authored IndustryPack views). Compare
# case-folded. (NOTE: system.* scripting calls are Jython = case-SENSITIVE, so
# unknown_system_calls() does NOT case-fold.)
_EXPR_LOWER: frozenset[str] = frozenset(f.lower() for f in EXPRESSION_FUNCTIONS)


def unknown_expression_functions(expr: str) -> list[str]:
    """Return the sorted distinct function names called in *expr* that are not
    known Ignition expression functions (matched case-insensitively). Quoted
    literals and `{...}` references are stripped first so identifiers inside them
    are not mistaken for calls."""
    scrubbed = _QUOTED.sub("", expr)
    scrubbed = re.sub(r"\{[^}]*\}", "", scrubbed)  # drop property refs
    names = {m.group(1) for m in _EXPR_CALL.finditer(scrubbed)}
    return sorted(n for n in names if n.lower() not in _EXPR_LOWER)


def unknown_system_calls(code: str) -> list[str]:
    """Return the sorted distinct `system.*` references in *code* (a script body)
    that are invalid: an unknown subpackage (always), or — for the
    leaf-enforced namespaces — an unknown leaf. Quoted literals are stripped so
    `system.*` mentioned inside a string is ignored. Project library
    calls are not checked (only `system.*`)."""
    scrubbed = _QUOTED.sub("", code)
    # Strip #-comments (after removing string literals, a remaining # starts a
    # real comment) — a comment that merely MENTIONS system.x is not a call.
    scrubbed = re.sub(r"#[^\n]*", "", scrubbed)
    bad: set[str] = set()
    for m in _SYSTEM_CALL.finditer(scrubbed):
        subpkg, leaf = m.group(1), m.group(2)
        full = f"system.{subpkg}.{leaf}"
        if subpkg not in SYSTEM_SUBPACKAGES:
            bad.add(full)
        elif subpkg in LEAF_ENFORCED_SUBPACKAGES and full not in SYSTEM_FUNCTIONS:
            bad.add(full)
    return sorted(bad)
