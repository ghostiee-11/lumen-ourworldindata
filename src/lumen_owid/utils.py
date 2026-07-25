"""Shared helpers: country geometry and the entity/year column conventions."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

# OWID chart CSVs label these columns Entity/Code/Year; the indicator parquets in the
# ETL catalog use country/year and carry no ISO code. Anything reading both has to
# cope with either spelling.
COUNTRY_COLUMNS = ("country", "Entity", "entity")
YEAR_COLUMNS = ("year", "Year")
CODE_COLUMNS = ("Code", "code", "iso_code")


def pick_column(
    df: pd.DataFrame, candidates: tuple[str, ...], default: str | None = None,
) -> str | None:
    """Return the first candidate present in the frame."""
    return next((column for column in candidates if column in df.columns), default)


def country_column(df: pd.DataFrame) -> str | None:
    return pick_column(df, COUNTRY_COLUMNS)


def year_column(df: pd.DataFrame) -> str | None:
    return pick_column(df, YEAR_COLUMNS)


def code_column(df: pd.DataFrame) -> str | None:
    return pick_column(df, CODE_COLUMNS)


def value_columns(df: pd.DataFrame) -> list[str]:
    """The numeric measure columns, i.e. everything that is not an identifier."""
    identifiers = set(COUNTRY_COLUMNS + YEAR_COLUMNS + CODE_COLUMNS)
    return [
        column for column in df.columns
        if column not in identifiers and pd.api.types.is_numeric_dtype(df[column])
    ]


@lru_cache(maxsize=1)
def country_geometry():
    """World country polygons keyed by ISO alpha-3, downloaded once and cached.

    Natural Earth ships five territories with ISO_A3 set to the sentinel "-99"
    (Kosovo, Somaliland and similar disputed cases), so ADM0_A3 fills those in.
    """
    import cartopy.io.shapereader as shapereader
    import geopandas as gpd

    path = shapereader.natural_earth(
        resolution="110m", category="cultural", name="admin_0_countries",
    )
    countries = gpd.read_file(path)
    countries["iso_a3"] = countries.ISO_A3.where(countries.ISO_A3 != "-99", countries.ADM0_A3)
    return countries[["iso_a3", "NAME", "geometry"]].rename(columns={"NAME": "country"})
