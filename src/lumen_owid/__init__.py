"""Chat with Our World In Data.

Our World In Data serves its charts and indicators as CSV and parquet over plain
HTTPS, which DuckDB reads in place. Nothing in this package downloads or caches
data: it supplies discovery, the metadata that lets a model pick the right series,
and the handful of reshapes and views that OWID's country/year tables always need.
"""
from .analysis import (
    ANALYSES,
    CompareCountries,
    CorrelateIndicators,
    MapAcrossCountries,
)
from .api import (
    chart_metadata,
    search_catalog,
    search_charts,
    search_indicators,
)
from .controls import OWIDSourceControls
from .operations import IndexToBaseYear, LatestPerCountry, OnlyCountries, PerCapita
from .source import OWIDSource, UnreadableDataset
from .ui import build_ui
from .views import OWIDChoropleth

__version__ = "0.1.0"

__all__ = [
    "ANALYSES",
    "CompareCountries",
    "CorrelateIndicators",
    "IndexToBaseYear",
    "LatestPerCountry",
    "MapAcrossCountries",
    "OWIDChoropleth",
    "OWIDSource",
    "OWIDSourceControls",
    "OnlyCountries",
    "PerCapita",
    "UnreadableDataset",
    "build_ui",
    "chart_metadata",
    "search_catalog",
    "search_charts",
    "search_indicators",
]
