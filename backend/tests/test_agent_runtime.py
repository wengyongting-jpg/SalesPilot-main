# -*- coding: utf-8 -*-
"""P3: the framework seam — model construction is the only thing this owns."""
from __future__ import annotations

import unittest

from backend import config
from backend.agent import runtime


class TestBuildModelSelectsOfflineByDefault(unittest.TestCase):
    def test_offline_provider_returns_none(self):
        original = config.LLM_PROVIDER
        config.LLM_PROVIDER = "offline"
        try:
            self.assertIsNone(runtime.build_model())
        finally:
            config.LLM_PROVIDER = original

    def test_openai_provider_with_no_api_key_returns_none(self):
        original_provider, original_key = config.LLM_PROVIDER, config.LLM_API_KEY
        config.LLM_PROVIDER = "openai"
        config.LLM_API_KEY = None
        try:
            self.assertIsNone(runtime.build_model())
        finally:
            config.LLM_PROVIDER, config.LLM_API_KEY = original_provider, original_key

    def test_openai_provider_with_an_api_key_builds_a_model(self):
        original_provider, original_key = config.LLM_PROVIDER, config.LLM_API_KEY
        config.LLM_PROVIDER = "openai"
        config.LLM_API_KEY = "test-key-not-a-real-secret"
        try:
            model = runtime.build_model()
            self.assertIsNotNone(model)
        finally:
            config.LLM_PROVIDER, config.LLM_API_KEY = original_provider, original_key
