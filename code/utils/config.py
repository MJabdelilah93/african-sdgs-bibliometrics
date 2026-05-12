"""Loads config.yaml from the article08 root and exposes it as `cfg`."""
from pathlib import Path
import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"

with open(_CONFIG_PATH, encoding="utf-8") as _fh:
    cfg: dict = yaml.safe_load(_fh)
