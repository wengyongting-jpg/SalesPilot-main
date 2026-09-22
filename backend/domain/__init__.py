# -*- coding: utf-8 -*-
"""Pure data: enums and dataclasses flowing through the system.

THE single source of truth for every string that reaches the wire. Every schema
the model sees, and every serialiser the API uses, derives from this package.

Imports nothing outside the standard library, and nothing from the rest of
`backend`. That constraint is what lets every other layer depend on it.
"""
