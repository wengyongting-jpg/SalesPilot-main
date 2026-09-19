# -*- coding: utf-8 -*-
"""FR-15 basic sales analytics tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from salespilot.agent import SalesPilotAgent
from salespilot.analytics import compute_analytics
from salespilot.seed import seed_demo_data


class TestAnalytics(unittest.TestCase):
    def setUp(self):
        self.agent = SalesPilotAgent()
        seed_demo_data(self.agent)

    def test_metrics_shape_and_values(self):
        metrics = compute_analytics(self.agent.repo)

        self.assertEqual(metrics["total_opportunities"], 3)
        self.assertEqual(metrics["by_priority"]["HIGH"], 2)
        self.assertGreaterEqual(metrics["human_cases_open"], 2)
        self.assertGreaterEqual(metrics["competitive_risks"], 1)
        self.assertGreaterEqual(metrics["escalated_opportunities"], 2)

        # Every funnel state key exists and counts add up to total
        self.assertEqual(
            sum(item["count"] for item in metrics["funnel"]),
            metrics["total_opportunities"],
        )
        # Signals detected during the demo script
        self.assertIn("Purchase", metrics["signals"])
        # JSON-serialisable
        import json

        json.dumps(metrics)


if __name__ == "__main__":
    unittest.main()
