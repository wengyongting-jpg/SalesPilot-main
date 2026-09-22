# -*- coding: utf-8 -*-
"""Customer-facing reply composition.

Two peer implementations behind one protocol: `model_based` and `template`. The
template composer marks its output `generation="template"` so a reader is never
misled into thinking a model produced wording that a template did.
"""
