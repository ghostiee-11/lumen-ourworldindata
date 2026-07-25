# API reference

Everything below is exported from the top-level `lumen_owid` package.

## OWIDSource

```python
class OWIDSource(DuckDBSource)
```

A DuckDB source that reads Our World In Data over HTTPS. Defaults to an ephemeral in-memory
database with `httpfs` loaded, so it needs no arguments.

Registered as `source_type = "owid"`, so it can also be referenced from a Lumen YAML spec.

### `add_chart(slug, table=None)`

Add a published chart by slug. Returns a **new** `OWIDSource` containing this table and every
table already loaded.

| Parameter | Meaning |
|---|---|
| `slug` | The chart slug, e.g. `"life-expectancy"` |
| `table` | Table name. Defaults to the slug normalized to a SQL identifier |

The chart's `metadata.json` is fetched and attached as the table's description and per-column
documentation.

```python
source = OWIDSource().add_chart("life-expectancy")
source.get_tables()          # ['life_expectancy']
```

Raises [`UnreadableDataset`](#unreadabledataset) if OWID will not serve the file.

### `add_indicator(parquet_url, table, column=None, description="")`

Add an indicator's parquet from the ETL catalog. Returns a new `OWIDSource`.

| Parameter | Meaning |
|---|---|
| `parquet_url` | From `search_indicators`, under `metadata.parquet_url` |
| `table` | Table name, normally the dataset name |
| `column` | The matched indicator column, recorded in the description |
| `description` | OWID's description of the indicator |

The parquet holds the whole source dataset, so `column` tells the model which of its many
columns the search actually matched.

!!! tip "Chaining"
    Both methods return a new source sharing one connection, so they chain, and everything ends
    up joinable:

    ```python
    source = (
        OWIDSource()
        .add_chart("gdp-per-capita-maddison-project-database")
        .add_chart("life-expectancy")
    )
    ```

## UnreadableDataset

```python
class UnreadableDataset(Exception)
```

Raised when OWID will not serve a dataset. The message carries OWID's own explanation, recovered
from the JSON error body, because DuckDB reports a blocked download only as
`HTTP 0 Internal Server Error`.

```python
try:
    OWIDSource().add_chart("suicide-death-rates")
except UnreadableDataset as error:
    print(error)
    # This chart contains non-redistributable data that we are not allowed to re-share...
```

`OWIDSourceControls` catches this and turns it into a user-facing message, so the app never
raises on a blocked chart.

## Search functions

### `search_charts(query="", limit=100)`

Search published charts. Returns a `DataFrame` of raw hits with `slug`, `title`, `subtitle` and
more. `limit` is capped at 100 by the API. An empty query returns popular charts.

### `search_indicators(query, limit=20)`

Semantic search over the indicator catalog. Requires a non-empty query; an empty one returns 422.
Nested fields arrive flattened, so the parquet URL is at `metadata.parquet_url`.

### `search_catalog(query, limit=5)`

Search both surfaces, charts first, and return rows normalized onto the shared catalog columns
described in [The catalog](catalog.md). Returns an empty frame if neither surface matches, and
degrades to charts only if the indicator service is unreachable.

### `chart_metadata(slug)`

The raw `<slug>.metadata.json`: a `chart` section with title, subtitle and citation, and a
`columns` section with `titleShort`, `descriptionShort`, `unit`, `citationLong` and more.

## Operations

SQL transforms, so they compose into Lumen pipelines and execute inside DuckDB. All take
`country` and `year` column names, since the two OWID surfaces spell them differently.

Each has an `apply(sql_in) -> sql_out` method.

### LatestPerCountry

`transform_type: owid_latest_per_country`

Keep only each country's most recent row.

| Parameter | Default | Meaning |
|---|---|---|
| `country` | `"country"` | Country column |
| `year` | `"year"` | Year column |
| `value` | `None` | Measure that must be present |

!!! warning "Always pass `value` when you have one"
    Several OWID datasets carry projections decades past the last real observation. Without
    `value`, the "latest" row for a country is often a projection year where the measure itself
    is null. On the UN population dataset that means 2100 rather than 2023.

```python
LatestPerCountry(country="Entity", year="Year", value="Population").apply(sql)
```

### PerCapita

`transform_type: owid_per_capita`

Divide a total by population. Adds a `<value>_per_capita` column.

| Parameter | Default | Meaning |
|---|---|---|
| `population` | `"population"` | Column to divide by |
| `scale` | `1` | Multiplier, e.g. `100000` for a rate per 100,000 |
| `value` | `None` | Column to convert. No-op when unset |

Divides through `NULLIF(..., 0)`, so a zero population yields null rather than an infinity that
would silently blank out a chart axis.

!!! note
    Pass a `value` different from `population`. Dividing a column by itself is meaningless and
    trips a binder bug in DuckDB 1.5.0.

### IndexToBaseYear

`transform_type: owid_index_to_base_year`

Rebase each country to 100. Adds a `<value>_indexed` column.

| Parameter | Default | Meaning |
|---|---|---|
| `base_year` | `None` | Year set to 100. Defaults to each country's earliest year |
| `value` | `None` | Column to rebase. No-op when unset |

Turns levels into relative change, which is how OWID itself presents most long-run comparisons
between countries starting from very different levels.

## Views

### OWIDChoropleth

```python
class OWIDChoropleth(View)
```

`view_type: owid_choropleth`. A world map of one measure, one value per country. Requires the
`geo` extra.

| Parameter | Default | Meaning |
|---|---|---|
| `value` | `None` | Column to shade by. Defaults to the first numeric column |
| `code` | `None` | ISO alpha-3 column. Detected when unset |
| `country` | `None` | Country name column, used when no ISO code exists |
| `cmap` | `"viridis"` | Colormap |

Matches on ISO alpha-3 where available, which every chart CSV provides as `Code`, and falls back
to country names otherwise. Rows matching no boundary, usually OWID aggregates such as
continents and income groups, are counted and reported beneath the map rather than dropped
silently.

## Analyses

`Analysis` subclasses the model can invoke by name. `ANALYSES` exports all three as a list ready
to hand to `ExplorerUI(analyses=...)`.

Being `ParameterizedFunction`s, they are configured through `.instance()`:

```python
MapAcrossCountries.instance(value="Population")(pipeline, context)
```

### MapAcrossCountries

Map one measure worldwide, using each country's latest non-null reading. Parameters: `value`.

### CompareCountries

Put several countries on one time axis. Parameters: `countries` (defaults to the six with the
most observations), `index_to_base_year`, `value`.

### CorrelateIndicators

Scatter two measures and report Pearson r, calling out weak relationships explicitly. Parameters:
`x`, `y`. Applies only when the table has at least two numeric columns.

## UI

### `build_ui(llm=None, **params)`

Return an `ExplorerUI` with the OWID catalog and analyses attached. Any `ExplorerUI` parameter
can be overridden. No sources are attached up front; everything is discovered.

```python
from lumen_owid import build_ui

build_ui(title="Development data").servable()
```

## Utilities

`lumen_owid.utils` holds the column conventions:

- `country_column(df)`, `year_column(df)`, `code_column(df)` — detect the spelling in use
- `value_columns(df)` — the numeric measure columns, excluding identifiers
- `country_geometry()` — Natural Earth country polygons keyed by ISO alpha-3, cached
