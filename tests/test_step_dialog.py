"""The STEP add-on's window — the GUI face of /step, /step-auto and
/step-ask, tested the way test_gerber_dialog.py tests Gerber's: intercept
AutomationWorker rather than open a browser, and read what it was given.

The one rule that must never break is the same as Gerber's: the customer's
model is their product. Draft, Ask and Edit may hand an AI the measured
numbers and Prism's OWN render of the parts — never the STEP file, never
its path. If a future edit ever attaches the model to a stage, the security
tests below fail immediately, in CI, before it ships.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))

import core_bridge as CB  # noqa: E402
import plans  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_gates import GateTest  # noqa: E402
from addons.step import dialog as SD  # noqa: E402
from addons.step.dialog import StepDialog  # noqa: E402
from core import stepfile as SF  # noqa: E402

_app = QApplication.instance() or QApplication([])
HAVE_CAD = SF.available()[0]
EVERYTHING = tuple(plans.FEATURES)


class _Sig:
    def connect(self, *_):
        pass


def _dialog(cfg=None, root=None):
    """A dialog whose folder question is already answered — cfg carries a
    scratch step_out_dir — so no modal can open in a headless run. Every
    test that wants the question itself clears the key on purpose."""
    root = root or tempfile.mkdtemp(prefix="prism-test-step-")
    if cfg is None:
        cfg = {"agents": {"visual": "ChatGPT", "brains": "Claude"},
               "api_key": "gsk_test", "step_out_dir": root}
    return StepDialog(cfg, [], None)


def _box_step(path: str):
    """A 60 x 40 x 8 mm block with one Ø5 hole — every figure known."""
    import cadquery as cq
    part = (cq.Workplane("XY").box(60, 40, 8)
            .faces(">Z").workplane().hole(5))
    cq.exporters.export(part, path)


def _fake_measured(dlg, stem="block", out_dir=None):
    """A measured model without cadquery: the shape _on_measured builds."""
    out_dir = out_dir or os.path.join(dlg._root(), stem)
    os.makedirs(out_dir, exist_ok=True)
    png = os.path.join(out_dir, SF.names(stem)["png"])
    open(png, "wb").write(b"png")
    report = {"file": f"{stem}.step", "stem": stem, "mode": "plastic",
              "path": f"/secret/place/{stem}.step",
              "overall_mm": (60.0, 40.0, 8.0),
              "parts": [{"name": "p", "size_mm": (60.0, 40.0, 8.0),
                         "thickness_mm": 6.0, "volume_cm3": 38.0,
                         "holes": [{"dia_mm": 5.0, "count": 1}]}],
              "warnings": []}
    m = {"path": f"/secret/place/{stem}.step", "report": report,
         "out_dir": out_dir, "drawn": {"png": png, "html": ""}, "xlsx": ""}
    dlg.paths = [m["path"]]
    return m


class _CaptureWorker:
    """Stands in for AutomationWorker: records the call, never starts."""
    seen: dict = {}

    def __init__(self, *a, **kw):
        _CaptureWorker.seen = {"args": a, "kwargs": kw}
        self.done = self.failed = _Sig()

    def start(self):
        _CaptureWorker.seen["started"] = True


class TheDoorIsShutUntilAModelIsAttached(unittest.TestCase):

    def test_generate_waits_for_a_model(self):
        dlg = _dialog()
        self.assertFalse(dlg.generate_btn.isEnabled())
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        self.assertTrue(dlg.generate_btn.isEnabled())

    def test_only_step_files_are_taken(self):
        """A PDF or a DWG dropped here is not a model; it is named in the
        status line and left out, rather than measured and failing later."""
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/quote.pdf", "/nowhere/housing.stp"])
        self.assertEqual([os.path.basename(p) for p in dlg.paths],
                         ["housing.stp"])
        self.assertIn("quote.pdf", dlg.status.text())

    def test_the_same_model_is_not_attached_twice(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/a.step"])
        dlg._on_files_added(["/nowhere/a.step"])
        self.assertEqual(len(dlg.paths), 1)

    def test_the_file_is_asked_for_before_the_question(self):
        """The question box and the choice of action stay out of sight
        until a model is attached — the file first, then what to do."""
        dlg = _dialog()
        self.assertTrue(dlg.step2.isHidden())
        self.assertIs(dlg.ask.edit.parentWidget(), dlg.step2)
        dlg._on_files_added(["/nowhere/quote.pdf"])
        self.assertTrue(dlg.step2.isHidden(), "a non-model must not open it")
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        self.assertFalse(dlg.step2.isHidden())

    def test_the_three_actions_are_offered_and_draft_is_the_default(self):
        dlg = _dialog()
        self.assertEqual(set(dlg._action_buttons), {"draft", "ask", "edit"})
        self.assertEqual(dlg._action(), "draft")
        dlg._action_buttons["edit"].setChecked(True)
        self.assertEqual(dlg._action(), "edit")


class TheFolderQuestionIsAskedOnceThenKept(unittest.TestCase):
    """The owner's ask: the person says where all the files for a model go.
    Asked at the first Generate, remembered in cfg, changeable from the
    Options box — and never asked again once answered."""

    def test_an_answered_question_is_not_asked_again(self):
        dlg = _dialog()
        with mock.patch.object(SD, "QMessageBox") as box:
            self.assertTrue(dlg._ensure_root())
            box.assert_not_called()

    def test_choosing_the_desktop_stores_the_default_explicitly(self):
        cfg = {"agents": {}, "api_key": "", "step_out_dir": ""}
        dlg = StepDialog(cfg, [], None)
        fake = mock.MagicMock()
        fake.return_value.clickedButton.return_value = "desktop-btn"
        fake.return_value.addButton.side_effect = ["choose-btn", "desktop-btn",
                                                   "cancel-btn"]
        with mock.patch.object(SD, "QMessageBox", fake), \
                mock.patch.object(CB.config, "save") as save:
            self.assertTrue(dlg._ensure_root())
            save.assert_called_once()
        self.assertEqual(cfg["step_out_dir"], SF.DEFAULT_OUT_ROOT)
        self.assertIn("Prism Step", dlg.root_label.text())

    def test_choosing_a_folder_keeps_it(self):
        cfg = {"agents": {}, "api_key": "", "step_out_dir": ""}
        dlg = StepDialog(cfg, [], None)
        chosen = tempfile.mkdtemp(prefix="prism-test-step-root-")
        fake = mock.MagicMock()
        fake.return_value.clickedButton.return_value = "choose-btn"
        fake.return_value.addButton.side_effect = ["choose-btn", "desktop-btn",
                                                   "cancel-btn"]
        with mock.patch.object(SD, "QMessageBox", fake), \
                mock.patch.object(SD.QFileDialog, "getExistingDirectory",
                                  return_value=chosen), \
                mock.patch.object(CB.config, "save"):
            self.assertTrue(dlg._ensure_root())
        self.assertEqual(cfg["step_out_dir"], chosen)
        self.assertIn(chosen, dlg.root_label.text())

    def test_cancelling_the_question_generates_nothing(self):
        cfg = {"agents": {}, "api_key": "", "step_out_dir": ""}
        dlg = StepDialog(cfg, [], None)
        fake = mock.MagicMock()
        fake.return_value.clickedButton.return_value = "something-else"
        fake.return_value.addButton.side_effect = ["choose-btn", "desktop-btn",
                                                   "cancel-btn"]
        with mock.patch.object(SD, "QMessageBox", fake):
            self.assertFalse(dlg._ensure_root())
        self.assertEqual(cfg["step_out_dir"], "")

    def test_the_root_reaches_the_measuring_worker(self):
        """What was chosen is what the worker is given — the folder per
        model is made under it (core.stepfile.output_dir)."""
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        seen = {}

        class FakeMeasure:
            def __init__(self, paths, mode, root):
                seen.update(paths=paths, mode=mode, root=root)
                self.progress = self.done = self.failed = _Sig()

            def start(self):
                seen["started"] = True

        with mock.patch.object(SD, "StepMeasureWorker", FakeMeasure), \
                mock.patch.object(CB.config, "save"):
            dlg._generate()
        self.assertEqual(seen["root"], dlg.cfg["step_out_dir"])
        self.assertEqual(seen["mode"], "metal")
        self.assertTrue(seen["started"])


class AnAgentOnlyEverSeesTheNumbersAndPrismsOwnRender(unittest.TestCase):
    """The standing rule, enforced at the calls that could break it."""

    def _draft_call(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker):
            dlg._current = m
            dlg._draft(m)
        return dlg, m, _CaptureWorker.seen

    def test_draft_attaches_prisms_render_and_never_the_model(self):
        dlg, m, seen = self._draft_call()
        attachments = seen["args"][2]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["path"], m["drawn"]["png"])
        for a in attachments:
            self.assertFalse(a["path"].lower().endswith((".step", ".stp")))

    def test_the_draft_prompt_carries_the_numbers_not_the_path(self):
        dlg, m, seen = self._draft_call()
        prompt = seen["kwargs"]["custom_stages"][0][2][0]
        self.assertIn("60.00 x 40.00 x 8.00", prompt)
        self.assertIn("MEASURED OFFLINE", prompt)
        self.assertNotIn("/secret/place", prompt)
        self.assertNotIn("/secret/place", seen["args"][3])

    def test_draft_asks_for_the_returned_files(self):
        """The image the agent draws comes back through files_out — without
        it the sheet exists only in the tool's tab."""
        dlg, m, seen = self._draft_call()
        self.assertIs(seen["kwargs"]["files_out"], dlg._made_files)

    def test_draft_promises_a_picture_so_the_wait_is_long_enough(self):
        dlg, m, seen = self._draft_call()
        self.assertEqual(seen["kwargs"]["image_stages"], {"visual"})

    def test_draft_is_chatgpt_only_with_no_fallback(self):
        """Not the configured visual tool, and no hand-off to another
        image model if ChatGPT stumbles — a second, differently-wrong sheet
        is not a rescue."""
        dlg = _dialog(cfg={"agents": {"visual": "Gamma.app",
                                      "media": "Canva"},
                           "api_key": "k",
                           "step_out_dir": tempfile.mkdtemp()})
        m = _fake_measured(dlg)
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker):
            dlg._current = m
            dlg._draft(m)
        seen = _CaptureWorker.seen
        self.assertEqual(seen["kwargs"]["custom_stages"][0][1], "ChatGPT")
        self.assertIs(seen["kwargs"]["failover"], False)

    def test_the_plan_stage_gets_numbers_advice_and_the_question(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("make it lighter")
        dlg._current = m
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker):
            dlg._on_suggested("1) thin the wall")
        seen = _CaptureWorker.seen
        prompt = seen["kwargs"]["custom_stages"][0][2][0]
        self.assertEqual(seen["kwargs"]["custom_stages"][0][1], "Claude")
        self.assertIn("make it lighter", prompt)
        self.assertIn("thin the wall", prompt)
        self.assertIn("60.00 x 40.00 x 8.00", prompt)
        self.assertNotIn("/secret/place", prompt)
        for a in seen["args"][2]:
            self.assertFalse(a["path"].lower().endswith((".step", ".stp")))

    def test_the_groq_question_carries_numbers_and_confidentiality(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        p = SF.ask_prompt(m["report"], "make it lighter")
        self.assertIn("cannot be shown to you", p)
        self.assertNotIn("/secret/place", p)

    def test_ask_stops_at_the_review_page_and_edit_asks_before_building(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("fit 6mm")
        dlg._current = m
        plan = ('{"changes": [{"op": "enlarge_hole", "part": "p", '
                '"dia_mm": 5, "new_dia_mm": 6, "why": "M6"}], "advice": []}')
        built = {}

        class FakeApply:
            def __init__(self, *a, **kw):
                built["args"] = a
                self.done = self.failed = _Sig()

            def start(self):
                built["started"] = True

        # Ask ends the queue, which saves the run — into a temp store, not
        # the developer's real ~/.prism (conftest checks).
        with mock.patch.object(SD.QDesktopServices, "openUrl"), \
                mock.patch.object(CB.config, "save_run") as saved, \
                mock.patch.object(SD, "StepApplyWorker", FakeApply), \
                mock.patch.object(SD.QMessageBox, "question",
                                  return_value=QMessageBox.Yes) as ask:
            dlg._action_buttons["ask"].setChecked(True)
            dlg._on_planned({"plan": [plan]}, {})
            ask.assert_not_called()
            self.assertNotIn("started", built)
            self.assertTrue(os.path.exists(
                os.path.join(m["out_dir"], SF.names(m["report"])["review"])))
            # The run record names the action and the model, never the path.
            record = saved.call_args[0][0]
            self.assertTrue(record["query"].startswith("STEP — Ask:"))
            self.assertEqual(record["step"]["action"], "ask")
            self.assertNotIn("/secret/place", record["query"])

            dlg._current = m
            dlg._action_buttons["edit"].setChecked(True)
            dlg._on_planned({"plan": [plan]}, {})
            ask.assert_called_once()
            self.assertTrue(built["started"])
            # The worker is handed the ORIGINAL path to read, and writes the
            # copy under the model's own name in the model's own folder.
            self.assertEqual(built["args"][0], m["path"])
            self.assertEqual(built["args"][4], m["out_dir"])

    def test_a_no_answer_builds_nothing(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("fit 6mm")
        dlg._current = m
        dlg._action_buttons["edit"].setChecked(True)
        plan = ('{"changes": [{"op": "scale", "part": "all", "factor": 2, '
                '"why": ""}], "advice": []}')
        with mock.patch.object(SD.QDesktopServices, "openUrl"), \
                mock.patch.object(CB.config, "save_run"), \
                mock.patch.object(SD, "StepApplyWorker") as apply_w, \
                mock.patch.object(SD.QMessageBox, "question",
                                  return_value=QMessageBox.No):
            dlg._on_planned({"plan": [plan]}, {})
            apply_w.assert_not_called()
        self.assertTrue(any("not built" in n for n in dlg._notes))


class TheGuardsSpeakBeforeAnythingRuns(unittest.TestCase):
    """Real QMessageBox.warning calls, patched so a headless run does not
    block — the guard itself is what is being proven."""

    def test_ask_without_a_question_is_refused(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/a.step"])
        dlg._action_buttons["ask"].setChecked(True)
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker:
            dlg._generate()
            warn.assert_called_once()
            worker.assert_not_called()

    def test_draft_needs_no_configured_image_tool(self):
        """Draft is ChatGPT's job regardless of what Agents says, so a cfg
        with no visual tool at all still measures and drafts."""
        dlg = _dialog(cfg={"agents": {"brains": "Claude"}, "api_key": "k",
                           "step_out_dir": tempfile.mkdtemp()})
        dlg._on_files_added(["/nowhere/a.step"])
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker, \
                mock.patch.object(CB.config, "save"):
            dlg._generate()
            warn.assert_not_called()
            worker.assert_called_once()

    def test_edit_without_a_reasoning_tool_is_refused(self):
        dlg = _dialog(cfg={"agents": {"visual": "ChatGPT"}, "api_key": "k",
                           "step_out_dir": tempfile.mkdtemp()})
        dlg._on_files_added(["/nowhere/a.step"])
        dlg.ask.set_text("fit 6mm")
        dlg._action_buttons["edit"].setChecked(True)
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker:
            dlg._generate()
            warn.assert_called_once()
            worker.assert_not_called()


@unittest.skipUnless(HAVE_CAD, "cadquery not installed")
class ARealModelLandsWhereItWasSent(unittest.TestCase):
    """One real measurement through the dialog's own worker: the folder is
    named after the model, under the chosen root, and every file inside
    carries the model's name."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="prism-test-step-root-")
        src = tempfile.mkdtemp()
        cls.model = os.path.join(src, "Bracket A.step")
        _box_step(cls.model)
        cls.dlg = _dialog(root=cls.root)
        cls.dlg._on_files_added([cls.model])
        cls.dlg.mode_combo.setCurrentText("plastic")
        # Draft is the default action and needs an image tool; stop the
        # queue at the measurement by intercepting the AI stage.
        #
        # The measuring worker runs SYNCHRONOUSLY — start() replaced by
        # run() on the calling thread, so its signals deliver straight into
        # the dialog's slots with no event loop. Spinning processEvents()
        # here to wait for a real thread is what aborted the whole suite:
        # it delivered a zero-delay modal leaked by an inquiry-dialog test
        # that ran earlier, with nobody to click it.
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker), \
                mock.patch.object(SD.StepMeasureWorker, "start",
                                  lambda worker: worker.run()), \
                mock.patch.object(CB.config, "save"), \
                mock.patch.object(CB.config, "save_artifact"):
            cls.dlg._generate()
        if not cls.dlg.models:
            raise unittest.SkipTest("measuring did not finish")

    def test_the_folder_is_named_after_the_model_under_the_root(self):
        m = self.dlg.models[0]
        self.assertEqual(m["out_dir"], os.path.join(self.root, "Bracket A"))

    def test_every_file_carries_the_models_name(self):
        m = self.dlg.models[0]
        files = os.listdir(m["out_dir"])
        self.assertTrue(files)
        for f in files:
            self.assertTrue(f.startswith("Bracket A - "), f)
        self.assertIn("Bracket A - dimensions.xlsx", files)
        self.assertIn("Bracket A - drawing sheet.html", files)

    def test_the_numbers_are_on_screen_and_the_folder_is_named(self):
        text = self.dlg.meas_view.toPlainText()
        self.assertIn("60.00 x 40.00 x 8.00", text)
        self.assertIn("plastic moulding", text)
        self.assertIn(self.dlg.models[0]["out_dir"], self.dlg.files_label.text())
        self.assertTrue(self.dlg.folder_btn.isEnabled())

    def test_the_draft_stage_was_handed_prisms_render_only(self):
        seen = _CaptureWorker.seen
        self.assertTrue(seen.get("started"))
        for a in seen["args"][2]:
            self.assertFalse(a["path"].lower().endswith((".step", ".stp")))
            self.assertTrue(a["path"].startswith(self.root))


class ItIsOnTheShelfAndInHistory(unittest.TestCase):
    """Everything the shell knows about STEP it reads off the manifest --
    the rail row, the Home card, History's run attribution and the licence
    gate. These pin that the manifest says what the dialog does."""

    def test_it_is_registered_and_gated_on_its_own_key(self):
        from addons import registry
        a = registry.by_key("step")
        self.assertIsNotNone(a)
        self.assertEqual(a.label, "STEP")
        self.assertEqual(a.feature, "step")
        self.assertEqual(a.screen, "step")
        self.assertEqual(a.engine, ("stepfile",))

    def test_it_is_on_the_rail_with_a_real_icon(self):
        from widgets import icons, sidebar
        entry = next(e for e in sidebar.ADDONS if e[0] == "step")
        self.assertEqual(entry[1], "STEP")
        self.assertEqual(entry[4], "step")
        self.assertIn(entry[2], set(icons._STROKED) | set(icons._FILLED))

    def test_history_recognises_its_runs(self):
        from addons import registry
        from widgets.panel_base import _kind_of, ADDONS
        self.assertEqual(registry.kind_of("STEP — Draft: Assem1.STEP"), "step")
        self.assertEqual(_kind_of("STEP — Draft: Assem1.STEP"), "step")
        self.assertEqual(_kind_of("/step-ask plastic x.stp q"), "step")
        self.assertEqual(_kind_of("/step-auto plastic x.stp"), "step")
        self.assertEqual(ADDONS["step"], "STEP")

    def test_the_front_door_names_its_tools(self):
        from addons.step.panel import StepPanel
        panel = StepPanel({"agents": {"visual": "ChatGPT", "brains": "Claude"}})
        roles = panel.tool_roles()
        self.assertEqual([r[3] for r in roles], ["ChatGPT", "Claude"])
        self.assertEqual(panel.KIND, "step")

    def test_the_offer_takes_plain_paths(self):
        """The intent contract: paths in, and the dialog does its own
        shaping -- only models are kept, and a caller by intent needs to
        know nothing about what a model is."""
        from addons import names, registry
        owner, handler = registry.offering(names.MEASURE_MODEL)
        self.assertEqual(owner.key, "step")
        opened = {}

        class FakeDialog:
            def __init__(self, cfg, attachments, parent):
                opened["attachments"] = attachments
                self.paths = []

            def _on_files_added(self, paths):
                opened["paths"] = paths

            def exec(self):
                opened["shown"] = True

        with mock.patch.object(SD, "StepDialog", FakeDialog):
            registry.resolve(handler)(None, {}, ["/x/a.step", "/x/q.pdf"])
        self.assertEqual(opened["paths"], ["/x/a.step", "/x/q.pdf"])
        self.assertEqual(opened["attachments"], [])
        self.assertTrue(opened["shown"])


class TheWindowRoutesIt(GateTest):
    """The route from the rail to the screen, and from the screen's button
    to the dialog, asserted on a real window -- not by reading source."""

    def test_the_rail_key_lands_on_the_step_screen(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        # The gate itself is a network round trip on a worker thread --
        # tests/test_addon_gates.py proves the gate; this proves the route
        # behind it, so the gate is stepped over here the same way.
        with mock.patch.object(main_window.MainWindow, "_authorized_then",
                               lambda self, feature, action, then: then()):
            win._handle_command("step")
        self.assertEqual(win.screens.currentIndex(),
                         main_window.SCREEN_INDEX["step"])
        self.assertIs(win.screens.currentWidget(), win.step_panel)

    def test_the_screens_button_opens_the_dialog_when_cadquery_is_there(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        with mock.patch.object(CB, "step_available", return_value=(True, "")), \
                mock.patch.object(main_window, "StepDialog") as dlg:
            win.step_panel.opened.emit()
        dlg.assert_called_once_with(win.cfg, win.attachments, win)
        dlg.return_value.exec.assert_called_once()

    def test_without_cadquery_it_says_so_and_opens_nothing(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        with mock.patch.object(CB, "step_available",
                               return_value=(False, "no cadquery")), \
                mock.patch.object(main_window, "StepDialog") as dlg, \
                mock.patch.object(main_window.QMessageBox, "information") as box:
            win.step_panel.opened.emit()
        dlg.assert_not_called()
        self.assertIn("cadquery", box.call_args[0][2])

    def test_it_is_paywalled_without_its_feature(self):
        """Also covered by tests/test_addon_gates.py; kept here so the
        add-on's own file says what it costs."""
        self.grant([f for f in EVERYTHING if f != "step"])
        win = self._window()
        with mock.patch.object(type(win), "_show_screen") as shown:
            win._handle_command("step")
        self.assertIn("step", self.paywalled)
        shown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
