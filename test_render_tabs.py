import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PRISM_SELFTEST"] = "1"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import main_window

app = QApplication.instance() or QApplication(sys.argv)
import paths
import theme
import i18n
import identity
import core_bridge as CB

theme.load_fonts()
cfg = CB.config.load()
i18n.start(cfg, app)

role_hue = identity.hue()
theme.apply_role(role_hue)
assets = paths.resource("assets").replace(os.sep, "/")
with open("style.qss", "r", encoding="utf-8") as f:
    qss = f.read()
qss = i18n.style_for_script(qss)
qss = theme.role_stylesheet(qss, role_hue)
app.setStyleSheet(qss.replace("%ASSETS%", assets))

win = main_window.MainWindow()
win.resize(1380, 850)
win.show()

out_dir = os.path.join(os.path.dirname(__file__), "ui_verification")
os.makedirs(out_dir, exist_ok=True)

screen_keys = [
    ("home", "home"),
    ("workbench", "workbench_newtask"),
    ("runs", "history_runs"),
    ("artifacts", "artifacts"),
    ("config", "settings_config"),
]

def capture_screens(idx=0):
    if idx < len(screen_keys):
        screen_name, file_label = screen_keys[idx]
        win._show_screen(screen_name)
        app.processEvents()
        win.repaint()
        app.processEvents()
        
        pix = win.grab()
        path = os.path.join(out_dir, f"{file_label}.png")
        pix.save(path, "PNG")
        print(f"Captured {screen_name} -> {path}")
        QTimer.singleShot(150, lambda: capture_screens(idx + 1))
    else:
        # Context rail open on workbench
        win._show_screen("workbench")
        win._set_context_open(True)
        app.processEvents()
        win.repaint()
        app.processEvents()
        pix = win.grab()
        path = os.path.join(out_dir, "workbench_with_context_rail.png")
        pix.save(path, "PNG")
        print(f"Captured workbench_with_context_rail -> {path}")
        app.quit()

QTimer.singleShot(200, capture_screens)
app.exec()
print("All screenshots generated successfully!")
