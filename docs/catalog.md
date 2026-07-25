# The catalog

How this package finds things, and what is reachable.

## Two surfaces

Our World In Data exposes several public APIs. Two of them matter here, and neither needs
authentication.

### Charts

```
GET https://ourworldindata.org/api/search?q=<query>&type=charts&hitsPerPage=<n>
```

Returns the published figures: `slug`, `title`, `subtitle`, `availableEntities` and more. Data
for a chart lives at `https://ourworldindata.org/grapher/<slug>.csv`, and its documentation at
`<slug>.metadata.json`.

`hitsPerPage` is capped at 100. Requesting more returns a 400.

### Indicators

```
GET https://search.owid.io/indicators?q=<query>&limit=<n>
```

Semantic search over the ETL catalog behind the charts. Each hit carries a `catalog_path` and,
under `metadata`, a `parquet_url` pointing at a file in
`https://catalog.ourworldindata.org/...`.

This service reports no catalog total; `total_results` simply echoes the page size. It is also a
separate deployment under active development, so the package treats its failure as non-fatal and
falls back to charts only.

## How search combines them

`search_catalog(query)` tries charts first and falls through to indicators:

```python
from lumen_owid import search_catalog

search_catalog("life expectancy")     # -> a chart
search_catalog("cropland area per person")   # -> possibly an indicator
```

Charts win when they exist because they are curated and carry prose the model can use. The
indicator catalog is the fallback for series nobody charted.

Both surfaces are normalized onto the same columns, so everything downstream is
surface-agnostic:

| Column | Meaning |
|---|---|
| `title` | Human-readable name |
| `description` | Subtitle for charts, description for indicators |
| `kind` | `chart` or `indicator` |
| `url` | The CSV or parquet URL |
| `table_name` | SQL identifier the table will get |
| `slug` | Chart slug, or `None` for indicators |
| `column` | Matched indicator column, or `None` for charts |

!!! note "Why indicators are named after the dataset"
    An indicator's parquet holds its *whole* source dataset, often 20+ columns. Naming the table
    after the single matched column would misrepresent what it contains, so the table takes the
    dataset name and the matched column is recorded in `column` and repeated in the table's
    description.

## Why search is live

The `OWIDSourceControls` table loads 100 popular charts at startup, purely so there is something
to browse. Search does not use that table.

`CatalogSourceControls` would normally embed the catalog into a vector store and search it
locally. With 12,200 charts that is a poor trade: a large startup cost to reproduce a search
engine OWID already runs. So `_search_catalog` is overridden to query OWID live and append the
hit to the catalog frame, which keeps every other part of the base class working unchanged.

The practical consequence: the browse table shows 100 charts, but the agent can reach all of
them.

## Countries and aggregates

OWID mixes real countries with aggregates in the same table. On the UN population
dataset there are 236 countries and 26 aggregates: continents, income groups, UN
regions and groupings such as "Least developed countries".

They are distinguishable by code length, since ISO alpha-3 is exactly three characters
and every aggregate identifier is longer or absent:

| Kind | Example | `Code` |
|---|---|---|
| Country | France | `FRA` |
| OWID region | Africa | `OWID_AFR` |
| UN region | Europe (UN) | `UN_EUR` |
| Grouping | Least developed countries | *(blank)* |

Use [`OnlyCountries`](api.md#onlycountries) to drop them. Chart tables only, since
indicator parquets publish no code column.

## Column naming, and why it bites

The two surfaces disagree about how to spell the key columns:

| | Country | Year | ISO code |
|---|---|---|---|
| Chart CSVs | `Entity` | `Year` | `Code` |
| Indicator parquets | `country` | `year` | usually absent |

Anything reading both has to cope with either. The operations take `country` and `year` as
parameters for this reason, and `lumen_owid.utils` provides `country_column`, `year_column` and
`code_column` to detect them.

## Loading

Loading is deliberately thin. `DuckDBSource` already builds a read expression from a URL, so the
only real work is choosing between two forms:

```sql
-- charts: an explicit sample_size is required, see below
SELECT * FROM read_csv('https://ourworldindata.org/grapher/<slug>.csv', sample_size=-1)

-- indicators
SELECT * FROM read_parquet('https://catalog.ourworldindata.org/....parquet')
```

Each result is materialized into a real table rather than registered as a view. A view over a
reader refetches the remote file on every query and cannot serve a windowed aggregate at all
(DuckDB raises `CSVReaderSerialize not implemented`). Materializing once takes repeat queries
from roughly half a second to about a millisecond.

!!! warning "The sample_size gotcha"
    OWID chart CSVs often leave an annotation column empty for thousands of rows before the
    first quoted value containing a comma appears. DuckDB's type sniffer samples 20,480 rows by
    default, so it guesses the column is simple and then aborts partway through the file. The
    Maddison GDP CSV breaks at line 21,152. `sample_size=-1` reads the whole file to infer types
    and fixes it.

## What is reachable

Measured against a random sample of 120 charts drawn across 14 topics:

| | Share | Note |
|---|---|---|
| Downloadable | ~93% | roughly 11,400 of 12,200 charts |
| No CSV published | ~4% | returns 404 |
| Non-redistributable | ~2% | returns 403 with an explanation |

Both failure modes surface as a message, never an exception, and carry OWID's own wording.
Popular health charts fail more often than average because many are built on IHME data, which
OWID may not redistribute.
