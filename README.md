# 🌍 lumen-ourworldindata

[![CI](https://img.shields.io/github/actions/workflow/status/ghostiee-11/lumen-ourworldindata/ci.yml?style=flat-square&branch=main)](https://github.com/ghostiee-11/lumen-ourworldindata/actions/workflows/ci.yml)
[![pypi-version](https://img.shields.io/pypi/v/lumen-ourworldindata.svg?logo=pypi&logoColor=white&style=flat-square)](https://pypi.org/project/lumen-ourworldindata)
[![python-version](https://img.shields.io/pypi/pyversions/lumen-ourworldindata?logoColor=white&logo=python&style=flat-square)](https://pypi.org/project/lumen-ourworldindata)

## Overview

https://github.com/user-attachments/assets/37765f77-00a2-4be2-814a-c1f335bfadb6

lumen-ourworldindata is an extension that lets [Lumen](https://lumen.holoviz.org/) explore
[Our World In Data](https://ourworldindata.org/), the public research database covering most
global development questions. It aims to let anyone ask a question in plain language and get an
answer computed from OWID's own data, without first knowing which dataset holds it.

Roughly **12,200 charts** are reachable, of which about 93% publish downloadable data, plus the
much larger indicator catalog behind them including series that were never charted.

Nothing is downloaded. OWID serves CSV and parquet over plain HTTPS and DuckDB reads those in
place, so this package supplies discovery, the metadata a model needs to pick the right series,
and the reshapes and views that OWID's country/year tables always want.

## Features

- Natural language querying of any Our World In Data chart or indicator
- Live search against OWID's own APIs, so the whole catalog is reachable rather than a snapshot
- Every dataset lands in one DuckDB source, so any OWID dataset joins any other in plain SQL
- OWID's own descriptions, units and citations are passed to the model, which is what lets it
  choose between near-identical series
- Domain analyses: map a measure across the world, compare countries on a common index, or test
  whether two indicators actually move together
- A choropleth view, matching the map tab OWID offers on almost every chart

## Installation

Install it via `pip`:

```bash
pip install lumen-ourworldindata
```

The world map needs country polygons, which are an optional extra:

```bash
pip install "lumen-ourworldindata[geo]"
```

## Usage

To launch the Lumen app, run:

```bash
lumen-owid
```

Then ask it something:

> how does the homelessness rate compare against GDP per capita?

It searches Our World In Data, loads both datasets into one DuckDB workspace, joins them on
country, and plots the result. Nothing about that question is special-cased; any two OWID
datasets join the same way.

You can also drive it directly:

```python
from lumen_owid import OWIDSource

source = OWIDSource().add_chart("life-expectancy")
source.execute("SELECT * FROM life_expectancy WHERE Entity = 'Japan'")
```

Or attach the catalog to your own Lumen app:

```python
from lumen.ai.ui import ExplorerUI
from lumen_owid import ANALYSES, OWIDSourceControls

ExplorerUI(source_controls=[OWIDSourceControls], analyses=ANALYSES).servable()
```

## A note on what the data can and cannot say

Our World In Data harmonizes across countries only as far as is possible, and says so in the
metadata this package forwards to the model. Definitions and collection methods genuinely differ
between countries. About 2% of charts are built on data OWID is not licensed to redistribute;
those are listed in search but cannot be loaded, and the app says so plainly rather than failing.

---

## Development

```bash
git clone https://github.com/ghostiee-11/lumen-ourworldindata
cd lumen-ourworldindata
```

For a simple setup use [`uv`](https://docs.astral.sh/uv/):

```bash
uv venv
source .venv/bin/activate # on linux. Similar commands for windows and osx
uv pip install -e ".[dev,geo]"
pytest tests
```

The offline suite is fully mocked and runs in seconds. The network suite hits the real services
and is the guard that fails when Our World In Data renames a column or retires an endpoint:

```bash
pytest tests -m "not network"   # fast, deterministic, what CI runs
pytest tests -m network         # live, run on demand
```

## Documentation

- [Getting started](docs/getting-started.md)
- [The catalog](docs/catalog.md) — how discovery works and what is reachable
- [Examples](docs/examples.md)
- [API reference](docs/api.md)
- [Limitations](docs/limitations.md) — read before publishing anything based on this

## ❤️ Contributing

Contributions are welcome. Please open an issue describing the change before sending a pull
request, run `ruff check src tests` and make sure `pytest tests` passes.

## License

BSD 3-Clause. Data is from Our World In Data and its cited providers, under CC BY 4.0.
