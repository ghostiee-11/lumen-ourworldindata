# Getting started

## Install

```bash
pip install lumen-ourworldindata
```

The world map needs country polygons, which are a separate extra so the core package stays light:

```bash
pip install "lumen-ourworldindata[geo]"
```

!!! note "Lumen version"
    This package builds on `CatalogSourceControls`, which is recent. If the import fails, install
    Lumen from main:

    ```bash
    pip install "git+https://github.com/holoviz/lumen@main#egg=lumen[ai]"
    ```

## Set an LLM key

The chat interface needs a model. Lumen picks one up from the environment:

```bash
export OPENAI_API_KEY="sk-..."
# or ANTHROPIC_API_KEY, or configure another provider through Lumen
```

Everything except the chat works without a key: the catalog browser, `OWIDSource`, the
operations and the views are all ordinary Python.

## Run it

```bash
lumen-owid
```

That serves the explorer on <http://localhost:5006>. Equivalent forms:

```bash
panel serve src/lumen_owid/app.py --show     # from a checkout
```

```python
from lumen_owid import build_ui

build_ui().servable()                         # in your own app.py
```

## Your first questions

Start here. It loads two datasets from two different OWID surfaces and joins them, which is the
whole package in one request:

> how does the homelessness rate compare against GDP per capita?

Then try these, each of which exercises a different piece:

| Ask | Exercises |
|---|---|
| *map life expectancy across the world* | the choropleth and `MapAcrossCountries` |
| *compare population in India, China and Nigeria indexed to 1950* | `CompareCountries` and `IndexToBaseYear` |
| *are street and shelter homelessness correlated?* | `CorrelateIndicators` |
| *load the suicide death rates chart* | the blocked-data path, see below |

## Browsing instead of asking

Click **Select Data to Explore** in the sidebar to get a filterable table of popular charts.
Click the download icon on a row to load it. This costs nothing and needs no key.

The table is a starting point, not the whole catalog. Searching through the chat reaches all
12,200 charts, because search goes to OWID rather than to the loaded table.

## When a dataset will not load

Some charts are listed in search but cannot be served. You will see a plain message rather than
an error, carrying OWID's own explanation:

> Suicide rate cannot be loaded. This chart contains non-redistributable data that we are not
> allowed to re-share.

That is expected for roughly 2% of charts. Another 4% publish no CSV at all. See
[Limitations](limitations.md).

## Using it as a library

You do not need the app at all:

```python
from lumen_owid import OWIDSource

source = OWIDSource().add_chart("life-expectancy")
source.get("life_expectancy").head()
```

Continue with [Examples](examples.md).
