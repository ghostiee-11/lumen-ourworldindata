from unittest.mock import Mock, patch

import pandas as pd

from lumen_owid.api import (
    charts_to_catalog,
    explain_unreadable,
    indicators_to_catalog,
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
