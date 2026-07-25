from unittest.mock import Mock, patch

import pandas as pd

from lumen_owid.api import (
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
