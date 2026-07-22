"""Runtime hook: keep `import distutils` working inside the frozen app.

Python 3.12 deleted distutils from the stdlib (PEP 632), and
undetected_chromedriver's patcher still does `from distutils.version import
LooseVersion` at import time. In a normal interpreter setuptools papers over
this with a .pth file that redirects the name to its vendored copy — but .pth
files are a site-packages mechanism, and a PyInstaller bundle has no
site-packages. So the shim that makes this work everywhere else is exactly the
thing that goes missing once the app is packaged.

The symptom, if this hook is removed: the app starts fine, every panel works,
and the first real run dies at driver setup with "No module named 'distutils'"
— i.e. the whole point of the product fails, on the machines of users who
cannot see a traceback.

Three tiers, most faithful first. The last one exists because tier two is not
guaranteed: importing setuptools can itself try to import distutils, so the
rescue can fail for the very reason it was needed. Only LooseVersion is ever
asked for, and it is 20 lines, so the bundle carries its own rather than
betting the product's main feature on a transitive import working out.

PyInstaller executes this before any application code, so whichever tier wins
is in place long before undetected_chromedriver is imported.
"""
import importlib.util
import sys
import types
import warnings


def _install_minimal_shim():
    """A distutils.version good enough for comparing Chrome version strings."""

    class LooseVersion:
        def __init__(self, vstring=""):
            self.vstring = str(vstring)
            parts = []
            for chunk in self.vstring.replace("-", ".").split("."):
                # "131", "0", "6778", "86" → ints; anything else sorts as text
                parts.append(int(chunk) if chunk.isdigit() else chunk)
            self.version = parts

        def _key(self):
            # Mixed int/str tuples can't be compared directly; normalise to
            # (0, number) / (1, text) so numbers sort before suffixes.
            return tuple((0, p, "") if isinstance(p, int) else (1, 0, p)
                         for p in self.version)

        def __str__(self):
            return self.vstring

        def __repr__(self):
            return f"LooseVersion('{self.vstring}')"

        def __eq__(self, other):
            return self._key() == LooseVersion(str(other))._key()

        def __lt__(self, other):
            return self._key() < LooseVersion(str(other))._key()

        def __le__(self, other):
            return self._key() <= LooseVersion(str(other))._key()

        def __gt__(self, other):
            return self._key() > LooseVersion(str(other))._key()

        def __ge__(self, other):
            return self._key() >= LooseVersion(str(other))._key()

        def __hash__(self):
            return hash(self._key())

    StrictVersion = LooseVersion   # uc never uses it; keep the name resolvable

    version_mod = types.ModuleType("distutils.version")
    version_mod.LooseVersion = LooseVersion
    version_mod.StrictVersion = StrictVersion
    version_mod.Version = LooseVersion

    package = types.ModuleType("distutils")
    package.__path__ = []          # marks it as a package so submodules resolve
    package.version = version_mod

    sys.modules["distutils"] = package
    sys.modules["distutils.version"] = version_mod


def _install():
    # setuptools' _distutils_hack complains, at length and on stderr, whenever
    # distutils is imported before setuptools. It fires from whichever import
    # happens to come second, so it can't be caught around one statement — and
    # nothing about it is actionable inside a frozen app.
    warnings.filterwarnings("ignore", message=r".*[Dd]istutils.*",
                            category=UserWarning)

    # find_spec, not import: on 3.11 distutils is present and uc can import it
    # itself later. Importing it here would only change the order the hack
    # complains about, and pull in a module the app may never need.
    # It is wrapped because find_spec doesn't only return None for a missing
    # module — a finder on the path can raise, and an exception escaping a
    # runtime hook takes the whole app down before main() is reached.
    try:
        if importlib.util.find_spec("distutils") is not None:
            return
    except Exception:
        pass
    try:                                    # setuptools' vendored copy
        import setuptools._distutils as _distutils
        import setuptools._distutils.version as _version
        sys.modules["distutils"] = _distutils
        sys.modules["distutils.version"] = _version
        return
    except Exception:
        pass
    _install_minimal_shim()


_install()
