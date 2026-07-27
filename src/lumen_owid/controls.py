"""Catalog controls for browsing and loading Our World In Data."""
from __future__ import annotations

import asyncio

import pandas as pd
import param
from lumen.ai.controls import CatalogSourceControls
from lumen.ai.controls.ingest import SourceResult, URLSourceControls

from .api import (
    GRAPHER,
    MAX_HITS,
    chart_slug,
    charts_to_catalog,
    normalize_name,
    search_catalog,
    search_charts,
)
from .source import OWIDSource, UnreadableDataset


class OWIDSourceControls(CatalogSourceControls):
    """Browse Our World In Data and load any chart or indicator into DuckDB.

    The table lists popular charts as a starting point. Because OWID publishes over
    twelve thousand charts, far too many to embed locally, the agent-facing search
    delegates to OWID's own search APIs rather than the vector store.
    """

    detail_columns = ["description", "kind", "entities", "url"]

    # Leaves room for the download button column the base class appends; widths
    # summing to 100% push it off the right edge of the table.
    display_columns = {
        "title": {"title": "Title", "width": "26%"},
        "description": {"title": "Description", "width": "42%"},
        "kind": {"title": "Kind", "width": "9%"},
        "entities": {"title": "Entities", "width": "9%"},
    }

    filter_columns = {"title": {"type": "input", "func": "like", "placeholder": "Filter titles"}}

    label = "Our World In Data"

    search_columns = ["title", "description"]

    def __init__(self, **params):
        super().__init__(**params)
        # One source for every dataset loaded, so joins across OWID stay in SQL.
        self._source = OWIDSource()

    async def _load_catalog(self) -> pd.DataFrame:
        return charts_to_catalog(await asyncio.to_thread(search_charts, "", MAX_HITS))

    async def _fetch_entry(self, entry: pd.Series) -> SourceResult:
        try:
            if entry.kind == "chart":
                source = await asyncio.to_thread(
                    self._source.add_chart, entry.slug, entry.table_name,
                )
            else:
                source = await asyncio.to_thread(
                    self._source.add_indicator, entry.url, entry.table_name,
                    entry.column, entry.description or "",
                )
        except UnreadableDataset as error:
            # OWID lists charts it will not serve, so this has to read as a message
            # carrying OWID's own reason rather than as an error.
            return SourceResult.empty(f"{entry.title} cannot be loaded. {error}")
        self._source = source
        self._register_source_output(source)
        # Coverage decides whether a dataset can answer the question at all, and a
        # join between a 23-entity table and a 285-entity one mostly produces nulls.
        coverage = f" Covers {entry.entities} entities." if entry.entities else ""
        return SourceResult.from_source(
            source, entry.table_name, message=f"Loaded {entry.title}.{coverage}",
        )

    async def _search_catalog(self, query: str) -> int | None:
        """Search OWID live rather than the local frame.

        Returning an index into ``catalog_df`` keeps the whole base loader (fetch,
        source registration, progress reporting) working unchanged.
        """
        hits = await asyncio.to_thread(search_catalog, query)
        if hits.empty:
            return None
        self.catalog_df = pd.concat([self.catalog_df, hits.head(1)], ignore_index=True)
        return len(self.catalog_df) - 1


class OWIDChartControls(URLSourceControls):
    """Load one specific Our World In Data chart, by slug or by pasted URL.

    The catalog controls answer "which chart do I want"; this answers "load the one I
    already have". Searching for a slug is not a substitute: searching for
    ``co2-emissions-per-capita`` returns ``co-emissions-per-capita``, a different chart.
    Since people cite OWID by pasting a grapher URL, that has to be a first-class way in.

    Built on ``URLSourceControls`` for the widget and the generated agent tool, but the
    download is replaced: OWID chart CSVs need an explicit ``sample_size`` and carry
    documentation worth attaching, neither of which a generic download provides.
    """

    label = "Our World In Data chart"

    slug = param.String(default="", doc="""
        Chart slug, or any grapher URL to take it from.""")

    url_template = f"{GRAPHER}/{{slug}}.csv"

    _query_params = ["slug"]

    def __init__(self, **params):
        super().__init__(**params)
        self._source = OWIDSource()

    async def _fetch_data(self, action_name: str, **params) -> SourceResult:
        """Load the chart through OWIDSource rather than a generic download."""
        reference = params.get("slug") or self.slug
        if not reference:
            return SourceResult.empty("Give a chart slug or a grapher URL.")

        slug = chart_slug(reference)
        self.progress(f"Loading {slug}…")
        try:
            source = await asyncio.to_thread(self._source.add_chart, slug)
        except UnreadableDataset as error:
            return SourceResult.empty(f"{slug} cannot be loaded. {error}")

        self._source = source
        self._register_source_output(source)
        table = normalize_name(slug)
        return SourceResult.from_source(source, table, message=f"Loaded {slug}.")
