"""Live guard against Our World In Data changing shape.

The rest of the suite is mocked, which keeps CI fast and deterministic but would not
notice if OWID renamed a column, retired an endpoint or changed a response shape.
These tests hit the real services and are expected to be run on demand.
"""
import pytest

from lumen_owid import LatestPerCountry, OnlyCountries, OWIDSource, UnreadableDataset
from lumen_owid.api import (
    chart_metadata,
    indicators_to_catalog,
    search_catalog,
    search_charts,
    search_indicators,
)

pytestmark = pytest.mark.network


def test_the_chart_search_still_returns_the_fields_we_build_urls_from():
    charts = search_charts("", limit=5)
    assert {"slug", "title", "subtitle"} <= set(charts.columns)
    assert len(charts) == 5


def test_the_indicator_search_still_returns_a_parquet_url():
    indicators = search_indicators("gdp per capita", limit=3)
    assert {"metadata.parquet_url", "metadata.column", "catalog_path"} <= set(indicators.columns)
    assert indicators["metadata.parquet_url"][0].endswith(".parquet")


def test_chart_metadata_still_carries_the_prose_the_model_relies_on():
    metadata = chart_metadata("life-expectancy")
    assert metadata["chart"]["title"]
    assert all("unit" in column for column in metadata["columns"].values())


def test_search_catalog_prefers_a_chart_for_a_charted_topic():
    assert search_catalog("life expectancy").iloc[0].kind == "chart"


def test_a_chart_loads_into_a_real_table():
    """A view over read_csv refetches on every query and breaks window functions."""
    source = OWIDSource().add_chart("life-expectancy")
    assert "life_expectancy" in source.get_tables()
    assert source.execute("SELECT table_name FROM duckdb_tables()").table_name.tolist()
    assert len(source.get("life_expectancy")) > 1000


def test_both_surfaces_land_in_one_source_and_join():
    """Lumen only keeps a join in SQL when every table shares one source."""
    entry = indicators_to_catalog(search_indicators("homelessness per 10,000 people", 3)).iloc[0]
    source = (
        OWIDSource()
        .add_indicator(entry.url, entry.table_name, entry.column, entry.description or "")
        .add_chart("gdp-per-capita-maddison-project-database")
    )
    assert len(source.get_tables()) == 2
    assert all(source.metadata[table]["description"] for table in source.get_tables())

    joined = source.execute("""
        WITH h AS (SELECT country, people_homeless_per_10k AS rate,
                     row_number() OVER (PARTITION BY country ORDER BY year DESC) AS rn
                   FROM better_data_homelessness WHERE people_homeless_per_10k IS NOT NULL),
             g AS (SELECT "Entity" AS country, "GDP per capita" AS gdp,
                     row_number() OVER (PARTITION BY "Entity" ORDER BY "Year" DESC) AS rn
                   FROM gdp_per_capita_maddison_project_database
                   WHERE "GDP per capita" IS NOT NULL)
        SELECT h.country, h.rate, g.gdp FROM h JOIN g ON h.country = g.country
        WHERE h.rn = 1 AND g.rn = 1
    """)
    assert len(joined) > 100


def test_a_non_redistributable_chart_declines_with_owids_reason():
    """About 2% of charts are listed but blocked, so this path is not an edge case."""
    with pytest.raises(UnreadableDataset, match="redistribut"):
        OWIDSource().add_chart("suicide-death-rates")


def test_only_countries_drops_owids_aggregates_from_a_real_table():
    """The UN population table ships continents and income groups beside countries."""
    source = OWIDSource().add_chart("population-with-un-projections")
    sql = LatestPerCountry(country="Entity", year="Year", value="Population").apply(
        "SELECT * FROM population_with_un_projections"
    )
    before = source.execute(sql)
    after = source.execute(OnlyCountries().apply(sql))

    assert len(after) < len(before)
    # Every survivor is a real ISO alpha-3 country, including no UN_ regions, which
    # an earlier prefix-matching version let through.
    assert (after.Code.str.len() == 3).all()
    for aggregate in ("Africa", "Europe (UN)", "Least developed countries"):
        assert aggregate in set(before.Entity)
        assert aggregate not in set(after.Entity)


def test_column_documentation_lands_on_columns_that_exist():
    """Shipped broken once: OWID keys metadata by indicator title, not CSV header.

    Documentation attached to a name the table does not have is invisible to the
    model, which quietly wasted the caveats this package exists to forward.
    """
    for slug in ("life-expectancy", "homelessness-rate-point-in-time-count", "child-mortality"):
        source = OWIDSource().add_chart(slug)
        table = source.get_tables()[0]
        documented = set(source.metadata[table]["columns"])
        assert documented, f"{slug} documented no columns at all"
        assert documented <= set(source.get(table).columns), f"{slug} documented a phantom column"
