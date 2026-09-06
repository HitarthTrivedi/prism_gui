"""Which way the app's dependencies are allowed to point.

Two inversions existed before this file, and both were invisible because
every offending import was written INSIDE A FUNCTION. A deferred import is a
circular dependency you have agreed not to look at: it runs, so nothing
complains, and the layering violation only shows up when you try to move
one of the two modules -- which is exactly what the add-ons migration does.

  1. dashboard_data.py -- a root DATA module, the one that feeds the Home
     screen -- imported dialogs/inquiry_setup_dialog.py to ask whether a
     mailbox was configured. Home therefore depended on a 1,100-line Qt
     dialog, and Email automation could not be extracted into an add-on
     without dragging Home along with it.

  2. widgets/inquiry_panel.py imported dialogs/inquiry_dialog.py AT MODULE
     SCOPE for two constants -- a 4,313-line dialog pulled in at import time
     for a list of tab labels.

Both now read inquiry_config.py, which is plain functions over a dict with
no Qt in it at all.

The rule for widgets is deliberately not "never import a dialog". A panel
opening a modal is normal and there are four of those in the tree
(artifacts -> preview, settings -> licence, settings -> legal, support ->
contact). Those are navigational, they happen on a click, and they are
written as deferred imports for that reason. What is banned is depending on
a dialog to LOAD.
"""
from __future__ import annotations

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Root modules that hold data or logic and must stay free of the UI layer.
# They are what the add-on split has to be able to leave behind.
DATA_MODULES = ("dashboard_data.py", "inquiry_config.py")

# What those may not touch, at any scope.
UI_PACKAGES = ("dialogs", "widgets")


def _parse(path: str) -> ast.Module:
    with open(path, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _module_of(node: ast.AST) -> str:
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    if isinstance(node, ast.Import):
        return node.names[0].name
    return ""


class TheDataLayerDoesNotKnowAboutTheUI(unittest.TestCase):

    def test_no_data_module_imports_a_dialog_or_a_widget(self):
        offenders = []
        for name in DATA_MODULES:
            path = os.path.join(ROOT, name)
            if not os.path.isfile(path):
                self.fail("%s is missing; the layering this file pins was "
                          "built on it" % name)
            for node in ast.walk(_parse(path)):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                top = _module_of(node).split(".")[0]
                if top in UI_PACKAGES:
                    offenders.append("%s:%d imports %s"
                                     % (name, node.lineno, _module_of(node)))
        self.assertEqual(
            offenders, [],
            "\n  ".join(["A data module reached into the UI layer:"]
                        + offenders)
            + "\n\nPut the shared thing in a module with no Qt in it "
              "(inquiry_config.py is the worked example) and have BOTH sides "
              "read that. Writing the import inside a function hides the "
              "cycle; it does not remove it, and the add-on split cannot "
              "move a screen whose data module imports its dialog.")


class AWidgetMayOpenADialogButNotDependOnOne(unittest.TestCase):

    def test_no_widget_imports_a_dialog_at_module_scope(self):
        """Module scope is the distinction that matters. A deferred import
        inside a method is "when the user clicks this, show that window". A
        module-level one is "this widget cannot be loaded without that
        dialog", which is a load-order dependency and a barrier to moving
        either file."""
        folder = os.path.join(ROOT, "widgets")
        offenders = []
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py"):
                continue
            tree = _parse(os.path.join(folder, name))
            # Only the direct children of the module body are module scope.
            for node in tree.body:
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                if _module_of(node).split(".")[0] == "dialogs":
                    offenders.append("widgets/%s:%d imports %s"
                                     % (name, node.lineno, _module_of(node)))
        self.assertEqual(
            offenders, [],
            "\n  ".join(["These widgets need a dialog just to be imported:"]
                        + offenders)
            + "\n\nIf it is copy or a constant, move it somewhere neither "
              "owns. If it is a window to open, import it inside the method "
              "that opens it, like the four panels that already do.")


if __name__ == "__main__":
    unittest.main()
