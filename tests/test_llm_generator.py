# -*- coding: utf-8 -*-
"""LLM response generator: grounding fallback when no LLM is available."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from salespilot.agent import SalesPilotAgent
from salespilot.providers import StubLLMClient
from salespilot.response import LLMResponseGenerator, ResponseGenerator


class _BrokenLLM(StubLLMClient):
    pass  # generate() raises UnavailableLLMError, simulating offline/no key


class TestLLMResponseGenerator(unittest.TestCase):
    def test_falls_back_to_template_when_llm_unavailable(self):
        generator = LLMResponseGenerator(
            llm_client=_BrokenLLM(), fallback=ResponseGenerator()
        )
        agent = SalesPilotAgent(response_generator=generator)
        result = agent.handle_message("C-L", "Lee", "What does Essential cover?")
        # Grounded template answer still served, workflow uninterrupted
        self.assertIn("B1", result.reply)

    def test_escalation_remains_deterministic(self):
        generator = LLMResponseGenerator(llm_client=_BrokenLLM())
        agent = SalesPilotAgent(response_generator=generator)
        result = agent.handle_message(
            "C-U", "Uma", "I have diabetes, will it be covered? Underwriting?"
        )
        self.assertIsNotNone(result.case)
        self.assertIn("human specialist", result.reply.lower())


if __name__ == "__main__":
    unittest.main()
