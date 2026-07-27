# lumen-ourworldindata

Explore [Our World In Data](https://ourworldindata.org/) from [Lumen](https://lumen.holoviz.org/)
by asking questions in plain language.

```bash
pip install "lumen-ourworldindata[geo]"
lumen-owid
```

Then ask it something like *how does the homelessness rate compare against GDP per capita?* It
searches Our World In Data, loads whatever datasets the question needs, joins them, and plots the
answer.

## The idea

Our World In Data has already done the hard part. It collects, harmonizes and documents data on
almost every global development question, publishes it as CSV and parquet over plain HTTPS, and
writes careful prose about what each series means and where it came from.

DuckDB can read those formats in place. So this package does not download, parse or cache
anything. It does three things instead.

### Discovery

OWID publishes around 12,200 charts, far too many to hold locally, so search delegates to OWID's
own APIs rather than a bundled snapshot. There are two surfaces and the package uses both:

| Surface | What it holds | When it wins |
|---|---|---|
| Charts | The published figures, curated, with prose | Almost always. This is what people mean by "an OWID chart" |
| Indicators | The much larger ETL catalog behind them | Series that were never charted |

Charts are tried first. The indicator catalog is the fallback that reaches the long tail.

### Metadata

OWID writes a description, a unit and a citation for every indicator. Those are attached to each
table as it loads, so the model can tell five near-identical homelessness series apart. This is
the part that separates a plausible answer from a correct one, and it is most of the value the
package adds.

### One workspace

Every dataset is added to the same DuckDB source. Lumen only avoids a materializing
cross-source merge when all tables share a source, so this is what keeps joins across OWID
datasets in SQL rather than in pandas. Any OWID dataset can be joined against any other, on
country and year, with no entity harmonization on your side, because OWID already did it.

## What you get

| Component | Purpose |
|---|---|
| [`OWIDSource`](api.md#owidsource) | Reads charts and indicators over HTTPS into one DuckDB workspace |
| [`OWIDSourceControls`](catalog.md) | Catalog browser, and the agent's live search tool |
| [`LatestPerCountry`](api.md#latestpercountry) | Each country's most recent non-null observation |
| [`PerCapita`](api.md#percapita) | Divide a total by population, guarding against divide-by-zero |
| [`IndexToBaseYear`](api.md#indextobaseyear) | Rebase each country to 100 so trajectories compare |
| [`WithGeometry`](api.md#withgeometry) | Attach country boundaries so any renderer can draw a map |
| [`MapAcrossCountries`](api.md#analyses) | Analysis: map one measure worldwide |
| [`CompareCountries`](api.md#analyses) | Analysis: several countries on one time axis |
| [`CorrelateIndicators`](api.md#analyses) | Analysis: scatter two measures, report Pearson r |

## What this deliberately does not do

There is no OWID chart class. Rendering is Lumen's job: a line over time is
`hvPlotView(kind="line", x=year, y=value, by=country)`, and a map is the same view with
`kind="polygons"` once `WithGeometry` has attached boundaries. Wrapping those in bespoke
classes would only take choices away from the model.

## Next

- [Getting started](getting-started.md) — install, run, and the first few questions to try
- [The catalog](catalog.md) — how discovery works and what is reachable
- [Examples](examples.md) — worked code for the common tasks
- [Extending Lumen](extending-lumen.md) — how to do this for your own data source
- [API reference](api.md) — every public class and function
- [Limitations](limitations.md) — what this data can and cannot support
