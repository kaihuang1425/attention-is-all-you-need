from __future__ import annotations

import pandas as pd
import pytest

from pipeline import load
from pipeline.config import raw_dir


def _have_data() -> bool:
    return (raw_dir() / "plays.csv").exists()


def pytest_collection_modifyitems(config, items):
    if _have_data():
        return
    skip = pytest.mark.skip(reason="event data missing: run scripts/get_data.sh or set NFL_DATA_DIR")
    for item in items:
        if "data" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def games() -> pd.DataFrame:
    return load.load_games()


@pytest.fixture(scope="session")
def plays() -> pd.DataFrame:
    return load.load_plays()


@pytest.fixture(scope="session")
def players() -> pd.DataFrame:
    return load.load_players()


@pytest.fixture(scope="session")
def pff() -> pd.DataFrame:
    return load.load_pff()


@pytest.fixture(scope="session")
def sample_tracking() -> pd.DataFrame:
    """Ten games of raw tracking, picked deterministically."""
    return pd.concat([df for _, df in load.iter_tracking(load.sample_game_ids(10))], ignore_index=True)
