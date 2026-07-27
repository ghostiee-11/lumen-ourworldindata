from unittest.mock import patch

import duckdb
import pandas as pd
import pytest

from lumen_owid.operations import (
    IndexToBaseYear,
    LatestPerCountry,
    OnlyCountries,
    PerCapita,
    WithGeometry,
)


@pytest.fixture
def connection(owid_frame):
    """A real table, not a registered frame.

    DuckDB cannot run a windowed aggregate over a registered dataframe or a view
    over a reader, which is the same limitation that forced OWIDSource to
    materialize rather than register its remote files.
    """
    con = duckdb.connect()
    con.register("owid_frame", owid_frame)
    con.execute("CREATE TABLE owid AS SELECT * FROM owid_frame")
    return con


def _run(connection, transform):
    return connection.execute(transform.apply("SELECT * FROM owid")).df()


def test_latest_per_country_keeps_one_row_each(connection):
    result = _run(connection, LatestPerCountry(country="Entity", year="Year"))
    assert len(result) == 6  # three countries plus three aggregates
    assert result.Entity.duplicated().sum() == 0
    assert set(result.Year) == {2020}


def test_latest_per_country_skips_rows_where_the_measure_is_missing(connection):
    """Several OWID datasets project decades past the last real observation, so the
    newest row for a country is often one where the measure is still null."""
    result = _run(connection, LatestPerCountry(country="Entity", year="Year", value="Rate"))
    assert "Norway" not in set(result.Entity)
    assert result.Rate.notna().all()


def test_index_to_base_year_starts_every_country_at_100(connection):
    result = _run(
        connection, IndexToBaseYear(country="Entity", year="Year", value="Rate", base_year=2000),
    )
    base = result[result.Year == 2000]
    assert set(base.Rate_indexed.dropna().round()) == {100}
    france = result[(result.Entity == "France") & (result.Year == 2020)]
    assert france.Rate_indexed.iloc[0] == pytest.approx(200)


def test_per_capita_does_not_divide_by_zero(connection):
    connection.execute("INSERT INTO owid VALUES ('Nowhere', 'NOW', 2020, 5.0, 0)")
    result = _run(connection, PerCapita(value="Rate", population="Population"))
    nowhere = result[result.Entity == "Nowhere"].Rate_per_capita.iloc[0]
    assert nowhere != nowhere  # NULL, not an infinity that would blank out an axis


def test_transforms_without_a_value_are_a_no_op(connection):
    """Params default to None so the transforms compose before being configured."""
    assert _run(connection, PerCapita()).shape == (8, 5)
    assert _run(connection, IndexToBaseYear()).shape == (8, 5)


def test_only_countries_drops_every_kind_of_aggregate(connection):
    """OWID_ regions, UN_ regions and codeless groupings all have to go.

    Filtering on code length rather than a prefix list is what makes the UN_ case
    work; it was missed by an earlier prefix-matching version.
    """
    result = _run(connection, OnlyCountries())
    assert set(result.Entity) == {"France", "Japan", "Norway"}
    for aggregate in ("Africa", "Least developed countries", "Europe (UN)"):
        assert aggregate not in set(result.Entity)


def test_only_countries_keeps_every_real_country(connection):
    result = _run(connection, OnlyCountries())
    assert set(result.Code) == {"FRA", "JPN", "NOR"}


def test_only_countries_composes_with_latest(connection):
    """The map path applies both, so they have to nest cleanly."""
    sql = OnlyCountries().apply("SELECT * FROM owid")
    result = connection.execute(
        LatestPerCountry(country="Entity", year="Year", value="Rate").apply(sql)
    ).df()
    assert set(result.Entity) == {"France", "Japan"}
    assert result.Year.tolist() == [2020, 2020]


def test_with_geometry_attaches_boundaries_and_drops_unmappable_rows(owid_frame):
    """Aggregates have no boundary to draw, so an inner join is the honest shape."""
    # geopandas and shapely are the optional geo extra, so they load only here.
    import geopandas as gpd
    from shapely.geometry import Point

    boundaries = gpd.GeoDataFrame({
        "iso_a3": ["FRA", "JPN"],
        "country": ["France", "Japan"],
        "geometry": [Point(2, 48).buffer(1), Point(139, 35).buffer(1)],
    })
    # Patched where it is used: operations imports the name at module load.
    with patch("lumen_owid.operations.country_geometry", return_value=boundaries):
        result = WithGeometry().apply(owid_frame)

    assert set(result.Entity) == {"France", "Japan"}
    assert "geometry" in result.columns
    assert "Africa" not in set(result.Entity)


def test_with_geometry_is_a_no_op_without_a_country_column():
    frame = pd.DataFrame({"value": [1, 2]})
    assert WithGeometry().apply(frame).equals(frame)
