"""The application shell: the window, its background workers, and the
widgets and dialogs it is built from.

Everything here is Prism itself rather than one of its features. An add-on
may import from here; nothing here may import an add-on. The shell knows
THAT add-ons exist -- it reads addons/registry.py -- and never which.
"""
