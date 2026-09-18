"""Token scrub helper tests.

scrub_token() masks any ``<name>:<secret>`` sequence where the secret is 20+
URL-safe chars, so host:port and hh:mm text never match.
"""
from __future__ import annotations

import random
import string
import unittest

from ignition_gen_sdk.cli._redact import scrub_token

_SECRET = "FAKEFAKEFAKEFAKEFAKEFAKEFAKE-not_real_X"  # 39 chars


class TestScrubToken(unittest.TestCase):
    def test_full_token_replaced(self) -> None:
        self.assertEqual(scrub_token(f"test:{_SECRET}"), "***REDACTED***")

    def test_token_embedded_in_multiline(self) -> None:
        out = scrub_token(f"status 200\nbody=agent:{_SECRET}\n")
        self.assertEqual(out, "status 200\nbody=***REDACTED***\n")

    def test_multiple_tokens_one_line(self) -> None:
        out = scrub_token(f"two: a:{_SECRET} and b.c:{_SECRET}")
        self.assertEqual(out, "two: ***REDACTED*** and ***REDACTED***")

    def test_no_token_pass_through(self) -> None:
        self.assertEqual(scrub_token("no token here"), "no token here")

    def test_host_port_and_time_untouched(self) -> None:
        for s in ("http://localhost:8088/data", "at 12:30:45", "key:short"):
            self.assertEqual(scrub_token(s), s)

    def test_minimum_length_boundary(self) -> None:
        self.assertEqual(scrub_token("test:" + "x" * 19), "test:" + "x" * 19)
        self.assertEqual(scrub_token("test:" + "x" * 20), "***REDACTED***")

    def test_bounds(self) -> None:
        self.assertEqual(scrub_token(f"prefix test:{_SECRET} suffix"), "prefix ***REDACTED*** suffix")
        self.assertEqual(scrub_token(f"tok=test:{_SECRET},other=x"), "tok=***REDACTED***,other=x")
        self.assertEqual(scrub_token(f"test:{_SECRET}:more"), "***REDACTED***:more")

    def test_property_100_random_non_tokens_unchanged(self) -> None:
        rng = random.Random(20260518)
        alphabet = string.ascii_letters + string.digits + " _-"
        for _ in range(100):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
            self.assertEqual(scrub_token(s), s)

    def test_empty_and_bare_prefix_unchanged(self) -> None:
        self.assertEqual(scrub_token(""), "")
        self.assertEqual(scrub_token("test:"), "test:")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
