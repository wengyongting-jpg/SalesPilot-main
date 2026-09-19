# -*- coding: utf-8 -*-
"""SQLite repository persistence tests."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from salespilot.agent import SalesPilotAgent
from salespilot.models import Priority
from salespilot.storage import SqliteRepository


class TestSqliteRepository(unittest.TestCase):
    def setUp(self):
        # ignore_cleanup_errors: Windows may briefly hold the SQLite file
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "salespilot_test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_opportunity_and_case_roundtrip(self):
        repo = SqliteRepository(self.db_path)
        agent = SalesPilotAgent(repository=repo)

        # Full Sarah conversation (private hospital -> price -> child ->
        # competitor -> purchase application)
        for text in (
            "Hi! I'm looking for health insurance with private hospital coverage.",
            "How much does CareSure Plus cost?",
            "Can I add my child to the plan?",
            "It's a bit expensive, and another insurer offered something cheaper.",
            "How do I apply? What documents do I need?",
        ):
            agent.handle_message("C-SQL", "Sarah", text)
        repo.close()

        # Reopen with a brand-new repository instance on the same file
        repo2 = SqliteRepository(self.db_path)
        opp = repo2.get_opportunity("C-SQL")
        self.assertIsNotNone(opp)
        self.assertEqual(opp.customer_name, "Sarah")
        self.assertEqual(opp.product.value, "plus")
        self.assertEqual(opp.turns, 5)
        self.assertTrue(opp.competitive_risk)
        self.assertIn("Family", opp.expansion)  # child -> family expansion track
        self.assertGreaterEqual(opp.score.total, 80)
        self.assertEqual(opp.score.priority, Priority.HIGH)
        self.assertEqual(len(opp.messages), 10)  # 5 customer + 5 agent
        self.assertEqual(len(opp.score_history), 5)
        self.assertGreaterEqual(len(repo2.list_cases()), 1)
        repo2.close()

    def test_list_and_delete(self):
        repo = SqliteRepository(self.db_path)
        agent = SalesPilotAgent(repository=repo)
        agent.handle_message("C-A", "Ann", "What does Essential cover?")
        self.assertEqual(len(repo.list_opportunities()), 1)
        repo.delete_opportunity("C-A")
        self.assertEqual(len(repo.list_opportunities()), 0)
        repo.close()

    def test_in_memory_database_supported(self):
        repo = SqliteRepository(":memory:")
        agent = SalesPilotAgent(repository=repo)
        result = agent.handle_message("C-M", "Mem", "Cheapest basic plan?")
        self.assertTrue(result.reply)
        self.assertEqual(len(repo.list_opportunities()), 1)
        repo.close()


if __name__ == "__main__":
    unittest.main()
