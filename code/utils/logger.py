"""Provides get_logger(stage_name) — writes to provenance/logs/<stage>.log."""
import logging
import sys
from pathlib import Path

_LOGS_DIR = Path(__file__).resolve().parents[2] / "provenance" / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(stage_name: str) -> logging.Logger:
    logger = logging.getLogger(stage_name)
    if logger.handlers:
        return logger  # already configured in this process
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(_LOGS_DIR / f"{stage_name}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger
