"""Catalog controls for browsing and loading Our World In Data."""
from __future__ import annotations

import asyncio

import pandas as pd
from lumen.ai.controls import CatalogSourceControls
from lumen.ai.controls.ingest import SourceResult

from .api import MAX_HITS, charts_to_catalog, search_catalog, search_charts
from .source import OWIDSource, UnreadableDataset


class OWIDSourceControls(CatalogSourceControls):
    """Browse Our World In Data and load any chart or indicator into DuckDB.

    The table lists popular charts as a starting point. Because OWID publishes over
    twelve thousand charts, far too many to embed locally, the agent-facing search
    delegates to OWID's own search APIs rather than the vector store.
    """

    detail_columns = ["description", "kind", "url"]

    # Leaves room for the download button column the base class appends; widths
    # summing to 100% push it off the right edge of the table.
    display_columns = {
        "title": {"title": "Title", "width": "28%"},
        "description": {"title": "Description", "width": "47%"},
        "kind": {"title": "Kind", "width": "10%"},
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
        return SourceResult.from_source(source, entry.table_name, message=f"Loaded {entry.title}.")

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
