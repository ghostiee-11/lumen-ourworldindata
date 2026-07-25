"""A DuckDB source that reads Our World In Data in place."""
from __future__ import annotations

from typing import ClassVar

import duckdb
import httpx
from lumen.sources.duckdb import DuckDBSource

from .api import chart_table_metadata, explain_unreadable

# httpfs lets DuckDB range-read the remote CSV and parquet files without downloading.
INITIALIZERS = ["INSTALL httpfs;", "LOAD httpfs;"]


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
        from .api import GRAPHER, normalize_name

        url = f"{GRAPHER}/{slug}.csv"
        # Chart CSVs need an explicit sample_size: OWID leaves annotation columns
        # empty for thousands of rows before a quoted value appears, which defeats
        # DuckDB's default 20480-row type sniff and aborts the read mid-file.
        return self._add(
            table or normalize_name(slug),
            f"SELECT * FROM read_csv('{url}', sample_size=-1)",
            url,
            lambda: chart_table_metadata(slug),
        )

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
