# Limitations

What this package, and this data, cannot do. Worth reading before publishing anything based on
an answer it gives you.

## The data is not as comparable as it looks

This is the big one, and Our World In Data says so itself in the metadata this package forwards
to the model.

OWID harmonizes country names, units and time ranges. It cannot harmonize away the fact that
countries define and measure things differently. A homelessness count is the clearest case: some
countries run a street count on a single night, some use a census, some publish an estimate, and
some report registered households assessed as homeless. Those are not the same measurement, and
a single-night count also misses anyone housed that night and homeless a week later.

The package surfaces the descriptions that say this. It cannot stop you ignoring them. If a
dataset carries a methodology column, look at it before comparing countries.

## Roughly 7% of charts cannot be loaded

Measured on a random sample of 120 charts across 14 topics:

| | Share | Behaviour |
|---|---|---|
| Downloadable | ~93% | loads normally |
| No CSV published | ~4% | message, HTTP 404 |
| Non-redistributable | ~2% | message with OWID's explanation, HTTP 403 |

Non-redistributable charts are built on data OWID is licensed to display but not to re-share,
notably IHME's Global Burden of Disease. These are over-represented among popular health charts,
so the visible failure rate while browsing can look worse than 7%.

Neither case raises. Both return a message carrying OWID's own wording.

## The indicator service is less stable than the chart API

`search.owid.io` is a separate deployment under active development. It is not as formally
documented as the grapher endpoints, rejects an empty query with a 422, and reports no catalog
total. The package treats its failure as non-fatal and falls back to chart search, so an outage
degrades the long tail rather than breaking search.

## Nothing is cached between sessions

Each `OWIDSource` is an in-memory DuckDB database. Datasets are read once per session and
materialized, so repeat queries within a session are fast, but restarting the app re-fetches.
That is deliberate: OWID updates its data, and a stale local cache is worse than a second of
network.

## The map is coarse and drops aggregates

The choropleth uses Natural Earth's 110m boundaries: 177 countries. Small states and territories
are absent. OWID also publishes many non-country entities, continents, income groups and custom
regions such as `OWID_AFR`, which match no boundary at all.

Those rows are counted and reported under the map rather than dropped silently, but they are
still not shown. On a typical dataset expect roughly two thirds of rows to land on the map.

## Correlations here are descriptive, nothing more

`CorrelateIndicators` reports Pearson r on whatever two columns it is given. It does not control
for anything, does not test significance, and is sensitive to outliers. Country-level
correlations are also vulnerable to the ecological fallacy: a relationship between national
averages does not imply the same relationship between individuals.

Treat a number from it as a prompt to look closer, not a finding.

## Comparing "latest" values compares different years

`LatestPerCountry` takes each country's most recent observation, because OWID coverage is ragged
and filtering to one shared year usually discards most of the data. The cost is that the
resulting cross-section mixes years. For slow-moving measures that is usually acceptable; for
volatile ones it is not.

## Requires a recent Lumen

The catalog controls build on `CatalogSourceControls`, which is recent. Against an older
released Lumen the import will fail. Install Lumen from main if needed.

## The LLM can still be wrong

The metadata makes it much likelier that the model picks the right series, and analyses give it
named, auditable steps instead of improvised SQL. Neither guarantees a correct answer. The SQL it
writes is visible in the interface. Read it.
