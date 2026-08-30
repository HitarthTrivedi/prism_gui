"""Motion — say what it's about, get a scene-graph video with a real camera.

Same shape as Reel (dialogs/reel_dialog.py): one prompt and one button.
Attach a logo or business card and the brand colours are measured off it,
the agent writes a storyboard and then each scene in turn, and the
renderer draws every frame locally from a JSON scene graph — a real
camera, charts, diagrams and UI mockups, not an HTML page filmed.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time

from PySide6.QtWidgets import QMessageBox, QProgressBar, QLabel, QPlainTextEdit

import core_bridge as CB
import i18n
import theme
import wakeword
from dialogs.base import PrismDialog
from workers import AutomationWorker, RecordWorker, MotionWorker
from widgets.ask_panel import AskPanel


class MotionDialog(PrismDialog):
    def __init__(self, cfg: dict, attachments: list, parent=None):
        super().__init__(
            i18n.t("Make a Motion Graphic"),
            i18n.t("A scene-graph video with a real camera — charts, "
                   "diagrams and UI mockups, drawn frame by frame on this "
                   "machine."),
            icon="video", parent=parent, closable=False)
        self.setWindowTitle("Make a Motion Graphic")
        self.resize(780, 700)
        self.setMinimumSize(620, 620)
        self.cfg = cfg
        self.motion_generate = CB.get_motion_generate()

        self.images: list[dict] = []
        self.brand: dict = {}
        self.spec: dict | None = None
        self.out_path = ""
        # The findable copy — see config.ARTIFACTS_DIR. `out_path` is where
        # the render actually lands (~/.prism/runs, hidden), which is why
        # Play/Show always prefer this one once it exists.
        self.artifact_path = ""
        self._worker = None
        self._render_worker = None
        self._rec = None

        root = self.body
        root.setSpacing(theme.ROW_GAP)

        title = QLabel("What should the motion graphic show?")
        title.setObjectName("h4")
        root.addWidget(title)

        self.ask = AskPanel(
            'Just say it — for example:\n'
            '"an animated architecture diagram of our distributed crawler"\n\n'
            "Attach a logo or business card and the brand colours are taken "
            "straight from it.")
        self.ask.speak_clicked.connect(self._toggle_record)
        self.ask.files_added.connect(self._on_files_added)
        root.addWidget(self.ask)

        # A measured result ("your brand colours came off this logo"), not a
        # placeholder — same convention as ReelDialog's brand_label.
        self.brand_label = QLabel("", self)
        self.brand_label.setWordWrap(True)
        self.brand_label.setVisible(False)
        self.brand_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f" font-size: 13px;")
        root.addWidget(self.brand_label)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.script_view = QPlainTextEdit()
        self.script_view.setReadOnly(True)
        self.script_view.setPlaceholderText(
            "The scenes will be listed here once written.")
        self.script_view.setMinimumHeight(150)
        root.addWidget(self.script_view, stretch=1)

        self.play_btn = self.button(i18n.t("Play"), "secondary",
                                    icon_name="play", small=True,
                                    on_click=self._play)
        self.play_btn.setEnabled(False)
        self.footer.add_utility(self.play_btn)
        self.folder_btn = self.button(i18n.t("Show file"), "secondary",
                                      icon_name="folder", small=True,
                                      on_click=self._reveal)
        self.folder_btn.setEnabled(False)
        self.footer.add_utility(self.folder_btn)
        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.reject))
        self.run_btn = self.button(i18n.t("Make my motion graphic"), "primary",
                                   icon_name="video", on_click=self._run)
        self.footer.set_primary(self.run_btn)

        if attachments:
            self._absorb([a["path"] for a in attachments])

    # ── inputs ──────────────────────────────────────────────────────────

    def _on_files_added(self, paths: list):
        self._absorb(paths)

    def _absorb(self, paths: list):
        """Only images matter here — they carry the brand and become
        `image` nodes the AI can place by name. Anything else is ignored
        rather than refused."""
        for p in paths:
            if not p.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                continue
            try:
                att = CB.files.attach(p)
            except Exception:
                continue
            if att["path"] not in [i["path"] for i in self.images]:
                self.images.append(att)
        if not self.images:
            return
        # Same pixel-level measurement Reel/Studio use — no Motion-specific
        # brand sampling exists or needs to.
        self.brand = CB.get_reel().sample_brand(
            [i["path"] for i in self.images]) or {}
        if self.brand:
            self.brand_label.setText(
                f"Brand colours read from {', '.join(i['name'] for i in self.images)} — "
                f"accent {self.brand.get('accent')}, deep {self.brand.get('deep')}. "
                "Measured from the artwork, not guessed.")
            self.brand_label.setVisible(True)

    def _toggle_record(self):
        if self._rec:
            self._rec.stop()
            self.ask.set_recording(False)
            return
        if not CB.voice.available():
            QMessageBox.information(
                self, "Speak",
                "Voice needs PyAudio on this machine:\n\n"
                f"    {wakeword.install_hint()}\n\n"
                "Everything else works — just type instead.")
            return
        self.ask.set_recording(True)
        self._rec = RecordWorker(self.cfg)
        self._rec.done.connect(self._on_spoken)
        self._rec.failed.connect(lambda e: self._on_spoken("", ""))
        self._rec.start()

    def _on_spoken(self, text: str, lang: str):
        self._rec = None
        self.ask.set_recording(False)
        if text:
            self.ask.append_text(text)

    # ── the run ─────────────────────────────────────────────────────────
    # One turn names the storyboard; every scene's nodes are then asked for
    # on their own turn, in the same tab, checked before the next is asked
    # for. See core.motion.generate.build_spec() — same shape as Studio's
    # design conversation, for the same reason: a whole motion graphic
    # asked for in one reply starves every scene of room to have real
    # motion in it.

    def _run(self):
        request = self.ask.text()
        if not request:
            QMessageBox.information(self, "Motion Graphics",
                                    "Tell me what the motion graphic is about.")
            return

        active = CB.config.active_agents(self.cfg)
        # "media" is deliberately excluded — that category holds the local
        # Reel/Studio renderers, which render video and cannot hold a text
        # conversation. Same precedent as /motion's own CLI agent choice.
        writer = (self.cfg.get("motion_agent") or active.get("brains")
                 or active.get("content"))
        if not writer:
            QMessageBox.warning(self, "Motion Graphics",
                                "No writing agent set up yet — open Agents first.")
            return
        self.request = request

        self._busy(True, f"{writer} is planning the storyboard…")
        prompt = self.motion_generate.storyboard_instructions(request, self.brand)
        self._worker = AutomationWorker(
            {}, self.cfg, self.images, f"motion graphic — {request}",
            custom_stages=[("storyboard", writer, [prompt])],
            chatgpt_analysis=False,
            motion_design_stage="storyboard")
        self._worker.stage_event.connect(self._on_motion_event)
        self._worker.done.connect(self._on_storyboard)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_motion_event(self, kind: str, payload: dict):
        if kind == "motion_scene":
            n, total = payload.get("index", 0) + 1, payload.get("total", 0)
            self._busy(True, f"Writing scene {n} of {total} — "
                             "each one is written and checked on its own.")
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(n - 1)

    def _on_storyboard(self, responses: dict, links: dict):
        # By the time this fires, automation.run()'s motion_feeder block has
        # already run the whole per-scene conversation and left the fully
        # assembled, validated spec — as JSON text — in responses["storyboard"].
        texts = [t for t in (responses.get("storyboard") or []) if t.strip()]
        if not texts:
            self._busy(False, "")
            QMessageBox.warning(self, "Motion Graphics",
                                "The agent returned nothing.")
            return
        try:
            spec = json.loads(texts[-1])
        except (ValueError, json.JSONDecodeError) as e:
            self._busy(False, "")
            QMessageBox.warning(
                self, "Motion Graphics",
                f"Could not parse the assembled motion graphic: {e}"
                + ("\n\nIts tab: " + links["storyboard"]
                   if links.get("storyboard") else ""))
            return
        self.spec = spec
        self._start_render(spec)

    def _start_render(self, spec: dict):
        scenes = spec.get("scenes", [])
        lines = [f"{i + 1}. scene  ·  {sc.get('duration', 0):.1f}s   "
                 f"{len(sc.get('nodes', []))} node(s)"
                 for i, sc in enumerate(scenes)]
        self.script_view.setPlainText("\n".join(lines))

        dur = float((spec.get("project") or {}).get("duration", 8.0))
        os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
        stamp = int(time.time())
        self.out_path = os.path.join(CB.config.RUNS_DIR, f"motion_{stamp}.mp4")
        # Saved beside the video and complete in itself — assets inlined —
        # so it re-renders identically next year without an AI in the loop.
        json.dump(spec, open(
            os.path.join(CB.config.RUNS_DIR, f"motion_{stamp}.json"), "w"),
            indent=2)

        self.progress.setRange(0, 100)
        self._busy(True, f"Rendering {len(scenes)} scenes, {dur:.0f}s, "
                         "1080x1920…")
        self._render_worker = MotionWorker(spec, self.out_path)
        self._render_worker.progress.connect(self._on_frames)
        self._render_worker.done.connect(self._on_rendered)
        self._render_worker.failed.connect(self._on_failed)
        self._render_worker.start()

    def _on_frames(self, done: int, total: int):
        self.progress.setValue(int(done / max(1, total) * 100))

    def _on_rendered(self, path: str):
        self.play_btn.setEnabled(True)
        self.folder_btn.setEnabled(True)
        try:
            self.artifact_path = CB.config.save_artifact(
                path, self.request, kind="motion", task=self.request)
        except Exception:                               # noqa: BLE001
            self.artifact_path = ""
        if self.artifact_path:
            self._busy(False, i18n.t(
                "Done — saved to Desktop/Prism Artifacts/{name}").replace(
                "{name}", os.path.basename(self.artifact_path)))
        else:
            self._busy(False, f"Done — {os.path.basename(path)}")
        CB.config.save_run({
            "query": f"motion — {self.request}",
            "motion": {"mp4": path, "brand": self.brand,
                      "artifact": self.artifact_path},
        })

    def closeEvent(self, event):
        """Wind up any worker before this dialog is destroyed.

        A QThread destroyed while still running aborts the whole process —
        see ReelDialog.closeEvent() for the same fix, applied there first.
        """
        for worker in (getattr(self, "_worker", None),
                       getattr(self, "_render_worker", None),
                       getattr(self, "_rec", None)):
            if worker is None or not worker.isRunning():
                continue
            if hasattr(worker, "stop"):
                worker.stop()
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)

    def _on_failed(self, error: str):
        self._busy(False, "")
        QMessageBox.warning(self, "Motion Graphics", error)

    def _busy(self, busy: bool, message: str):
        self.progress.setVisible(busy)
        if busy and self.progress.maximum() == 0:
            self.progress.setRange(0, 0)
        self.run_btn.setEnabled(not busy)
        self.status.setText(message)

    # ── output ──────────────────────────────────────────────────────────

    def _play(self):
        path = self.artifact_path or self.out_path
        if not path:
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # noqa: F821
        else:
            subprocess.Popen(["xdg-open", path])

    def _reveal(self):
        path = self.artifact_path or self.out_path
        if not path:
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        elif os.name == "nt":
            subprocess.Popen(["explorer", "/select,", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
