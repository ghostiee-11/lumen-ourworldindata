import pandas as pd
import pytest

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
            "title": "People experiencing homelessness per 10,000 people",
            "description": "Due to different definitions and data collection methods...",
            "catalog_path": (
                "grapher/igh/2024-07-05/better_data_homelessness/"
                "better_data_homelessness#people_homeless_per_10k"
            ),
            "metadata": {
                "parquet_url": (
                    "https://catalog.ourworldindata.org/grapher/igh/2024-07-05/"
                    "better_data_homelessness/better_data_homelessness.parquet"
                ),
                "column": "people_homeless_per_10k",
            },
        }
    ]
}


@pytest.fixture
def chart_payload():
    return CHART_PAYLOAD


@pytest.fixture
def indicator_payload():
    return INDICATOR_PAYLOAD


@pytest.fixture
def owid_frame():
    """A small OWID-shaped table: long format, one row per country per year."""
    return pd.DataFrame({
        "Entity": ["France", "France", "Japan", "Japan", "Norway"],
        "Code": ["FRA", "FRA", "JPN", "JPN", "NOR"],
        "Year": [2000, 2020, 2000, 2020, 2020],
        "Rate": [10.0, 20.0, 5.0, 2.5, None],
        "Population": [59.0, 67.0, 126.0, 125.0, 5.4],
    })
