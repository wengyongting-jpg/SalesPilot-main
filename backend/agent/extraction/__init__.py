# -*- coding: utf-8 -*-
"""Extraction of intent, product, signals and concern from a customer message.

Two peer implementations behind one protocol: `model_based` and `rules`. They
are peers, not a primary and a patch. The original build kept the rule-based
classifiers as an exception handler and the two drifted until the prompt offered
the model enum values the domain did not accept -- a defect that silently
disabled three HITL triggers. A declared shared contract is the fix.
"""
