"""Views for the shapes Our World In Data is usually read in.

OWID has two signature outputs: a world map and a line over time. Almost every chart on
the site offers both as tabs. Lumen has neither in a form that understands OWID's column
conventions, so this supplies both.
"""
from __future__ import annotations

from typing import ClassVar

import hvplot.pandas  # noqa: F401  (registers the .hvplot accessor)
import panel as pn
import param
from lumen.views.base import View

from .utils import (
    code_column,
    country_column,
    country_geometry,
    value_columns,
    year_column,
)


class OWIDChoropleth(View):
    """A world map of one OWID measure, one value per country.

    Countries are matched on ISO alpha-3 where the data carries a ``Code`` column,
    which every OWID chart CSV does. Indicator parquets carry only country names, so
    those fall back to a name match, and any country that fails to match is reported
    rather than silently dropped from the map.
    """

    cmap = param.String(default="viridis", doc="""
        Name of the colormap used to shade countries.""")

    code = param.String(default=None, doc="""
        Column holding an ISO alpha-3 country code. Detected when not given.""")

    country = param.String(default=None, doc="""
        Column holding the country name, used when no ISO code is available.""")

    value = param.String(default=None, doc="""
        Column to shade countries by. Defaults to the first numeric column.""")

    view_type: ClassVar[str] = "owid_choropleth"

    def get_panel(self) -> pn.viewable.Viewable:
        import geoviews as gv

        data = self.get_data()
        value = self.value or next(iter(value_columns(data)), None)
        if value is None:
            return pn.pane.Markdown("No numeric column to map.")

        geometry = country_geometry()
        code = self.code or code_column(data)
        if code is not None and data[code].notna().any():
            left, right = "iso_a3", code
        else:
            right = self.country or country_column(data)
            if right is None:
                return pn.pane.Markdown("No country or code column to map on.")
            left = "country"
        # DuckDB hands back pandas' arrow-backed "str" dtype while the geometry uses
        # object, and pandas matches nothing across those two without complaining.
        data = data.assign(**{right: data[right].astype("object")})
        merged = geometry.merge(
            data, left_on=left, right_on=right, how="left", suffixes=("", "_owid"),
        )

        matched = int(merged[value].notna().sum())
        polygons = gv.Polygons(merged, vdims=[value]).opts(
            cmap=self.cmap, colorbar=True, tools=["hover"], responsive=True,
            height=460, line_color="white", line_width=0.5, title=value,
        )
        missing = len(data) - matched
        if missing <= 0:
            return pn.pane.HoloViews(polygons, sizing_mode="stretch_width")
        return pn.Column(
            pn.pane.HoloViews(polygons, sizing_mode="stretch_width"),
            pn.pane.Markdown(
                f"*{matched} of {len(data)} rows placed on the map. "
                f"{missing} did not match a country boundary, usually aggregates "
                f"such as continents or income groups.*"
            ),
            sizing_mode="stretch_width",
        )


class OWIDTimeSeries(View):
    """One measure over time, one line per country.

    The counterpart to the map: a map answers "who is high and who is low", a line
    answers "what changed". Both are tabs on almost every chart OWID publishes.

    Series count is the real constraint. An OWID table carries every country it has
    data for, often over two hundred, and a chart with two hundred lines communicates
    nothing. Rather than draw them all, this keeps the best-covered countries up to
    ``max_series`` and reports how many were left out, so a partial view never reads as
    the whole picture.

    Be aware of what "best covered" selects for. Ranking by number of observations
    favours countries with long statistical records, which on a historical series means
    wealthy ones: life expectancy defaults to eight Western European countries. That is
    a reasonable default and a poor answer to some questions, so pass ``countries``
    explicitly whenever the comparison matters.
    """

    countries = param.List(default=[], doc="""
        Countries to plot. Empty means the best-covered ones, up to ``max_series``.""")

    country = param.String(default=None, doc="""
        Column holding the country name. Detected when not given.""")

    max_series = param.Integer(default=8, doc="""
        Maximum number of lines. Beyond roughly eight, colours stop being tellable
        apart whatever palette is used. Named to avoid View.limit, which truncates
        rows rather than series.""")

    value = param.String(default=None, doc="""
        Column to plot. Defaults to the first numeric column.""")

    year = param.String(default=None, doc="""
        Column holding the time period. Detected when not given.""")

    view_type: ClassVar[str] = "owid_time_series"

    def get_panel(self) -> pn.viewable.Viewable:
        data = self.get_data()
        value = self.value or next(iter(value_columns(data)), None)
        country = self.country or country_column(data)
        year = self.year or year_column(data)
        if value is None or country is None or year is None:
            return pn.pane.Markdown("Need a country, a year and a numeric column to plot.")

        present = data[data[value].notna()]
        if present.empty:
            return pn.pane.Markdown(f"No values to plot for {value}.")

        available = present[country].nunique()
        best_covered = present[country].value_counts().head(self.max_series)
        chosen = self.countries or best_covered.index.tolist()
        subset = present[present[country].isin(chosen)].sort_values(year)
        if subset.empty:
            return pn.pane.Markdown(f"None of {', '.join(chosen)} appear in this table.")

        plot = subset.hvplot.line(
            x=year, y=value, by=country, responsive=True, height=400, legend="right",
        )
        panel = pn.pane.HoloViews(plot, sizing_mode="stretch_width")
        hidden = available - subset[country].nunique()
        if hidden <= 0:
            return panel
        return pn.Column(
            panel,
            pn.pane.Markdown(
                f"*Showing the {subset[country].nunique()} best-covered of {available} "
                f"countries. {hidden} are not plotted.*"
            ),
            sizing_mode="stretch_width",
        )
