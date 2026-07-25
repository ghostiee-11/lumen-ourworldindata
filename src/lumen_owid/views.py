"""Views for the shapes Our World In Data is usually read in.

The world map is OWID's signature output: almost every chart on the site offers a map
tab. Lumen has no choropleth of its own, so this supplies one that speaks OWID's
column conventions directly.
"""
from __future__ import annotations

from typing import ClassVar

import panel as pn
import param
from lumen.views.base import View

from .utils import code_column, country_column, country_geometry, value_columns


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
