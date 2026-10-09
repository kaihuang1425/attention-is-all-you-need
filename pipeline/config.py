"""Paths and model parameters, read from pipeline/config.yaml."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _repo_path(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else REPO_ROOT / p


def raw_dir() -> Path:
    """Folder holding games.csv, plays.csv, ... and tracking/. NFL_DATA_DIR overrides config."""
    env = os.environ.get("NFL_DATA_DIR")
    return Path(env) if env else _repo_path(load_config()["data"]["raw_dir"])


def derived_dir() -> Path:
    return _repo_path(load_config()["data"]["derived_dir"])


def external_dir() -> Path:
    return _repo_path(load_config()["data"]["external_dir"])


def export_dir() -> Path:
    return _repo_path(load_config()["data"]["export_dir"])
