"""The build has to be able to SEE the add-ons and the whole engine.

Two enumerations decide what reaches a frozen build, and both fail silently
when they are wrong: the app compiles, the build succeeds, and the customer
opens a windowed executable with no console and a feature that is not there.

Neither can be exercised by importing the spec -- prism.spec runs inside
PyInstaller with its own globals -- so these tests re-derive the same walks
against the same trees and check the answers, plus assert that both build
files still mention the packages at all.

Why each matters
────────────────
`_engine_modules()` used to be `os.listdir(core)` filtered on ".py", which
cannot see a SUBPACKAGE. core/motion/ is one, so core.motion.generate,
core.motion.render and core.motion.schema have never been in any frozen
build. That has cost nothing so far only because Motion Graphics is disabled
at source by core/motion/render.py's _DISABLED_PENDING_ASSET_FIX -- the day
somebody turns that off, the feature would be an ImportError in front of a
customer.

`_addon_modules()` is new, and it guards the worst failure available in the
add-on design. registry.py's imports are static precisely so the analyser
can follow them, but the manifests ALSO name panels and dialogs by dotted
string ("addons.gerber.panel:GerberPanel"), and a string is invisible to
every analyser there is.
"""
from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "prism_terminal")
SPEC = os.path.join(ROOT, "packaging", "prism.spec")
BUILD = os.path.join(ROOT, "packaging", "build.py")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _walk_engine() -> list[str]:
    """The same walk prism.spec._engine_modules() does."""
    core = os.path.join(ENGINE, "core")
    found = ["core"]
    for folder, dirs, files in os.walk(core):
        dirs[:] = [d for d in dirs
                   if d != "__pycache__" and not d.startswith(".")]
        rel = os.path.relpath(folder, core)
        package = "core" if rel == "." else "core." + rel.replace(os.sep, ".")
        if package != "core":
            found.append(package)
        for name in sorted(files):
            if name.endswith(".py") and name != "__init__.py":
                found.append(package + "." + name[:-3])
    return found


class TheEngineWalkReachesSubpackages(unittest.TestCase):

    def test_the_spec_walks_rather_than_lists(self):
        source = _read(SPEC)
        self.assertIn("os.walk", source,
                      "prism.spec no longer walks the engine tree; a flat "
                      "listdir cannot see core/motion/ and every module in "
                      "it silently stops being bundled")

    @unittest.skipUnless(os.path.isdir(os.path.join(ENGINE, "core", "motion")),
                         "the engine submodule is not checked out here")
    def test_the_motion_subpackage_is_reachable(self):
        found = _walk_engine()
        self.assertIn("core.motion", found)
        for name in ("core.motion.generate", "core.motion.render",
                     "core.motion.schema"):
            with self.subTest(module=name):
                self.assertIn(
                    name, found,
                    "%s is not enumerated, so it would not be bundled -- the "
                    "exact gap that made core/motion/ absent from every "
                    "frozen build" % name)

    @unittest.skipUnless(os.path.isdir(os.path.join(ENGINE, "core")),
                         "the engine submodule is not checked out here")
    def test_the_flat_scan_would_have_missed_them(self):
        """Proves the bug was real rather than theoretical: the OLD
        enumeration, run against today's engine, finds none of them."""
        core = os.path.join(ENGINE, "core")
        old = ["core"] + ["core." + n[:-3] for n in sorted(os.listdir(core))
                          if n.endswith(".py") and n != "__init__.py"]
        self.assertNotIn("core.motion.render", old)
        self.assertIn("core.motion.render", _walk_engine())

    def test_hidden_cache_directories_are_not_modules(self):
        found = _walk_engine()
        self.assertFalse(
            any(part.startswith(".") for name in found for part in name.split(".")),
            "a hidden cache directory was turned into a PyInstaller hidden import")
        source = _read(SPEC)
        self.assertIn(
            'not d.startswith(".")', source,
            "prism.spec must reject hidden metadata directories such as "
            "core/.pytest_cache")


class TheBuildKnowsAboutAddons(unittest.TestCase):

    def test_the_spec_enumerates_the_addons_package(self):
        source = _read(SPEC)
        self.assertIn("_addon_modules", source,
                      "packaging/prism.spec does not enumerate addons/, so a "
                      "frozen build can ship an empty add-on shelf")
        self.assertIn("_addon_modules()", source.split("hiddenimports =")[1][:200],
                      "_addon_modules is defined but not added to "
                      "hiddenimports")

    def test_the_nuitka_build_includes_the_addons_package(self):
        self.assertIn(
            "--include-package=addons", _read(BUILD),
            "packaging/build.py does not include addons/, so the Nuitka "
            "build can compile cleanly and open with an empty shelf")

    def test_every_registered_addon_has_a_module_in_the_walk(self):
        from addons import registry
        modules = registry.addon_modules()
        self.assertIn("addons.registry", modules)
        self.assertIn("addons.manifest", modules)
        for key in registry.keys():
            with self.subTest(addon=key):
                self.assertIn(
                    "addons.%s.addon" % key, modules,
                    "%r is registered but its manifest module is not in the "
                    "walk the build uses" % key)


if __name__ == "__main__":
    unittest.main()
