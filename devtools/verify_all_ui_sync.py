import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath("."))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

app = QApplication.instance() or QApplication(sys.argv)

import theme
theme.load_fonts()

with open("style.qss", "r", encoding="utf-8") as f:
    app.setStyleSheet(f.read())

from addons.boq.panel import BoqPanel
from addons.gerber.panel import GerberPanel
from addons.step.panel import StepPanel
from addons.bom.panel import BomPanel
from addons.inquiry.panel import InquiryPanel
from widgets.input_panel import InputPanel
from widgets.controls import Toast

os.makedirs("ui_audit_verification", exist_ok=True)

results = {}

# 1. Verify Add-on Attach buttons
addon_classes = [
    ("BOQ", BoqPanel),
    ("Gerber", GerberPanel),
    ("STEP", StepPanel),
    ("BOM", BomPanel),
]

for name, cls in addon_classes:
    p = cls()
    p.build()
    p.resize(900, 350)
    p.show()
    app.processEvents()
    
    actions = p.header_actions()
    btn = actions[0] if actions else None
    has_icon = btn is not None and not btn.icon().isNull()
    btn_text = btn.text() if btn else ""
    
    pix = btn.icon().pixmap(QSize(18, 18))
    img = pix.toImage()
    visible_pixels = sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 20)
    
    screenshot_path = f"ui_audit_verification/{name.lower()}_attach_btn.png"
    p.grab().save(screenshot_path)
    
    results[f"{name}_attach"] = {
        "text": btn_text,
        "has_icon": has_icon,
        "visible_pixels": visible_pixels,
        "screenshot": screenshot_path,
        "status": "PASS" if (has_icon and visible_pixels > 0) else "FAIL"
    }
    print(f"[{results[f'{name}_attach']['status']}] {name}: text={btn_text!r}, icon_pixels={visible_pixels}")

# 2. Verify InputPanel "Add file" and "Make a plan"
inp = InputPanel()
inp.resize(900, 320)
inp.show()
app.processEvents()

add_file_btn = inp.attach_file_btn
has_add_file_icon = not add_file_btn.icon().isNull()
pix_file = add_file_btn.icon().pixmap(QSize(18, 18))
img_file = pix_file.toImage()
add_file_pixels = sum(1 for x in range(img_file.width()) for y in range(img_file.height()) if img_file.pixelColor(x, y).alpha() > 20)

plan_btn = inp.route_btn
plan_text = plan_btn.text()
plan_centered = (plan_text == plan_text.strip())

inp_screenshot = "ui_audit_verification/input_panel_workbench.png"
inp.grab().save(inp_screenshot)

results["input_add_file"] = {
    "text": add_file_btn.text(),
    "has_icon": has_add_file_icon,
    "visible_pixels": add_file_pixels,
    "status": "PASS" if (has_add_file_icon and add_file_pixels > 0) else "FAIL"
}
results["input_make_plan"] = {
    "text": plan_text,
    "is_trimmed": plan_centered,
    "status": "PASS" if plan_centered else "FAIL"
}
print(f"[{results['input_add_file']['status']}] InputPanel Add file: icon_pixels={add_file_pixels}")
print(f"[{results['input_make_plan']['status']}] InputPanel Make a plan: text={plan_text!r}")

# 3. Verify Inquiry Panel
inq = InquiryPanel(cfg={})
inq.resize(900, 350)
inq.show()
app.processEvents()
inq_screenshot = "ui_audit_verification/inquiry_panel.png"
inq.grab().save(inq_screenshot)
print(f"[PASS] Inquiry panel captured: {inq_screenshot}")

print("\n--- Summary ---")
for k, v in results.items():
    print(f"  {k}: {v['status']}")
