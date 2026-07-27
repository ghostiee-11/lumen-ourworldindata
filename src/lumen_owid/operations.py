"""SQL transforms for the shapes Our World In Data always comes in.

Every OWID table is long format, one row per country per year, so the same three
reshapes show up in almost every question: take each country's most recent reading,
divide a total by population, or rebase a series so countries can be compared from a
common starting point. These are SQLTransforms so they compose into Lumen pipelines
and run inside DuckDB rather than pulling data into pandas.
"""
from __future__ import annotations

from typing import ClassVar

import param
from lumen.transforms.base import Transform
from lumen.transforms.sql import SQLTransform

from .utils import code_column, country_column, country_geometry


class OWIDTransform(SQLTransform):
    """Shared country and year column names.

    Chart CSVs spell these Entity/Year and indicator parquets spell them
    country/year, so both are parameters rather than assumptions.
    """

    country = param.String(default="country", doc="""
        Name of the column identifying the country or region.""")

    year = param.String(default="year", doc="""
        Name of the column identifying the time period.""")

    __abstract = True


class OnlyCountries(OWIDTransform):
    """Drop Our World In Data's aggregate rows, keeping actual countries.

    OWID publishes continents, income groups and custom regions alongside countries in
    the same table, so a cross-country comparison silently gains rows for "Africa" and
    "High-income countries" unless they are removed. On the UN population dataset that
    is 26 aggregates among 262 entities.

    Aggregates are identified by code length. ISO alpha-3 is exactly three characters,
    so anything else is a synthetic identifier: OWID's own regions (``OWID_AFR``), the
    UN's (``UN_EUR``), or no code at all for groupings like "Least developed countries".
    Matching on length rather than on a list of known prefixes means a prefix OWID adds
    later is handled without a change here.

    This is reliable on chart tables, which always publish a ``Code`` column, and
    inapplicable to indicator parquets, which do not carry one. Use
    :func:`lumen_owid.utils.code_column` to check before applying it.
    """

    code = param.String(default="Code", doc="""
        Name of the column holding an ISO alpha-3 country code.""")

    transform_type: ClassVar[str] = "owid_only_countries"

    def apply(self, sql_in: str) -> str:
        return f'SELECT * FROM ({sql_in}) WHERE length("{self.code}") = 3'


class LatestPerCountry(OWIDTransform):
    """Keep only each country's most recent row.

    OWID coverage is ragged: countries report in different years, so filtering to a
    single shared year usually throws most of the data away. Taking each country's
    latest reading keeps them all, at the cost of comparing across nearby years.

    Pass ``value`` whenever there is a specific measure of interest. Several OWID
    datasets carry projections decades past the last observation, so the newest row
    for a country is often one where the measure itself is still null.
    """

    value = param.String(default=None, doc="""
        Measure that must be present. Rows where it is null are ignored when
        deciding which row is the most recent.""")

    transform_type: ClassVar[str] = "owid_latest_per_country"

    def apply(self, sql_in: str) -> str:
        source = sql_in
        if self.value:
            source = f'SELECT * FROM ({sql_in}) WHERE "{self.value}" IS NOT NULL'
        # QUALIFY filters on a window function without projecting a helper column,
        # so nothing has to be excluded afterwards. The SELECT * EXCLUDE form this
        # replaces tripped a DuckDB binder error once the transforms were composed.
        return (
            f'SELECT * FROM ({source}) QUALIFY row_number() OVER '
            f'(PARTITION BY "{self.country}" ORDER BY "{self.year}" DESC) = 1'
        )


class PerCapita(OWIDTransform):
    """Divide a total by population, so countries of different sizes compare.

    Guards against division by zero rather than letting DuckDB return infinity,
    because a silent infinity propagates into charts as a blank axis.
    """

    population = param.String(default="population", doc="""
        Name of the population column to divide by.""")

    scale = param.Number(default=1, doc="""
        Multiplier applied after dividing, e.g. 100000 for a rate per 100,000.""")

    value = param.String(default=None, doc="""
        Name of the column to convert to a per-capita figure.""")

    transform_type: ClassVar[str] = "owid_per_capita"

    def apply(self, sql_in: str) -> str:
        if not self.value:
            return sql_in
        return (
            f'SELECT *, ("{self.value}" / NULLIF("{self.population}", 0)) * {self.scale} '
            f'AS "{self.value}_per_capita" FROM ({sql_in})'
        )


class IndexToBaseYear(OWIDTransform):
    """Rebase each country's series to 100 at a base year.

    Turns levels into relative change, which is how OWID itself presents most
    long-run comparisons between countries that start from very different levels.
    """

    base_year = param.Integer(default=None, doc="""
        The year set to 100. Defaults to each country's earliest available year.""")

    value = param.String(default=None, doc="""
        Name of the column to rebase.""")

    transform_type: ClassVar[str] = "owid_index_to_base_year"

    def apply(self, sql_in: str) -> str:
        if not self.value:
            return sql_in
        if self.base_year is None:
            baseline = (
                f'first_value("{self.value}") OVER '
                f'(PARTITION BY "{self.country}" ORDER BY "{self.year}")'
            )
        else:
            baseline = (
                f'max(CASE WHEN "{self.year}" = {self.base_year} THEN "{self.value}" END) '
                f'OVER (PARTITION BY "{self.country}")'
            )
        return (
            f'SELECT *, ("{self.value}" / NULLIF({baseline}, 0)) * 100 '
            f'AS "{self.value}_indexed" FROM ({sql_in})'
        )


class WithGeometry(Transform):
    """Attach country boundaries so a frame can be drawn as a map.

    This is the only part of a choropleth that is specific to Our World In Data.
    Rendering is not: once boundaries are present, ``hvPlotView(kind="polygons",
    geo=True, c=...)`` draws the map, and the model can choose that or anything else.
    Without them hvPlot silently returns a single-row plot rather than failing, which
    is the failure this transform exists to prevent.

    Matching is on ISO alpha-3 where the frame has a code column, which every chart
    CSV does, and on country name otherwise. Rows that match no boundary, typically
    OWID aggregates such as continents, are dropped by design: they have nothing to
    draw. Use :class:`OnlyCountries` first if you would rather see them excluded
    explicitly in SQL.
    """

    transform_type: ClassVar[str] = "owid_with_geometry"

    def apply(self, table):
        geometry = country_geometry()
        code = code_column(table)
        if code is not None and table[code].notna().any():
            left, right = "iso_a3", code
        else:
            right = country_column(table)
            if right is None:
                return table
            left = "country"
        # DuckDB hands back pandas' arrow-backed "str" dtype while the geometry uses
        # object, and pandas matches nothing across those two without complaining.
        table = table.assign(**{right: table[right].astype("object")})
        return geometry.merge(table, left_on=left, right_on=right, how="inner",
                              suffixes=("", "_owid"))
