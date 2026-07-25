# Examples

Every example here is plain Python and needs no LLM key.

## Load a chart and query it

```python
from lumen_owid import OWIDSource

source = OWIDSource().add_chart("life-expectancy")
source.execute("""
    SELECT "Entity", "Year", "Period life expectancy at birth - Sex: all - Age: 0" AS life_expectancy
    FROM life_expectancy
    WHERE "Entity" = 'Japan'
    ORDER BY "Year" DESC
    LIMIT 5
""")
```

Chart CSVs label their columns `Entity`, `Code` and `Year`, and the measure columns keep OWID's
long human-readable names, so they need quoting.

## Find something without knowing its slug

```python
from lumen_owid import search_catalog

hits = search_catalog("child mortality")
hits[["title", "kind", "table_name"]]
```

`search_catalog` tries charts first and falls back to the indicator catalog. To go straight to
one surface, use `search_charts` or `search_indicators`.

## Load whatever the search found

The catalog row carries everything needed, whichever surface it came from:

```python
from lumen_owid import OWIDSource, search_catalog

entry = search_catalog("child mortality").iloc[0]
source = OWIDSource()

if entry.kind == "chart":
    source = source.add_chart(entry.slug, entry.table_name)
else:
    source = source.add_indicator(entry.url, entry.table_name, entry.column, entry.description)

source.get(entry.table_name).head()
```

## Load several charts at once

```python
from lumen_owid import OWIDSource

source, failures = OWIDSource().add_charts([
    "life-expectancy",
    "child-mortality",
    "suicide-death-rates",     # blocked by OWID, so it lands in failures
])

source.get_tables()   # ['life_expectancy', 'child_mortality']
failures              # {'suicide-death-rates': 'This chart contains non-redistributable...'}
```

Documentation is fetched concurrently, so this is faster than looping `add_chart`, and a
slug OWID will not serve is reported rather than sinking the whole batch.

## Join two datasets

Both surfaces land in the same DuckDB workspace, so this is ordinary SQL across two remote files
that were never downloaded.

```python
from lumen_owid import OWIDSource
from lumen_owid.api import indicators_to_catalog, search_indicators

entry = indicators_to_catalog(search_indicators("homelessness per 10,000 people", 3)).iloc[0]

source = (
    OWIDSource()
    .add_indicator(entry.url, entry.table_name, entry.column, entry.description or "")
    .add_chart("gdp-per-capita-maddison-project-database")
)

source.execute("""
    WITH h AS (
        SELECT country, people_homeless_per_10k AS rate,
               row_number() OVER (PARTITION BY country ORDER BY year DESC) AS rn
        FROM better_data_homelessness WHERE people_homeless_per_10k IS NOT NULL
    ), g AS (
        SELECT "Entity" AS country, "GDP per capita" AS gdp,
               row_number() OVER (PARTITION BY "Entity" ORDER BY "Year" DESC) AS rn
        FROM gdp_per_capita_maddison_project_database WHERE "GDP per capita" IS NOT NULL
    )
    SELECT h.country, h.rate, g.gdp
    FROM h JOIN g ON h.country = g.country
    WHERE h.rn = 1 AND g.rn = 1
""")
```

Note the join key: the indicator table uses `country`, the chart table uses `Entity`. Both are
harmonized to the same country names by OWID, so they match without further work.

## Reshape with the operations

```python
from lumen_owid import IndexToBaseYear, LatestPerCountry, PerCapita

source = OWIDSource().add_chart("population-with-un-projections")
sql = 'SELECT * FROM population_with_un_projections'

# Each country's latest row where Population is present. Without value= this
# returns the year 2100, because the dataset carries UN projections.
latest = LatestPerCountry(country="Entity", year="Year", value="Population").apply(sql)
source.execute(latest)

# Every country starts at 100, so trajectories compare regardless of size.
indexed = IndexToBaseYear(country="Entity", year="Year", value="Population", base_year=1950).apply(sql)
source.execute(indexed + " WHERE \"Entity\" = 'India' ORDER BY \"Year\" LIMIT 3")
```

Operations compose, since each takes SQL in and returns SQL out:

```python
per_capita = PerCapita(value="Deaths", population="Population", scale=100_000)
LatestPerCountry(country="Entity", year="Year").apply(per_capita.apply(sql))
```

## Register a reshaped table

To use a transform result as a table, hand it to `create_sql_expr_source`:

```python
source = source.create_sql_expr_source({"latest": latest}, materialize=True)
source.get("latest")
```

## Map a measure

```python
from lumen.pipeline import Pipeline
from lumen_owid import OWIDChoropleth

OWIDChoropleth(pipeline=Pipeline(source=source, table="latest"), value="Population")
```

Countries match on the ISO alpha-3 `Code` column. Rows matching no boundary, usually OWID
aggregates such as continents and income groups, are counted and reported beneath the map.

## Run an analysis directly

Analyses are `ParameterizedFunction`s, so configure with `.instance()`:

```python
from lumen.pipeline import Pipeline
from lumen_owid import CorrelateIndicators

pipeline = Pipeline(source=source, table="homelessness_rate_point_in_time_count")
CorrelateIndicators.instance()(pipeline, {})
```

## Handle a dataset OWID will not serve

```python
from lumen_owid import OWIDSource, UnreadableDataset

try:
    OWIDSource().add_chart("suicide-death-rates")
except UnreadableDataset as error:
    print(error)
    # This chart contains non-redistributable data that we are not allowed to re-share...
```

Inside the app this is caught and shown as a message, so a blocked chart never raises.

## Attach the catalog to your own Lumen app

```python
from lumen.ai.ui import ExplorerUI
from lumen_owid import ANALYSES, OWIDSourceControls

ExplorerUI(
    source_controls=[OWIDSourceControls],
    analyses=ANALYSES,
    title="Development data",
).servable()
```

Or take the assembled version and override what you need:

```python
from lumen_owid import build_ui

build_ui(title="Development data").servable()
```
