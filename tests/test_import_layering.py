"""
Layering guards for the MonitorHub packages.

``app/cli`` is the presentation/command layer; ``app/utils`` and ``app/monitor``
are the reusable backend it is built on, so imports only ever point *into*
``app/cli`` and never out of it. These tests pin that rule down.

The check is static (AST) and covers every module of the guarded package, which
is sufficient: a transitive ``app.utils`` -> ``app.cli`` edge can only exist if
some module inside the guarded package imports ``app.cli`` directly. Parsing
instead of importing also keeps the guard free of side effects (importing e.g.
``app.utils.logger_setup`` configures logging).
"""

import ast
import importlib
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Package directory (relative to the repository root) -> forbidden import
# prefixes. Directories are scanned recursively.
FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    "app/utils": ("app.cli", "app.webgui"),
    "app/monitor": ("app.cli", "app.webgui"),
    "app/webgui": ("app.cli",),
}


def package_name_for(source_path: Path) -> str:
    """Return the dotted package a source file belongs to."""
    relative = source_path.resolve().parent.relative_to(REPO_ROOT)
    return ".".join(relative.parts)


def imported_modules(source: str, package_name: str) -> set[str]:
    """
    Return every module name imported by source.

    ``package_name`` is the dotted package of the module the source belongs to;
    it is needed to resolve relative imports (``from ..cli import x`` in
    ``app/utils/example.py`` becomes ``app.cli``).
    """
    base_parts = package_name.split(".") if package_name else []
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=f"{package_name}.py")):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            # Level 1 is the current package; every extra dot goes up one level.
            base = base_parts[: len(base_parts) - node.level + 1]
            if node.module:
                modules.add(".".join([*base, node.module]))
            else:
                modules.update(
                    ".".join([*base, alias.name]) for alias in node.names
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def guarded_sources(package: str) -> list[Path]:
    """Return every Python source file of a guarded package, sorted."""
    return sorted((REPO_ROOT / package).rglob("*.py"))


def violations_in(
    source: str, package_name: str, forbidden: tuple[str, ...]
) -> list[str]:
    """Return the imports of source that target a forbidden package."""
    return sorted(
        target
        for target in imported_modules(source, package_name)
        if any(
            target == prefix or target.startswith(f"{prefix}.")
            for prefix in forbidden
        )
    )


class TestImportScanner(unittest.TestCase):
    """The scanner must resolve every import form the codebase uses."""

    def test_import_statement(self):
        self.assertEqual(
            {"app.cli.x"}, imported_modules("import app.cli.x\n", "app.utils")
        )

    def test_from_absolute_import(self):
        self.assertEqual(
            {"app.cli.prompt_service"},
            imported_modules(
                "from app.cli.prompt_service import PromptService\n", "app.utils"
            ),
        )

    def test_from_relative_import_with_module(self):
        self.assertEqual(
            {"app.cli"}, imported_modules("from ..cli import stuff\n", "app.utils")
        )

    def test_from_relative_import_without_module(self):
        self.assertEqual(
            {"app.utils.logger_setup"},
            imported_modules("from . import logger_setup\n", "app.utils"),
        )

    def test_dynamic_import_is_not_a_module_import(self):
        source = 'importlib.import_module("app.cli.prompt_service")\n'
        self.assertEqual(set(), imported_modules(source, "app.utils"))


class TestBackendPackagesDoNotImportCli(unittest.TestCase):
    """The backend layers must not depend on the presentation layer."""

    def test_guarded_packages_have_sources(self):
        for package in FORBIDDEN_IMPORTS:
            with self.subTest(package=package):
                self.assertTrue(
                    guarded_sources(package),
                    f"no Python sources found under {package}",
                )

    def test_no_forbidden_imports(self):
        for package, forbidden in FORBIDDEN_IMPORTS.items():
            for source_path in guarded_sources(package):
                source = source_path.read_text(encoding="utf-8")
                with self.subTest(
                    package=package, module=str(source_path.relative_to(REPO_ROOT))
                ):
                    self.assertEqual(
                        [],
                        violations_in(
                            source, package_name_for(source_path), forbidden
                        ),
                        f"{package} must not import {', '.join(forbidden)}",
                    )


class TestDiagnosticUtilLocation(unittest.TestCase):
    """DiagnosticUtil drives an interactive CLI report, so it lives in app.cli."""

    def test_module_is_gone_from_app_utils(self):
        self.assertFalse((REPO_ROOT / "app/utils/diagnostic_util.py").exists())
        self.assertIsNone(importlib.util.find_spec("app.utils.diagnostic_util"))

    def test_module_lives_in_app_cli(self):
        module = importlib.import_module("app.cli.diagnostic_util")
        self.assertEqual("app.cli.diagnostic_util", module.DiagnosticUtil.__module__)


if __name__ == "__main__":
    unittest.main()
