"""Lumen AI with the Our World In Data catalog attached.

    panel serve scripts/app.py --show

Needs an LLM key in the environment, for example OPENAI_API_KEY or ANTHROPIC_API_KEY.
Browse the catalog in the sidebar, or just ask a question and let the agent search
Our World In Data for the datasets it needs.
"""
from lumen.ai.controls import OWIDSourceControls
from lumen.ai.ui import ExplorerUI

ExplorerUI(source_controls=[OWIDSourceControls]).servable()
