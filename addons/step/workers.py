"""STEP's background work, off the UI thread.

Three workers because the dialog's three actions are three different kinds
of wait: OpenCascade reading a model (seconds to a minute), one Groq call
(seconds), and a boolean cut plus a re-measure plus a render (tens of
seconds). Each on its own thread, each reporting in its own words.

Every one subclasses workers._Worker -- never QThread directly -- so a
running worker is anchored until it finishes and cannot be collected
mid-run (tests/test_worker_mandate.py, and BUGS.md for what that cost).
The engine is reached through core_bridge only (tests/test_engine_facade.py).
"""
from __future__ import annotations

import os

from PySide6.QtCore import Signal

import core_bridge as CB
from workers import _Worker


class StepMeasureWorker(_Worker):
    """Measure one or more STEP models -- the offline half every action
    starts with. Each model lands in its own folder under `root`, named
    after it, with its Excel sheet and drawing sheet, and every file
    carries the model's name (core.stepfile.names)."""
    progress = Signal(str)
    done = Signal(list)              # [{"path","report","out_dir","drawn","xlsx"}]
    failed = Signal(str)

    def __init__(self, paths: list[str], mode: str, root: str):
        super().__init__()
        self.paths, self.mode, self.root = paths, mode, root

    def run(self):
        try:
            SF = CB.get_stepfile()
            ok, why = SF.available()
            if not ok:
                self.failed.emit(why)
                return
            results = []
            for path in self.paths:
                name = os.path.basename(path)
                self.progress.emit(f"measuring {name} ({self.mode})…")
                report = SF.analyse(path, mode=self.mode)
                out_dir = SF.output_dir(path, self.root)
                names = SF.names(report)
                xlsx = ""
                try:
                    xlsx = SF.write_xlsx(
                        report, os.path.join(out_dir, names["xlsx"]))
                except Exception as e:                  # noqa: BLE001
                    self.progress.emit(f"! Excel sheet not written: {e}")
                self.progress.emit(f"drawing the parts of {name}…")
                drawn = SF.render_sheet(report, out_dir)
                results.append({"path": path, "report": report,
                                "out_dir": out_dir, "drawn": drawn,
                                "xlsx": xlsx})
            self.done.emit(results)
        except Exception as e:
            self.failed.emit(str(e))


class StepAskWorker(_Worker):
    """One Groq call: the measured numbers and the question -- never the
    model -- in, suggestions out."""
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: dict, report: dict, question: str):
        super().__init__()
        self.cfg, self.report, self.question = cfg, report, question

    def run(self):
        try:
            SF = CB.get_stepfile()
            text = CB.router.groq_chat(
                self.cfg.get("api_key", ""),
                self.cfg.get("model", "llama-3.3-70b-versatile"),
                SF.ask_prompt(self.report, self.question),
                temperature=0.4, timeout=60).strip()
            self.done.emit(text)
        except Exception as e:
            self.failed.emit(str(e))


class StepApplyWorker(_Worker):
    """Apply a validated plan to a COPY of the model, re-measure the copy,
    and rewrite the review page with the real After column. The original
    file is never written -- core.stepfile.apply_plan exports a new one."""
    done = Signal(dict)              # {"out", "log", "after", "review"}
    failed = Signal(str)

    def __init__(self, path: str, plan: dict, report: dict, mode: str,
                 out_dir: str, question: str):
        super().__init__()
        self.path, self.plan, self.report = path, plan, report
        self.mode, self.out_dir, self.question = mode, out_dir, question

    def run(self):
        try:
            import shutil
            SF = CB.get_stepfile()
            names = SF.names(self.report)
            out_path = os.path.join(self.out_dir, names["modified"])
            built = SF.apply_plan(self.path, self.plan, out_path)
            after = SF.analyse(out_path, mode=self.mode)
            try:
                SF.write_xlsx(after,
                              os.path.join(self.out_dir, names["xlsx_after"]))
            except Exception:                           # noqa: BLE001
                pass
            try:
                drawn = SF.render_sheet(
                    after, os.path.join(self.out_dir, names["after_dir"]))
                if drawn.get("png"):
                    shutil.copyfile(drawn["png"], os.path.join(
                        self.out_dir, names["png_after"]))
            except Exception:                           # noqa: BLE001
                pass
            review = SF.review_html(self.report, self.plan, self.out_dir,
                                    question=self.question, after=after)
            self.done.emit({"out": out_path, "log": built["log"],
                            "after": after, "review": review})
        except Exception as e:
            self.failed.emit(str(e))
