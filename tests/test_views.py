import pandas as pd
import panel as pn
import pytest
from lumen.pipeline import Pipeline
from lumen.sources.duckdb import DuckDBSource

from lumen_owid.views import OWIDTimeSeries


@pytest.fixture
def wide_frame():
    """Twelve countries over three years, with uneven coverage.

    France and Japan report every year, the rest report once, which is what makes
    "best covered" a meaningful ordering.
    """
    rows = []
    for year in (2000, 2010, 2020):
        rows += [
            {"country": "France", "year": year, "rate": 10.0 + year % 100},
            {"country": "Japan", "year": year, "rate": 5.0 + year % 100},
        ]
    for i in range(10):
        rows.append({"country": f"Country {i}", "year": 2020, "rate": float(i)})
    return pd.DataFrame(rows)


def _view(frame, **params):
    source = DuckDBSource.from_df({"owid": frame})
    return OWIDTimeSeries(pipeline=Pipeline(source=source, table="owid"), **params)


def _series(panel):
    """The country of each line. hvplot(by=...) returns an NdOverlay keyed by country."""
    plot = panel[0].object if isinstance(panel, pn.Column) else panel.object
    return {key[0] if isinstance(key, tuple) else key for key in plot.keys()}


def _notes(panel):
    return " ".join(
        pane.object for pane in getattr(panel, "objects", [])
        if isinstance(getattr(pane, "object", None), str)
    )


def test_series_are_capped_and_the_omission_is_reported(wide_frame):
    """Two hundred lines communicate nothing, but a silent cap misleads."""
    panel = _view(wide_frame, value="rate", max_series=4).get_panel()
    notes = _notes(panel)
    assert "4 best-covered of 12" in notes
    assert "8 are not plotted" in notes


def test_the_best_covered_countries_are_the_ones_kept(wide_frame):
    """France and Japan have three observations each; everyone else has one."""
    panel = _view(wide_frame, value="rate", max_series=2).get_panel()
    assert _series(panel) == {"France", "Japan"}


def test_no_note_when_every_country_fits(wide_frame):
    panel = _view(wide_frame, value="rate", max_series=50).get_panel()
    assert not isinstance(panel, pn.Column)


def test_an_explicit_selection_wins_over_coverage(wide_frame):
    panel = _view(wide_frame, value="rate", countries=["Country 3"]).get_panel()
    assert _series(panel) == {"Country 3"}


def test_a_selection_that_matches_nothing_says_so(wide_frame):
    panel = _view(wide_frame, value="rate", countries=["Atlantis"]).get_panel()
    assert "Atlantis" in panel.object


def test_missing_columns_are_reported_rather_than_raised():
    frame = pd.DataFrame({"country": ["France"], "year": [2020]})
    assert "numeric column" in _view(frame).get_panel().object


def test_an_all_null_measure_is_reported():
    frame = pd.DataFrame({"country": ["France"], "year": [2020], "rate": [None]})
    assert "No values to plot" in _view(frame, value="rate").get_panel().object
