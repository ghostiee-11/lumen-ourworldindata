# Extending Lumen for your own data

This package is small. Most of what makes it useful is discovery and metadata, not code,
and that shape transfers to any other source. This is what was learned building it, in
the order the decisions come up.

## Start by finding out how little you need

Before writing a class, check what Lumen already does with your data. `DuckDBSource`
reads a CSV or parquet URL in place, builds the read expression itself, and joins
anything already loaded. That covered the entire data path here, so this package
contains no downloader, no cache, and no parser.

```python
from lumen.sources.duckdb import DuckDBSource

DuckDBSource(
    uri=":memory:",
    initializers=["INSTALL httpfs;", "LOAD httpfs;"],
    tables={"data": "https://example.org/data.parquet"},
)
```

If that already answers your question, you do not need a package. What you probably need
is the part Lumen cannot guess: **where the data lives and what it means.**

## The four extension points

| You want to | Subclass | Contract |
|---|---|---|
| Read from a system Lumen does not know | `DuckDBSource` | your own `add_*` methods |
| Let people browse a catalog | `CatalogSourceControls` | `_load_catalog`, `_fetch_entry`, `_entry_to_text` |
| Reshape data the same way every time | `SQLTransform` or `Transform` | `apply` |
| Give the model a named, auditable step | `Analysis` | `applies`, `__call__` |

Nothing else was needed here. Notably absent: a `Source` subclass from scratch, and any
`View` subclass at all.

## Source: subclass DuckDBSource, not Source

`Source` is a large interface. `DuckDBSource` already implements it and gives you SQL,
schema inference, and cross-table joins. Subclassing it means writing only the part that
knows about your system:

```python
class OWIDSource(DuckDBSource):
    source_type = "owid"

    def __init__(self, **params):
        params.setdefault("uri", ":memory:")
        params.setdefault("initializers", ["INSTALL httpfs;", "LOAD httpfs;"])
        super().__init__(**params)

    def add_chart(self, slug):
        ...  # build one read expression, attach documentation
```

Two things that are easy to get wrong:

**Keep everything in one source.** `create_sql_expr_source` returns a *new* source that
shares the connection and unions the tables. Rebind to it. Lumen only avoids a
materializing cross-source merge when every table shares a source, so one source per
dataset quietly moves your joins into pandas.

**Materialize; do not register a view over a reader.** Registering
`read_csv(url)` as a view re-fetches on every query and cannot serve a windowed
aggregate at all. Reading once into a real table took repeat queries here from about
half a second to a millisecond.

```python
self._connection.execute(f'CREATE OR REPLACE TABLE "{table}" AS ({expression})')
```

## Controls: the catalog is the product

`CatalogSourceControls` gives you a browsable table, filtering, and an agent-facing
search tool for three methods. The interesting decision is what `_search_catalog` does.

The default embeds your catalog into a vector store. That is right for a fixed catalog
and wrong for a large or changing one. Our World In Data publishes over twelve thousand
charts and runs its own search engine, so this package overrides `_search_catalog` to
query that live and append the hit to the catalog frame, which leaves every other part
of the base class working:

```python
async def _search_catalog(self, query: str) -> int | None:
    hits = await asyncio.to_thread(search_catalog, query)
    if hits.empty:
        return None
    self.catalog_df = pd.concat([self.catalog_df, hits.head(1)], ignore_index=True)
    return len(self.catalog_df) - 1
```

Ask whether your source already has a search engine before you build a second one.

## Metadata is most of the value

This is the part that is easy to skip and hardest to replace. A model choosing between
five near-identical series cannot do it from column names. It needs the prose your
source already wrote.

Attach it through `Source.metadata`:

```python
{"table": {"description": "...", "columns": {"column_name": "..."}}}
```

Three lessons, each of which cost real debugging:

**Check that documented columns exist.** OWID keys its metadata by indicator title while
the CSV headers are the chart's display names, so every column description was attached
to a column that was not in the table. Nothing errors; the documentation is simply
invisible. Assert it:

```python
assert set(source.metadata[table]["columns"]) <= set(source.get(table).columns)
```

**Budget it.** Forwarding every caveat sounds free until a thirty-column dataset crowds
out the rest of the prompt. Share a budget across the table rather than capping each
column, so the common case is untouched.

**Do not guess when you are unsure.** Where documentation could not be matched to a
column with confidence, this package drops it. Documentation on the wrong column is
worse than none.

## Transforms: encode the reshapes your data always needs

Every domain has verbs that recur. For country-year data they are "latest observation
per country", "per capita", and "index to a base year". Writing them as `SQLTransform`
subclasses means they compose into pipelines and run in the database:

```python
class LatestPerCountry(SQLTransform):
    def apply(self, sql_in: str) -> str:
        return f'SELECT * FROM ({sql_in}) QUALIFY row_number() OVER (...) = 1'
```

Use `Transform` instead when the work genuinely needs pandas, as attaching map
boundaries does.

## Views: usually do not

This is the strongest recommendation here, and it is the one thing this package got
wrong first.

It originally shipped an `OWIDChoropleth` and an `OWIDTimeSeries`. Both were deleted,
because `hvPlotView` already does the drawing:

```python
hvPlotView(pipeline=..., kind="line", x="Year", y="Life expectancy", by=["Entity"])
hvPlotView(pipeline=..., kind="polygons", c="Life expectancy", geo=True)
```

A bespoke view class hardcodes a chart the model should be choosing. What survived is
the one piece Lumen genuinely cannot do: joining country names to map boundaries, which
is now a `Transform`. The test is simple. Ask what your view does that `hvPlotView` or
`VegaLiteView` cannot, and if the answer is data preparation, ship a transform instead.

## Analyses: name the questions people actually ask

An `Analysis` is a step the model can invoke by name instead of improvising SQL. Good
ones correspond to questions, not to chart types.

```python
class CorrelateIndicators(Analysis):
    @classmethod
    async def applies(cls, pipeline) -> bool:
        return len(value_columns(pipeline.data)) >= 2

    def __call__(self, pipeline, context):
        ...
```

Two notes. `Analysis` is a `ParameterizedFunction`, so configure with
`.instance(value="x")` before calling. And although `Analysis.columns` documents tuple
support for "one of these columns", the UI renders the list with `", ".join(...)` and
raises on a tuple, so override `applies` when your columns have more than one spelling.

## Be a good citizen

Your source is probably someone else's server, and often a nonprofit's. Concurrency is
where a helpful library turns into a crawler. Three concurrent fetches recovered most of
the available speedup here; eight would have been rude for very little gain.

```python
MAX_CONCURRENT_FETCHES = 3
```

Handle refusal as data, not as an exception. Roughly 7% of OWID charts cannot be served
because of licensing or because no CSV exists, and both are listed in search results. A
batch load reports them and continues rather than discarding the rest, and the message
carries the source's own explanation rather than a status code.

## Test against the real thing

Mock everything in CI so it stays fast and deterministic, then keep a separate live
suite behind a marker and run it on demand:

```bash
pytest tests -m "not network"   # CI
pytest tests -m network         # the guard that catches the source changing shape
```

Every significant bug in this package was found by the live suite, not the mocked one:
the column-documentation mismatch, a bare URL that was not valid SQL, a parameter that
silently shadowed `View.limit`, and aggregates surviving a filter because the source
uses more than one prefix. Mocks confirm your code does what you wrote. Only real data
tells you whether what you wrote was right.
