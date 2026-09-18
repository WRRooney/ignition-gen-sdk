"""Tests for the alarm-pipeline codec and its CLI verb.

The codec exists to lift inline Jython out of alarm pipelines and into a
project library, because a pipeline is the one gateway resource with no write
API and no text form — logic left inside one is unversioned and Designer-only.

The load-bearing guarantee is NEGATIVE: replacing a pooled string must not
disturb the block graph. The node stream refers to strings by id rather than
offset, so that holds by construction, and the tests below assert it directly
rather than trusting the reasoning.
"""
from __future__ import annotations

import gzip
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Real pipelines from a gateway data dir (IGNITION_CORPUS_DIR + IGNITION_PIPELINE_PROJECT).
# Absent on a CI node, so the tests that use them skip rather than fail.
_LIVE_PIPELINES = (
    Path(os.environ.get("IGNITION_CORPUS_DIR") or "/nonexistent") / "projects"
    / os.environ.get("IGNITION_PIPELINE_PROJECT", "Demo")
    / "com.inductiveautomation.alarm-notification/alarm-pipelines"
)


def _synthetic(strings, body=b"\x11\x22\x33\x44", gzipped=True):
    """Build a minimal file with the real header/pool layout."""
    header = b"\xaa" * 16 + struct.pack(">I", 2) + struct.pack(">Q", 0) + b"\x00" * 20
    parts = [header, struct.pack(">I", len(strings))]
    for i, text in enumerate(strings):
        # bytes pass through so a test can build a pool that is not valid UTF-8
        encoded = text if isinstance(text, bytes) else text.encode("utf-8")
        parts.append(struct.pack(">I", i))
        parts.append(len(encoded).to_bytes(3, "big"))
        parts.append(encoded)
    parts.append(body)
    raw = b"".join(parts)
    return gzip.compress(raw, mtime=0) if gzipped else raw


class TestRoundTrip(unittest.TestCase):
    def test_synthetic_round_trips_byte_exact(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        raw = _synthetic(["alpha", "\treturn event.get('customRoster')", ""])
        parsed = AlarmPipeline.parse(raw)
        self.assertEqual(parsed.strings,
                         ["alpha", "\treturn event.get('customRoster')", ""])
        self.assertEqual(gzip.decompress(parsed.emit()), gzip.decompress(raw))

    def test_uncompressed_payload_is_handled(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        raw = _synthetic(["a", "b"], gzipped=False)
        parsed = AlarmPipeline.parse(raw)
        self.assertFalse(parsed.gzipped)
        self.assertEqual(parsed.emit(), raw)

    @unittest.skipUnless(_LIVE_PIPELINES.is_dir(), "gateway pipelines not present")
    def test_every_real_pipeline_round_trips_byte_exact(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        found = sorted(_LIVE_PIPELINES.glob("*/data.bin"))
        self.assertTrue(found, "no data.bin under the pipelines directory")
        for path in found:
            raw = path.read_bytes()
            with self.subTest(pipeline=path.parent.name):
                self.assertEqual(
                    gzip.decompress(AlarmPipeline.parse(raw).emit()),
                    gzip.decompress(raw))


class TestReplace(unittest.TestCase):
    def test_replace_leaves_the_block_graph_byte_identical(self):
        # The whole safety argument in one assertion.
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        raw = _synthetic(["keep", "\told script\n\tmore", "keep2"],
                         body=b"\xde\xad\xbe\xef" * 8)
        parsed = AlarmPipeline.parse(raw)
        before = parsed.body
        parsed.replace("\told script\n\tmore", "\tapp.notify.advance(event)")
        self.assertEqual(parsed.body, before)
        again = AlarmPipeline.parse(parsed.emit())
        self.assertEqual(again.body, before)
        self.assertEqual(again.ids, parsed.ids)
        self.assertEqual(again.strings,
                         ["keep", "\tapp.notify.advance(event)", "keep2"])

    def test_replace_matches_whole_entries_only(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        parsed = AlarmPipeline.parse(_synthetic(["email", "emailer"]))
        parsed.replace("email", "sms")
        self.assertEqual(parsed.strings, ["sms", "emailer"])

    def test_replace_hits_every_duplicate(self):
        # The three notification blocks share one roster script.
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        parsed = AlarmPipeline.parse(_synthetic(["\tx", "other", "\tx"]))
        self.assertEqual(parsed.replace("\tx", "\ty"), 2)
        self.assertEqual(parsed.strings, ["\ty", "other", "\ty"])

    def test_missing_text_raises(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        parsed = AlarmPipeline.parse(_synthetic(["a"]))
        with self.assertRaises(KeyError):
            parsed.replace("nope", "x")

    def test_scripts_finds_tab_indented_bodies(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        parsed = AlarmPipeline.parse(
            _synthetic(["notascript", "\tone\n\ttwo", "\tsingle", "  spaces"]))
        self.assertEqual([i for i, _ in parsed.scripts()], [1, 2])
        self.assertEqual([i for i, _ in parsed.scripts(minimum_lines=2)], [1])

    def test_oversize_string_is_rejected_not_truncated(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import (
            AlarmPipeline, AlarmPipelineFormatError)

        parsed = AlarmPipeline.parse(_synthetic(["a"]))
        parsed.strings[0] = "x" * ((1 << 24) + 1)
        with self.assertRaises(AlarmPipelineFormatError):
            parsed.emit()

    def test_garbage_is_rejected(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import (
            AlarmPipeline, AlarmPipelineFormatError)

        with self.assertRaises(AlarmPipelineFormatError):
            AlarmPipeline.parse(b"nope")


class TestCli(unittest.TestCase):
    def _project(self, root: Path, name="Demo"):
        proj = root / "projects" / name
        (proj / "com.inductiveautomation.perspective" / "views").mkdir(parents=True)
        (proj / "project.json").write_text('{"title":"%s"}' % name)
        pipe = (proj / "com.inductiveautomation.alarm-notification"
                / "alarm-pipelines" / "Notify")
        pipe.mkdir(parents=True)
        (pipe / "data.bin").write_bytes(
            _synthetic(["\told\n\tbody", "keep"], body=b"\x01\x02\x03\x04"))
        return pipe / "data.bin"

    def _invoke(self, root: Path, args):
        with patch.dict(os.environ,
                        {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)},
                        clear=False):
            from typer.testing import CliRunner

            from ignition_gen_sdk.cli import app

            return CliRunner().invoke(app, args)

    def test_replace_text_writes_and_preserves_the_graph(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self._project(root)
            before = AlarmPipeline.parse(data.read_bytes()).body
            old = root / "old.py"
            new = root / "new.py"
            old.write_text("\told\n\tbody\n")  # trailing newline must be tolerated
            new.write_text("\tapp.notify.advance(event)\n")
            res = self._invoke(root, [
                "alarm-pipeline", "replace-text", "--project", "Demo",
                "--name", "Notify", "--old-file", str(old), "--new-file", str(new),
                "--no-scan"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            after = AlarmPipeline.parse(data.read_bytes())
            self.assertEqual(after.strings,
                             ["\tapp.notify.advance(event)", "keep"])
            self.assertEqual(after.body, before)

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self._project(root)
            before = data.read_bytes()
            res = self._invoke(root, [
                "alarm-pipeline", "replace-text", "--project", "Demo",
                "--name", "Notify", "--old", "keep", "--new", "kept",
                "--dry-run"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            self.assertEqual(data.read_bytes(), before)

    def test_unmatched_text_exits_nonzero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self._project(root)
            before = data.read_bytes()
            res = self._invoke(root, [
                "alarm-pipeline", "replace-text", "--project", "Demo",
                "--name", "Notify", "--old", "absent", "--new", "x", "--no-scan"])
            self.assertEqual(res.exit_code, 1)
            self.assertEqual(data.read_bytes(), before)

    def test_list_and_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._project(root)
            res = self._invoke(root, ["alarm-pipeline", "list",
                                      "--project", "Demo"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            self.assertIn("Notify", res.output)
            res = self._invoke(root, ["alarm-pipeline", "show",
                                      "--project", "Demo", "--name", "Notify"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            self.assertIn("old", res.output)

    def test_missing_pipeline_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._project(root)
            res = self._invoke(root, ["alarm-pipeline", "show",
                                      "--project", "Demo", "--name", "Nope"])
            self.assertEqual(res.exit_code, 1)


if __name__ == "__main__":
    unittest.main()


class TestNonUtf8Pool(unittest.TestCase):
    def test_arbitrary_bytes_round_trip_exactly(self):
        # decode("utf-8", "replace") turned any non-UTF-8 byte into U+FFFD and
        # emit() wrote those three replacement bytes back -- a silent
        # corruption that GREW the file, and that re-parsing could not detect
        # because the lossy decode is idempotent. surrogateescape makes
        # byte-exactness a property of the codec instead of a lucky consequence
        # of every pipeline on this gateway happening to be ASCII.
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        raw = _synthetic([b"ok", b"caf\xe9", b"\xc0\x80"])
        parsed = AlarmPipeline.parse(raw)
        self.assertEqual(gzip.decompress(parsed.emit()), gzip.decompress(raw))

    def test_replace_still_works_alongside_non_utf8_entries(self):
        from ignition_gen_sdk.serializers.alarm_pipeline import AlarmPipeline

        raw = _synthetic([b"\xff\xfe", b"\told"])
        parsed = AlarmPipeline.parse(raw)
        parsed.replace("\told", "\tapp.notify.tick(event)")
        again = AlarmPipeline.parse(parsed.emit())
        self.assertEqual(again.strings[1], "\tapp.notify.tick(event)")
        # The neighbouring non-UTF-8 entry must be untouched, byte for byte.
        self.assertEqual(again.strings[0].encode("utf-8", "surrogateescape"),
                         b"\xff\xfe")


class TestReplaceTextRejectsEmpty(unittest.TestCase):
    def test_empty_old_is_refused(self):
        # Pool index 0 is the empty string in every pipeline on this gateway,
        # so an empty --old matched it and rewrote the file.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "projects" / "Demo"
            (proj / "com.inductiveautomation.perspective" / "views").mkdir(parents=True)
            (proj / "project.json").write_text('{"title":"Demo"}')
            pipe = (proj / "com.inductiveautomation.alarm-notification"
                    / "alarm-pipelines" / "Notify")
            pipe.mkdir(parents=True)
            data = pipe / "data.bin"
            data.write_bytes(_synthetic([b"", b"keep"]))
            before = data.read_bytes()
            with patch.dict(os.environ,
                            {"IGNITION_API_TOKEN": "test:dummy",
                             "IGNITION_DATA_DIR": str(root)}, clear=False):
                from typer.testing import CliRunner

                from ignition_gen_sdk.cli import app

                res = CliRunner().invoke(app, [
                    "alarm-pipeline", "replace-text", "--project", "Demo",
                    "--name", "Notify", "--old", "", "--new", "x", "--no-scan"])
            self.assertEqual(res.exit_code, 1)
            self.assertEqual(data.read_bytes(), before)
