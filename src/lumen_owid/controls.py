"""Source controls for browsing and loading Our World In Data.

OWID publishes its data as CSV and parquet over plain HTTPS, and ``DuckDBSource``
already turns such a URL into a ``READ_CSV``/``READ_PARQUET`` expression on its own.
Nothing here downloads, parses, or caches data. This module only does discovery:
it surfaces the OWID catalog and hands OWID's own descriptions to the LLM.
"""
from __future__ import annotations

import httpx
import pandas as pd

CHART_SEARCH = "https://ourworldindata.org/api/search"
GRAPHER = "https://ourworldindata.org/grapher"
INDICATOR_SEARCH = "https://search.owid.io/indicators"

TIMEOUT = 30


def search_charts(query: str = "", limit: int = 50) -> pd.DataFrame:
    """Search the published OWID charts, returning one row per chart."""
    response = httpx.get(
        CHART_SEARCH,
        params={"q": query, "type": "charts", "hitsPerPage": limit},
        timeout=TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()
    return pd.json_normalize(response.json()["results"])


def search_indicators(query: str, limit: int = 20) -> pd.DataFrame:
    """Semantic search over every OWID indicator, including uncharted ones."""
    response = httpx.get(
        INDICATOR_SEARCH,
        params={"q": query, "limit": limit},
        timeout=TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()
    return pd.json_normalize(response.json()["results"])


def chart_metadata(slug: str) -> dict:
    """Fetch one chart's metadata: titles, units, descriptions and citations."""
    response = httpx.get(f"{GRAPHER}/{slug}.metadata.json", timeout=TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    return response.json()
