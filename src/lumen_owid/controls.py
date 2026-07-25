"""Source controls for browsing and loading Our World In Data.

OWID publishes its data as CSV and parquet over plain HTTPS, and ``DuckDBSource``
already turns such a URL into a ``READ_CSV``/``READ_PARQUET`` expression on its own.
Nothing here downloads, parses, or caches data. This module only does discovery:
it surfaces the OWID catalog and hands OWID's own descriptions to the LLM.
"""
from __future__ import annotations

import asyncio

import httpx
import pandas as pd

from lumen.ai.controls import CatalogSourceControls
from lumen.ai.controls.ingest import SourceResult
from lumen.sources.duckdb import DuckDBSource
from lumen.util import normalize_table_name

CHART_SEARCH = "https://ourworldindata.org/api/search"
GRAPHER = "https://ourworldindata.org/grapher"
INDICATOR_SEARCH = "https://search.owid.io/indicators"

# httpfs lets DuckDB range-read the remote CSV and parquet files in place.
INITIALIZERS = ["INSTALL httpfs;", "LOAD httpfs;"]

# The chart search API rejects hitsPerPage above 100.
MAX_HITS = 100

TIMEOUT = 30


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


def charts_to_catalog(hits: pd.DataFrame) -> pd.DataFrame:
    """Normalize chart search hits onto the shared catalog columns."""
    return pd.DataFrame({
        "title": hits["title"],
        "description": hits.get("subtitle", ""),
        "kind": "chart",
        "url": hits["slug"].map(lambda slug: f"{GRAPHER}/{slug}.csv"),
        "table_name": hits["slug"].map(normalize_table_name),
        "slug": hits["slug"],
        "column": None,
    })


def indicators_to_catalog(hits: pd.DataFrame) -> pd.DataFrame:
    """Normalize indicator search hits onto the shared catalog columns.

    An indicator's parquet holds its whole source dataset, so the table is named
    after the dataset and the matched indicator is recorded in ``column``.
    """
    return pd.DataFrame({
        "title": hits["title"],
        "description": hits.get("description", ""),
        "kind": "indicator",
        "url": hits["metadata.parquet_url"],
        "table_name": hits["catalog_path"].map(
            lambda path: normalize_table_name(path.split("#")[0].split("/")[-1])
        ),
        "slug": None,
        "column": hits["metadata.column"],
    })


class OWIDControls(CatalogSourceControls):
    """Browse Our World In Data and load any chart or indicator into DuckDB.

    The Tabulator lists popular charts as a starting point. Because OWID publishes
    over twelve thousand charts, far too many to embed locally, the agent-facing
    search delegates to OWID's own search APIs instead of the vector store.
    """

    label = "Our World In Data"

    display_columns = {
        "title": {"title": "Title", "width": "30%"},
        "description": {"title": "Description", "width": "55%"},
        "kind": {"title": "Kind", "width": "15%"},
    }

    filter_columns = {"title": {"type": "input", "func": "like", "placeholder": "Filter titles"}}

    search_columns = ["title", "description"]

    detail_columns = ["description", "kind", "url"]

    def __init__(self, **params):
        super().__init__(**params)
        # One shared source for every dataset loaded. SQLAgent only avoids a
        # materializing cross-source merge when all tables live together, so
        # keeping a single source is what makes OWID joins cheap.
        self._source = DuckDBSource(
            uri=":memory:", ephemeral=True, initializers=INITIALIZERS, tables={},
            name="ourworldindata",
        )

    async def _load_catalog(self) -> pd.DataFrame:
        hits = await asyncio.to_thread(search_charts, "", MAX_HITS)
        return charts_to_catalog(hits)

    async def _fetch_entry(self, entry: pd.Series) -> SourceResult:
        table = entry.table_name
        if entry.kind == "chart":
            description = await asyncio.to_thread(self._table_metadata, entry.slug)
        else:
            description = {
                "description": f"{entry.description} Relevant column: {entry.column}.",
            }
        # create_sql_expr_source unions the new table with those already loaded.
        # A parquet URL can go in bare, since DuckDBSource builds READ_PARQUET itself,
        # but chart CSVs need an explicit sample_size: OWID leaves annotation columns
        # empty for thousands of rows before a quoted value appears, which defeats
        # DuckDB's default 20480-row type sniff and aborts the read mid-file.
        expression = entry.url
        if entry.kind == "chart":
            expression = f"SELECT * FROM read_csv('{entry.url}', sample_size=-1)"
        self._source = self._source.create_sql_expr_source(
            {table: expression},
            materialize=True,
            metadata={**self._source.metadata, table: description},
        )
        self._register_source_output(self._source)
        return SourceResult.from_source(self._source, table, message=f"Loaded {entry.title}.")

    async def _search_catalog(self, query: str) -> int | None:
        """Search OWID live, charts first, then the uncharted indicator long tail.

        Returning an index into ``catalog_df`` keeps the whole base loader
        (fetch, source registration, progress) working unchanged.
        """
        for search, to_catalog in ((search_charts, charts_to_catalog), (search_indicators, indicators_to_catalog)):
            try:
                hits = await asyncio.to_thread(search, query, 5)
            except httpx.HTTPError:
                # The indicator service is a separate deployment under active
                # development, so a failure there degrades to charts-only
                # rather than taking the whole search down.
                continue
            if hits.empty:
                continue
            self.catalog_df = pd.concat(
                [self.catalog_df, to_catalog(hits.head(1))], ignore_index=True,
            )
            return len(self.catalog_df) - 1
        return None

    @staticmethod
    def _table_metadata(slug: str) -> dict:
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
