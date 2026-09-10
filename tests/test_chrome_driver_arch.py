"""An Intel browser driver on an Apple silicon Mac with no Rosetta.

A client's M2 (10 Sep 2026): Prism.app was the Apple silicon build, Chrome
was universal, and the first run died with "[Errno 86] Bad CPU type in
executable". `file` on their machine showed the cached driver in
~/Library/Application Support/undetected_chromedriver was x86_64 -- carried
over from an older Intel Mac by Migration Assistant -- and the Mac had no
Rosetta to run it. The cleanup meant to catch that shelled out to `file`
and swallowed every failure, so it did nothing and said nothing.

Pinned here:

  · the Mach-O header is read in Python -- thin x86_64, thin arm64, and a
    universal binary are told apart without `file`;
  · on Darwin/arm64 the cleanup deletes an Intel driver before Chrome is
    launched, and leaves an arm64 or universal one alone;
  · elsewhere (Linux x86, say) a native x86_64 driver is never touched;
  · an errno 86 out of the launch purges the cache and retries once, and a
    second errno 86 becomes a message that says "Intel" and names the
    folder -- never a bare errno.

No Chrome, no network: undetected_chromedriver is replaced by a fake
module for the duration of each test.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: F401,E402
from core import automation as AU  # noqa: E402


def _thin(cputype: int) -> bytes:
    # MH_MAGIC_64 little-endian, then cputype, padded to a plausible size.
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", cputype) + b"\0" * 64


def _fat(*cputypes: int) -> bytes:
    head = b"\xca\xfe\xba\xbe" + struct.pack(">I", len(cputypes))
    for ct in cputypes:
        head += struct.pack(">IIIII", ct, 0, 0, 0, 0)
    return head + b"\0" * 64


class ReadingTheHeader(unittest.TestCase):

    def _write(self, data: bytes) -> str:
        d = tempfile.mkdtemp(prefix="prism-macho-")
        p = os.path.join(d, "undetected_chromedriver")
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_thin_x86_64(self):
        self.assertEqual(AU._macho_arches(self._write(_thin(AU._MACHO_X86_64))), {"x86_64"})

    def test_thin_arm64(self):
        self.assertEqual(AU._macho_arches(self._write(_thin(AU._MACHO_ARM64))), {"arm64"})

    def test_universal(self):
        self.assertEqual(AU._macho_arches(self._write(_fat(AU._MACHO_X86_64, AU._MACHO_ARM64))),
                         {"x86_64", "arm64"})

    def test_not_macho_and_missing(self):
        self.assertEqual(AU._macho_arches(self._write(b"#!/bin/sh\necho hi\n")), set())
        self.assertEqual(AU._macho_arches("/nonexistent/driver"), set())

    def test_wrong_arch_only_on_apple_silicon(self):
        intel = self._write(_thin(AU._MACHO_X86_64))
        with mock.patch.object(AU.platform, "system", return_value="Darwin"), \
                mock.patch.object(AU.platform, "machine", return_value="arm64"):
            self.assertIn("Intel", AU._driver_wrong_arch(intel))
            self.assertEqual(AU._driver_wrong_arch(self._write(_thin(AU._MACHO_ARM64))), "")
            self.assertEqual(AU._driver_wrong_arch(
                self._write(_fat(AU._MACHO_X86_64, AU._MACHO_ARM64))), "")
        with mock.patch.object(AU.platform, "system", return_value="Linux"), \
                mock.patch.object(AU.platform, "machine", return_value="x86_64"):
            self.assertEqual(AU._driver_wrong_arch(intel), "")


class _FakeUC(types.ModuleType):
    """Stands in for undetected_chromedriver: Chrome() records its calls and
    raises whatever the test queued."""

    def __init__(self, failures):
        super().__init__("undetected_chromedriver")
        self.failures = list(failures)
        self.calls = []
        self.driver_paths = []
        fake = self

        class ChromeOptions:
            def add_argument(self, *_):
                pass

        class Chrome:
            def __init__(self, options=None, user_data_dir=None, version_main=None,
                         driver_executable_path=None):
                fake.calls.append(version_main)
                fake.driver_paths.append(driver_executable_path)
                if fake.failures:
                    raise fake.failures.pop(0)
                self.current_url = "about:blank"

        self.ChromeOptions = ChromeOptions
        self.Chrome = Chrome


class TheCleanupAndTheRetry(unittest.TestCase):

    def setUp(self):
        self.cache = tempfile.mkdtemp(prefix="prism-uc-cache-")
        self.profile = tempfile.mkdtemp(prefix="prism-profile-")
        self.driver = os.path.join(self.cache, "undetected_chromedriver")

    def _put(self, data: bytes):
        with open(self.driver, "wb") as f:
            f.write(data)

    def _run(self, fake, system="Darwin", machine="arm64", own_driver=""):
        quiet = ("seed_profile", "_clear_profile_locks", "_release_profile",
                 "_prune_preferences", "_ensure_session_restore", "_reset_to_blank_tab")
        patches = [mock.patch.object(AU, name) for name in quiet]
        patches += [
            mock.patch.object(AU, "_apple_silicon_driver", return_value=own_driver),
            mock.patch.object(AU, "profile_is_seeded", return_value=True),
            mock.patch.object(AU, "detect_chrome_version", return_value=None),
            mock.patch.object(AU, "_uc_cache_dir", return_value=self.cache),
            mock.patch.object(AU, "PROFILE_DIR", self.profile),
            mock.patch.object(AU.platform, "system", return_value=system),
            mock.patch.object(AU.platform, "machine", return_value=machine),
            mock.patch.dict(sys.modules, {"undetected_chromedriver": fake}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return AU._setup_chrome_driver()

    def test_an_intel_driver_is_deleted_before_chrome_starts(self):
        self._put(_thin(AU._MACHO_X86_64))
        fake = _FakeUC([])
        drv = self._run(fake)
        self.assertIsNotNone(drv)
        self.assertFalse(os.path.exists(self.driver), "the Intel driver must be gone")
        self.assertEqual(fake.calls, [None])

    def test_an_arm64_driver_is_kept(self):
        self._put(_thin(AU._MACHO_ARM64))
        self._run(_FakeUC([]))
        self.assertTrue(os.path.exists(self.driver))

    def test_a_native_x86_driver_on_linux_is_kept(self):
        self._put(_thin(AU._MACHO_X86_64))
        self._run(_FakeUC([]), system="Linux", machine="x86_64")
        self.assertTrue(os.path.exists(self.driver))

    def test_errno_86_purges_the_cache_and_retries_once(self):
        self._put(_thin(AU._MACHO_ARM64))       # looks fine; the launch says otherwise
        fake = _FakeUC([OSError(86, "Bad CPU type in executable")])
        drv = self._run(fake)
        self.assertIsNotNone(drv)
        self.assertEqual(len(fake.calls), 2)
        self.assertFalse(os.path.exists(self.driver), "the cache was purged before the retry")

    def test_a_second_errno_86_is_explained_in_words(self):
        fake = _FakeUC([OSError(86, "Bad CPU type in executable"),
                        OSError(86, "Bad CPU type in executable")])
        with self.assertRaises(RuntimeError) as ctx:
            self._run(fake)
        msg = str(ctx.exception)
        self.assertIn("Intel", msg)
        self.assertIn("Rosetta", msg)
        self.assertIn("undetected_chromedriver", msg)
        self.assertNotIn("Traceback", msg)


    def test_prisms_own_arm64_driver_is_handed_to_uc_on_apple_silicon(self):
        own = os.path.join(self.cache, "own-chromedriver")
        with open(own, "wb") as f:
            f.write(_thin(AU._MACHO_ARM64))
        fake = _FakeUC([])
        self._run(fake, own_driver=own)
        self.assertEqual(fake.driver_paths, [own])

    def test_without_an_own_driver_uc_chooses_as_before(self):
        fake = _FakeUC([])
        self._run(fake, own_driver="")
        self.assertEqual(fake.driver_paths, [None])

    def test_an_undeletable_driver_folder_is_moved_aside(self):
        self._put(_thin(AU._MACHO_X86_64))
        parent = os.path.dirname(self.cache)
        with mock.patch.object(AU, "_uc_cache_dir", return_value=self.cache), \
                mock.patch.object(AU.os, "remove", side_effect=PermissionError("nope")):
            AU._purge_uc_cache("test")
        self.assertFalse(os.path.exists(self.cache), "the folder was renamed away")
        aside = [d for d in os.listdir(parent)
                 if d.startswith(os.path.basename(self.cache) + ".intel-")]
        self.assertEqual(len(aside), 1, aside)


class FetchingTheArm64Driver(unittest.TestCase):
    """_apple_silicon_driver talks to Chrome-for-Testing through _http_get;
    here that is a fake that serves a version string and a zip holding a
    fake arm64 Mach-O, so nothing leaves the machine."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="prism-own-driver-")
        self.fetched = []

    def _serve(self, arch=AU._MACHO_ARM64):
        import io
        import zipfile

        def get(url, timeout=60.0):
            self.fetched.append(url)
            if "LATEST_RELEASE" in url:
                return b"152.0.7977.82\n"
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("chromedriver-mac-arm64/LICENSE", "x")
                z.writestr("chromedriver-mac-arm64/chromedriver", _thin(arch))
            return buf.getvalue()
        return get

    def _patched(self, get, system="Darwin", machine="arm64"):
        ps = [mock.patch.object(AU, "_http_get", side_effect=get),
              mock.patch.object(AU, "_PRISM_DRIVER_DIR", self.dir),
              mock.patch.object(AU.platform, "system", return_value=system),
              mock.patch.object(AU.platform, "machine", return_value=machine)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def test_downloads_once_per_chrome_major_and_reuses_it(self):
        self._patched(self._serve())
        path = AU._apple_silicon_driver(152)
        self.assertTrue(path.endswith(os.path.join("152", "chromedriver")))
        self.assertTrue(os.access(path, os.X_OK))
        self.assertEqual(AU._macho_arches(path), {"arm64"})
        self.assertIn("LATEST_RELEASE_152", self.fetched[0])
        self.assertIn("/mac-arm64/chromedriver-mac-arm64.zip", self.fetched[1])
        again = AU._apple_silicon_driver(152)
        self.assertEqual(again, path)
        self.assertEqual(len(self.fetched), 2, "the second call did not download")

    def test_an_unknown_chrome_version_uses_the_stable_feed(self):
        self._patched(self._serve())
        AU._apple_silicon_driver(None)
        self.assertIn("LATEST_RELEASE_STABLE", self.fetched[0])

    def test_a_download_that_is_not_arm64_is_refused(self):
        self._patched(self._serve(arch=AU._MACHO_X86_64))
        self.assertEqual(AU._apple_silicon_driver(152), "")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "152", "chromedriver")))

    def test_a_failed_download_falls_back_to_uc(self):
        def boom(url, timeout=60.0):
            raise OSError("offline")
        self._patched(boom)
        self.assertEqual(AU._apple_silicon_driver(152), "")

    def test_nothing_happens_off_apple_silicon(self):
        self._patched(self._serve(), system="Linux", machine="x86_64")
        self.assertEqual(AU._apple_silicon_driver(152), "")
        self.assertEqual(self.fetched, [])


if __name__ == "__main__":
    unittest.main()
