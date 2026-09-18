"""Tests for the two ign verbs added for the Alarm Analysis integration.

`ign named-query write` did not exist at all — named queries were the one
project resource with no sanctioned writer, and hand-writing under projects/**
is banned. `ign style-class write` was the missing half of a verb that could
already list and delete.

The load-bearing behaviour under test:
  - a named query's parameters must match the SQL exactly, and the check must
    see through single-quoted literals (a LIKE pattern containing ':' is not a
    parameter) while still catching ':name' inside a COMMENT, which Ignition
    really does bind;
  - sqlType lands in resource.json as the Ignition DataType ORDINAL, not the
    type name and not java.sql.Types;
  - --cache-seconds is what turns on gateway-side result sharing, so it has to
    reach the resource as cacheEnabled/cacheAmount/cacheUnit;
  - style-class write refuses a single payload handed to it without --name,
    which would otherwise silently create classes called "base" and "variants".
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _runner():
    from typer.testing import CliRunner

    return CliRunner()


def _make_project(root: Path, name: str = "Demo") -> Path:
    proj = root / "projects" / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


def _invoke(root: Path, args: list[str]):
    with patch.dict(
        os.environ,
        {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)},
        clear=False,
    ):
        from ignition_gen_sdk.cli import app

        return _runner().invoke(app, args)


_SQL = """SELECT COUNT(*) AS alarm_count
FROM alarm_events
WHERE eventtime >= :startDate AND eventtime < :endDate
  AND (:pathFilter = '' OR source LIKE CONCAT('%:/tag:', :pathFilter, '%'))
"""


def _write_sql(root: Path, text: str = _SQL) -> Path:
    p = root / "q.sql"
    p.write_text(text)
    return p


class TestNamedQueryWrite(unittest.TestCase):
    def test_writes_sql_and_resource_with_ordinal_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            sql = _write_sql(root)
            res = _invoke(
                root,
                [
                    "named-query", "write",
                    "--project", "Demo",
                    "--query-path", "Alarm/MySQL/RateTimeline",
                    "--file", str(sql),
                    "--database", "Alarms",
                    "--param", "startDate:DateTime",
                    "--param", "endDate:DateTime",
                    "--param", "pathFilter:String",
                    "--cache-seconds", "30",
                    "--no-scan",
                ],
            )
            self.assertEqual(res.exit_code, 0, msg=res.output)
            dest = (
                root / "projects/Demo/ignition/named-query"
                / "Alarm/MySQL/RateTimeline"
            )
            self.assertEqual(dest.joinpath("query.sql").read_text(), _SQL)
            meta = json.loads(dest.joinpath("resource.json").read_text())
            self.assertEqual(meta["scope"], "DG")
            self.assertEqual(meta["version"], 2)
            self.assertEqual(meta["files"], ["query.sql"])
            attrs = meta["attributes"]
            self.assertEqual(attrs["database"], "Alarms")
            # DateTime = 8, String = 7 (Ignition DataType ordinals).
            self.assertEqual(
                [(p["identifier"], p["sqlType"]) for p in attrs["parameters"]],
                [("startDate", 8), ("endDate", 8), ("pathFilter", 7)],
            )
            self.assertTrue(attrs["cacheEnabled"])
            self.assertEqual(attrs["cacheAmount"], 30)
            self.assertEqual(attrs["cacheUnit"], "SEC")

    def test_cache_seconds_zero_leaves_caching_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            sql = _write_sql(root, "SELECT 1 AS one\n")
            res = _invoke(
                root,
                ["named-query", "write", "--project", "Demo",
                 "--query-path", "Alarm/MySQL/Ping", "--file", str(sql),
                 "--database", "Alarms", "--no-scan"],
            )
            self.assertEqual(res.exit_code, 0, msg=res.output)
            attrs = json.loads(
                (root / "projects/Demo/ignition/named-query/Alarm/MySQL/Ping"
                 / "resource.json").read_text()
            )["attributes"]
            self.assertFalse(attrs["cacheEnabled"])

    def test_undeclared_parameter_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            sql = _write_sql(root)
            res = _invoke(
                root,
                ["named-query", "write", "--project", "Demo",
                 "--query-path", "Alarm/MySQL/Bad", "--file", str(sql),
                 "--database", "Alarms", "--param", "startDate:DateTime",
                 "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1)
            self.assertFalse(
                (root / "projects/Demo/ignition/named-query").exists(),
                "nothing may be written when the parameter check fails",
            )

    def test_parameter_in_a_comment_counts_as_used(self):
        # Ignition scans comments, so ':limit' in one is a real bind parameter.
        # If the checker stripped comments this would pass and the query would
        # then fail at runtime with a missing-parameter error.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            sql = _write_sql(root, "-- page it with :limit rows\nSELECT 1 AS one\n")
            res = _invoke(
                root,
                ["named-query", "write", "--project", "Demo",
                 "--query-path", "Alarm/MySQL/Cmt", "--file", str(sql),
                 "--database", "Alarms", "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1)
            self.assertIn("limit", res.output)

    def test_colon_inside_a_string_literal_is_not_a_parameter(self):
        from ignition_gen_sdk.backends.project_disk import sql_bind_parameters

        self.assertEqual(
            sql_bind_parameters(
                "WHERE source LIKE CONCAT('%:/tag:', :pathFilter, '%')"
            ),
            {"pathFilter"},
        )

    def test_apostrophe_in_a_comment_does_not_swallow_later_parameters(self):
        # A literal scan that runs across comments treats the apostrophe in
        # "chart's" as an opening quote and eats the rest of the file, so every
        # real parameter after it reads as undeclared.
        from ignition_gen_sdk.backends.project_disk import sql_bind_parameters

        sql = (
            "-- fixed at 3600s; it does not follow the chart's bucket width\n"
            "SELECT COALESCE(NULLIF(displaypath, ''), source) AS n\n"
            "FROM alarm_events WHERE eventtime >= :startDate\n"
        )
        self.assertEqual(sql_bind_parameters(sql), {"startDate"})

    def test_postgres_cast_operator_is_not_a_parameter(self):
        from ignition_gen_sdk.backends.project_disk import sql_bind_parameters

        self.assertEqual(
            sql_bind_parameters("SELECT :bucket::int AS b"), {"bucket"}
        )

    def test_unknown_datatype_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            sql = _write_sql(root, "SELECT :x AS x\n")
            res = _invoke(
                root,
                ["named-query", "write", "--project", "Demo",
                 "--query-path", "Alarm/MySQL/Bad2", "--file", str(sql),
                 "--database", "Alarms", "--param", "x:Varchar", "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1)

    def test_list_reports_database_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            sql = _write_sql(root)
            _invoke(
                root,
                ["named-query", "write", "--project", "Demo",
                 "--query-path", "Alarm/MySQL/RateTimeline", "--file", str(sql),
                 "--database", "Alarms", "--param", "startDate:DateTime",
                 "--param", "endDate:DateTime", "--param", "pathFilter:String",
                 "--cache-seconds", "30", "--no-scan"],
            )
            res = _invoke(root, ["named-query", "list", "--project", "Demo"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            self.assertIn("Alarm/MySQL/RateTimeline", res.output)
            self.assertIn("Alarms", res.output)
            self.assertIn("30sec", res.output)

    def test_delete_removes_the_query_and_leaves_siblings(self):
        # Retiring the caller of a named query leaves the query itself behind:
        # nothing imports it, so a dead one keeps looking live in the Designer.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            sql = _write_sql(root)
            for name in ("JournalPage", "RateTimeline"):
                _invoke(
                    root,
                    ["named-query", "write", "--project", "Demo",
                     "--query-path", f"Alarm/MySQL/{name}", "--file", str(sql),
                     "--database", "Alarms", "--param", "startDate:DateTime",
                     "--param", "endDate:DateTime", "--param", "pathFilter:String",
                     "--no-scan"],
                )
            nq = root / "projects" / "Demo" / "ignition" / "named-query"

            dry = _invoke(
                root,
                ["named-query", "delete", "--project", "Demo",
                 "--query-path", "Alarm/MySQL/JournalPage", "--dry-run"],
            )
            self.assertEqual(dry.exit_code, 0, msg=dry.output)
            self.assertTrue((nq / "Alarm" / "MySQL" / "JournalPage").is_dir())

            res = _invoke(
                root,
                ["named-query", "delete", "--project", "Demo",
                 "--query-path", "Alarm/MySQL/JournalPage", "--no-scan"],
            )
            self.assertEqual(res.exit_code, 0, msg=res.output)
            self.assertFalse((nq / "Alarm" / "MySQL" / "JournalPage").exists())
            self.assertTrue((nq / "Alarm" / "MySQL" / "RateTimeline").is_dir())

    def test_delete_of_a_missing_query_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            res = _invoke(
                root,
                ["named-query", "delete", "--project", "Demo",
                 "--query-path", "Alarm/MySQL/Nope", "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1)

    def test_delete_refuses_to_escape_the_named_query_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            res = _invoke(
                root,
                ["named-query", "delete", "--project", "Demo",
                 "--query-path", "../../../etc", "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1)



class TestViewDeletePrunesFolders(unittest.TestCase):
    def _backend(self, root: Path):
        with patch.dict(
            os.environ,
            {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)},
            clear=False,
        ):
            from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
            from ignition_gen_sdk.config import Settings

            return ProjectDiskBackend(Settings())  # type: ignore[call-arg]

    def test_empty_parents_are_removed_but_siblings_survive(self):
        # Perspective renders every directory under views/ as a folder, so a
        # delete that leaves the parent behind leaves a permanent empty folder
        # in the Designer's resource tree.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            backend = self._backend(root)
            views = (
                root / "projects/Demo/com.inductiveautomation.perspective"
                / "views"
            )
            for path in ("Probe/Deep/Leaf", "Probe/Deep/Sibling", "Keep/One"):
                (views / path).mkdir(parents=True)
                (views / path / "view.json").write_text("{}")

            backend.delete_view("Demo", "Probe/Deep/Leaf")
            self.assertTrue((views / "Probe/Deep/Sibling").is_dir(),
                            "a sibling view must keep its parent alive")

            backend.delete_view("Demo", "Probe/Deep/Sibling")
            self.assertFalse((views / "Probe").exists(),
                             "the now-empty branch should be pruned")
            self.assertTrue((views / "Keep/One").is_dir())
            self.assertTrue(views.is_dir(), "views root itself is never removed")


class TestStyleClassWrite(unittest.TestCase):
    def _payload(self, root: Path, data: dict) -> Path:
        p = root / "s.json"
        p.write_text(json.dumps(data))
        return p

    def test_single_named_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            f = self._payload(root, {"base": {"color": "var(--info)"}})
            res = _invoke(
                root,
                ["style-class", "write", "--project", "Demo",
                 "--name", "alarm-kpi-value", "--file", str(f), "--no-scan"],
            )
            self.assertEqual(res.exit_code, 0, msg=res.output)
            dest = (
                root / "projects/Demo/com.inductiveautomation.perspective"
                / "style-classes/alarm-kpi-value"
            )
            self.assertEqual(
                json.loads(dest.joinpath("style.json").read_text()),
                {"base": {"color": "var(--info)"}},
            )
            self.assertEqual(
                json.loads(dest.joinpath("resource.json").read_text())["files"],
                ["style.json"],
            )

    def test_bulk_map_writes_every_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            f = self._payload(
                root,
                {
                    "alarm-chip-critical": {"base": {"color": "var(--priority-critical)"}},
                    "alarm-chip-high": {"base": {"color": "var(--priority-high)"}},
                },
            )
            res = _invoke(
                root,
                ["style-class", "write", "--project", "Demo",
                 "--file", str(f), "--no-scan"],
            )
            self.assertEqual(res.exit_code, 0, msg=res.output)
            base = (
                root / "projects/Demo/com.inductiveautomation.perspective"
                / "style-classes"
            )
            self.assertTrue((base / "alarm-chip-critical/style.json").is_file())
            self.assertTrue((base / "alarm-chip-high/style.json").is_file())

    def test_single_payload_without_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            f = self._payload(root, {"base": {"color": "red"}})
            res = _invoke(
                root,
                ["style-class", "write", "--project", "Demo",
                 "--file", str(f), "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1)
            self.assertIn("--name", res.output)

    def test_unknown_top_level_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            f = self._payload(root, {"base": {}, "hover": {}})
            res = _invoke(
                root,
                ["style-class", "write", "--project", "Demo",
                 "--name", "x", "--file", str(f), "--no-scan"],
            )
            self.assertEqual(res.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
