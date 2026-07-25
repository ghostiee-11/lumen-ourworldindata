# lumen-ourworldindata

Explore [Our World In Data](https://ourworldindata.org/) from [Lumen](https://lumen.holoviz.org/)
by asking questions in plain language.

## How it works

Our World In Data publishes everything as CSV and parquet over plain HTTPS, and DuckDB reads
those formats in place. So this package does not download, parse or cache anything. It does
three things instead.

**Discovery.** OWID has around 12,200 charts, far too many to hold locally, so search goes to
OWID's own APIs. Charts are tried first because they are curated and carry usable prose; the
indicator catalog is the fallback that reaches series which were never charted.

**Metadata.** OWID writes careful descriptions, units and citations for every indicator. Those
are attached to each table so the model can tell five near-identical homelessness series apart.
This is the part that makes the difference between a plausible answer and a correct one.

**One source.** Every dataset is added to the same DuckDB source. Lumen only avoids a
materializing cross-source merge when all tables share a source, so this is what keeps joins
across OWID datasets in SQL rather than in pandas.

## Quick start

```bash
pip install "lumen-ourworldindata[geo]"
lumen-owid
```

Ask it: *how does the homelessness rate compare against GDP per capita?*

## Components

| Component | Purpose |
|---|---|
| `OWIDSource` | Reads charts and indicators over HTTPS into one DuckDB workspace |
| `OWIDSourceControls` | Catalog browser plus the agent's live search tool |
| `LatestPerCountry` | Each country's most recent non-null observation |
| `PerCapita` | Divide a total by population, guarding against division by zero |
| `IndexToBaseYear` | Rebase each country to 100 so trajectories compare |
| `OWIDChoropleth` | World map, matching OWID's own map tab |
| `MapAcrossCountries` | Analysis: map one measure worldwide |
| `CompareCountries` | Analysis: several countries on one time axis |
| `CorrelateIndicators` | Analysis: scatter two measures and report Pearson r |

## Limits worth knowing

About 4% of charts publish no CSV and about 2% are built on data OWID may not redistribute.
Both are listed in search results, and loading one returns OWID's own explanation rather than an
error.

OWID's country counts are harmonized only as far as is possible; definitions and collection
methods differ between countries. The metadata forwarded to the model says so, and any published
conclusion should too.
