"""The Email add-on.

A regular package, not a namespace package: PyInstaller resolves
regular packages reliably and namespace packages notoriously badly,
and a frozen build that silently ships no add-ons is the single worst
failure mode in this design.
"""
