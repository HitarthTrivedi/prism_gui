"""The Windows failures — the browser, the uploads, the downloads.

Every test here is a bug a customer hit on Windows and nobody hit while
developing on Linux or macOS. They are grouped by the thing that broke:

  1. Prism Studio's renderer asked Playwright for a browser the build
     deliberately did not ship (chrome-headless-shell), and reported itself
     "available" right up to the moment it failed.
  2. Files produced by an agent — a .docx, a deck — were never fetched,
     because the test for "is this link a file" was true for every link on
     the page and the four junk links ahead of the real one used up the cap.
  3. Attachments silently failed to reach a tool when one of them had gone
     from the temp directory, and the one-at-a-time fallback only ever tried
     the first file input on the page.

None of them needs a browser, a network or a display: each one fakes the
Selenium/Playwright object at exactly the boundary the bug lived on.
"""
from __future__ import annotations

import base64
import inspect
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402

automation = CB.get_automation()
from core import browser  # noqa: E402

# The BOQ screen's guidance is checked by building the real dialog, and Qt
# aborts the process outright if a QWidget is constructed with no
# QApplication — same bootstrap every other dialog test module uses.
_app = QApplication.instance() or QApplication([])


# ── 1. the browser Studio actually launches ──────────────────────────────────

class _FakeChromium:
    """Playwright's BrowserType, as far as launch_chromium can tell.

    `has_shell` is the whole point: a packaged Prism has Chromium and NOT
    chrome-headless-shell, and a bare launch() asks for the shell.
    """

    def __init__(self, has_shell: bool):
        self.has_shell = has_shell
        self.calls: list[dict] = []

    def launch(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("channel") == "chromium":
            return "full-chromium"
        if not self.has_shell:
            raise RuntimeError(
                "BrowserType.launch: Executable doesn't exist at "
                r"C:\Prism\_internal\playwright\driver\package\.local-browsers"
                r"\chromium_headless_shell-1234\chrome-headless-shell-win64"
                r"\chrome-headless-shell.exe")
        return "headless-shell"


class _FakePlaywright:
    def __init__(self, has_shell: bool):
        self.chromium = _FakeChromium(has_shell)


class StudioLaunchesTheBrowserThatShips(unittest.TestCase):
    """The reported failure, in one sentence: `Render failed: Executable
    doesn't exist at …chrome-headless-shell.exe`."""

    def test_a_bundle_without_the_shell_still_renders(self):
        pw = _FakePlaywright(has_shell=False)
        self.assertEqual(browser.launch_chromium(pw, args=["--x"]),
                         "full-chromium")

    def test_it_asks_for_the_full_build_by_name(self):
        pw = _FakePlaywright(has_shell=True)
        browser.launch_chromium(pw)
        self.assertEqual(pw.chromium.calls[0].get("channel"), "chromium",
                         "without channel='chromium' a headless launch "
                         "resolves to chrome-headless-shell, which "
                         "packaging/prism.spec trims out of the bundle")

    def test_arguments_are_still_passed_through(self):
        pw = _FakePlaywright(has_shell=False)
        browser.launch_chromium(pw, args=["--hide-scrollbars"])
        self.assertEqual(pw.chromium.calls[0]["args"], ["--hide-scrollbars"])

    def test_it_falls_back_when_the_channel_is_refused(self):
        """A machine with ONLY the shell (playwright install --only-shell, or
        a Playwright too old for the channel option) must still render."""
        pw = _FakePlaywright(has_shell=True)

        def only_shell(**kwargs):
            pw.chromium.calls.append(kwargs)
            if kwargs.get("channel"):
                raise RuntimeError("Unsupported channel 'chromium'")
            return "headless-shell"

        pw.chromium.launch = only_shell
        self.assertEqual(browser.launch_chromium(pw), "headless-shell")


class AvailabilityMeansTheBinaryIsThere(unittest.TestCase):
    """`available()` used to check that `import playwright` worked. A
    packaged build has the Python package whether or not it has a browser, so
    it always said yes — and the render failed halfway through instead."""

    def setUp(self):
        self._cached = browser._cached_path
        self.addCleanup(setattr, browser, "_cached_path", self._cached)

    def test_no_binary_is_not_available(self):
        browser._cached_path = None
        ok, why = browser.available()
        self.assertFalse(ok)
        self.assertIn("playwright install chromium", why)

    def test_a_binary_is_available(self):
        browser._cached_path = "/somewhere/chrome"
        self.assertEqual(browser.available(), (True, ""))

    def test_the_build_gate_starts_the_browser_rather_than_stat_ing_it(self):
        """The shipped bug was a launch resolving to a binary the bundle did
        not carry — while Chromium itself sat right there. A file-exists
        check on Chromium would have passed on the broken build, which is
        exactly why the packaging gate does the whole round trip."""
        source = inspect.getsource(browser.selftest)
        self.assertIn("launch_chromium", source)
        self.assertIn("screenshot", source)

    def test_a_browser_that_will_not_start_is_reported_not_raised(self):
        """It runs inside packaging/smoke_test.py, where an exception is a
        traceback instead of a named failure."""
        with mock.patch.object(browser, "launch_chromium",
                               side_effect=RuntimeError(
                                   "BrowserType.launch: Executable doesn't "
                                   "exist at …chrome-headless-shell.exe")):
            ok, why = browser.selftest()
        self.assertFalse(ok)
        self.assertIn("Executable doesn't exist", why)

    def test_studio_reports_the_same_answer(self):
        """core.reel_web.available() must not have its own opinion — it is
        the one the GUI asks before offering the button."""
        from core import reel_web
        browser._cached_path = None
        ok, why = reel_web.available()
        if "ffmpeg" not in why.lower():      # FFmpeg is checked first
            self.assertFalse(ok)
            self.assertIn("playwright install chromium", why)


# ── 2. what comes back from an agent ─────────────────────────────────────────

class _FakeAnchor:
    """A Selenium WebElement for an <a>, with the one behaviour that mattered.

    `get_attribute("download")` returns the DOM *property*, which is "" on
    every anchor whether or not it has the attribute. `get_dom_attribute`
    reads the attribute itself and returns None when it is absent. Both
    verified against a real Chrome before this test was written.
    """

    def __init__(self, href: str, download=None):
        self.href = href
        self._download = download

    def get_attribute(self, name):
        if name == "href":
            return self.href
        if name == "download":
            return self._download if self._download is not None else ""
        return None

    def get_dom_attribute(self, name):
        return self._download


class _FakeDriver:
    def __init__(self, anchors, scoped=None):
        self.anchors = anchors
        self.scoped = scoped        # what the SCOPED query returns, if given
        self.queries: list[str] = []
        self.fetched: list[str] = []

    def find_elements(self, by, selector):
        self.queries.append(selector)
        if self.scoped is not None and selector != "a[href]":
            return list(self.scoped)
        return list(self.anchors) if selector.strip().endswith("a[href]") else []

    def set_script_timeout(self, seconds):
        pass

    def execute_script(self, script, *args):
        return []

    def execute_async_script(self, script, href):
        self.fetched.append(href)
        if href.endswith(".docx"):
            return ("data:application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document;base64,"
                    + base64.b64encode(b"PK\x03\x04 not really a docx").decode())
        # Every ordinary link answers too — fetching a nav link returns the
        # page's own HTML, which is exactly why the junk got saved.
        return "data:text/html;base64," + base64.b64encode(b"<html></html>").decode()


class TheDeliverableIsWhatComesBack(unittest.TestCase):

    def _page(self):
        # DOM order matters: five ordinary links ahead of the real file is
        # what pushed the .docx past the harvester's cap of four.
        return _FakeDriver([
            _FakeAnchor("https://claude.ai/chats"),
            _FakeAnchor("https://claude.ai/settings"),
            _FakeAnchor("https://claude.ai/help"),
            _FakeAnchor("https://support.anthropic.com"),
            _FakeAnchor("https://claude.ai/new"),
            _FakeAnchor("https://files.claude.ai/x/quotation.docx"),
        ])

    def test_a_link_without_a_download_attribute_is_not_a_file(self):
        self.assertIsNone(automation._download_attr(_FakeAnchor("/chats")))

    def test_an_explicit_download_attribute_survives(self):
        self.assertEqual(
            automation._download_attr(_FakeAnchor("/dl", "report.docx")),
            "report.docx")

    def test_a_bare_download_attribute_is_kept_as_present(self):
        """`<a href="/api/file/9" download>` IS a deliverable — it just has
        no filename to take an extension from. It must not read as absent."""
        self.assertEqual(automation._download_attr(_FakeAnchor("/f", "")), "")

    def test_the_docx_is_the_thing_that_is_fetched(self):
        driver = self._page()
        out = automation._harvest_files(driver, {}, "content")
        self.assertEqual(driver.fetched,
                         ["https://files.claude.ai/x/quotation.docx"],
                         "nav links must not be fetched at all — fetching "
                         "them is what used up the cap of four before the "
                         "real file was reached")
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["name"].endswith(".docx"))
        self.assertTrue(out[0]["_generated"])

    def test_the_reply_is_searched_branch_by_branch(self):
        """A response_selector is a LIST of alternatives, and `f"{sel} img"`
        scopes only the LAST one — the rest come back as the message DIVs
        themselves. Verified against a real Chrome: ChatGPT's selector with
        " img" appended matches a <div>, and with this fix matches the
        <img>."""
        chatgpt = ("[data-message-author-role='assistant'], "
                   "[data-message-role='assistant'], .markdown.prose")
        scoped = automation._within(chatgpt, "img")
        self.assertEqual(
            scoped,
            "[data-message-author-role='assistant'] img, "
            "[data-message-role='assistant'] img, "
            ".markdown.prose img")

    def test_a_comma_inside_brackets_does_not_split_the_selector(self):
        self.assertEqual(automation._within("[data-x='a,b'], :is(.p, .q)", "img"),
                         "[data-x='a,b'] img, :is(.p, .q) img")

    def test_a_single_selector_is_unchanged_in_meaning(self):
        self.assertEqual(automation._within(".prose", "a[href]"), ".prose a[href]")

    def test_a_message_container_is_not_mistaken_for_a_deliverable(self):
        """What the unscoped selector actually returned: the reply DIV. It
        has no href, so nothing was harvested — and because the query DID
        match something, the whole-page fallback never ran either."""
        container = _FakeAnchor("")          # a div: href reads back empty
        driver = _FakeDriver(anchors=[], scoped=[container])
        self.assertEqual(automation._harvest_files(driver, {}, "content"), [])

    def test_a_blob_download_button_still_counts(self):
        driver = _FakeDriver([_FakeAnchor("blob:https://chatgpt.com/abc",
                                          "analysis.docx")])
        out = automation._harvest_files(driver, {}, "content")
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["name"].endswith(".docx"))


# ── 3. attachments going the other way ───────────────────────────────────────

class _FakeFileInput:
    def __init__(self, accepts: bool):
        self.accepts = accepts
        self.received: list[str] = []
        self.sends = 0

    def send_keys(self, text):
        self.sends += 1
        if not self.accepts:
            raise RuntimeError("element not interactable")
        for path in text.split("\n"):
            if not os.path.isfile(path):
                # ChromeDriver's own behaviour, and the reason one stale path
                # took the whole batch down.
                raise RuntimeError(f"invalid argument: File not found : {path}")
            self.received.append(path)


class _UploadDriver:
    """A page whose composer takes `appears_after` looks to render.

    Real tools do: run() navigates and sleeps four seconds, and chatgpt.com
    on a cold profile is not finished in four seconds.
    """

    def __init__(self, inputs, appears_after: int = 0):
        self.inputs = inputs
        self.appears_after = appears_after
        self.looks = 0

    def find_elements(self, by, selector):
        self.looks += 1
        return [] if self.looks <= self.appears_after else list(self.inputs)

    def find_element(self, by, selector):
        from selenium.common.exceptions import NoSuchElementException
        found = self.find_elements(by, selector)
        if not found:
            raise NoSuchElementException(selector)
        return found[0]

    def execute_script(self, script, *args):
        return False        # nothing on the page is still busy


class AttachmentsReachTheTool(unittest.TestCase):

    def setUp(self):
        folder = tempfile.mkdtemp(prefix="prism-upload-")
        self.real = os.path.join(folder, "drawing.pdf")
        with open(self.real, "wb") as f:
            f.write(b"%PDF-1.4\n")
        self.gone = os.path.join(folder, "harvested_from_stage_one.png")
        # _upload_files waits out the tool's ingest (15s at minimum) before
        # returning. That wait is real behaviour and worth keeping; sitting
        # through it three times is not.
        patch = mock.patch.object(automation.time, "sleep")
        patch.start()
        self.addCleanup(patch.stop)

    def _attachments(self, *paths):
        return [{"path": p, "name": os.path.basename(p), "size": 9}
                for p in paths]

    def test_one_missing_file_does_not_lose_the_others(self):
        inp = _FakeFileInput(accepts=True)
        driver = _UploadDriver([inp])
        sent = automation._upload_files(
            driver, {}, self._attachments(self.gone, self.real), "ChatGPT")
        self.assertEqual(sent, 1)
        self.assertEqual(inp.received, [self.real])
        # One send, not a failed batch followed by a per-file retry: the
        # stale path is dropped BEFORE the send. It matters beyond tidiness
        # — the retry re-finds the input each time, and a composer that
        # replaces its <input type=file> between sends loses the file.
        self.assertEqual(inp.sends, 1)

    def test_the_fallback_tries_every_file_input_not_just_the_first(self):
        """Pages keep more than one <input type=file> around, and the one
        that works is not reliably the first in the DOM."""
        refuses, accepts = _FakeFileInput(False), _FakeFileInput(True)
        driver = _UploadDriver([refuses, accepts])
        sent = automation._upload_files(
            driver, {}, self._attachments(self.real), "Claude")
        self.assertEqual(sent, 1)
        self.assertEqual(accepts.received, [self.real])

    def test_a_composer_that_renders_late_still_gets_the_files(self):
        """The upload path used to look for the file input exactly once, four
        seconds after navigating, and report "this tool has no file-upload
        field" if it wasn't there yet — while the typing path, on the same
        page at the same moment, waited up to 30s for its textarea and found
        it. The customer's drawing simply never went up."""
        inp = _FakeFileInput(accepts=True)
        driver = _UploadDriver([inp], appears_after=2)
        sent = automation._upload_files(
            driver, {}, self._attachments(self.real), "ChatGPT")
        self.assertEqual(sent, 1)
        self.assertEqual(inp.received, [self.real])

    def test_nothing_to_send_is_not_reported_as_sent(self):
        inp = _FakeFileInput(accepts=True)
        driver = _UploadDriver([inp])
        sent = automation._upload_files(
            driver, {}, self._attachments(self.gone), "Gemini")
        self.assertEqual(sent, 0)
        self.assertEqual(inp.received, [])


# ── 4. the profile only one browser can hold ─────────────────────────────────

class OnlyPrismsOwnChromeIsClosed(unittest.TestCase):
    """Chrome allows one browser per user-data-dir; a second launch on the
    same folder hands over to the first and exits, and chromedriver then
    reports `cannot connect to chrome at 127.0.0.1:<port>`. Clearing the
    leftover browser is the fix — and it is a kill, so what it matches has
    to be exactly right."""

    PROFILE = "/home/om/.prism/chrome_profile"

    def setUp(self):
        self.marker = "--user-data-dir=" + self.PROFILE

    def test_prisms_own_browser_is_matched(self):
        ps = (f" 4021 /usr/bin/google-chrome {self.marker} "
              "--profile-directory=Default --remote-debugging-port=53695\n")
        self.assertEqual(automation._posix_chrome_pids(ps, self.marker), ["4021"])

    def test_the_users_everyday_chrome_is_left_alone(self):
        ps = (" 3300 /usr/bin/google-chrome --user-data-dir=/home/om/.config/"
              "google-chrome --profile-directory=Default\n")
        self.assertEqual(automation._posix_chrome_pids(ps, self.marker), [])

    def test_a_process_that_merely_mentions_the_path_is_not_chrome(self):
        """`ps` reports whole command lines, so a shell running a script that
        names the profile matched the first version of this — which killed
        the shell that was testing it."""
        ps = (f" 5150 /bin/bash -c echo {self.marker} >> notes.txt\n"
              f" 5151 python3 /home/om/tools/inspect.py {self.marker}\n")
        self.assertEqual(automation._posix_chrome_pids(ps, self.marker), [])

    def test_being_unable_to_look_is_not_the_same_as_finding_nothing(self):
        """On Windows this shells out to PowerShell. If that fails —
        execution policy, WMI off, no powershell.exe — returning [] would
        read as "the profile is free", _release_profile would do nothing,
        and the customer would get "cannot connect to chrome" back with no
        clue why. The one platform the guard exists for is the one where the
        probe is most likely to fail."""
        with mock.patch.object(automation.subprocess, "check_output",
                               side_effect=OSError("powershell not found")):
            self.assertIsNone(automation._chrome_pids_using_profile())

    def test_a_probe_that_could_not_run_says_so(self):
        said = []
        with mock.patch.object(automation, "_chrome_pids_using_profile",
                               return_value=None), \
             mock.patch.object(automation.ui, "warn", said.append):
            self.assertEqual(automation._release_profile(), 0)
        self.assertTrue(any("leftover Chrome" in s for s in said))

    def test_finding_nothing_is_silent(self):
        said = []
        with mock.patch.object(automation, "_chrome_pids_using_profile",
                               return_value=[]), \
             mock.patch.object(automation.ui, "warn", said.append):
            self.assertEqual(automation._release_profile(), 0)
        self.assertEqual(said, [])

    def test_the_windows_probe_carries_no_quote_for_windows_to_mangle(self):
        """Python builds a Windows command line with list2cmdline, which
        escapes an embedded " as \\" — and powershell's -Command does not
        unescape it the way a C program's argv would, so the script arrives
        as a parse error. A `-Filter "Name='chrome.exe'"` would have failed
        the whole probe on the only platform that runs it."""
        source = inspect.getsource(automation._chrome_pids_using_profile)
        script = source.split("Get-CimInstance", 1)[1].split("]", 1)[0]
        self.assertNotIn('\\"', script)
        self.assertIn("-eq 'chrome.exe'", script)

    def test_chrome_helper_processes_count_too(self):
        ps = (f" 4021 /opt/chrome/chrome {self.marker}\n"
              f" 4044 /opt/chrome/chrome --type=renderer {self.marker}\n")
        self.assertEqual(automation._posix_chrome_pids(ps, self.marker),
                         ["4021", "4044"])


# ── 5. finding Chrome at all ─────────────────────────────────────────────────

class ChromeIsFoundWhereWindowsActuallyPutsIt(unittest.TestCase):
    """Chrome's installer defaults to a per-user install without admin
    rights, which lands in %LOCALAPPDATA% and not in Program Files. Runs
    worked anyway (undetected-chromedriver has its own finder that checks
    there); Login tabs did not, and told the customer their sign-ins would
    not carry into Prism. Reported as "the agents don't open"."""

    WINDOWS_ENV = {
        "PROGRAMFILES": r"C:\Program Files",
        "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
        "PROGRAMW6432": r"C:\Program Files",
        "LOCALAPPDATA": r"C:\Users\OM\AppData\Local",
    }

    def _windows_candidates(self):
        with mock.patch.object(automation.platform, "system",
                               return_value="Windows"), \
             mock.patch.dict(os.environ, self.WINDOWS_ENV, clear=False):
            return [c.replace("/", "\\")
                    for c in automation._chrome_binaries()]

    def test_a_per_user_install_is_a_candidate(self):
        self.assertIn(
            r"C:\Users\OM\AppData\Local\Google\Chrome\Application\chrome.exe",
            self._windows_candidates())

    def test_the_program_files_installs_are_still_candidates(self):
        found = self._windows_candidates()
        self.assertIn(r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      found)
        self.assertIn(
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            found)

    def test_the_same_path_twice_is_listed_once(self):
        """PROGRAMFILES and PROGRAMW6432 are the same folder on a 64-bit
        process, and every caller loops over this list doing real work."""
        found = self._windows_candidates()
        self.assertEqual(len(found), len(set(found)))

    def test_windows_paths_are_not_offered_on_other_platforms(self):
        with mock.patch.object(automation.platform, "system",
                               return_value="Linux"):
            self.assertTrue(all(c.startswith("/")
                                for c in automation._chrome_binaries()))


# ── 6. the helper programs Prism does not ship ───────────────────────────────

class TheDwgConverterIsFoundWhereItInstalls(unittest.TestCase):
    """PATH was the entire search, and PATH is the one place neither
    converter puts itself: ODA File Converter's Windows installer adds
    nothing to it, and Homebrew's /opt/homebrew/bin is absent from the
    environment a Finder-launched .app inherits. Both mean "installed, and
    Prism says it isn't"."""

    def setUp(self):
        self.boq = CB.get_boq()
        self.root = tempfile.mkdtemp(prefix="prism-oda-")

    def _oda(self, version: str) -> str:
        """A Windows ODA install, versioned folder and all."""
        folder = os.path.join(self.root, "Program Files", "ODA",
                              f"ODAFileConverter {version}")
        os.makedirs(folder, exist_ok=True)
        exe = os.path.join(folder, "ODAFileConverter.exe")
        with open(exe, "w") as f:
            f.write("")
        os.chmod(exe, 0o755)
        return exe

    def _windows_candidates(self):
        with mock.patch.object(self.boq.platform, "system",
                               return_value="Windows"), \
             mock.patch.dict(os.environ,
                             {"PROGRAMFILES": os.path.join(self.root,
                                                           "Program Files")},
                             clear=False):
            return self.boq._installed_converter_paths()

    def test_a_versioned_windows_install_is_found(self):
        exe = self._oda("25.4.0")
        self.assertIn(exe, self._windows_candidates())

    def test_the_newest_version_is_offered_first(self):
        self._oda("25.4.0")
        newest = self._oda("26.2.0")
        found = [c for c in self._windows_candidates() if os.path.isfile(c)]
        self.assertEqual(found[0], newest)

    def test_homebrews_bin_is_searched_on_a_mac(self):
        """It is on PATH in Terminal and not in a double-clicked app."""
        with mock.patch.object(self.boq.platform, "system",
                               return_value="Darwin"):
            found = self.boq._installed_converter_paths()
        self.assertIn("/opt/homebrew/bin/dwg2dxf", found)
        self.assertIn(
            "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
            found)

    def test_an_explicit_override_wins(self):
        exe = self._oda("26.2.0")
        with mock.patch.dict(os.environ, {self.boq.ENV_CONVERTER: exe},
                             clear=False):
            self.assertEqual(self.boq.find_dwg_converter(), exe)

    def test_the_screen_says_dxf_before_a_drawing_is_attached(self):
        """A .dwg needs a converter Prism is not allowed to ship, and .dxf
        needs nothing. Saying so only in the error — after the customer has
        picked the file, named the job and pressed the button — turns a menu
        item they already know into a dead end."""
        from PySide6.QtWidgets import QLabel
        from dialogs.boq_dialog import BoqDialog
        with mock.patch.object(self.boq, "find_dwg_converter", return_value=None):
            dialog = BoqDialog({"api_key": "k"}, [])
        self.addCleanup(dialog.deleteLater)
        notes = [w.text() for w in dialog.findChildren(QLabel)
                 if w.objectName() == "note"]
        self.assertTrue(any("DXF" in n for n in notes))

    def test_a_client_who_has_a_converter_is_not_nagged(self):
        from PySide6.QtWidgets import QLabel
        from dialogs.boq_dialog import BoqDialog
        with mock.patch.object(self.boq, "find_dwg_converter",
                               return_value="/usr/bin/ODAFileConverter"):
            dialog = BoqDialog({"api_key": "k"}, [])
        self.addCleanup(dialog.deleteLater)
        notes = [w.text() for w in dialog.findChildren(QLabel)
                 if w.objectName() == "note"]
        self.assertFalse(any("DXF" in n for n in notes))

    def test_windows_is_told_how_to_install_one(self):
        """The old message offered `brew install` and a Linux note — leaving
        the one platform with no answer as the one most customers use."""
        with mock.patch.object(self.boq.platform, "system",
                               return_value="Windows"), \
             mock.patch.object(self.boq, "find_dwg_converter", return_value=None):
            with self.assertRaises(self.boq.BoqError) as caught:
                self.boq.dwg_to_dxf(os.path.join(self.root, "plan.dwg"))
        message = str(caught.exception)
        self.assertIn("opendesign.com", message)
        self.assertNotIn("brew", message)


if __name__ == "__main__":
    unittest.main()


# ── 7. brief 03 — the QA pass ────────────────────────────────────────────────

class TheSuiteCanRunOnAMachineThatIsNotOurs(unittest.TestCase):
    """Two things stopped ~1,500 tests ever running in CI, and neither was a
    failing test."""

    def test_a_missing_dev_signing_key_skips_one_file_not_the_run(self):
        """tests/test_sign_manifest.py read a gitignored key at MODULE scope,
        so on a fresh clone or any CI runner it raised during collection and
        took the whole suite with it."""
        import test_sign_manifest as TSM
        source = inspect.getsource(TSM)
        self.assertNotIn("\nDEV_KEY = open(", source,
                         "reading the key at import time aborts collection")
        self.assertIn("skipUnless", source)

    def test_the_sample_jobs_folder_is_configurable(self):
        """Five test files hardcoded one developer's Mac path, so 22
        real-customer-job tests skipped everywhere else — silently."""
        import sample_jobs
        self.assertEqual(sample_jobs.ENV_VAR, "PRISM_SAMPLE_JOBS")
        with mock.patch.dict(os.environ, {"PRISM_SAMPLE_JOBS": "/somewhere"}):
            self.assertEqual(sample_jobs.path("gerber_test"),
                             os.path.join("/somewhere", "gerber_test"))

    def test_a_skipped_sample_says_which_folder_it_wanted(self):
        """Q3's DONE: 'the output says visibly why not. Silence is not
        acceptable.'"""
        with mock.patch.dict(os.environ,
                             {"PRISM_SAMPLE_JOBS": "/definitely/not/here"}):
            import sample_jobs
            why = sample_jobs.missing("gerber_test")
        self.assertIn("/definitely/not/here", why)
        self.assertIn("PRISM_SAMPLE_JOBS", why)

    def test_no_hardcoded_developer_path_is_left_in_the_tests(self):
        # Built rather than written, so this file does not match its own
        # scan — the first version of this test failed on itself.
        needle = "/Users/" + "hitarthtrivedi"
        here = os.path.dirname(os.path.abspath(__file__))
        offenders = []
        for name in sorted(os.listdir(here)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            with open(os.path.join(here, name), encoding="utf-8") as f:
                if needle in f.read():
                    offenders.append(name)
        self.assertEqual(offenders, [],
                         "a sample path belongs in tests/sample_jobs.py")


class ARenderChecksForRoomFirst(unittest.TestCase):
    """KNOWN_ISSUES #12. A disk that fills mid-encode gives FFmpeg's own 'No
    space left on device' at minute four of a seven-minute job and leaves a
    truncated .mp4 that looks like a file."""

    def setUp(self):
        self.ff = CB.get_ffmpeg()

    def test_plenty_of_room_says_nothing(self):
        self.assertEqual(self.ff.check_space("/tmp/out.mp4", need_mb=1), "")

    def test_no_room_is_a_sentence_with_the_numbers_in_it(self):
        why = self.ff.check_space("/tmp/out.mp4", need_mb=10 ** 10)
        self.assertIn("Not enough free space", why)
        self.assertIn("MB", why)

    def test_an_unmeasurable_disk_does_not_block_the_render(self):
        """Refusing to render because a disk-space PROBE failed would turn a
        diagnostic into an outage."""
        with mock.patch.object(self.ff, "free_mb", return_value=None):
            self.assertEqual(self.ff.check_space("/tmp/out.mp4"), "")

    def test_both_renderers_check_before_they_start(self):
        for module in ("reel", "reel_web"):
            source = inspect.getsource(
                __import__(f"core.{module}", fromlist=["x"]).render)
            self.assertIn("check_space", source, f"core.{module}.render")


class TheLicenceFlagsThatPadlockADemo(unittest.TestCase):
    """Two feature names look obvious and are wrong, and both are invisible
    until someone clicks — which on demo day is in front of the customer."""

    def setUp(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "devtools"))
        import mint
        self.mint = mint

    def test_there_is_no_gerber_feature_so_minting_one_fails(self):
        import plans
        self.assertNotIn("gerber", plans.FEATURES,
                         "Gerber is gated on 'boq' — main_window._open_gerber")
        with self.assertRaises(SystemExit) as caught:
            self.mint.parse_features("core,gerber")
        self.assertIn("boq", str(caught.exception))

    def test_the_brief_s_own_mint_line_is_accepted(self):
        self.assertEqual(
            self.mint.parse_features("core,boq,email,reel,inbox"),
            ["core", "boq", "email", "reel", "inbox"])

    def test_email_without_inbox_warns_about_email_automation(self):
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err):
            self.mint.parse_features("core,boq,email")
        self.assertIn("inbox", err.getvalue())


# ── 8. the prompt that was never actually sent ───────────────────────────────

class _Composer:
    """A chat composer, as far as the typing code can tell.

    `holds` is what is really in the box — which is the whole point: the run
    that prompted this reported "uploaded 1 file(s) → prompt 1/1" over a
    ChatGPT tab whose message box was empty, then waited 300s for a reply to
    a question nobody had been asked.
    """

    def __init__(self, holds: str = "", tag: str = "DIV"):
        self.holds = holds
        self.tag = tag
        self.keys: list = []

    def send_keys(self, *value):
        self.keys.append(value)


class _TypingDriver:
    def __init__(self, composer):
        self.composer = composer

    def execute_script(self, script, *args):
        return self.composer.holds

    def find_element(self, by, selector):
        return self.composer


class ThePromptHasToActuallyLand(unittest.TestCase):

    PROMPT = ("Act as a senior social-media copywriter. Your ONLY task is: "
              "write the reel script.\n\nSTRICT PIPELINE RULES:\n1. Perform "
              "ONLY the task above.")

    def test_an_empty_box_is_not_success(self):
        self.assertFalse(automation._text_landed("", self.PROMPT))

    def test_leftover_text_from_the_last_prompt_is_not_success(self):
        """The old check was `innerText.trim().length > 0`, so the previous
        prompt still sitting in the editor counted as this one landing."""
        self.assertFalse(
            automation._text_landed("Write me a BOQ for CCTV", self.PROMPT))

    def test_a_partial_insert_is_not_success(self):
        half = self.PROMPT[:len(self.PROMPT) // 2]
        self.assertFalse(automation._text_landed(half, self.PROMPT))

    def test_a_rich_editor_reflowing_whitespace_is_still_success(self):
        """ProseMirror legitimately normalises blank lines — that must not
        read as a failure, or every prompt would retry forever."""
        self.assertTrue(
            automation._text_landed(" ".join(self.PROMPT.split()), self.PROMPT))

    def test_the_text_actually_being_there_is_success(self):
        self.assertTrue(automation._text_landed(self.PROMPT, self.PROMPT))

    def test_a_composer_still_holding_the_prompt_did_not_send_it(self):
        """`submitted = True` only ever meant `btn.click()` did not raise.
        With an empty composer ChatGPT has no send button, so the wait timed
        out, ENTER went to an empty box, and nothing happened — silently."""
        composer = _Composer(holds=self.PROMPT)
        driver = _TypingDriver(composer)
        self.assertFalse(automation._prompt_was_sent(
            driver, composer, self.PROMPT, timeout=1))

    def test_a_composer_that_emptied_did_send_it(self):
        composer = _Composer(holds="")
        driver = _TypingDriver(composer)
        self.assertTrue(automation._prompt_was_sent(
            driver, composer, self.PROMPT, timeout=1))

    def test_the_run_loop_refuses_to_wait_on_a_prompt_it_never_sent(self):
        source = inspect.getsource(automation.run)
        self.assertIn("nothing_was_sent", source)
        self.assertIn("never received the prompt", source)

    def test_fast_type_verifies_rather_than_trusting_the_editor(self):
        source = inspect.getsource(automation._fast_type)
        self.assertIn("_text_landed", source,
                      "the contenteditable branch used to return on "
                      "'is the box non-empty', which is not the same question")
