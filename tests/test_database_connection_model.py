"""`ConnectionConfig` + `DatabaseConnection`.

Covers:
- Demo_DB SQLite happy-path round-trip; plain/null password accepted.
- JWE refusal password JWE-refusal (flat + nested shapes) + canonical
  JWE_KEYS_REQUIRED constant.
- BackupConfig refusal on envelope (populated / None / empty all refused).
- Extra-field rejection (extra="forbid" inherited from IgnitionBaseModel).

Fixtures loaded from `fixtures/database-connections/`:
- `Demo_DB.json` — byte-identical to on-disk SQLite happy-path config (24 keys).
- `Sensors_DB_jwe_password.json` — sanitized MySQL config with placeholder JWE values
  (no live ciphertext in the repo).
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

from pydantic import ValidationError


def _add_pkg_path() -> None:
    here = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(here))


_add_pkg_path()


_FIXTURE_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures"
    / "database-connections"
)


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text())


class TestConnectionConfigRoundTrip(unittest.TestCase):
    """ConnectionConfig accepts the canonical Demo_DB fixture and the
    emitted JSON is identical to the input. Plain-string and None passwords
    pass through unchanged."""

    def test_demo_db_round_trip(self) -> None:
        from ignition_gen_sdk.models.databases import ConnectionConfig

        demo_db = _load_fixture("Demo_DB.json")
        cc = ConnectionConfig(**demo_db)
        emitted = cc.model_dump(exclude_none=True, mode="json")
        self.assertEqual(emitted, demo_db)

    def test_database_connection_envelope_minimal(self) -> None:
        from ignition_gen_sdk.models.databases import (
            ConnectionConfig,
            DatabaseConnection,
        )

        demo_db = _load_fixture("Demo_DB.json")
        dc = DatabaseConnection(name="Demo_DB", config=ConnectionConfig(**demo_db))
        self.assertTrue(dc.enabled is True and dc.description is None)

    def test_plain_string_password_accepted(self) -> None:
        from ignition_gen_sdk.models.databases import ConnectionConfig

        cc = ConnectionConfig(
            driver="MySQL",
            translator="MYSQL",
            connectURL="jdbc:mysql://x:3306/y",
            password="plaintext_secret",
        )
        self.assertEqual(cc.password, "plaintext_secret")

    def test_null_password_accepted(self) -> None:
        from ignition_gen_sdk.models.databases import ConnectionConfig

        cc = ConnectionConfig(
            driver="MySQL",
            translator="MYSQL",
            connectURL="jdbc:mysql://x:3306/y",
            password=None,
        )
        self.assertIsNone(cc.password)


class TestFND05Refusal(unittest.TestCase):
    """Any password whose shape matches AES-256-GCM JWE — either the
    flat 5-key dict or the realistic nested `{type, data:{...JWE...}}`
    envelope — is refused with a Gateway-UI Hint."""

    def test_fnd05_jwe_refusal_nested(self) -> None:
        from ignition_gen_sdk.models.databases import ConnectionConfig

        sensors_db = _load_fixture("Sensors_DB_jwe_password.json")
        with self.assertRaises(ValidationError) as cm:
            ConnectionConfig(**sensors_db)
        msg = str(cm.exception)
        self.assertIn("JWE credential", msg)
        self.assertIn("/web/config/databases.connections", msg)

    def test_fnd05_jwe_refusal_flat(self) -> None:
        from ignition_gen_sdk.models.databases import ConnectionConfig

        with self.assertRaises(ValidationError) as cm:
            ConnectionConfig(
                driver="MySQL",
                translator="MYSQL",
                connectURL="jdbc:mysql://x:3306/y",
                password={
                    "ciphertext": "x",
                    "encrypted_key": "y",
                    "iv": "z",
                    "protected": "a",
                    "tag": "b",
                },
            )
        msg = str(cm.exception)
        self.assertIn("JWE credential", msg)

    def test_jwe_keys_required_constant(self) -> None:
        from ignition_gen_sdk.models.databases import JWE_KEYS_REQUIRED

        self.assertEqual(
            JWE_KEYS_REQUIRED,
            frozenset({"ciphertext", "encrypted_key", "iv", "protected", "tag"}),
        )


class TestD04BackupConfigRefusal(unittest.TestCase):
    """DatabaseConnection envelope refuses any payload containing a
    `backupConfig` key, regardless of value (populated / None / empty)."""

    def _minimal_config(self) -> dict:
        return {
            "driver": "SQLite",
            "translator": "SQLITE",
            "connectURL": "jdbc:sqlite:test.db",
        }

    def test_d04_backup_config_refused_when_populated(self) -> None:
        from ignition_gen_sdk.models.databases import DatabaseConnection

        with self.assertRaises(ValidationError) as cm:
            DatabaseConnection(
                name="x",
                config=self._minimal_config(),
                backupConfig={
                    "driver": "SQLite",
                    "translator": "SQLITE",
                    "connectURL": "jdbc:sqlite:bak.db",
                },
            )
        msg = str(cm.exception)
        self.assertIn("backupConfig", msg)
        self.assertIn("not supported by the SDK", msg)
        self.assertIn("/web/config/databases.connections", msg)

    def test_d04_backup_config_refused_when_empty(self) -> None:
        from ignition_gen_sdk.models.databases import DatabaseConnection

        # Empty dict, None — both must still trigger the refusal.
        for empty_value in ({}, None):
            with self.assertRaises(ValidationError) as cm:
                DatabaseConnection(
                    name="x",
                    config=self._minimal_config(),
                    backupConfig=empty_value,
                )
            self.assertIn("backupConfig", str(cm.exception))

    def test_extra_field_rejected(self) -> None:
        from ignition_gen_sdk.models.databases import ConnectionConfig

        with self.assertRaises(ValidationError):
            ConnectionConfig(
                driver="SQLite",
                translator="SQLITE",
                connectURL="jdbc:sqlite:test.db",
                somethingNew="x",
            )


if __name__ == "__main__":
    unittest.main()
