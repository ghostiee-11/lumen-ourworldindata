import asyncio

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from lumen_owid import OWIDControls, search_charts, search_indicators
from lumen_owid.controls import (
    chart_metadata, charts_to_catalog, indicators_to_catalog,
)

CHART_PAYLOAD = {
    "results": [
        {
            "slug": "homelessness-rate-point-in-time-count",
            "title": "Homelessness rate",
            "subtitle": "Population reported as experiencing homelessness...",
        }
    ]
}

INDICATOR_PAYLOAD = {
    "results": [
        {
            "title": "Rate of people experiencing homelessness",
            "description": "Includes people living in the streets...",
            "catalog_path": "grapher/oecd/2024-04-30/affordable_housing_database/affordable_housing_database#point_in_time_total",
            "metadata": {
                "parquet_url": "https://catalog.ourworldindata.org/grapher/oecd/2024-04-30/affordable_housing_database/affordable_housing_database.parquet",
                "column": "point_in_time_total",
            },
        }
    ]
}


def _mock_get(payload):
    response = Mock()
    response.json.return_value = payload
    return patch("httpx.get", return_value=response)


def test_search_charts_flattens_results():
    with _mock_get(CHART_PAYLOAD):
        df = search_charts("homelessness")
    assert list(df.slug) == ["homelessness-rate-point-in-time-count"]


def test_search_indicators_flattens_nested_metadata():
    """The parquet URL lives under a nested key, so it must survive normalization."""
    with _mock_get(INDICATOR_PAYLOAD):
        df = search_indicators("homelessness")
    assert df["metadata.parquet_url"][0].endswith(".parquet")


def test_charts_to_catalog_builds_the_csv_url():
    with _mock_get(CHART_PAYLOAD):
        entry = charts_to_catalog(search_charts("homelessness")).iloc[0]
    assert entry.url == (
        "https://ourworldindata.org/grapher/homelessness-rate-point-in-time-count.csv"
    )
    assert entry.table_name == "homelessness_rate_point_in_time_count"
    assert entry.kind == "chart"


def test_indicators_are_named_after_the_dataset_not_the_column():
    """An indicator's parquet holds its whole dataset, so the column name would mislead."""
    with _mock_get(INDICATOR_PAYLOAD):
        entry = indicators_to_catalog(search_indicators("homelessness")).iloc[0]
    assert entry.table_name == "affordable_housing_database"
    assert entry.column == "point_in_time_total"
    assert entry.url.endswith(".parquet")


def test_both_surfaces_share_the_catalog_columns():
    with _mock_get(CHART_PAYLOAD):
        charts = charts_to_catalog(search_charts("x"))
    with _mock_get(INDICATOR_PAYLOAD):
        indicators = indicators_to_catalog(search_indicators("x"))
    assert list(charts.columns) == list(indicators.columns)


@pytest.mark.network
def test_live_endpoints_still_return_the_columns_we_rely_on():
    charts = search_charts("", limit=5)
    assert {"slug", "title", "subtitle"} <= set(charts.columns)

    indicators = search_indicators("gdp per capita", limit=3)
    assert {"metadata.parquet_url", "metadata.column", "catalog_path"} <= set(indicators.columns)

    metadata = chart_metadata("homelessness-rate-point-in-time-count")
    assert metadata["chart"]["title"]


@pytest.mark.network
def test_homelessness_against_gdp_lands_in_one_source_and_joins():
    """The end to end guard: two surfaces, one source, and the headline finding.

    A chart CSV and an indicator parquet must end up in the same DuckDB source,
    otherwise SQLAgent falls back to a materializing cross-source merge. The
    correlation is asserted loosely so this fails when OWID reshapes a table
    rather than when a single value shifts.
    """
    controls = OWIDControls()
    controls.catalog_df = asyncio.run(controls._load_catalog())
    entries = pd.concat([
        indicators_to_catalog(search_indicators("homelessness point in time total", 3).head(1)),
        charts_to_catalog(search_charts("GDP per capita maddison project database", 5).head(1)),
    ], ignore_index=True)
    for _, entry in entries.iterrows():
        asyncio.run(controls._fetch_entry(entry))

    source = controls._source
    assert set(source.get_tables()) == {
        "affordable_housing_database", "gdp_per_capita_maddison_project_database",
    }
    assert all(source.metadata[table]["description"] for table in source.get_tables())

    joined = source.execute("""
        WITH h AS (SELECT country, point_in_time_total AS rate,
                     row_number() OVER (PARTITION BY country ORDER BY year DESC) AS rn
                   FROM affordable_housing_database WHERE point_in_time_total IS NOT NULL),
             g AS (SELECT "Entity" AS country, "GDP per capita" AS gdp,
                     row_number() OVER (PARTITION BY "Entity" ORDER BY "Year" DESC) AS rn
                   FROM gdp_per_capita_maddison_project_database
                   WHERE "GDP per capita" IS NOT NULL)
        SELECT h.country, h.rate, g.gdp FROM h JOIN g ON h.country = g.country
        WHERE h.rn = 1 AND g.rn = 1
    """)
    assert len(joined) >= 20
    assert abs(joined.rate.corr(joined.gdp)) < 0.3


@pytest.mark.network
def test_live_search_reaches_charts_beyond_the_loaded_catalog():
    """OWID has over 12,000 charts, so search must go to OWID, not the local frame."""
    controls = OWIDControls()
    controls.catalog_df = asyncio.run(controls._load_catalog())
    before = len(controls.catalog_df)

    index = asyncio.run(controls._search_catalog("homelessness rate point in time"))
    assert index == before
    assert "homelessness" in controls.catalog_df.iloc[index].title.lower()
