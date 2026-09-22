from __future__ import annotations

import unittest

from backend.evals.cases import CASES


class TestEvaluationCases(unittest.TestCase):
    def test_suite_has_twenty_unique_cases(self):
        ids = [case["id"] for case in CASES]
        self.assertEqual(20, len(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_case_is_multi_turn_and_labelled(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertGreaterEqual(len(case["turns"]), 3)
                self.assertTrue(case["final"])
                for text, expected in case["turns"]:
                    self.assertTrue(text.strip())
                    self.assertIsInstance(expected, dict)

