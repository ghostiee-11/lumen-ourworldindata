"""Assemble Lumen AI with the Our World In Data catalog and analyses attached."""
from __future__ import annotations

from lumen.ai.llm import Llm
from lumen.ai.ui import ExplorerUI

from .analysis import ANALYSES
from .controls import OWIDSourceControls


def build_ui(llm: Llm | None = None, **params) -> ExplorerUI:
    """Return an ExplorerUI that can browse, load and analyse Our World In Data.

    No sources are attached up front. Everything is discovered through the catalog
    or through the agent's search, so the app starts empty and stays that way until
    a question needs data.
    """
    params.setdefault("source_controls", [OWIDSourceControls])
    params.setdefault("analyses", ANALYSES)
    params.setdefault("title", "Our World In Data")
    if llm is not None:
        params["llm"] = llm
    return ExplorerUI(**params)
