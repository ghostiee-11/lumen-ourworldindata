import asyncio
from unittest.mock import patch

import pytest

from lumen_owid import OWIDChartControls
from lumen_owid.api import chart_slug
from lumen_owid.source import UnreadableDataset


@pytest.mark.parametrize("reference", [
    "co2-emissions-per-capita",
    "https://ourworldindata.org/grapher/co2-emissions-per-capita",
    "https://ourworldindata.org/grapher/co2-emissions-per-capita.csv",
    "https://ourworldindata.org/grapher/co2-emissions-per-capita?tab=map&country=USA",
    "ourworldindata.org/grapher/co2-emissions-per-capita/",
])
def test_a_slug_is_recoverable_from_any_way_people_cite_a_chart(reference):
    """People paste grapher URLs; requiring a bare slug would reject the common case."""
    assert chart_slug(reference) == "co2-emissions-per-capita"


def test_loading_by_slug_is_not_the_same_as_searching_for_it():
    """Search for 'co2-emissions-per-capita' returns 'co-emissions-per-capita'.

    That near miss is the reason this control exists rather than leaving slugs to the
    catalog search.
    """
    assert chart_slug("co2-emissions-per-capita") == "co2-emissions-per-capita"


def test_the_chart_control_exposes_a_tool_to_the_agent():
    assert [name for name, _ in OWIDChartControls().as_tools()]


def test_loading_routes_through_owid_source_not_a_generic_download():
    """A generic download loses the sample_size fix and OWID's documentation."""
    controls = OWIDChartControls()
    with patch.object(controls._source, "add_chart") as add_chart:
        add_chart.return_value = controls._source
        asyncio.run(controls._fetch_data(None, slug="https://ourworldindata.org/grapher/x"))
    add_chart.assert_called_once_with("x")


def test_a_blocked_chart_declines_with_the_reason():
    controls = OWIDChartControls()
    with patch.object(
        controls._source, "add_chart", side_effect=UnreadableDataset("not redistributable"),
    ):
        result = asyncio.run(controls._fetch_data(None, slug="blocked"))
    assert result.sources == []
    assert "not redistributable" in result.message


def test_nothing_to_load_says_so():
    result = asyncio.run(OWIDChartControls()._fetch_data(None, slug=""))
    assert "slug or a grapher URL" in result.message
