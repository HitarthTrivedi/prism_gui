import os
import sys
import time
import traceback

sys.path.insert(0, "/home/parth-soni/alphakore/prism+gui/prism_gui")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFontDatabase, QColor
from PySide6.QtWidgets import QApplication

import core_bridge as CB
import identity
import paths
import theme
import i18n

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

cfg = CB.config.load()
try:
    i18n.start(cfg, app)
except Exception as e:
    print("i18n start error:", e)

role_hue = identity.hue()
theme.apply_role(role_hue)

style_path = paths.resource("style.qss")
if os.path.exists(style_path):
    with open(style_path, "r", encoding="utf-8") as f:
        qss = f.read()
    assets = paths.resource("assets").replace(os.sep, "/")
    qss = i18n.style_for_script(qss)
    qss = theme.role_stylesheet(qss, role_hue)
    app.setStyleSheet(qss.replace("%ASSETS%", assets))

out_dir = "/home/parth-soni/.gemini/antigravity/brain/fc15e152-33f1-4ac7-bed1-b556d70079bd/ui_audit_full"
os.makedirs(out_dir, exist_ok=True)

from main_window import MainWindow

win = MainWindow()
win.resize(1280, 800)
win.show()
app.processEvents()

def save_widget(w, filename, delay=0.05):
    try:
        w.show()
        app.processEvents()
        if delay > 0:
            time.sleep(delay)
            app.processEvents()
        pix = w.grab()
        dest = os.path.join(out_dir, filename)
        pix.save(dest)
        print(f"Captured: {filename} ({pix.width()}x{pix.height()}, {os.path.getsize(dest)} bytes)")
    except Exception as e:
        print(f"FAILED {filename}: {e}")
        traceback.print_exc()

# ── 1. MAIN SCREENS & ADDONS ───────────────────────────
screens_to_test = [
    ("home", "screen_01_home.png"),
    ("workbench", "screen_02_workbench_compose.png"),
    ("runs", "screen_03_history.png"),
    ("catalog", "screen_04_ai_tools_catalog.png"),
    ("guide", "screen_05_guide.png"),
    ("support", "screen_06_support.png"),
    ("artifacts", "screen_07_artifacts.png"),
    ("config", "screen_08_settings_overview.png"),
    # Addon screens
    ("gerber", "addon_01_gerber.png"),
    ("boq", "addon_02_boq.png"),
    ("step", "addon_03_step.png"),
    ("bom", "addon_04_bom.png"),
    ("email", "addon_05_email.png"),
    ("inquiry", "addon_06_inquiry.png"),
    ("leads", "addon_07_leads.png"),
]

for sname, fname in screens_to_test:
    win._show_screen(sname)
    app.processEvents()
    save_widget(win, fname)

# ── 1b. WORKBENCH IN RUNNING/PLAN STATE ────────────────
win._show_screen("workbench")
dummy_routing = {
    "research": {"needed": True, "questions": ["Research competitor components and thermal limits"]},
    "brains": {"needed": True, "questions": ["Analyze feasibility and synthesize design recommendations"]},
    "content": {"needed": True, "questions": ["Draft comprehensive engineering and executive report"]},
}
try:
    win.agents_panel.set_content(dummy_routing, cfg.get("agents", {}), "High-efficiency Power Converter Design")
    win.work_stack.setCurrentIndex(1) # RUNNING
    app.processEvents()
    save_widget(win, "screen_02b_workbench_plan.png")
except Exception as e:
    print("Error setting plan:", e)

# ── 2. SETTINGS PANEL SUBSECTIONS ──────────────────────
win._show_screen("config")
app.processEvents()
if hasattr(win, "settings_panel"):
    sp = win.settings_panel
    sections = [
        "licence", "profile", "agents", "language", 
        "status", "appearance", "privacy", "more"
    ]
    for sec in sections:
        try:
            sp.show_section(sec)
            app.processEvents()
            save_widget(win, f"settings_sec_{sec}.png")
        except Exception as e:
            print(f"Error showing settings section {sec}:", e)

# ── 3. ADDON DIALOGS ────────────────────────────────────
dialog_specs = [
    ("addons.gerber.dialog", "GerberDialog", "dialog_gerber.png", (cfg, [], win)),
    ("addons.boq.dialog", "BoqDialog", "dialog_boq.png", (cfg, [], win)),
    ("addons.step.dialog", "StepDialog", "dialog_step.png", (cfg, [], win)),
    ("addons.email.dialog", "EmailSetupDialog", "dialog_email_setup.png", (cfg, win)),
    ("addons.email.dialog", "EmailComposeDialog", "dialog_email_compose.png", (cfg, [], win)),
    ("addons.inquiry.dialog", "InquiryDialog", "dialog_inquiry.png", (cfg, win)),
    ("addons.leads.dialog", "LeadsDialog", "dialog_leads.png", (cfg, win)),
    ("addons.motion.dialog", "MotionDialog", "dialog_motion.png", (cfg, [], win)),
    ("addons.reel.dialog", "ReelDialog", "dialog_reel.png", (cfg, [], win)),
]

for mod_name, cls_name, fname, args in dialog_specs:
    try:
        mod = __import__(mod_name, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        dlg = cls(*args)
        dlg.resize(900, 700)
        save_widget(dlg, fname)
        try:
            dlg.close()
        except Exception:
            pass
    except Exception as e:
        print(f"Error launching {cls_name}: {e}")

# ── 4. FEATURE DIALOGS ──────────────────────────────────
feature_dialogs = [
    ("dialogs.history_dialog", "HistoryDialog", "dialog_history.png", (win,)),
    ("dialogs.license_dialog", "LicenseDialog", "dialog_license.png", (win, "activate")),
    ("dialogs.contact_dialog", "ContactDialog", "dialog_contact.png", ("", win)),
    ("dialogs.legal_dialog", "LegalDialog", "dialog_legal.png", ("Terms of Service", "terms.txt", win)),
    ("dialogs.completion_dialog", "CompletionDialog", "dialog_completion.png", (
        [{"stage": "research", "agent": "Perplexity", "text": "Market research completed.", "url": ""}],
        win
    )),
]

for mod_name, cls_name, fname, args in feature_dialogs:
    try:
        mod = __import__(mod_name, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        dlg = cls(*args)
        dlg.resize(800, 600)
        save_widget(dlg, fname)
        try:
            dlg.close()
        except Exception:
            pass
    except Exception as e:
        print(f"Error launching feature dialog {cls_name}: {e}")

print("FULL DEEP AUDIT CAPTURE COMPLETE!")
