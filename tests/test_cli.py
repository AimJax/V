import sys
import unittest

from pathlib import Path
from unittest.mock import patch

from support import temporary_directory

from v.cli import _memory_store, main


class CliTests(unittest.TestCase):
    def test_memory_export_dispatches_destination_and_overwrite(self):
        with patch.object(
            sys,
            "argv",
            ["v", "memory", "export", "G:/V/backups/memories.json", "--overwrite"],
        ), patch("v.cli._run_memory_export", return_value=0) as export:
            result = main()

        self.assertEqual(result, 0)
        export.assert_called_once_with(
            "G:/V/backups/memories.json",
            overwrite=True,
        )

    def test_memory_import_dispatches_source(self):
        with patch.object(
            sys,
            "argv",
            ["v", "memory", "import", "G:/V/backups/memories.json"],
        ), patch("v.cli._run_memory_import", return_value=0) as restore:
            result = main()

        self.assertEqual(result, 0)
        restore.assert_called_once_with("G:/V/backups/memories.json")

    def test_memory_database_path_cannot_escape_project_root(self):
        with temporary_directory() as temp:
            root = Path(temp).resolve()
            with patch(
                "v.cli.load_settings",
                return_value={"paths": {"memory_db": "../outside.sqlite3"}},
            ), patch("v.cli.project_root", return_value=root):
                with self.assertRaisesRegex(ValueError, "inside V_HOME"):
                    _memory_store()


if __name__ == "__main__":
    unittest.main()
