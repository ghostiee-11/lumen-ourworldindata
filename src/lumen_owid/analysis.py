"""Analyses for the questions Our World In Data is usually asked.

Each one is a named, auditable step the LLM can invoke instead of improvising SQL:
map a measure across the world, rebase countries onto a common index, or check
whether two indicators actually move together. They exist because these three
questions account for most of what people come to OWID for.
"""
from __future__ import annotations

import hvplot.pandas  # noqa: F401  (registers the .hvplot accessor)
import panel as pn
import param
from lumen.ai.analysis import Analysis
from lumen.pipeline import Pipeline

from .operations import IndexToBaseYear, LatestPerCountry
from .utils import country_column, value_columns, year_column
from .views import OWIDChoropleth


class OWIDAnalysis(Analysis):
    """Shared column detection for OWID's long-format country/year tables.

    ``Analysis.columns`` is left empty and ``applies`` is overridden instead. Chart
    CSVs spell the key columns Entity/Year while indicator parquets spell them
    country/year, and although the base class supports a tuple to mean "one of
    these", Lumen renders the analysis list with ``", ".join(columns)``, which
    raises on a tuple before the app can start.
    """

    __abstract = True

    @classmethod
    async def applies(cls, pipeline) -> bool:
        return country_column(pipeline.data) is not None

    def _columns(self, pipeline: Pipeline) -> tuple[str, str, list[str]]:
        data = pipeline.data
        return country_column(data), year_column(data), value_columns(data)


class MapAcrossCountries(OWIDAnalysis):
    """Show one measure as a world map, using each country's latest reading.

    OWID's own charts default to a map for exactly this question, and a map answers
    "who is high and who is low" far faster than a 200-row table.
    """

    value = param.String(default=None, doc="""
        Measure to map. Defaults to the first numeric column.""")


    def __call__(self, pipeline: Pipeline, context) -> pn.viewable.Viewable:
        country, year, values = self._columns(pipeline)
        value = self.value or next(iter(values), None)
        if value is None:
            return pn.pane.Markdown("No numeric column to map.")
        table = f"{pipeline.table}_owid_mapped"
        source = pipeline.source.create_sql_expr_source({
            table: LatestPerCountry(country=country, year=year, value=value).apply(
                pipeline.source.get_sql_expr(pipeline.table)
            )
        }, materialize=True)
        return OWIDChoropleth(pipeline=Pipeline(source=source, table=table), value=value)


class CompareCountries(OWIDAnalysis):
    """Put a handful of countries on one time axis, optionally rebased to 100.

    Countries that start from very different levels are hard to compare directly, so
    indexing to a base year is offered here rather than left as manual SQL.
    """

    countries = param.List(default=[], doc="""
        Countries to compare. Empty means the six with the most observations.""")

    index_to_base_year = param.Boolean(default=False, doc="""
        Rebase each country to 100 at its first year, comparing change not level.""")

    value = param.String(default=None, doc="""
        Measure to plot. Defaults to the first numeric column.""")


    def __call__(self, pipeline: Pipeline, context) -> pn.viewable.Viewable:
        country, year, values = self._columns(pipeline)
        value = self.value or next(iter(values), None)
        if value is None:
            return pn.pane.Markdown("No numeric column to plot.")

        data = pipeline.data
        chosen = self.countries or (
            data[data[value].notna()][country].value_counts().head(6).index.tolist()
        )
        subset = data[data[country].isin(chosen)]
        plotted = value
        if self.index_to_base_year:
            source = pipeline.source
            table = f"{pipeline.table}_owid_indexed"
            source = source.create_sql_expr_source({
                table: IndexToBaseYear(country=country, year=year, value=value).apply(
                    source.get_sql_expr(pipeline.table)
                )
            }, materialize=True)
            subset = source.get(table)
            subset = subset[subset[country].isin(chosen)]
            plotted = f"{value}_indexed"

        return pn.pane.HoloViews(
            subset.sort_values(year).hvplot.line(
                x=year, y=plotted, by=country, responsive=True, height=400,
                title=f"{plotted} by country",
            ),
            sizing_mode="stretch_width",
        )


class CorrelateIndicators(OWIDAnalysis):
    """Scatter two measures against each other and report the correlation.

    Reports Pearson r alongside the plot because the interesting OWID answer is very
    often that two things people assume are linked are not.
    """

    x = param.String(default=None, doc="Measure on the horizontal axis.")

    y = param.String(default=None, doc="Measure on the vertical axis.")


    @classmethod
    async def applies(cls, pipeline) -> bool:
        return len(value_columns(pipeline.data)) >= 2

    def __call__(self, pipeline: Pipeline, context) -> pn.viewable.Viewable:
        country, _, values = self._columns(pipeline)
        x = self.x or values[0]
        y = self.y or values[1]
        data = pipeline.data[[country, x, y]].dropna()
        if data.empty:
            return pn.pane.Markdown(f"No rows where both {x} and {y} are present.")

        correlation = data[x].corr(data[y])
        plot = data.hvplot.scatter(
            x=x, y=y, hover_cols=[country], responsive=True, height=400, size=60,
        )
        return pn.Column(
            pn.pane.HoloViews(plot, sizing_mode="stretch_width"),
            pn.pane.Markdown(
                f"**Pearson r = {correlation:.3f}** across {len(data)} countries. "
                f"{'Little to no linear relationship.' if abs(correlation) < 0.3 else ''}"
            ),
            sizing_mode="stretch_width",
        )


ANALYSES = [MapAcrossCountries, CompareCountries, CorrelateIndicators]
