"""
year_split_query.py
Utility: produce year-restricted copies of composed SDG queries for
chunked Scopus CSV export (Scopus caps exports at 20,000 records).

Usage (library)
---------------
    from code.utils.year_split_query import split_query_by_years
    paths = split_query_by_years(13, [(2015, 2018), (2019, 2022), (2023, 2025)])

Usage (CLI)
-----------
    python -m code.utils.year_split_query --sdg 13 --ranges 2015-2018 2019-2022 2023-2025
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple


BASE    = Path(__file__).resolve().parent.parent.parent
COMPOSED = BASE / "sdg_queries" / "composed"

# Matches the PUBYEAR clause we write in every composed query
_PUBYEAR_PAT = re.compile(r"AND PUBYEAR > \d{4} AND PUBYEAR < \d{4}")


def split_query_by_years(
    sdg_number: int,
    year_ranges: List[Tuple[int, int]],
) -> List[str]:
    """
    Produce year-range variants of a composed SDG query file.

    For each (start, end) pair the PUBYEAR clause is replaced with:
        AND PUBYEAR > {start-1} AND PUBYEAR < {end+1}
    so that the range [start, end] is fully inclusive.

    Output files are written to sdg_queries/composed/ as:
        SDG{nn}_full_{start}-{end}.txt

    Parameters
    ----------
    sdg_number : int         SDG number 1-17.
    year_ranges : list       List of (start_year, end_year) tuples, inclusive.

    Returns
    -------
    list[str]  Paths of every file created.
    """
    nn  = f"{sdg_number:02d}"
    src = COMPOSED / f"SDG{nn}_full.txt"

    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")

    original = src.read_text(encoding="utf-8")

    if not _PUBYEAR_PAT.search(original):
        raise ValueError(
            f"No PUBYEAR clause found in {src.name}. "
            "Expected pattern: AND PUBYEAR > NNNN AND PUBYEAR < NNNN"
        )

    created: List[str] = []
    for start, end in year_ranges:
        new_clause = f"AND PUBYEAR > {start - 1} AND PUBYEAR < {end + 1}"
        new_query  = _PUBYEAR_PAT.sub(new_clause, original)
        out_path   = COMPOSED / f"SDG{nn}_full_{start}-{end}.txt"
        out_path.write_text(new_query, encoding="utf-8")
        created.append(str(out_path))

    return created


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_range(s: str) -> Tuple[int, int]:
    parts = s.split("-")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"Range must be start-end, got: {s}")
    return int(parts[0]), int(parts[1])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Produce year-range variants of a composed SDG query."
    )
    parser.add_argument("--sdg",    type=int, required=True, help="SDG number 1-17")
    parser.add_argument("--ranges", type=_parse_range, nargs="+", required=True,
                        metavar="START-END",
                        help="Year ranges, e.g. 2015-2020 2021-2025")
    args = parser.parse_args()

    created = split_query_by_years(args.sdg, args.ranges)
    for p in created:
        print(f"  Created: {Path(p).name}")


if __name__ == "__main__":
    main()
