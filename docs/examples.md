# Examples

## Load a chart and query it

```python
from lumen_owid import OWIDSource

source = OWIDSource().add_chart("life-expectancy")
source.execute('SELECT * FROM life_expectancy WHERE "Entity" = \'Japan\' ORDER BY "Year" DESC LIMIT 5')
```

Chart CSVs label their columns `Entity`, `Code` and `Year`. Indicator parquets from the ETL
catalog use `country` and `year` instead, so code that handles both should not assume either.

## Join two datasets

Both surfaces land in the same DuckDB workspace, so this is one query across two remote files
that were never downloaded.

```python
from lumen_owid import OWIDSource
from lumen_owid.api import indicators_to_catalog, search_indicators

entry = indicators_to_catalog(search_indicators("homelessness per 10,000 people", 3)).iloc[0]

source = (
    OWIDSource()
    .add_indicator(entry.url, entry.table_name, entry.column, entry.description)
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

118 countries match, and the correlation is about -0.14. Wealth barely predicts measured
homelessness at all.

## Reshape with the operations

```python
from lumen_owid import IndexToBaseYear, LatestPerCountry

sql = 'SELECT * FROM population_with_un_projections'

# Each country's latest row where Population is actually present. Without the value
# argument this returns the year 2100, because the dataset carries UN projections.
LatestPerCountry(country="Entity", year="Year", value="Population").apply(sql)

# Every country starts at 100, so trajectories compare regardless of size.
IndexToBaseYear(country="Entity", year="Year", value="Population", base_year=1950).apply(sql)
```

## Map a measure

```python
from lumen.pipeline import Pipeline
from lumen_owid import OWIDChoropleth

OWIDChoropleth(pipeline=Pipeline(source=source, table="latest"), value="Population")
```

Countries match on the ISO alpha-3 `Code` column when present. Rows that match no boundary,
usually OWID aggregates like continents and income groups, are counted and reported beneath the
map rather than dropped silently.

## Handle a dataset OWID will not serve

```python
from lumen_owid import OWIDSource, UnreadableDataset

try:
    OWIDSource().add_chart("suicide-death-rates")
except UnreadableDataset as error:
    print(error)
    # This chart contains non-redistributable data that we are not allowed to re-share...
```
