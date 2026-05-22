"""Compatibility shim for older imports.

The proxy app now lives in :mod:`proxy.app`; this module remains so external
code importing ``proxy.legacy_app.app`` keeps working during the transition.
"""

from proxy.app import app, create_app
