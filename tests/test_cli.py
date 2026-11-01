import sys
import unittest

from pathlib import Path
from unittest.mock import AsyncMock, patch

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

    def test_memory_evaluate_dispatches_local_benchmark(self):
        with patch.object(
            sys,
            "argv",
            ["v", "memory", "evaluate"],
        ), patch(
            "v.cli._run_memory_evaluation",
            new=AsyncMock(return_value=0),
        ) as evaluate:
            result = main()

        self.assertEqual(result, 0)
        evaluate.assert_awaited_once_with()

    def test_memory_backfill_dispatches_batch_and_new_run_options(self):
        with patch.object(
            sys,
            "argv",
            ["v", "memory", "backfill", "--batch-size", "7", "--new-run"],
        ), patch(
            "v.cli._run_memory_backfill",
            new=AsyncMock(return_value=0),
        ) as backfill:
            result = main()

        self.assertEqual(result, 0)
        backfill.assert_awaited_once_with(batch_size=7, new_run=True)

    def test_memory_backfill_status_does_not_contact_the_model(self):
        with patch.object(
            sys,
            "argv",
            ["v", "memory", "backfill", "--status"],
        ), patch("v.cli._print_backfill_status", return_value=0) as status:
            result = main()

        self.assertEqual(result, 0)
        status.assert_called_once_with()

    def test_memory_review_list_dispatches_status_and_limit(self):
        with patch.object(
            sys,
            "argv",
            ["v", "memory", "review", "list", "--status", "rejected", "--limit", "25"],
        ), patch("v.cli._run_memory_review_list", return_value=0) as listing:
            result = main()

        self.assertEqual(result, 0)
        listing.assert_called_once_with(status="rejected", limit=25)

    def test_memory_review_approve_dispatches_edits(self):
        with patch.object(
            sys,
            "argv",
            [
                "v", "memory", "review", "approve", "candidate-1",
                "--content", "Edited content",
                "--importance", "5",
            ],
        ), patch("v.cli._run_memory_review_approve", return_value=0) as approve:
            result = main()

        self.assertEqual(result, 0)
        approve.assert_called_once_with(
            "candidate-1",
            {"content": "Edited content", "importance": 5},
        )

    def test_memory_review_reject_dispatches_reason(self):
        with patch.object(
            sys,
            "argv",
            [
                "v", "memory", "review", "reject", "candidate-2",
                "--reason", "Temporary information",
            ],
        ), patch("v.cli._run_memory_review_reject", return_value=0) as reject:
            result = main()

        self.assertEqual(result, 0)
        reject.assert_called_once_with("candidate-2", "Temporary information")

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
