"""Does Prism actually speak the user's language — and only where it should?

Two halves, and the second matters more than the first.

Translating is easy. What is dangerous about the approach in i18n.py is that
it patches Qt's own text methods, so the SAME call that draws "Start the work"
also draws a customer's name, a file path, an API key and whole paragraphs
written by Claude. The catalogue is the allow-list that makes that safe, and
most of what follows is proving the allow-list holds.

Qt runs offscreen; no window is ever shown.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton)

import core_bridge as CB  # noqa: E402
import i18n  # noqa: E402
import paths  # noqa: E402

_app = QApplication.instance() or QApplication([])

# install() is process-wide and irreversible, so it happens once here and
# every test below runs against the patched Qt — which is also how the real
# app runs it.
i18n.install()

PACKS = [c for c, _n, _v in i18n.available() if c != "en"]


class Lookup(unittest.TestCase):
    def setUp(self):
        i18n.load("hi")

    def tearDown(self):
        i18n.load("en")

    def test_a_catalogued_string_is_translated(self):
        self.assertNotEqual(i18n.t("Make a plan"), "Make a plan")

    def test_icon_padding_survives(self):
        """Buttons are padded for their icon ("  Start the work"). The pad is
        not part of the key, and it has to come back."""
        out = i18n.t("  Start the work")
        self.assertTrue(out.startswith("  "), repr(out))
        self.assertEqual(out.strip(), i18n.t("Start the work"))

    def test_english_is_a_passthrough(self):
        i18n.load("en")
        self.assertEqual(i18n.t("Make a plan"), "Make a plan")

    def test_an_unknown_language_falls_back_rather_than_raising(self):
        i18n.load("xx")
        self.assertEqual(i18n.current(), "en")
        self.assertEqual(i18n.t("Make a plan"), "Make a plan")


class NothingElseIsTouched(unittest.TestCase):
    """The whole safety argument for patching Qt, one case per kind of thing
    that must survive a trip through t() unchanged."""

    def setUp(self):
        i18n.load("hi")

    def tearDown(self):
        i18n.load("en")

    def test_a_stage_result_is_left_alone(self):
        answer = ("Here is the brief you asked for. The market splits into "
                  "three segments, and the second is the one worth chasing.")
        self.assertEqual(i18n.t(answer), answer)

    def test_a_tool_name_is_left_alone(self):
        for brand in ("ChatGPT", "Claude", "Apollo", "Perplexity", "Canva"):
            self.assertEqual(i18n.t(brand), brand)

    def test_the_product_name_is_left_alone(self):
        self.assertEqual(i18n.t("Prism"), "Prism")

    def test_a_file_path_is_left_alone(self):
        path = "/Users/someone/Documents/Delta_Investor_Deck.pptx"
        self.assertEqual(i18n.t(path), path)

    def test_an_api_key_is_left_alone(self):
        key = "gsk_abcdefghijklmnopqrstuvwx"
        self.assertEqual(i18n.t(key), key)

    def test_a_line_edits_contents_are_never_translated(self):
        """QLineEdit's constructor takes CONTENT, not a label — Setup builds
        the key field as QLineEdit(cfg["api_key"]). Its __init__ is left
        unpatched precisely so this cannot go wrong."""
        edit = QLineEdit("Make a plan")   # a catalogued string, as content
        self.assertEqual(edit.text(), "Make a plan")

    def test_a_pack_cannot_smuggle_in_a_key_the_catalogue_forbids(self):
        """Packs are editable JSON in the user's home directory. load()
        intersects with the catalogue so an added key does nothing."""
        i18n._active = {}
        i18n.load("hi")
        for key in i18n._active:
            self.assertIn(key, i18n.catalogue())


class ThroughQt(unittest.TestCase):
    """t() being right is not the same as the window being translated. These
    go through the patched Qt methods the app actually calls."""

    def setUp(self):
        i18n.load("hi")

    def tearDown(self):
        i18n.load("en")

    def test_constructor_text(self):
        self.assertEqual(QLabel("Your plan").text(), i18n.t("Your plan"))
        self.assertEqual(QPushButton("Save").text(), i18n.t("Save"))
        self.assertEqual(QCheckBox("Attached").text(), i18n.t("Attached"))

    def test_set_text(self):
        label = QLabel()
        label.setText("Find the people")
        self.assertEqual(label.text(), i18n.t("Find the people"))

    def test_tooltips(self):
        button = QPushButton()
        button.setToolTip("Runs every step still switched on.")
        self.assertEqual(button.toolTip(),
                         i18n.t("Runs every step still switched on."))

    def test_placeholders_translate_but_contents_do_not(self):
        edit = QLineEdit()
        edit.setPlaceholderText("blank = auto-detect")
        self.assertEqual(edit.placeholderText(),
                         i18n.t("blank = auto-detect"))

    def test_combo_items(self):
        combo = QComboBox()
        combo.addItems(["Make a plan", "ChatGPT"])
        self.assertEqual(combo.itemText(0), i18n.t("Make a plan"))
        self.assertEqual(combo.itemText(1), "ChatGPT")   # a brand, untouched

    def test_a_button_built_with_an_icon_still_translates_its_label(self):
        """QPushButton(icon, text) puts the string at argument 1, so the ctor
        wrapper translates the first STRING argument, not argument zero."""
        from PySide6.QtGui import QIcon
        self.assertEqual(QPushButton(QIcon(), "Save").text(), i18n.t("Save"))


class Packs(unittest.TestCase):
    def test_at_least_one_pack_ships(self):
        self.assertTrue(PACKS, "no language packs found in lang/")

    def test_every_pack_key_is_in_the_catalogue(self):
        """A key that is not in the catalogue is dead weight — load() drops
        it — and usually means the English copy changed under the pack."""
        cat = i18n.catalogue()
        for code in PACKS:
            pack = i18n._read(paths.resource("lang", f"{code}.json"))
            for key in pack:
                self.assertIn(key, cat, f"{code}.json has a stale key: {key!r}")

    def test_placeholders_survive_translation(self):
        """A dropped {n} either raises from .format() or silently loses the
        number out of the sentence. Both have shipped in other products."""
        for code in PACKS:
            pack = i18n._read(paths.resource("lang", f"{code}.json"))
            for english, translated in pack.items():
                self.assertEqual(
                    set(re.findall(r"\{[a-z_]+\}", english)),
                    set(re.findall(r"\{[a-z_]+\}", translated)),
                    f"{code}: placeholder mismatch on {english!r}")

    def test_no_pack_entry_is_blank(self):
        for code in PACKS:
            with open(paths.resource("lang", f"{code}.json"),
                      encoding="utf-8") as f:
                raw = json.load(f)["strings"]
            blank = [k for k, v in raw.items() if not v.strip()]
            self.assertFalse(blank, f"{code}: blank translations: {blank[:3]}")

    def test_coverage_is_reported_honestly(self):
        for code in PACKS:
            done, total = i18n.coverage(code)
            self.assertGreater(total, 0)
            self.assertLessEqual(done, total)

    def test_the_catalogue_is_not_empty(self):
        """An empty catalogue turns every language into English with no error
        anywhere — exactly the failure a packaging mistake produces."""
        self.assertGreater(len(i18n.catalogue()), 100)

    def test_available_only_offers_languages_that_have_a_pack(self):
        for code, _name, _native in i18n.available():
            if code == "en":
                continue
            self.assertTrue(
                os.path.exists(paths.resource("lang", f"{code}.json"))
                or os.path.exists(paths.user_dir("lang", f"{code}.json")))


class AnswerLanguage(unittest.TestCase):
    """What the tools write back — a different setting from the UI language,
    and the one that can damage a deliverable if it misfires."""

    def test_unset_means_no_directive(self):
        self.assertEqual(CB.lang.directive(""), "")

    def test_a_language_produces_a_directive_naming_it_in_english(self):
        text = CB.lang.directive("gu")
        self.assertIn("Gujarati", text)

    def test_the_directive_protects_addresses_and_links(self):
        """A model told to write everything in Hindi will transliterate a
        domain name into Devanagari, and the email then bounces."""
        text = CB.lang.directive("hi").lower()
        for must in ("email address", "url", "file name", "code"):
            self.assertIn(must, text)

    def test_an_unknown_code_is_ignored(self):
        self.assertEqual(CB.lang.directive("zz"), "")

    def test_the_two_language_tables_agree(self):
        """i18n owns the endonyms, the engine owns the names it puts in
        prompts. Different files, one set of codes."""
        self.assertEqual(set(i18n.LANGUAGES), set(CB.lang.NAMES))
        for code, (english, _native, _rtl) in i18n.LANGUAGES.items():
            self.assertEqual(english, CB.lang.NAMES[code])


class Presentation(unittest.TestCase):
    def test_arabic_is_right_to_left_and_hindi_is_not(self):
        self.assertTrue(i18n.is_rtl("ar"))
        self.assertFalse(i18n.is_rtl("hi"))

    def test_indic_languages_get_a_font_that_can_draw_them(self):
        """Barlow has no Devanagari. Without this the headings — which pin
        `font-family: "Barlow Condensed"` with no fallback at all — are left
        to whatever Qt substitutes."""
        qss = '#h5 { font-family: "Barlow Condensed"; font-size: 16px; }'
        out = i18n.style_for_script(qss, "hi")
        self.assertIn("Barlow Condensed", out)
        self.assertIn("Noto Sans Devanagari", out)

    def test_latin_languages_leave_the_stylesheet_alone(self):
        qss = '#h5 { font-family: "Barlow Condensed"; }'
        self.assertEqual(i18n.style_for_script(qss, "es"), qss)

    def test_extending_the_stylesheet_twice_does_not_stack(self):
        qss = 'QWidget { font-family: "Barlow", "Inter"; }'
        once = i18n.style_for_script(qss, "gu")
        self.assertEqual(once, i18n.style_for_script(once, "gu"))

    def test_the_real_stylesheet_still_parses_as_qss(self):
        """Rewriting font stacks with a regex over the shipped file — prove it
        does not mangle the rest of it."""
        path = paths.resource("style.qss")
        if not os.path.exists(path):
            self.skipTest("style.qss not present")
        with open(path, encoding="utf-8") as f:
            original = f.read()
        patched = i18n.style_for_script(original, "hi")
        self.assertEqual(original.count("{"), patched.count("{"))
        self.assertEqual(original.count("}"), patched.count("}"))
        self.assertEqual(original.count("font-family:"),
                         patched.count("font-family:"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class FileDialogsAreLeftAlone(unittest.TestCase):
    """QFileDialog's statics must stay stock. Wrapping them broke attaching
    files entirely: they are the entry point to a NATIVE OS panel, not to a Qt
    widget, and a Python frame in the middle of that call is not ours to add.

    The caption they were wrapped for is not even drawn on macOS, so the patch
    cost the one code path every attachment goes through and bought nothing.
    Captions are translated at the call sites instead.
    """

    def test_the_static_openers_are_not_patched(self):
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        for cls, name in ((QFileDialog, "getOpenFileName"),
                          (QFileDialog, "getOpenFileNames"),
                          (QFileDialog, "getSaveFileName"),
                          (QFileDialog, "getExistingDirectory"),
                          (QInputDialog, "getText")):
            fn = getattr(cls, name)
            self.assertNotEqual(
                getattr(fn, "__module__", ""), "i18n",
                f"{cls.__name__}.{name} has been wrapped again — that is what "
                f"stopped Add file working.")

    def test_call_sites_translate_their_own_captions(self):
        """Since the statics are stock, a bare literal caption would ship
        untranslated and nobody would notice until a Hindi screenshot."""
        import re as _re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pattern = _re.compile(
            r"QFileDialog\.get(?:OpenFileName|OpenFileNames|SaveFileName|"
            r"ExistingDirectory)\(\s*[^,)]+,\s*(?!i18n\.t\()[\"']")
        offenders = []
        for folder in (".", "widgets", "dialogs"):
            base = os.path.join(root, folder)
            for name in sorted(os.listdir(base)):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as f:
                    if pattern.search(f.read()):
                        offenders.append(os.path.join(folder, name))
        self.assertFalse(offenders,
                         f"file-dialog captions not wrapped in i18n.t(): "
                         f"{offenders}")
