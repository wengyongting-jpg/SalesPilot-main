# -*- coding: utf-8 -*-
"""The HTTP surface, split by visibility tier.

`routes/customer.py` serves the customer chat; `routes/admin.py` serves the staff
console. The split is not a filter -- `schemas/customer.py` has no shape for a
score, a state, a signal or any telemetry, so that data cannot reach a customer
browser even by mistake.

See `docs/v0.0/api/interface-v1.md` section 2 for the tier table.
"""
