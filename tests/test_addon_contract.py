"""The add-on boundaries, as tests rather than as a convention.

`docs/architecture/06-addons.md` has always described how an add-on is
wired -- rail entry, launcher, licence gate, dialog, worker, engine call
through core_bridge. It described it as a RECIPE, six steps to follow by
hand, and hand-wiring is why the same fact ended up written in seven tables
that disagree.

This file is the recipe made checkable. Each test pins one rule, and each
one is here because breaking it fails somewhere expensive: at release, in
CI, or in front of a customer in a windowed build with no console.

Note what is NOT tested yet. Nothing consumes the registry at this stage --
it exists, it is proven to reproduce the live tables exactly, and the
rewiring is a separate commit so that reverting one is not reverting both.
The tests that only make sense after the rewiring (no shell module imports
an add-on; no module keeps a private add-on table) arrive with it.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import plans                                            # noqa: E402
from addons import manifest, names, registry            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS_DIR = os.path.join(ROOT, "addons")

# The manifest layer, which packaging/prism.spec imports in a bare
# interpreter. Everything here must be importable with no Qt, no engine and
# no display.
STDLIB_ONLY = ["addons/__init__.py", "addons/manifest.py", "addons/names.py",
               "addons/registry.py"]

# Modules the manifest layer is allowed to import besides the standard
# library: itself.
OWN = {"addons"}


def _imports(path: str) -> list[tuple[str, int]]:
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            found.append((node.module or "", node.lineno))
    return found


def _addon_packages() -> list[str]:
    return sorted(
        name for name in os.listdir(ADDONS_DIR)
        if os.path.isdir(os.path.join(ADDONS_DIR, name))
        and name != "__pycache__")


class TheManifestLayerIsStdlibOnly(unittest.TestCase):
    """packaging/prism.spec imports addons.registry in a bare interpreter to
    compute hiddenimports, exactly as it already imports app_meta and
    licensing.keys. A Qt import here would need a display on the build box;
    an engine import would break the build the day the submodule moves."""

    def test_the_manifest_layer_imports_nothing_but_the_standard_library(self):
        stdlib = set(getattr(sys, "stdlib_module_names", ()))
        offenders = []
        for rel in STDLIB_ONLY + [
                "addons/%s/addon.py" % p for p in _addon_packages()]:
            path = os.path.join(ROOT, rel)
            if not os.path.isfile(path):
                continue
            for name, lineno in _imports(path):
                top = name.split(".")[0]
                if not top or top in stdlib or top in OWN:
                    continue
                offenders.append("%s:%d  %s" % (rel, lineno, name))
        self.assertEqual(
            offenders, [],
            "The manifest layer imported something outside the standard "
            "library:\n  " + "\n  ".join(offenders)
            + "\n\nprism.spec imports addons.registry in a bare interpreter. "
              "Qt would need a display on the build box; the engine would "
              "break the build when the submodule moves. Name the thing with "
              "a dotted string and let the registry resolve it lazily.")

    def test_a_bare_interpreter_can_import_the_registry(self):
        """The AST check above can be satisfied by a file that still fails to
        import. This is the same check CI already makes for `updater`."""
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.'); "
             "import addons.registry as R; print(len(R.REGISTRY))"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(
            proc.returncode, 0,
            "addons.registry does not import in a bare interpreter, so the "
            "frozen build cannot enumerate add-ons:\n" + proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(len(registry.REGISTRY)))


class NoAddOnKnowsAnotherAddOn(unittest.TestCase):
    """The whole product depends on this one. Four people can work in four
    folders only while those folders do not reach into each other."""

    def test_no_add_on_imports_another_add_on(self):
        offenders = []
        for pkg in _addon_packages():
            folder = os.path.join(ADDONS_DIR, pkg)
            for dirpath, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, name)
                    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                    for mod, lineno in _imports(path):
                        parts = mod.split(".")
                        if (len(parts) >= 2 and parts[0] == "addons"
                                and parts[1] not in ("manifest", "names",
                                                     "registry")
                                and parts[1] != pkg):
                            offenders.append("%s:%d  %s"
                                             % (rel, lineno, mod))
        self.assertEqual(
            offenders, [],
            "These add-ons import each other:\n  " + "\n  ".join(offenders)
            + "\n\nAsk for the work by intent instead -- declare it in "
              "addons/names.py, offer it from the add-on that does it, and "
              "route through the host. An import couples you to the other "
              "add-on's module path, class name, constructor AND to the "
              "customer being entitled to it.")

    def test_every_add_on_package_is_in_the_registry(self):
        """Unregistered code ships, is unreachable and is UNGATED, which is
        the worst of the three."""
        registered = set(registry.keys())
        on_disk = {p for p in _addon_packages()
                   if os.path.isfile(os.path.join(ADDONS_DIR, p, "addon.py"))}
        self.assertEqual(
            on_disk - registered, set(),
            "these add-ons exist on disk but are in no registry line, so "
            "they ship without appearing and without a licence check: "
            + ", ".join(sorted(on_disk - registered)))
        self.assertEqual(
            registered - on_disk, set(),
            "the registry names add-ons with no package: "
            + ", ".join(sorted(registered - on_disk)))


class TheManifestsAgreeWithTheRestOfTheApp(unittest.TestCase):

    def test_every_feature_key_exists_in_plans(self):
        """A key the licence server cannot mint padlocks the add-on for
        everyone -- which looks like a bug in the add-on rather than in a
        table, and is therefore debugged in the wrong file."""
        unknown = sorted({a.feature for a in registry.REGISTRY
                          if a.feature and a.feature not in plans.FEATURES})
        self.assertEqual(unknown, [],
                         "not present in plans.FEATURES: " + ", ".join(unknown))

    def test_run_prefixes_are_unique(self):
        """Two add-ons claiming one prefix means History attributes runs to
        whichever sorts first, silently."""
        seen = {}
        clashes = []
        for a in registry.REGISTRY:
            for prefix in a.run_prefixes:
                if prefix in seen:
                    clashes.append("%r claimed by %s and %s"
                                   % (prefix, seen[prefix], a.key))
                seen[prefix] = a.key
        self.assertEqual(clashes, [], "\n".join(clashes))

    def test_run_prefixes_are_never_translated(self):
        """These match f-strings written in the dialogs. A translated prefix
        matches nothing and History silently empties in Hindi -- no error, an
        empty list. devtools/extract_strings.py's _is_copy() already rejects
        a string with a trailing space, which is why every display prefix
        here ends in one."""
        for a in registry.REGISTRY:
            for prefix in a.run_prefixes:
                with self.subTest(addon=a.key, prefix=prefix):
                    self.assertTrue(
                        prefix.startswith("/") or prefix.endswith(" "),
                        "%r would be picked up as translatable copy; a run "
                        "prefix must be a slash command or end in a space"
                        % prefix)

    def test_every_intent_is_offered_by_at_most_one_addon(self):
        owners = {}
        clashes = []
        for a in registry.REGISTRY:
            for offer in a.offers:
                if offer.intent in owners:
                    clashes.append("%s offered by %s and %s"
                                   % (offer.intent, owners[offer.intent], a.key))
                owners[offer.intent] = a.key
        self.assertEqual(clashes, [], "\n".join(clashes))

    def test_every_intent_used_is_declared_in_names(self):
        """A typo'd intent is indistinguishable from a feature the customer
        has not bought: both draw no button and neither raises."""
        unknown = []
        for a in registry.REGISTRY:
            for offer in a.offers:
                if offer.intent not in names.ALL:
                    unknown.append("%s offers %r" % (a.key, offer.intent))
            for want in a.wants:
                if want not in names.ALL:
                    unknown.append("%s wants %r" % (a.key, want))
        self.assertEqual(unknown, [],
                         "not in addons/names.ALL:\n  " + "\n  ".join(unknown))

    def test_every_want_is_offered_by_somebody(self):
        """Not strictly required -- a want with no offer correctly degrades to
        a hidden button -- but in this build every want is deliberate, and a
        silently missing one is worth failing over."""
        for a in registry.REGISTRY:
            for want in a.wants:
                with self.subTest(addon=a.key, intent=want):
                    owner, handler = registry.offering(want)
                    self.assertIsNotNone(
                        owner, "%s wants %r and nothing offers it"
                               % (a.key, want))


class TheDottedReferencesResolve(unittest.TestCase):
    """The price of trading static analysis for strings, paid here."""

    def test_every_dialog_and_probe_resolves(self):
        for a in registry.REGISTRY:
            for field in ("dialog", "probe"):
                dotted = getattr(a, field)
                if not dotted:
                    continue
                with self.subTest(addon=a.key, field=field, target=dotted):
                    try:
                        got = registry.resolve(dotted)
                    except Exception as exc:            # noqa: BLE001
                        self.fail("%s.%s = %r did not resolve: %s"
                                  % (a.key, field, dotted, exc))
                    self.assertIsNotNone(got)

    def test_offer_handlers_live_inside_their_own_addon(self):
        """Not resolved yet, on purpose: the hand-off is wired at S8, and
        addons/<key>/contract.py does not exist until then. What IS checkable
        now is that no add-on has declared a handler pointing into somebody
        else's package -- which would be the import ban, laundered through a
        string."""
        for a in registry.REGISTRY:
            for offer in a.offers:
                with self.subTest(addon=a.key, intent=offer.intent):
                    self.assertTrue(
                        offer.handler.startswith("addons.%s." % a.key),
                        "%s offers %s through %r, which is not in its own "
                        "package" % (a.key, offer.intent, offer.handler))


class TheRegistryStillMatchesTheLiveTables(unittest.TestCase):
    """A transitional test, and the most valuable one in this file right now.

    The registry does not drive anything yet. Its whole claim is that it can
    reproduce the hand-maintained tables EXACTLY -- so this asserts that,
    key for key and in order. It stays until the tables are gone, and until
    then it is what makes the rewiring provably behaviour-neutral.
    """

    def test_the_rail_and_home_shelves_match_the_hand_written_tables(self):
        import widgets.home_panel as home_panel
        import widgets.sidebar as sidebar
        self.assertEqual([a.key for a in registry.shelf(manifest.RAIL)],
                         [row[0] for row in sidebar.ADDONS],
                         "the registry's rail shelf no longer reproduces "
                         "widgets/sidebar.ADDONS")
        self.assertEqual([a.key for a in registry.shelf(manifest.HOME)],
                         [row[0] for row in home_panel.ADDONS],
                         "the registry's home shelf no longer reproduces "
                         "widgets/home_panel.ADDONS")

    def test_the_licence_gate_matches_the_rail_for_every_addon(self):
        import widgets.sidebar as sidebar
        for row in sidebar.ADDONS:
            key, feature = row[0], row[4]
            with self.subTest(addon=key):
                entry = registry.by_key(key)
                self.assertIsNotNone(entry, "%r is on the rail and not in "
                                            "the registry" % key)
                self.assertEqual(
                    entry.feature, feature,
                    "widgets/sidebar.py gates %r on %r, the manifest says %r"
                    % (key, feature, entry.feature))

    def test_the_agent_gate_matches_main_windows_table(self):
        import main_window
        for agent, feature in main_window.AGENT_FEATURES.items():
            with self.subTest(agent=agent):
                self.assertEqual(
                    registry.feature_of_agent(agent), feature,
                    "main_window.AGENT_FEATURES gates %r on %r, the registry "
                    "says %r" % (agent, feature,
                                 registry.feature_of_agent(agent)))

    def test_the_run_prefixes_match_the_panel_base(self):
        import widgets.panel_base as panel_base
        live = {key: tuple(prefixes)
                for key, prefixes in panel_base._RUN_PREFIXES}
        mine = {a.key: a.run_prefixes for a in registry.REGISTRY
                if a.run_prefixes}
        self.assertEqual(
            mine, live,
            "the registry's run prefixes no longer reproduce "
            "widgets/panel_base._RUN_PREFIXES -- History would start "
            "attributing runs to the wrong add-on, or to none")


if __name__ == "__main__":
    unittest.main()
