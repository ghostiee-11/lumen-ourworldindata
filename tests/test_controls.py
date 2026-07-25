from unittest.mock import Mock, patch

import pytest

from lumen_owid.controls import (
    chart_metadata, search_charts, search_indicators,
)

CHART_PAYLOAD = {
    "results": [
        {
            "slug": "homelessness-rate-point-in-time-count",
            "title": "Homelessness rate",
            "subtitle": "Population reported as experiencing homelessness...",
            "availableEntities": ["Australia", "Canada"],
        }
    ]
}

INDICATOR_PAYLOAD = {
    "results": [
        {
            "title": "Rate of people experiencing homelessness",
            "description": "Includes people living in the streets...",
            "catalog_path": "grapher/oecd/2024-04-30/ahd/ahd#point_in_time_total",
            "metadata": {
                "parquet_url": "https://catalog.ourworldindata.org/grapher/oecd/2024-04-30/ahd/ahd.parquet",
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
    assert df.title[0] == "Homelessness rate"


def test_search_indicators_flattens_nested_metadata():
    """The parquet URL lives under a nested key, so it must survive normalization."""
    with _mock_get(INDICATOR_PAYLOAD):
        df = search_indicators("homelessness")
    assert df["metadata.parquet_url"][0].endswith(".parquet")
    assert df["metadata.column"][0] == "point_in_time_total"


@pytest.mark.network
def test_live_endpoints_still_return_the_columns_we_rely_on():
    charts = search_charts("", limit=5)
    assert {"slug", "title", "subtitle"} <= set(charts.columns)

    indicators = search_indicators("gdp per capita", limit=3)
    assert {"metadata.parquet_url", "metadata.column"} <= set(indicators.columns)

    metadata = chart_metadata("homelessness-rate-point-in-time-count")
    assert metadata["chart"]["title"]
    assert all("unit" in column for column in metadata["columns"].values())
