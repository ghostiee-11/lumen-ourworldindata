"""Live guard against Our World In Data changing shape.

Lumen's own tests for OWIDSourceControls are fully mocked, which keeps its CI fast
and deterministic. Nothing there would notice if OWID renamed a column or retired a
dataset, so this suite hits the real endpoints and is the reason the post can be
rebuilt with confidence.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_post import load, prose  # noqa: E402

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def joined():
    return load()


def test_both_datasets_still_join_on_country(joined):
    assert len(joined) >= 100
    assert {"country", "year", "rate", "gdp", "methodology"} <= set(joined.columns)
    assert joined.rate.notna().all()
    assert joined.gdp.notna().all()


def test_the_methodology_mix_is_still_reported(joined):
    """The caveat in the post is computed from this column, not asserted by hand."""
    assert joined.methodology.notna().any()
    assert joined.methodology.nunique() > 1


def test_wealth_still_fails_to_explain_homelessness(joined):
    """Asserted loosely: this should fail on a reshaped table, not on a revised value."""
    assert abs(joined.rate.corr(joined.gdp)) < 0.3


def test_the_prose_numbers_come_from_the_data(joined):
    intro, middle, _ = prose(joined)
    assert f"{joined.rate.corr(joined.gdp):.3f}" in intro
    assert str(len(joined)) in intro
    assert joined.iloc[0].country in middle
