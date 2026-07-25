from unittest.mock import Mock, patch

import pandas as pd

from lumen_owid.api import (
    align_column_docs,
    chart_table_metadata,
    charts_to_catalog,
    explain_unreadable,
    indicators_to_catalog,
    key_points,
    search_catalog,
    search_charts,
    search_indicators,
)


def _mock_get(payload):
    response = Mock()
    response.json.return_value = payload
    return patch("httpx.get", return_value=response)


def test_search_charts_flattens_results(chart_payload):
    with _mock_get(chart_payload):
        assert list(search_charts("x").slug) == ["homelessness-rate-point-in-time-count"]


def test_search_indicators_flattens_nested_metadata(indicator_payload):
    """The parquet URL lives under a nested key, so it must survive normalization."""
    with _mock_get(indicator_payload):
        assert search_indicators("x")["metadata.parquet_url"][0].endswith(".parquet")


def test_charts_to_catalog_builds_the_csv_url(chart_payload):
    with _mock_get(chart_payload):
        entry = charts_to_catalog(search_charts("x")).iloc[0]
    assert entry.url.endswith("/grapher/homelessness-rate-point-in-time-count.csv")
    assert entry.table_name == "homelessness_rate_point_in_time_count"
    assert entry.kind == "chart"


def test_indicators_are_named_after_the_dataset_not_the_column(indicator_payload):
    """An indicator's parquet holds its whole dataset, so the column name would mislead."""
    with _mock_get(indicator_payload):
        entry = indicators_to_catalog(search_indicators("x")).iloc[0]
    assert entry.table_name == "better_data_homelessness"
    assert entry.column == "people_homeless_per_10k"
    assert entry.kind == "indicator"


def test_both_surfaces_share_the_catalog_columns(chart_payload, indicator_payload):
    with _mock_get(chart_payload):
        charts = charts_to_catalog(search_charts("x"))
    with _mock_get(indicator_payload):
        indicators = indicators_to_catalog(search_indicators("x"))
    assert list(charts.columns) == list(indicators.columns)


def test_search_catalog_prefers_charts(chart_payload):
    charts = pd.DataFrame(chart_payload["results"])
    with patch("lumen_owid.api.search_charts", return_value=charts), \
         patch("lumen_owid.api.search_indicators") as indicators:
        assert search_catalog("x").iloc[0].kind == "chart"
    indicators.assert_not_called()


def test_search_catalog_survives_the_indicator_service_failing():
    """search.owid.io is a separate deployment, so its outage must not break search."""
    import httpx

    empty = pd.DataFrame({"slug": [], "title": [], "subtitle": []})
    with patch("lumen_owid.api.search_charts", return_value=empty), \
         patch("lumen_owid.api.search_indicators", side_effect=httpx.ConnectError("down")):
        assert search_catalog("x").empty


def test_a_served_but_unreadable_file_reports_the_real_cause():
    """A reassuring message here cost real debugging time once already."""
    with patch("httpx.get", return_value=Mock(raise_for_status=Mock(return_value=None))):
        message = explain_unreadable("https://example.org/x.parquet", ValueError("bad magic"))
    assert "bad magic" in message


def test_a_blocked_file_reports_owids_own_reason():
    import httpx

    reason = "This chart contains non-redistributable data"
    response = Mock(status_code=403)
    response.json.return_value = {"status": 403, "error": reason}
    error = httpx.HTTPStatusError("403", request=Mock(), response=response)
    with patch("httpx.get", return_value=Mock(raise_for_status=Mock(side_effect=error))):
        assert explain_unreadable("https://example.org/x.csv") == reason


KEY = (
    "- Data for the United Kingdom only considers England and is expressed in households.\n"
    "- France excludes asylum seekers to facilitate cross-country comparison.\n"
    "- Countries use different definitions and are harmonized to the extent possible."
)


def test_key_points_keeps_whole_bullets():
    """Half a caveat is worse than none, since it reads as a complete statement."""
    result = key_points(KEY, budget=200)
    assert result.startswith("Data for the United Kingdom")
    assert "France excludes asylum seekers to facilitate cross-country comparison." in result
    assert not result.endswith("harmoni")


def test_key_points_respects_the_budget():
    """A wide dataset would otherwise crowd the rest of the prompt out."""
    assert len(key_points(KEY, budget=100)) <= 100
    assert len(key_points(KEY, budget=10_000)) < len(KEY)  # bullet markers dropped


def test_key_points_tolerates_a_missing_field():
    assert key_points(None) == ""
    assert key_points("") == ""
    assert key_points("- ") == ""


def test_chart_metadata_forwards_the_caveats_to_the_model():
    payload = {
        "chart": {"title": "Homelessness rate", "subtitle": "sub", "citation": "OECD (2024)"},
        "columns": {
            "Rate": {
                "descriptionShort": "People sleeping rough.",
                "unit": "people per 100,000",
                "descriptionKey": KEY,
            }
        },
    }
    with _mock_get(payload):
        metadata = chart_table_metadata("some-slug")

    column = metadata["columns"]["Rate"]
    assert "People sleeping rough." in column
    assert "people per 100,000" in column
    assert "United Kingdom only considers England" in column


def test_the_key_point_budget_is_shared_across_columns():
    """A one-column chart should keep everything; a wide one must still fit.

    Measured over 59 charts the median carries 234 characters in total, so a fixed
    per-column budget would truncate the informative charts to protect against a case
    that is rare.
    """
    long_key = "\n".join(f"- Caveat number {i} about how this was measured." for i in range(60))

    def build(column_count):
        payload = {
            "chart": {"title": "T"},
            "columns": {
                f"col{i}": {"descriptionShort": "s", "descriptionKey": long_key}
                for i in range(column_count)
            },
        }
        with _mock_get(payload):
            return chart_table_metadata("slug")["columns"]

    narrow = build(1)["col0"]
    wide = build(30)
    # The narrow chart keeps far more per column, but every column of the wide one
    # still carries several whole caveats rather than being squeezed to nothing.
    assert len(narrow) > 4 * len(wide["col0"])
    assert all(text.count("Caveat number") >= 3 for text in wide.values())
    assert sum(len(text) for text in wide.values()) < 30 * len(narrow)


def test_a_single_oversized_bullet_is_still_returned():
    """Dropping it entirely would lose the caveat, which is the point of the function."""
    single = "- " + "This measurement is not comparable across countries. " * 20
    assert key_points(single, budget=50).startswith("This measurement is not comparable")


def test_chart_entries_carry_how_many_entities_they_cover(chart_payload):
    """Coverage decides whether a dataset can answer a question before it is loaded."""
    payload = {"results": [dict(chart_payload["results"][0], availableEntities=["a", "b", "c"])]}
    with _mock_get(payload):
        entry = charts_to_catalog(search_charts("x")).iloc[0]
    assert entry.entities == 3


def test_a_chart_without_an_entity_list_reports_unknown_not_zero(chart_payload):
    with _mock_get(chart_payload):
        entry = charts_to_catalog(search_charts("x")).iloc[0]
    assert entry.entities is None


def test_indicator_coverage_is_unknown(indicator_payload):
    """The indicator API publishes no entity list, so claiming zero would be wrong."""
    with _mock_get(indicator_payload):
        entry = indicators_to_catalog(search_indicators("x")).iloc[0]
    assert entry.entities is None
def test_column_docs_prefer_an_exact_name_match():
    docs = {"Life expectancy": "how long people live"}
    aligned = align_column_docs(docs, ["Entity", "Year", "Life expectancy"])
    assert aligned == {"Life expectancy": "how long people live"}


def test_column_docs_fall_back_to_position_when_the_chart_renames():
    """The homelessness chart renames all three of its indicators, so names never match.

    Its CSV headers describe where people slept; the metadata keys are ETHOS
    categories. Position is what connects them.
    """
    docs = {
        "Rate of people experiencing homelessness (ETHOS 1)": "streets",
        "Rate of people experiencing homelessness (ETHOS 2 and 3)": "shelters",
        "Rate of people experiencing homelessness (ETHOS 1, 2 and 3)": "either",
    }
    columns = [
        "Entity", "Code", "Year",
        "Living in the streets or public spaces",
        "Staying in temporary accommodation or shelters",
        "Either",
    ]
    assert align_column_docs(docs, columns) == {
        "Living in the streets or public spaces": "streets",
        "Staying in temporary accommodation or shelters": "shelters",
        "Either": "either",
    }


def test_identifier_columns_never_consume_a_position():
    """Entity, Code and Year are not indicators; counting them would misalign everything."""
    aligned = align_column_docs({"Some indicator": "text"}, ["Entity", "Code", "Year", "Rate"])
    assert aligned == {"Rate": "text"}


def test_annotation_columns_are_skipped():
    """The Maddison GDP chart carries a trailing (Annotations) column."""
    docs = {"GDP per capita": "output per person"}
    columns = ["Entity", "Code", "Year", "GDP per capita", "GDP per capita (Annotations)"]
    assert align_column_docs(docs, columns) == {"GDP per capita": "output per person"}


def test_documentation_is_dropped_rather_than_guessed():
    """maternal-mortality documents three indicators but plots two.

    Attaching the wrong caveat to a column is worse than attaching none.
    """
    docs = {"A": "a", "B": "b", "C": "c"}
    assert align_column_docs(docs, ["Entity", "Year", "First", "Second"]) == {}


def test_a_partial_name_match_still_aligns_the_rest():
    docs = {"Rate": "the rate", "Renamed indicator": "the other one"}
    aligned = align_column_docs(docs, ["Entity", "Rate", "Something else"])
    assert aligned == {"Rate": "the rate", "Something else": "the other one"}
