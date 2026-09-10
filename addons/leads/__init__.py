"""The Leads & Outreach add-on.

A regular package, not a namespace package: PyInstaller resolves regular
packages reliably and namespace packages badly, and a frozen build that
silently ships no add-ons is the worst kind of accident (see
addons/registry.py). The prospector *engine* it drives lives in the
top-level `prospector/` package — this add-on is only the front door and
its off-thread workers.
"""
