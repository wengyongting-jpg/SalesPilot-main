# -*- coding: utf-8 -*-
"""P0: the layering rules of docs/backend-plan.md §4, made executable.

Those rules are the whole point of the rebuild's directory design. Written as
prose they are advice; written here they are a build failure. The specific defect
this guards against is the one that motivated the rebuild: the model-facing layer
and the domain layer drifting apart because nothing prevented them from reaching
into each other.

The test reads source with `ast` rather than importing, so a layering violation is
reported even in a module that cannot currently be imported.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PACKAGE = "backend"

# Which backend packages each backend package may import. The direction is
# one-way: domain <- kernel <- services -> agent -> providers, and api -> services.
ALLOWED: dict[str, set[str]] = {
    # Pure data. The single source of truth for every wire string.
    "domain": set(),
    # Deterministic business core. Auditable, offline, framework-free.
    "kernel": {"domain"},
    # Knowledge base access.
    "knowledge": {"domain", "config"},
    # The only package allowed to call a model.
    "agent": {"domain", "knowledge", "providers", "observability", "config"},
    # Instrumentation. Never imported by domain or kernel.
    "observability": {"domain", "config"},
    # Model transports.
    "providers": {"observability", "config"},
    # Persistence.
    "storage": {"domain", "config"},
    # Use-cases. The only package that writes storage.
    "services": {
        "domain", "kernel", "knowledge", "agent",
        "storage", "observability", "config",
    },
    # HTTP surface. Wires services; never reaches into kernel or agent directly.
    "api": {"domain", "services", "storage", "observability", "config"},
}

# Packages that must stay importable with nothing but the standard library, so
# they remain unit-testable, offline and auditable.
STDLIB_ONLY = ("domain", "kernel")

# The agent framework is an implementation detail of one package.
FRAMEWORK_MODULES = {"pydantic_ai", "openai"}
FRAMEWORK_OWNER = "agent"


def _python_files() -> list[Path]:
    return [
        path
        for path in BACKEND.rglob("*.py")
        if "tests" not in path.relative_to(BACKEND).parts
        and "__pycache__" not in path.parts
    ]


def _package_of(path: Path) -> str | None:
    """Return the top-level backend package a file belongs to, or None for
    top-level modules such as config.py and cli.py."""
    parts = path.relative_to(BACKEND).parts
    return parts[0] if len(parts) > 1 else None


def _imported_roots(path: Path) -> set[tuple[str, int]]:
    """Every top-level module name this file imports, with its line number.

    `from backend.domain.enums import X` yields `backend.domain`; `import json`
    yields `json`. Relative imports are resolved against the file's own package
    so `from ..domain import X` is caught too.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    own_parts = (PACKAGE,) + path.relative_to(BACKEND).parts[:-1]
    found: set[tuple[str, int]] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative import: walk up `level` packages from this module.
                base = own_parts[: len(own_parts) - node.level + 1]
                if node.module:
                    found.add((".".join(base + (node.module,)), node.lineno))
                else:
                    # `from .. import config` — the imported *names* are the
                    # targets. Resolving only the module part would leave this
                    # form invisible to the check, which is exactly the blind
                    # spot that let `kernel` import `config` unnoticed.
                    for alias in node.names:
                        found.add((".".join(base + (alias.name,)), node.lineno))
            elif node.module:
                found.add((node.module, node.lineno))
    return found


def _backend_target(module: str) -> str | None:
    """`backend.domain.enums` -> `domain`; anything else -> None.

    Returns None for a name that is not a real module or package. `from .. import
    __version__` resolves to `backend.__version__`, which is an attribute of the
    package rather than a dependency on anything — and this rule is about module
    dependencies. Checking the filesystem is what keeps the previous fix to
    `_imported_roots` from turning every attribute import into a false violation.
    """
    parts = module.split(".")
    if parts[0] != PACKAGE or len(parts) < 2:
        return None
    name = parts[1]
    if (BACKEND / name).is_dir() or (BACKEND / f"{name}.py").exists():
        return name
    return None


class TestImportDirection(unittest.TestCase):
    """Rule 1 of §4: import direction is one-way."""

    def test_every_package_stays_inside_its_allowlist(self):
        violations = []
        for path in _python_files():
            package = _package_of(path)
            if package is None or package not in ALLOWED:
                continue
            for module, line in sorted(_imported_roots(path)):
                target = _backend_target(module)
                if target is None or target == package:
                    continue
                if target not in ALLOWED[package]:
                    violations.append(
                        f"{path.relative_to(BACKEND)}:{line} — "
                        f"{package!r} may not import {target!r} "
                        f"(allowed: {sorted(ALLOWED[package]) or 'nothing'})"
                    )
        self.assertEqual([], violations, "\n" + "\n".join(violations))

    def test_domain_and_kernel_need_only_the_standard_library(self):
        """Rule: these two packages stay offline, framework-free and auditable.

        If this fails, the deterministic core has acquired a dependency and can
        no longer be trusted to run in a demo with no network.
        """
        violations = []
        for path in _python_files():
            package = _package_of(path)
            if package not in STDLIB_ONLY:
                continue
            for module, line in sorted(_imported_roots(path)):
                root = module.split(".")[0]
                if root == PACKAGE or root in sys.stdlib_module_names:
                    continue
                violations.append(
                    f"{path.relative_to(BACKEND)}:{line} — {package!r} must be "
                    f"stdlib-only but imports third-party {root!r}"
                )
        self.assertEqual([], violations, "\n" + "\n".join(violations))

    def test_observability_is_never_imported_by_the_deterministic_core(self):
        """Rule 5 of §4: business rules stay free of instrumentation."""
        violations = []
        for path in _python_files():
            if _package_of(path) not in STDLIB_ONLY:
                continue
            for module, line in sorted(_imported_roots(path)):
                if _backend_target(module) == "observability":
                    violations.append(f"{path.relative_to(BACKEND)}:{line}")
        self.assertEqual(
            [], violations,
            "domain/ and kernel/ must not import observability/: "
            + ", ".join(violations),
        )

    def test_the_agent_framework_belongs_to_one_package(self):
        """Rule 2 of §4: only agent/ may call a model.

        Keeping the framework confined is also what makes the go/no-go decision
        in P3 cheap: if it has leaked, replacing it stops being a one-module job.
        """
        violations = []
        for path in _python_files():
            package = _package_of(path)
            for module, line in sorted(_imported_roots(path)):
                root = module.split(".")[0]
                if root in FRAMEWORK_MODULES and package != FRAMEWORK_OWNER:
                    where = package or path.name
                    violations.append(
                        f"{path.relative_to(BACKEND)}:{line} — {root!r} imported "
                        f"from {where!r}; only {FRAMEWORK_OWNER!r} may"
                    )
        self.assertEqual([], violations, "\n" + "\n".join(violations))


class TestSkeleton(unittest.TestCase):
    """P0: the package exists, imports, and documents its own rules."""

    def test_backend_imports(self):
        import backend

        self.assertTrue(hasattr(backend, "__version__"))

    def test_every_planned_package_exists(self):
        expected = set(ALLOWED) | {"tests"}
        actual = {
            child.name
            for child in BACKEND.iterdir()
            if child.is_dir() and not child.name.startswith("__")
        }
        self.assertEqual(
            set(), expected - actual,
            f"missing packages: {sorted(expected - actual)}",
        )

    def test_no_legacy_console_is_carried_over(self):
        """Rule 6 of §4: the rebuild serves no static UI."""
        self.assertFalse((BACKEND / "static").exists())

    def test_import_direction_rule_is_stated_in_the_package_docstring(self):
        import backend

        self.assertIsNotNone(backend.__doc__)
        doc = backend.__doc__.lower()
        for token in ("domain", "kernel", "services", "agent", "providers", "api"):
            self.assertIn(token, doc, f"{token!r} missing from the layering rule")


if __name__ == "__main__":
    unittest.main()
