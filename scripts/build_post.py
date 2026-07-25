"""Build the homelessness against GDP data blog post.

Loads two Our World In Data datasets through lumen-ourworldindata, joins them in
DuckDB, and exports a standalone HTML report. Every figure quoted in the prose is
computed from the joined frame, so the text cannot drift from the data.

    python scripts/build_post.py
"""
from __future__ import annotations

from pathlib import Path

import holoviews as hv
import pandas as pd
import panel as pn

from lumen_owid import OWIDSource
from lumen_owid.api import indicators_to_catalog, search_indicators

hv.extension("bokeh")

OUT = Path(__file__).resolve().parent.parent / "out" / "homelessness-vs-gdp.html"

# Categorical slot 1, validated against both the light and dark chart surfaces.
BLUE = "#2a78d6"
INK = "#52514e"

# The homelessness series is only published as an indicator, and the Maddison GDP
# series is the chart the question was originally asked about, so the post draws one
# dataset from each of OWID's two surfaces.
HOMELESSNESS = "homelessness per 10,000 people"
GDP_CHART = "gdp-per-capita-maddison-project-database"

JOIN = """
WITH h AS (
    SELECT country, year, people_homeless_per_10k AS rate, methodology,
           row_number() OVER (PARTITION BY country ORDER BY year DESC) AS rn
    FROM better_data_homelessness WHERE people_homeless_per_10k IS NOT NULL
), g AS (
    SELECT "Entity" AS country, "GDP per capita" AS gdp,
           row_number() OVER (PARTITION BY "Entity" ORDER BY "Year" DESC) AS rn
    FROM gdp_per_capita_maddison_project_database WHERE "GDP per capita" IS NOT NULL
)
SELECT h.country, h.year, h.rate, h.methodology, g.gdp
FROM h JOIN g ON h.country = g.country
WHERE h.rn = 1 AND g.rn = 1
ORDER BY h.rate DESC
"""


def load() -> pd.DataFrame:
    """Load both datasets into one DuckDB source and return the joined frame."""
    entry = indicators_to_catalog(search_indicators(HOMELESSNESS, 3).head(1)).iloc[0]
    source = (
        OWIDSource()
        .add_indicator(entry.url, entry.table_name, entry.column, entry.description or "")
        .add_chart(GDP_CHART)
    )
    return source.execute(JOIN)


def scatter(df: pd.DataFrame) -> hv.Overlay:
    """GDP against homelessness rate, labelled only at the points worth naming."""
    points = hv.Points(df, kdims=["gdp", "rate"]).opts(
        color=BLUE, size=9, alpha=0.85, line_color="white", line_width=1.5, padding=0.1,
    )
    named = df[df.country.isin(list(df.nlargest(3, "rate").country) + list(df.nlargest(2, "gdp").country))]
    labels = hv.Labels(named, kdims=["gdp", "rate"], vdims=["country"]).opts(
        text_color=INK, text_font_size="9pt", yoffset=18,
    )
    return (points * labels).opts(
        width=760, height=420, show_grid=True, toolbar="above",
        xlabel="GDP per capita (int-$)", ylabel="Homeless per 10,000",
        title="Wealth does not predict measured homelessness",
    )


def ranked_bars(df: pd.DataFrame) -> hv.Bars:
    """The highest rates as a ranked bar, where the spread is easier to read.

    Capped at the top 20: all 118 countries would give each bar about six pixels and
    an unreadable axis. The cap is stated in the title so nothing looks like the
    whole picture when it is not.
    """
    ordered = df.sort_values("rate", ascending=False).head(20)
    return hv.Bars(ordered, kdims=["country"], vdims=["rate"]).opts(
        color=BLUE, width=760, height=380, xrotation=60, show_grid=True,
        xlabel="", ylabel="Homeless per 10,000",
        title="The 20 highest reported rates",
    )


def prose(df: pd.DataFrame) -> tuple[str, str, str]:
    """Build the narrative from the data so the numbers cannot go stale."""
    correlation = df.rate.corr(df.gdp)
    top, bottom = df.iloc[0], df.iloc[-1]
    richest = df.loc[df.gdp.idxmax()]
    poorest = df.loc[df.gdp.idxmin()]

    intro = f"""
# Does homelessness track how rich a country is?

It is an easy assumption to make. Richer countries have more to spend on housing,
shelters and welfare, so you would expect their streets to be emptier.

Our World In Data publishes both halves of that question: a homelessness rate per
10,000 people, compiled by the Institute of Global Homelessness, and GDP per capita
from the Maddison Project. Taking the most recent observation for each of the
{len(df)} countries that report both, the correlation between them is
**{correlation:.3f}**.

That is nothing. Wealth explains essentially none of the variation.
"""

    middle = f"""
## The spread is enormous, and it is not ordered by money

{top.country} reports {top.rate:.1f} people per 10,000 and {bottom.country} reports
{bottom.rate:.2f}. Run the comparison the other way and the pattern is just as absent.
{richest.country} is the richest country here at ${richest.gdp:,.0f} per person and
reports {richest.rate:.1f} per 10,000, while {poorest.country}, on
${poorest.gdp:,.0f}, reports {poorest.rate:.1f}.

Whatever drives these numbers, it is policy, housing supply and how each country
counts, not national income.
"""

    methods = df.methodology.fillna("Undefined").value_counts()
    method_lines = "\n".join(
        f"- {method}: {count} countries" for method, count in methods.items()
    )

    caveat = f"""
## Read these numbers carefully

This is the part that matters most, and Our World In Data says so in its own metadata:
these counts are **not directly comparable across countries**, because each country
uses its own definition of homelessness and its own collection method.

That is not a vague warning. The dataset records how each country arrived at its
number, and among the {len(df)} countries here the methods are:

{method_lines}

A street count and a register of households assessed as homeless are not measuring the
same thing, and neither is an estimate. Countries also differ on whether the definition
includes people in emergency accommodation or in insecure housing at all, which the
dataset tracks in separate columns.

So the honest claim is narrow: **national wealth does not predict measured
homelessness.** That is not the same as saying money cannot reduce homelessness. It
says that knowing a country's GDP tells you almost nothing about what its count will
say, and that differences in how countries define and measure the problem are large
enough to swamp differences in how rich they are.

## How this was built

Both datasets came from Our World In Data through [Lumen](https://lumen.holoviz.org),
one from the chart catalog and one from the indicator catalog. Neither was
downloaded: OWID serves CSV and parquet over HTTPS, and DuckDB reads both in place,
so the join above is a single SQL statement across two remote files.

```
from lumen.ai.ui import ExplorerUI
from lumen_owid import OWIDSourceControls

ExplorerUI(source_controls=[OWIDSourceControls]).servable()
```

Data: Institute of Global Homelessness (2024) and the Maddison Project Database,
via Our World In Data, CC BY 4.0.
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
