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

from lumen.transforms.sql import SQLTransform


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
        return (
            f'SELECT * EXCLUDE (_owid_rank) FROM (SELECT *, row_number() OVER '
            f'(PARTITION BY "{self.country}" ORDER BY "{self.year}" DESC) AS _owid_rank '
            f'FROM ({source})) WHERE _owid_rank = 1'
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
