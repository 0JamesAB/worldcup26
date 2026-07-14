"""Public-API freeze guard.

Every tui module declares __all__; this suite pins the contract:
  - each __all__ name exists in its module (no stale exports),
  - __all__ entries are unique and never underscore-private,
  - every name tui/__init__.py re-exports from a submodule is part of
    that submodule's declared public API,
  - tui.__version__ matches the pyproject.toml version.
"""

import ast
import os
import re
import unittest

import tui
from tui import (app, canvas, commands, interact, layout, region, styles,
                 term, testing, theme, widgets)

MODULES = {
    "term": term, "canvas": canvas, "region": region, "layout": layout,
    "theme": theme, "styles": styles, "widgets": widgets,
    "interact": interact, "app": app, "commands": commands,
    "testing": testing,
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


class TestModuleAll(unittest.TestCase):
    def test_every_module_declares_all(self):
        for name, mod in MODULES.items():
            self.assertTrue(hasattr(mod, "__all__"),
                            "tui.%s has no __all__" % name)

    def test_all_names_exist(self):
        for name, mod in MODULES.items():
            for pub in mod.__all__:
                self.assertTrue(hasattr(mod, pub),
                                "tui.%s.__all__ lists missing name %r"
                                % (name, pub))

    def test_all_names_are_public_and_unique(self):
        for name, mod in MODULES.items():
            self.assertEqual(len(mod.__all__), len(set(mod.__all__)),
                             "tui.%s.__all__ has duplicates" % name)
            for pub in mod.__all__:
                self.assertFalse(pub.startswith("_"),
                                 "tui.%s.__all__ lists private name %r"
                                 % (name, pub))


class TestInitReexports(unittest.TestCase):
    def test_init_imports_are_in_source_all(self):
        """Every `from .mod import name` in tui/__init__.py must name a
        member of tui.mod.__all__ — the package facade cannot widen a
        module's public API."""
        tree = ast.parse(_read("tui", "__init__.py"))
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            mod = MODULES.get(node.module)
            if mod is None:
                continue
            for alias in node.names:
                self.assertIn(alias.name, mod.__all__,
                              "tui/__init__.py imports %r from tui.%s but it "
                              "is not in that module's __all__"
                              % (alias.name, node.module))
                checked += 1
        self.assertGreater(checked, 20)  # the import block really was seen


class TestVersion(unittest.TestCase):
    def test_version_matches_pyproject(self):
        m = re.search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"),
                      re.MULTILINE)
        self.assertIsNotNone(m, "no version in pyproject.toml")
        self.assertEqual(tui.__version__, m.group(1))

    def test_version_value(self):
        self.assertEqual(tui.__version__, "0.6.0.dev0")


if __name__ == "__main__":
    unittest.main()
