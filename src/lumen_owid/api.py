"""Client for the public Our World In Data APIs.

OWID exposes two discovery surfaces. Charts are the curated, published figures most
people mean when they cite OWID; indicators are the much larger catalog behind them,
including series that were never charted. Both resolve to a plain HTTPS URL that
DuckDB can read in place, so nothing here downloads data.
"""
from __future__ import annotations

import httpx
import pandas as pd

CHART_SEARCH = "https://ourworldindata.org/api/search"
GRAPHER = "https://ourworldindata.org/grapher"
INDICATOR_SEARCH = "https://search.owid.io/indicators"

# The chart search API rejects hitsPerPage above 100.
MAX_HITS = 100

TIMEOUT = 30

# The columns every catalog entry carries, whichever surface it came from.
CATALOG_COLUMNS = ["title", "description", "kind", "url", "table_name", "slug", "column"]


def normalize_name(name: str) -> str:
    """Turn a slug or catalog path into a valid, readable SQL identifier."""
    return "".join(char if char.isalnum() else "_" for char in name).strip("_").lower()


def search_charts(query: str = "", limit: int = MAX_HITS) -> pd.DataFrame:
    """Search the published OWID charts, returning one row per chart."""
    response = httpx.get(
        CHART_SEARCH,
        params={"q": query, "type": "charts", "hitsPerPage": min(limit, MAX_HITS)},
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


def chart_table_metadata(slug: str) -> dict:
    """Hand OWID's own prose to the LLM so it can tell similar series apart."""
    meta = chart_metadata(slug)
    chart = meta["chart"]
    return {
        "description": " ".join(
            part for part in (chart["title"], chart.get("subtitle"), chart.get("citation")) if part
        ),
        "columns": {
            name: " ".join(
                part for part in (column.get("descriptionShort"), column.get("unit")) if part
            )
            for name, column in meta["columns"].items()
        },
    }


def explain_unreadable(url: str, cause: Exception | None = None) -> str:
    """Ask OWID why a file could not be read, for the message shown to the user.

    DuckDB reports a blocked download as a bare "HTTP 0 Internal Server Error", so the
    reason has to be recovered from OWID, which returns it as JSON in the body. When
    OWID serves the file happily the fault is ours, so the underlying error is passed
    through rather than replaced with something reassuring and useless.
    """
    try:
        httpx.get(url, timeout=TIMEOUT, follow_redirects=True).raise_for_status()
    except httpx.HTTPStatusError as error:
        try:
            return error.response.json()["error"]
        except (ValueError, KeyError):
            return f"Our World In Data returned {error.response.status_code}."
    except httpx.HTTPError as error:
        return f"Could not reach Our World In Data: {error}"
    if cause is not None:
        return f"Our World In Data served the file but it could not be read: {cause}"
    return "The dataset could not be read."


def charts_to_catalog(hits: pd.DataFrame) -> pd.DataFrame:
    """Normalize chart search hits onto the shared catalog columns."""
    return pd.DataFrame({
        "title": hits["title"],
        "description": hits.get("subtitle", ""),
        "kind": "chart",
        "url": hits["slug"].map(lambda slug: f"{GRAPHER}/{slug}.csv"),
        "table_name": hits["slug"].map(normalize_name),
        "slug": hits["slug"],
        "column": None,
    })


def indicators_to_catalog(hits: pd.DataFrame) -> pd.DataFrame:
    """Normalize indicator search hits onto the shared catalog columns.

    An indicator's parquet holds its whole source dataset, so the table is named after
    the dataset and the matched indicator is recorded in ``column``.
    """
    return pd.DataFrame({
        "title": hits["title"],
        "description": hits.get("description", ""),
        "kind": "indicator",
        "url": hits["metadata.parquet_url"],
        "table_name": hits["catalog_path"].map(
            lambda path: normalize_name(path.split("#")[0].split("/")[-1])
        ),
        "slug": None,
        "column": hits["metadata.column"],
    })


def search_catalog(query: str, limit: int = 5) -> pd.DataFrame:
    """Search both surfaces, charts first, and return normalized catalog rows.

    Charts win when they exist because they are curated and carry usable prose. The
    indicator service is a separate deployment under active development, so its
    failure degrades to charts-only rather than taking the search down.
    """
    surfaces = ((search_charts, charts_to_catalog), (search_indicators, indicators_to_catalog))
    for search, to_catalog in surfaces:
        try:
            hits = search(query, limit)
        except httpx.HTTPError:
            continue
        if not hits.empty:
            return to_catalog(hits)
    return pd.DataFrame(columns=CATALOG_COLUMNS)
