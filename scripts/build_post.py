"""Build the homelessness against GDP data blog post.

Loads two Our World In Data datasets through lumen-ourworldindata, joins them in
DuckDB, and exports a standalone HTML report. Every figure quoted in the prose is
computed from the joined frame, so the text cannot drift from the data.

    python scripts/build_post.py
"""
from __future__ import annotations

import asyncio

from pathlib import Path

import holoviews as hv
import pandas as pd
import panel as pn

from lumen_owid import OWIDControls, search_charts, search_indicators
from lumen_owid.controls import charts_to_catalog, indicators_to_catalog

hv.extension("bokeh")

OUT = Path(__file__).resolve().parent.parent / "out" / "homelessness-vs-gdp.html"

# Categorical slot 1, validated against both the light and dark chart surfaces.
BLUE = "#2a78d6"
INK = "#52514e"

# The homelessness series is only published as an indicator, and the Maddison GDP
# series is the chart the question was originally asked about, so the post uses
# one dataset from each OWID surface.
HOMELESSNESS = "homelessness point in time total"
GDP = "GDP per capita maddison project database"

JOIN = """
WITH h AS (
    SELECT country, year, point_in_time_total AS rate,
           row_number() OVER (PARTITION BY country ORDER BY year DESC) AS rn
    FROM affordable_housing_database WHERE point_in_time_total IS NOT NULL
), g AS (
    SELECT "Entity" AS country, "GDP per capita" AS gdp,
           row_number() OVER (PARTITION BY "Entity" ORDER BY "Year" DESC) AS rn
    FROM gdp_per_capita_maddison_project_database WHERE "GDP per capita" IS NOT NULL
)
SELECT h.country, h.year, h.rate, g.gdp
FROM h JOIN g ON h.country = g.country
WHERE h.rn = 1 AND g.rn = 1
ORDER BY h.rate DESC
"""


def load() -> pd.DataFrame:
    """Load both datasets into one DuckDB source and return the joined frame."""
    controls = OWIDControls()
    controls.catalog_df = asyncio.run(controls._load_catalog())
    entries = pd.concat([
        indicators_to_catalog(search_indicators(HOMELESSNESS, 3).head(1)),
        charts_to_catalog(search_charts(GDP, 5).head(1)),
    ], ignore_index=True)
    for _, entry in entries.iterrows():
        asyncio.run(controls._fetch_entry(entry))
    return controls._source.execute(JOIN)


def scatter(df: pd.DataFrame) -> hv.Overlay:
    """GDP against homelessness rate, labelled only at the points worth naming."""
    points = hv.Points(df, kdims=["gdp", "rate"]).opts(
        color=BLUE, size=9, alpha=0.85, line_color="white", line_width=1.5, padding=0.1,
    )
    named = df[df.country.isin(["Norway", "Ireland", "Japan", "United Kingdom", "United States"])]
    labels = hv.Labels(named, kdims=["gdp", "rate"], vdims=["country"]).opts(
        text_color=INK, text_font_size="9pt", yoffset=18,
    )
    return (points * labels).opts(
        width=760, height=420, show_grid=True, toolbar="above",
        xlabel="GDP per capita (int-$)", ylabel="Homeless per 100,000",
        title="Wealth does not predict measured homelessness",
    )


def ranked_bars(df: pd.DataFrame) -> hv.Bars:
    """The same rates as a ranked bar, where the spread is easier to read."""
    ordered = df.sort_values("rate", ascending=False)
    return hv.Bars(ordered, kdims=["country"], vdims=["rate"]).opts(
        color=BLUE, width=760, height=380, xrotation=60, show_grid=True,
        xlabel="", ylabel="Homeless per 100,000",
        title="The same countries, ranked by homelessness rate",
    )


def prose(df: pd.DataFrame) -> tuple[str, str, str]:
    """Build the narrative from the data so the numbers cannot go stale."""
    correlation = df.rate.corr(df.gdp)
    top, bottom = df.iloc[0], df.iloc[-1]
    richest = df.loc[df.gdp.idxmax()]
    ireland = df[df.country == "Ireland"].iloc[0]

    intro = f"""
# Does homelessness track how rich a country is?

It is an easy assumption to make. Richer countries have more to spend on housing,
shelters and welfare, so you would expect their streets to be emptier.

Our World In Data publishes both halves of that question: a homelessness rate per
100,000 people, collected by counting people sleeping rough or in shelters on a
single night, and GDP per capita from the Maddison Project. Taking the most recent
observation for each of the {len(df)} countries that report both, the correlation
between them is **{correlation:.3f}**.

That is nothing. Wealth explains essentially none of the variation.
"""

    middle = f"""
## The spread is enormous, and it is not ordered by money

{top.country} reports {top.rate:.0f} people per 100,000 and {bottom.country} reports
{bottom.rate:.1f}, a gap of more than {top.rate / bottom.rate:.0f} times. Those two
countries have almost the same GDP per capita, about
${top.gdp:,.0f} and ${bottom.gdp:,.0f}.

Run it the other way and the pattern is just as absent. {richest.country} is the
richest country here at ${richest.gdp:,.0f} per person and reports
{richest.rate:.0f} per 100,000. {ireland.country}, at ${ireland.gdp:,.0f}, reports
{ireland.rate:.0f}, nearly {ireland.rate / richest.rate:.0f} times as many.

Whatever drives these numbers, it is policy, housing supply and how each country
counts, not national income.
"""

    caveat = """
## Read these numbers carefully

This is the part that matters most, and OWID says so in its own metadata.

These counts are **not directly comparable across countries**. Each country uses its
own definition of homelessness and its own collection method, and OWID harmonizes
them only as far as is possible. Some countries include people in tents and
unconventional dwellings; others do not. France excludes asylum seekers. The United
Kingdom figure covers England only and counts *households*, not people, which is a
large part of why it sits at the top of this chart.

A single-night count also misses anyone who was housed that night and homeless a week
later, so every figure here understates the number of people who experience
homelessness over a year.

So the honest claim is narrow: **national wealth does not predict measured
homelessness.** That is not the same as saying money cannot reduce homelessness. It
says that knowing a country's GDP tells you almost nothing about what its count will
say, and that differences in how countries define and measure the problem are large
enough to swamp differences in how rich they are.

## How this was built

Both datasets came from Our World In Data through
[lumen-ourworldindata](https://github.com/holoviz-topics/lumen-ourworldindata), one
from the chart catalog and one from the indicator catalog. Neither was downloaded:
OWID serves CSV and parquet over HTTPS, and DuckDB reads both in place, so the join
above is a single SQL statement across two remote files.

```
from lumen.ai.ui import ExplorerUI
from lumen_owid import OWIDControls

ExplorerUI(source_controls=[OWIDControls]).servable()
```

Data: OECD (2024) and the Maddison Project Database, via Our World In Data, CC BY 4.0.
"""
    return intro, middle, caveat


def main() -> None:
    df = load()
    intro, middle, caveat = prose(df)
    # A post is a linear document, so this is a plain Column rather than
    # Report.from_views, whose export wraps each view in an accordion card that
    # has no title and starts collapsed.
    post = pn.Column(
        pn.pane.Markdown(intro),
        pn.pane.HoloViews(scatter(df)),
        pn.pane.Markdown(middle),
        pn.pane.HoloViews(ranked_bars(df)),
        pn.pane.Markdown(caveat),
        width=820,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    post.save(OUT, title="Does homelessness track how rich a country is?")
    print(f"{len(df)} countries, correlation {df.rate.corr(df.gdp):.4f}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
