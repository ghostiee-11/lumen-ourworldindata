from unittest.mock import Mock, patch

import duckdb
import pytest

from lumen_owid.source import INITIALIZERS, OWIDSource, UnreadableDataset


def _captured_sql(method, *args, **kwargs):
    """Run an add_* method against a stubbed connection and return the SQL it ran.

    The whole connection is swapped rather than its execute method, because
    DuckDBPyConnection attributes are read-only and cannot be patched in place.
    """
    source = OWIDSource()
    connection = Mock()
    with patch.object(source, "_connection", connection), \
         patch.object(source, "create_sql_expr_source") as create, \
         patch("lumen_owid.source.chart_table_metadata", return_value={"description": "d"}):
        getattr(source, method)(*args, **kwargs)
    return connection.execute.call_args.args[0], create.call_args


def test_defaults_load_httpfs():
    """Without httpfs DuckDB cannot open an https URL at all."""
    assert OWIDSource().initializers == INITIALIZERS


def test_a_chart_is_read_with_a_full_type_sniff():
    """OWID leaves annotation columns empty past DuckDB's default 20480-row sample.

    Without an explicit sample_size the read aborts partway through the file.
    """
    sql, _ = _captured_sql("add_chart", "some-slug")
    assert "read_csv(" in sql
    assert "sample_size=-1" in sql


def test_an_indicator_is_wrapped_in_a_select():
    """A bare URL is not a statement, so CREATE TABLE AS (url) is a syntax error.

    This shipped broken once: charts worked because they were already a SELECT.
    """
    url = "https://catalog.ourworldindata.org/grapher/x/y/z/z.parquet"
    sql, _ = _captured_sql("add_indicator", url, "z", "col", "desc")
    assert sql.startswith('CREATE OR REPLACE TABLE "z" AS (SELECT')
    assert f"read_parquet('{url}')" in sql


def test_the_matched_indicator_column_reaches_the_metadata():
    """The model has to choose between many near-identical series."""
    _, create = _captured_sql(
        "add_indicator", "https://example.org/z.parquet", "z", "people_per_10k", "Counts people.",
    )
    assert "people_per_10k" in create.kwargs["metadata"]["z"]["description"]


def test_data_is_materialized_rather_than_left_as_a_view():
    """A view over read_csv refetches on every query and breaks windowed aggregates."""
    sql, create = _captured_sql("add_chart", "some-slug")
    assert sql.startswith("CREATE OR REPLACE TABLE")
    assert create.kwargs["materialize"] is False


def test_an_unreadable_dataset_raises_with_owids_reason():
    source = OWIDSource()
    connection = Mock()
    connection.execute.side_effect = duckdb.Error("HTTP 0")
    with patch.object(source, "_connection", connection), \
         patch("lumen_owid.source.explain_unreadable", return_value="not redistributable"), \
         patch("lumen_owid.source.chart_table_metadata", return_value={"description": "d"}):
        with pytest.raises(UnreadableDataset, match="not redistributable"):
            source.add_chart("blocked-slug")
