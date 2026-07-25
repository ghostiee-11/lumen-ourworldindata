# Does homelessness track how rich a country is?

A data blog post built with Lumen and Our World In Data, and a demo app for the
`OWIDSourceControls` that live in Lumen core.

The short answer is no. Across the 22 countries that report both, the correlation
between the homelessness rate and GDP per capita is **0.069**. Ireland reports 253
people per 100,000 at $60,257 per person; Norway reports 26 at $88,366.

Read the caveats in the post before quoting that anywhere. These counts are not
directly comparable across countries.

## Build the post

```bash
python scripts/build_post.py
open out/homelessness-vs-gdp.html
```

Every number in the prose is computed from the joined data, so the text cannot
drift from what the datasets actually say.

## Try the catalog

```bash
panel serve scripts/app.py --show
```

Needs an LLM key in the environment. Browse the Our World In Data catalog in the
sidebar, or ask a question and let the agent find the datasets for you.

## Check it still works

```bash
pytest -m network
```

Lumen's own tests for these controls are fully mocked, so this is the live guard:
it fails if Our World In Data reshapes either table.

Data: OECD (2024) and the Maddison Project Database, via Our World In Data, CC BY 4.0.
