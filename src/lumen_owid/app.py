"""The servable application.

    panel serve -m lumen_owid.app --show
"""
from .ui import build_ui

build_ui().servable()
