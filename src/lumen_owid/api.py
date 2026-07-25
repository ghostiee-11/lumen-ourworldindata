"""Client for the public Our World In Data APIs.

OWID exposes two discovery surfaces. Charts are the curated, published figures most
people mean when they cite OWID; indicators are the much larger catalog behind them,
including series that were never charted. Both resolve to a plain HTTPS URL that
DuckDB can read in place, so nothing here downloads data.
"""
from __future__ import annotations

import httpx
import pandas as pd

from .utils import CODE_COLUMNS, COUNTRY_COLUMNS, YEAR_COLUMNS

CHART_SEARCH = "https://ourworldindata.org/api/search"
GRAPHER = "https://ourworldindata.org/grapher"
INDICATOR_SEARCH = "https://search.owid.io/indicators"

# The chart search API rejects hitsPerPage above 100.
MAX_HITS = 100

# How much of OWID's descriptionKey to forward per table, shared across its columns.
# Measured over 59 charts, the median carries 234 characters in total and only three
# exceeded 8,000, so a per-table budget leaves the common case untouched and trims only
# the wide outliers. The floor keeps something useful on a 30-column table.
KEY_POINT_TABLE_BUDGET = 6000
KEY_POINT_MINIMUM = 300

TIMEOUT = 30

# The columns every catalog entry carries, whichever surface it came from.
CATALOG_COLUMNS = [
    "title", "description", "kind", "url", "table_name", "slug", "column", "entities",
]


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


def key_points(description_key: str | None, budget: int = KEY_POINT_TABLE_BUDGET) -> str:
    """Condense OWID's ``descriptionKey`` bullets to fit a character budget.

    This field carries the caveats that decide whether a comparison is even valid, the
    "data for the United Kingdom covers England only and counts households" kind, so it
    is worth forwarding. It also runs past 1,500 characters per column, and a wide
    dataset would otherwise crowd out the rest of the prompt.

    Whole bullets are kept and the remainder dropped, because half a caveat is worse
    than none: a truncated sentence reads as a complete statement.
    """
    if not description_key:
        return ""
    points, used = [], 0
    for point in description_key.split("\n-"):
        point = point.strip().lstrip("-").strip()
        if not point:
            continue
        # The first point is always kept, even when it alone exceeds the budget:
        # returning nothing would drop the caveat entirely, which is the outcome this
        # whole function exists to avoid.
        if points and used + len(point) > budget:
            break
        points.append(point)
        used += len(point)
    return " ".join(points)


def align_column_docs(docs: dict[str, str], columns: list[str]) -> dict[str, str]:
    """Re-key column documentation onto the names the loaded table actually uses.

    OWID keys its metadata by indicator title, but a chart CSV's headers are the
    chart's display names, which it is free to override: "Period life expectancy at
    birth" arrives as "Life expectancy", and the homelessness chart renames all three
    of its indicators. Only about 58% of charts agree on the name, so documentation
    keyed straight from the metadata describes columns that do not exist.

    Exact matches are taken first. Whatever is left is aligned by position, which held
    for 32 of 33 sampled charts once annotation columns are set aside. When the counts
    disagree, as they do when a chart documents an indicator it does not plot, the
    remainder is dropped: no documentation is better than documentation attached to
    the wrong column.
    """
    aligned = {column: docs[column] for column in columns if column in docs}

    # Identifier and annotation columns are never documented indicators, so they must
    # not consume a position when aligning.
    identifiers = set(COUNTRY_COLUMNS + YEAR_COLUMNS + CODE_COLUMNS)
    remaining_columns = [
        column for column in columns
        if column not in aligned and column not in identifiers
        and "(Annotations)" not in column
    ]
    remaining_docs = [text for name, text in docs.items() if name not in aligned]
    if len(remaining_columns) == len(remaining_docs):
        aligned.update(zip(remaining_columns, remaining_docs))
    return aligned


def chart_table_metadata(slug: str) -> dict:
    """Hand OWID's own prose to the LLM so it can tell similar series apart."""
    meta = chart_metadata(slug)
    chart = meta["chart"]
    columns = meta["columns"]
    # Share the budget across columns, so a single-column chart keeps all its caveats
    # and a thirty-column one still fits.
    budget = max(KEY_POINT_MINIMUM, KEY_POINT_TABLE_BUDGET // max(len(columns), 1))
    return {
        "description": " ".join(
            part for part in (chart["title"], chart.get("subtitle"), chart.get("citation")) if part
        ),
        "columns": {
            name: " ".join(
                part for part in (
                    column.get("descriptionShort"),
                    column.get("unit"),
                    key_points(column.get("descriptionKey"), budget),
                ) if part
            )
            for name, column in columns.items()
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


def entity_counts(hits: pd.DataFrame) -> pd.Series | None:
    """How many entities each chart covers, or None where OWID lists none.

    Unknown coverage is not zero coverage, so a missing list stays None rather than
    becoming a count that reads as "this dataset is empty".
    """
    if "availableEntities" not in hits:
        return None
    return hits["availableEntities"].map(
        lambda names: len(names) if isinstance(names, list) else None
    )


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
        # How many entities the chart covers, so a dataset can be ruled out before it
        # is loaded. These include aggregates such as continents, hence "entities"
        # rather than "countries": a GDP chart lists 285 against 236 real countries.
        "entities": entity_counts(hits),
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
        # The indicator API publishes no entity list, so coverage is unknown here
        # rather than zero.
        "entities": None,
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
