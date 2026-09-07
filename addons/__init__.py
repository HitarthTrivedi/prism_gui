"""Prism's add-ons.

Deliberately empty. `packaging/prism.spec` imports `addons.registry` in a
bare interpreter to build its hiddenimports list, the same way it already
imports `app_meta` and `licensing.keys`. Anything imported here would be
imported there too -- a Qt import would need a display on the build box, an
engine import would break the build the day the submodule moves.

The rule is enforced, not merely written down: see
tests/test_addon_contract.py::test_the_registry_imports_nothing_but_the_standard_library
"""
