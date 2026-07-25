"""The servable application.

    panel serve src/lumen_owid/app.py --show

Imported absolutely rather than relatively: panel serve executes this file as a
script, where a relative import has no parent package to resolve against.
"""
from lumen_owid.ui import build_ui

build_ui().servable()
