"""
Which Chrome profile Prism copies, and why it kept copying none
──────────────────────────────────────────────────────────────
The complaint: "it opens a new Chrome profile every time, which limits what
the AI can do". The cause was two hardcoded assumptions:

    src_default = os.path.join(user_chrome_dir(), "Default")
    opts.add_argument("--profile-directory=Default")

Chrome does not have to have a profile called "Default". Add a second Google
account, or sign in through a managed account, and you get `Profile 1`,
`Profile 3`, … with no `Default` at all. The machine that produced this report
has eleven profiles, eight signed-in accounts, and no `Default`. So the copy
found nothing, warned once into a log nobody reads, and created a blank
profile — and every run opened a logged-out browser.

It was permanent, too: `profile_is_seeded()` asked whether `Preferences`
existed, and Chrome writes that itself the first time it opens a BLANK
profile. So the blank profile marked itself as seeded and no later run ever
tried again.
"""
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prism_terminal"))

from core import automation  # noqa: E402


def build_chrome(root: str, profiles: dict, last_used: str = ""):
    """A believable Chrome User Data directory.

    `profiles` maps directory name → account address ("" for a profile nobody
    is signed into).
    """
    for directory, account in profiles.items():
        path = os.path.join(root, directory)
        os.makedirs(os.path.join(path, "Network"), exist_ok=True)
        with open(os.path.join(path, "Network", "Cookies"), "wb") as f:
            f.write(b"SQLite format 3\x00")
        for name in ("Login Data", "Preferences"):
            with open(os.path.join(path, name), "w", encoding="utf-8") as f:
                f.write("{}")
    # Chrome's own scratch profiles, which are never what anybody means.
    for junk in ("Guest Profile", "System Profile"):
        os.makedirs(os.path.join(root, junk), exist_ok=True)
    with open(os.path.join(root, "Local State"), "w", encoding="utf-8") as f:
        json.dump({"profile": {
            "last_used": last_used,
            "info_cache": {d: {"name": d.replace("Profile", "Account"),
                               "user_name": a}
                           for d, a in profiles.items()}}}, f)


class _both:
    """Two patches as one context manager."""

    def __init__(self, *patches):
        self.patches = patches

    def __enter__(self):
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()
        return False


class Harness(unittest.TestCase):
    """Real directories, no real Chrome and no real ~/.prism."""

    PROFILES = {"Profile 1": "hetvaghela2005@gmail.com",
                "Profile 20": "het.shaktiailabs@gmail.com",
                "Profile 3": "someone@else.example",
                "Profile 12": ""}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chrome = os.path.join(self.tmp.name, "User Data")
        os.makedirs(self.chrome)
        build_chrome(self.chrome, self.PROFILES, last_used="Profile 20")

        self.prism = os.path.join(self.tmp.name, "prism-profile")
        self._patches = [
            mock.patch.object(automation, "user_chrome_dir",
                              lambda: self.chrome),
            mock.patch.object(automation, "PROFILE_DIR", self.prism),
            mock.patch.object(automation, "SEED_MARKER",
                              os.path.join(self.prism, "prism-seeded-from.json")),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()
        self.tmp.cleanup()

    def seeded_default(self, *parts):
        return os.path.join(self.prism, "Default", *parts)


# ── finding the profiles at all ──────────────────────────────────────────────

class FindingTheRealProfiles(Harness):

    def test_a_chrome_with_no_default_is_still_read(self):
        """The whole bug in one assertion."""
        self.assertNotIn("Default", self.PROFILES)
        found = [p["dir"] for p in automation.chrome_profiles()]
        self.assertEqual(sorted(found), sorted(self.PROFILES))

    def test_chromes_own_scratch_profiles_are_not_offered(self):
        found = [p["dir"] for p in automation.chrome_profiles()]
        self.assertNotIn("Guest Profile", found)
        self.assertNotIn("System Profile", found)

    def test_the_one_chrome_used_last_comes_first(self):
        self.assertEqual(automation.chrome_profiles()[0]["dir"], "Profile 20")

    def test_each_one_carries_the_account_that_identifies_it(self):
        by_dir = {p["dir"]: p for p in automation.chrome_profiles()}
        self.assertEqual(by_dir["Profile 1"]["account"],
                         "hetvaghela2005@gmail.com")
        self.assertIn("het.shaktiailabs@gmail.com",
                      automation.describe_profile(by_dir["Profile 20"]))

    def test_no_chrome_at_all_is_not_a_crash(self):
        with mock.patch.object(automation, "user_chrome_dir",
                               lambda: os.path.join(self.tmp.name, "nope")):
            self.assertEqual(automation.chrome_profiles(), [])
            self.assertIsNone(automation.preferred_profile({}))

    def test_an_unreadable_local_state_falls_back_to_the_directories(self):
        """Chrome's own file, possibly mid-write. The scan must not need it."""
        with open(os.path.join(self.chrome, "Local State"), "w") as f:
            f.write("{not json")
        self.assertEqual(len(automation.chrome_profiles()), len(self.PROFILES))


class ChoosingOne(Harness):

    def test_the_account_address_picks_it(self):
        chosen = automation.preferred_profile(
            {"chrome_profile": "someone@else.example"})
        self.assertEqual(chosen["dir"], "Profile 3")

    def test_the_directory_name_picks_it(self):
        chosen = automation.preferred_profile({"chrome_profile": "Profile 1"})
        self.assertEqual(chosen["dir"], "Profile 1")

    def test_case_does_not_matter(self):
        chosen = automation.preferred_profile(
            {"chrome_profile": "HET.SHAKTIAILABS@GMAIL.COM"})
        self.assertEqual(chosen["dir"], "Profile 20")

    def test_nothing_chosen_means_the_one_chrome_used_last(self):
        self.assertEqual(automation.preferred_profile({})["dir"], "Profile 20")

    def test_a_profile_that_has_been_deleted_falls_back_and_says_so(self):
        with mock.patch.object(automation.ui, "warn") as warned:
            chosen = automation.preferred_profile(
                {"chrome_profile": "gone@nowhere.example"})
        self.assertEqual(chosen["dir"], "Profile 20")
        self.assertTrue(warned.called, "silently using another account is worse")


# ── the copy ─────────────────────────────────────────────────────────────────

class CopyingTheLoginsIn(Harness):

    def test_it_copies_the_chosen_profile(self):
        self.assertTrue(automation.seed_profile(cfg={"chrome_profile": "Profile 1"}))
        self.assertEqual(automation.seeded_from(), "Profile 1")
        self.assertTrue(os.path.exists(self.seeded_default("Network", "Cookies")))

    def test_whatever_it_came_from_it_lands_in_default(self):
        """Prism's own directory holds exactly one profile, so the launch flag
        can stay --profile-directory=Default and nothing has to agree."""
        automation.seed_profile(cfg={"chrome_profile": "Profile 20"})
        self.assertTrue(os.path.isdir(self.seeded_default()))

    def test_a_second_run_does_not_copy_again(self):
        automation.seed_profile(cfg={})
        self.assertFalse(automation.seed_profile(cfg={}),
                         "a full profile copy on every run is the slow bug")

    def test_choosing_a_different_account_copies_again(self):
        automation.seed_profile(cfg={"chrome_profile": "Profile 1"})
        self.assertTrue(automation.seed_profile(cfg={"chrome_profile": "Profile 3"}))
        self.assertEqual(automation.seeded_from(), "Profile 3")

    def test_forcing_copies_again(self):
        automation.seed_profile(cfg={})
        self.assertTrue(automation.seed_profile(force=True, cfg={}))


class ABlankProfileIsNotASeededOne(Harness):
    """The reason it never recovered. Chrome writes Preferences and Login Data
    itself the first time it opens an empty profile, so the old
    `does Preferences exist?` test called a logged-out profile seeded."""

    def test_files_chrome_made_itself_do_not_count(self):
        os.makedirs(self.seeded_default(), exist_ok=True)
        for name in ("Preferences", "Login Data", "Cookies"):
            with open(self.seeded_default(name), "w") as f:
                f.write("{}")
        self.assertFalse(automation.profile_is_seeded(),
                         "a blank profile marked itself as done for ever")

    def test_only_a_real_copy_counts(self):
        automation.seed_profile(cfg={})
        self.assertTrue(automation.profile_is_seeded())

    def test_and_it_will_still_copy_over_a_blank_one(self):
        os.makedirs(self.seeded_default(), exist_ok=True)
        with open(self.seeded_default("Preferences"), "w") as f:
            f.write("{}")
        self.assertTrue(automation.seed_profile(cfg={}))


class WhenChromeIsOpen(Harness):
    """Windows will not hand over Network/Cookies while Chrome holds it, and
    shutil.copytree collects failures and raises at the END — so one locked
    cookie jar aborted the whole seed. On Windows, with Chrome open, that is
    every time."""

    def _lock_the_cookies(self):
        """Stand in for Chrome holding the cookie jar open.

        Both halves, because that is what actually happens: the file cannot be
        copied AND cannot be read, and it is the second one Prism uses to
        decide whether trying again is worth it.
        """
        real = automation.shutil.copy2

        def refuse(src, dst, **kw):
            if os.path.basename(src) == "Cookies":
                raise OSError(32, "being used by another process")
            return real(src, dst, **kw)

        return _both(mock.patch.object(automation.shutil, "copy2", refuse),
                     mock.patch.object(automation, "_cookies_readable",
                                       lambda path: False))

    def test_a_locked_cookie_file_does_not_abort_the_copy(self):
        with self._lock_the_cookies(), mock.patch.object(automation.ui, "warn"):
            self.assertTrue(automation.seed_profile(cfg={}))
        self.assertTrue(os.path.exists(self.seeded_default("Preferences")),
                        "the rest of the profile should still arrive")

    def test_it_says_so_rather_than_pretending(self):
        with self._lock_the_cookies(), mock.patch.object(automation.ui, "warn") as warned:
            automation.seed_profile(cfg={})
        said = " ".join(str(c) for c in warned.call_args_list).lower()
        self.assertIn("chrome is open", said)
        self.assertIn("sign in", said)

    def test_the_failure_is_remembered(self):
        with self._lock_the_cookies(), mock.patch.object(automation.ui, "warn"):
            automation.seed_profile(cfg={})
        self.assertFalse(automation._marker().get("cookies"))

    def test_it_tries_again_once_chrome_has_been_closed(self):
        with self._lock_the_cookies(), mock.patch.object(automation.ui, "warn"):
            automation.seed_profile(cfg={})
        # Chrome closed: the cookie file is readable again.
        self.assertTrue(automation.seed_profile(cfg={}),
                        "the logins must arrive without the customer being "
                        "told to do anything twice")
        self.assertTrue(automation._marker().get("cookies"))

    def test_but_not_on_every_run_while_chrome_stays_open(self):
        """A full profile copy per run, achieving nothing, is its own bug."""
        with self._lock_the_cookies(), mock.patch.object(automation.ui, "warn"):
            automation.seed_profile(cfg={})
            self.assertFalse(automation.seed_profile(cfg={}))


class TheLaunchUsesPrismsOwnCopy(unittest.TestCase):
    """Not the customer's live profile: Chrome refuses to open one that is
    already running, and driving it would put automation in the window they
    do their banking in."""

    def test_the_driver_is_pointed_at_the_prism_profile(self):
        source = inspect.getsource(automation._setup_chrome_driver)
        self.assertIn("user_data_dir=", source)
        self.assertIn("--profile-directory=Default", source)

    def test_the_chosen_profile_reaches_the_launcher(self):
        source = inspect.getsource(automation._setup_chrome_driver)
        self.assertIn("cfg=cfg", source)


if __name__ == "__main__":
    unittest.main()
