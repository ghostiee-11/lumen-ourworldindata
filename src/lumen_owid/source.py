"""A DuckDB source that reads Our World In Data in place."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar

import duckdb
import httpx
from lumen.sources.duckdb import DuckDBSource

from .api import GRAPHER, chart_table_metadata, explain_unreadable, normalize_name

# httpfs lets DuckDB range-read the remote CSV and parquet files without downloading.
INITIALIZERS = ["INSTALL httpfs;", "LOAD httpfs;"]


def chart_read_expression(slug: str) -> str:
    """SQL that reads a chart CSV in place.

    The explicit sample_size is required: OWID leaves annotation columns empty for
    thousands of rows before a quoted value appears, which defeats DuckDB's default
    20480-row type sniff and aborts the read mid-file.
    """
    return f"SELECT * FROM read_csv('{GRAPHER}/{slug}.csv', sample_size=-1)"


class UnreadableDataset(Exception):
    """Raised when OWID will not serve a dataset, carrying OWID's own reason.

    OWID answers 403 for charts built on data it is not licensed to redistribute and
    404 for charts that publish no CSV, yet both still appear in search results.
    """


class OWIDSource(DuckDBSource):
    """Reads Our World In Data charts and indicators directly over HTTPS.

    OWID serves CSV and parquet that DuckDB reads in place, so this never downloads
    or caches anything. Every dataset is added to the *same* source: Lumen only
    avoids a materializing cross-source merge when all tables share a source, which
    is what keeps joins across OWID datasets in SQL.
    """

    source_type: ClassVar[str] = "owid"

    def __init__(self, **params):
        params.setdefault("uri", ":memory:")
        params.setdefault("ephemeral", True)
        params.setdefault("initializers", INITIALIZERS)
        params.setdefault("tables", {})
        super().__init__(**params)

    def add_chart(self, slug: str, table: str | None = None) -> OWIDSource:
        """Add a published chart by slug, with OWID's prose attached as metadata."""
        return self._add(
            table or normalize_name(slug),
            chart_read_expression(slug),
            f"{GRAPHER}/{slug}.csv",
            lambda: chart_table_metadata(slug),
        )

    def add_charts(self, slugs: list[str]) -> tuple[OWIDSource, dict[str, str]]:
        """Add several charts, fetching their metadata concurrently.

        Most real questions need two or three datasets, and loading them one at a time
        serialises a documentation fetch per chart. Fetching those concurrently
        measured about 1.8x faster on three cold charts and 1.2x once OWID's CDN had
        them warm, so this helps but is not transformative. The data reads stay
        sequential because they write to one DuckDB connection.

        Returns the new source and a mapping of slug to reason for any chart that
        could not be loaded. Roughly 7% of OWID charts cannot be served at all, so one
        bad slug must not discard the rest of the batch.
        """
        if not slugs:
            return self, {}

        with ThreadPoolExecutor(max_workers=min(len(slugs), 8)) as pool:
            fetched = list(pool.map(self._describe, slugs))

        source, failures = self, {}
        for slug, metadata, error in fetched:
            if error is not None:
                failures[slug] = error
                continue
            try:
                source = source._register_chart(slug, metadata)
            except UnreadableDataset as unreadable:
                # A chart can document itself happily and still refuse to serve its
                # data, which is exactly what OWID does for non-redistributable
                # sources, so the read has to be guarded as well as the metadata.
                failures[slug] = str(unreadable)
        return source, failures

    def add_indicator(
        self, parquet_url: str, table: str, column: str | None = None, description: str = "",
    ) -> OWIDSource:
        """Add an indicator's parquet from the OWID ETL catalog."""
        detail = f"{description} Relevant column: {column}." if column else description
        return self._add(
            table,
            f"SELECT * FROM read_parquet('{parquet_url}')",
            parquet_url,
            lambda: {"description": detail},
        )

    def _register_chart(self, slug: str, metadata: dict) -> OWIDSource:
        """Load a chart whose metadata has already been fetched."""
        return self._add(
            normalize_name(slug),
            chart_read_expression(slug),
            f"{GRAPHER}/{slug}.csv",
            lambda: metadata,
        )

    @staticmethod
    def _describe(slug: str) -> tuple[str, dict | None, str | None]:
        """Fetch one chart's metadata, reporting failure rather than raising.

        Runs in a worker thread, where an exception would otherwise surface only when
        the result is read and would abandon the rest of the batch.
        """
        try:
            return slug, chart_table_metadata(slug), None
        except httpx.HTTPError as error:
            return slug, None, explain_unreadable(f"{GRAPHER}/{slug}.csv", error)

    def _add(self, table: str, expression: str, url: str, metadata) -> OWIDSource:
        try:
            resolved = metadata()
            # Read the remote file exactly once into a real table. Registering the
            # expression itself would leave a view over read_csv/read_parquet, which
            # re-fetches on every query and cannot serve a windowed aggregate at all
            # ("CSVReaderSerialize not implemented").
            self._connection.execute(f'CREATE OR REPLACE TABLE "{table}" AS ({expression})')
        except (duckdb.Error, httpx.HTTPStatusError) as error:
            raise UnreadableDataset(explain_unreadable(url, error)) from error
        # create_sql_expr_source unions the new table with those already loaded and
        # returns a source of this same type sharing the connection.
        return self.create_sql_expr_source(
            {table: f'SELECT * FROM "{table}"'},
            materialize=False,
            metadata={**self.metadata, table: resolved},
        )
