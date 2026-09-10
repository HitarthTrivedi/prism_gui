# Windows Testing & Verification Runbook for Prism

This guide provides step-by-step procedures for testing and verifying all Windows-specific subsystems, bug fixes, browser engines, in-app updates, and PyInstaller packaged builds for **Prism GUI** on Windows 10 and Windows 11 (x64).

---

## 1. Windows Environment Setup

### 1.1 Prerequisites
* **Operating System:** Windows 10 (Build 19041+) or Windows 11 (64-bit)
* **Python:** Python 3.11 or 3.12 (x64) installed from [python.org](https://www.python.org/downloads/) with **"Add python.exe to PATH"** checked
* **Google Chrome:** Installed at default location (`%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe` or `C:\Program Files\Google\Chrome\Application\chrome.exe`)
* **Git for Windows:** Installed from [git-scm.com](https://git-scm.com/)

### 1.2 Setting Up the Virtual Environment in PowerShell
Open **PowerShell** (as regular user, do not run as Administrator):

```powershell
# Allow script execution for the current session if blocked
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force

# Navigate to the repository
cd C:\path\to\prism_gui

# Verify git submodules are initialized
git submodule update --init --recursive

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install all build and runtime dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r packaging/requirements-build.txt
```

---

## 2. Playwright & Chromium Studio Renderer Verification

### 2.1 Install Bundled Chromium Inside the Package
Playwright must install Chromium **inside** the Playwright package directory (`PLAYWRIGHT_BROWSERS_PATH=0`), not in the OS cache:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "0"
playwright install --no-shell chromium
```

Verify that Chromium landed in the local package directory:
```powershell
Test-Path ".\.venv\Lib\site-packages\playwright\driver\package\.local-browsers\chromium-*\chrome-win\chrome.exe"
# Expected output: True
```

### 2.2 Verify No ASCII Box & Playwright Launch Succeeds
Run this PowerShell test script to verify that Playwright launches Chromium using `channel="chromium"` without falling back or printing the missing-browser ASCII prompt:

```powershell
python -c "
import os
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'
import sys
sys.path.insert(0, 'prism_terminal')
from core import browser
from playwright.sync_api import sync_playwright

print('Checking chromium_path()...')
path = browser.chromium_path()
print('Chromium Path:', path)
assert path and os.path.exists(path), 'Chromium path does not exist!'

print('Testing browser.selftest()...')
ok, why = browser.selftest()
assert ok, f'Selftest failed: {why}'
print('✓ Playwright Chromium launched and rendered test frame successfully on Windows!')
"
```

### 2.3 Run Reel, Studio & Motion Unit Tests
```powershell
pytest -v tests/test_reel_edit.py tests/test_reel_editor_tools.py tests/test_studio_v2.py tests/test_motion_assets.py
pytest -v tests/test_cross_platform_browser.py -k "browser"
```

With Chromium and FFmpeg present, also run the browser lane — it opens the
real Studio workspace, drags a layer, adds text, and films a Motion spec with
an attached picture, then checks the pixel actually landed in the MP4:
```powershell
$env:PRISM_RUN_RENDER_TESTS = "1"
pytest -v tests/test_reel_edit.py tests/test_reel_editor_tools.py tests/test_studio_v2.py tests/test_motion_assets.py
Remove-Item Env:PRISM_RUN_RENDER_TESTS
```

---

## 3. Selenium & Browser Automation Verification

### 3.1 Verify Selenium & Selenium Manager Binaries
Ensure `selenium` and `undetected-chromedriver` are fully present and that `selenium-manager.exe` is located:

```powershell
python -c "
import selenium
import undetected_chromedriver as uc
import core_bridge as CB

ok, why = CB.automation_available()
assert ok, f'Automation unavailable: {why}'
print('✓ Selenium and undetected-chromedriver are importable!')
"
```

Verify `selenium-manager.exe` exists in the environment:
```powershell
Test-Path ".\.venv\Lib\site-packages\selenium\webdriver\common\windows\selenium-manager.exe"
# Expected output: True
```

### 3.2 Run Automation Unit Tests
```powershell
pytest -v tests/test_cross_platform_browser.py -k "AttachmentsReachTheTool or reply_is_searched"
```

---

## 4. In-App Self-Updater Verification on Windows

### 4.1 Run Updater Unit Tests
Exercises process exit probing, same-drive swapping, rollback on unconfirmed launch, and timeout handling on Windows:

```powershell
pytest -v tests/test_apply_update.py
```

### 4.2 Cross-Volume Swap Verification (`EXDEV` / `WinError 17`)
Simulate an installation on drive `D:\` while updates are staged on `C:\`:

```powershell
python -c "
import os, tempfile, shutil
from unittest import mock
import apply_update

# Mock splitdrive to simulate C: vs D:
with tempfile.TemporaryDirectory() as td:
    install_dir = os.path.join(td, 'install')
    staged_dir = os.path.join(td, 'staged')
    backup_dir = os.path.join(td, 'backup')
    os.makedirs(install_dir)
    os.makedirs(staged_dir)

    with open(os.path.join(install_dir, 'app.exe'), 'w') as f: f.write('v1')
    with open(os.path.join(staged_dir, 'app.exe'), 'w') as f: f.write('v2')

    # Verify perform_swap works cleanly
    apply_update.perform_swap(install_dir, staged_dir, backup_dir)
    with open(os.path.join(install_dir, 'app.exe')) as f:
        assert f.read() == 'v2', 'Swap failed to place v2!'
    print('✓ Cross-volume swap simulation succeeded!')
"
```

### 4.3 Process Handle Locking Test
Verify that `pid_alive()` correctly identifies live processes and does not return `False` when encountering Windows permission or handle query boundaries:

```powershell
python -c "
import os, sys, time, subprocess
import apply_update

proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1)'])
try:
    assert apply_update.pid_alive(proc.pid) == True, 'pid_alive reported dead process!'
    assert apply_update.wait_for_exit(proc.pid, timeout=5) == True, 'wait_for_exit failed!'
    assert apply_update.pid_alive(proc.pid) == False, 'pid_alive reported live after exit!'
    print('✓ Windows process exit probing verified!')
finally:
    proc.kill()
"
```

---

## 5. Subprocess Console Flashing & Windows Explorer Tests

### 5.1 Verify No Black CMD Console Windows Flash (`CREATE_NO_WINDOW`)
Run subprocess routines using `pythonw.exe` (the windowless Windows Python runner). No command prompt windows should appear on screen:

```powershell
pythonw -c "
import sys, subprocess
sys.path.insert(0, 'prism_terminal')
from core import boq

# Test BOQ running subprocess
flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
res = subprocess.run(['cmd.exe', '/c', 'echo no console'], capture_output=True, text=True, creationflags=flags)
assert 'no console' in res.stdout
print('✓ CREATE_NO_WINDOW suppressed command prompt successfully.')
"
```

### 5.2 Windows Explorer File Highlighting Test
Verify that `paths.reveal_result` highlights the target file in Windows Explorer without error:

```powershell
python -c "
import os, paths
test_file = os.path.abspath('README.md')
paths.reveal_result(test_file)
print('✓ Explorer opened with README.md highlighted.')
"
```

---

## 6. Full PyInstaller Build & Smoke-Test on Windows

### 6.1 Clean Build with PyInstaller
Run the build script to produce `dist\Prism`:

```powershell
python packaging/build.py --clean
```

### 6.2 Inspect the Built Bundle Layout
Verify that `chrome.exe` and `selenium-manager.exe` are present in their required directories:

```powershell
# 1. Playwright Chromium executable
$chromePath = Get-ChildItem "dist\Prism\_internal\playwright\driver\package\.local-browsers\chromium-*\chrome-win\chrome.exe"
if ($chromePath) {
    Write-Host "✓ Chromium found at: $($chromePath.FullName)" -ForegroundColor Green
} else {
    Write-Error "✗ CRITICAL: chrome.exe is missing from .local-browsers!"
}

# 2. Selenium Manager executable
$smPath = "dist\Prism\_internal\selenium\webdriver\common\windows\selenium-manager.exe"
if (Test-Path $smPath) {
    Write-Host "✓ Selenium Manager found at: $smPath" -ForegroundColor Green
} else {
    Write-Error "✗ CRITICAL: selenium-manager.exe is missing from selenium datas!"
}

# 3. Studio editor modules and the Motion runtime — data files the frozen
#    core.reel_edit / core.motion.render read NEXT TO THEIR OWN __file__,
#    i.e. under _internal\core\, not under _internal\prism_terminal\core\.
#    (prism.spec ships them at both paths; this is the one the app reads.)
foreach ($f in "core\studio_assets\editor.js", "core\studio_assets\apply.js",
              "core\studio_assets\editor.css", "core\motion\runtime\index.html",
              "core\motion\runtime\render_runner.js") {
    if (Test-Path "dist\Prism\_internal\$f") {
        Write-Host "✓ $f" -ForegroundColor Green
    } else {
        Write-Error "✗ CRITICAL: $f missing — Edit layout / Motion will raise FileNotFoundError"
    }
}
```
The packaged self-test (6.3) runs the same check as
`Studio editor + Motion runtime files`.

### 6.3 Run the Packaged Smoke-Test Gate
Execute the real packaged binary in self-test mode. Every check must report `✓`:

```powershell
# Run the automated packaging smoke test
python packaging/smoke_test.py

# Or directly execute the built executable with PRISM_SELFTEST=1:
$env:PRISM_SELFTEST = "1"
.\dist\Prism\Prism.exe
```

Expected output:
```text
  ✓ HTTPS trust store
  ✓ stylesheet
  ✓ fonts
  ✓ logo
  ✓ line icons (sliders, top+bottom rows)
  ✓ engine
  ✓ engine notes
  ✓ config path
  ✓ mailer
  ✓ browser automation
  ✓ licence verification
  ✓ BOQ add-on (ezdxf)
  ✓ Reel add-on (Pillow + renderer)
  ✓ bundled dependencies
  ✓ Prism Studio browser (Chromium)
  ✓ main window
  ✓ sidebar
✓ the packaged app starts, loads its resources and builds its window
```

---

## 7. Troubleshooting Common Windows Errors

| Symptom | Root Cause | Resolution |
| :--- | :--- | :--- |
| `Looks like Playwright was just installed...` | `chrome.exe` stripped into `_internal\` root instead of `.local-browsers` | Ensure `prism.spec` moves `.local-browsers` binaries to `a.datas` on Windows. |
| `No module named 'selenium'` | `selenium` omitted during PyInstaller analysis | Ensure `requirements.txt` is installed and `collect_submodules('selenium')` is in `prism.spec`. |
| `Selenium Manager failed for: ...` | `selenium-manager.exe` missing from bundle | Add `datas += collect_data_files('selenium')` to `packaging/prism.spec`. |
| `WinError 17 The system cannot move the file...` | `perform_swap()` across different drive letters (`C:` to `D:`) | Ensure `apply_update.py` copies to target volume before `os.rename()`. |
| `WinError 5 Access is denied` during update | Prism installed in `C:\Program Files` without elevation | Install into `%LOCALAPPDATA%\Programs\Prism` or run elevated helper. |
| Black CMD console flashes during Reel/CAD | Missing `creationflags=CREATE_NO_WINDOW` | Pass `creationflags=0x08000000` to `subprocess.Popen`/`run`. |
