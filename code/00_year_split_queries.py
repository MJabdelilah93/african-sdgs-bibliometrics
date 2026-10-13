"""
00_year_split_queries.py
Produce the publication-year split variants of the composed SDG queries whose Scopus
result counts exceed the 20,000-record CSV export limit.

The ranges below are those of the Scopus exports of 8 May 2026 (one export file per
range; see provenance/query_manifest.csv). SDGs 5, 7, 8, 10 and 14 were exported with
the unsplit query (SDG{nn}_full.txt).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "utils"))

from year_split_query import split_query_by_years

SPLITS = {
    1:  [(2015, 2020), (2021, 2025)],
    2:  [(2015, 2021), (2022, 2025)],
    3:  [(2015, 2018), (2019, 2021), (2022, 2023), (2024, 2025)],
    4:  [(2015, 2020), (2021, 2025)],
    6:  [(2015, 2020), (2021, 2023), (2024, 2025)],
    9:  [(2015, 2020), (2021, 2023), (2024, 2025)],
    11: [(2015, 2020), (2021, 2025)],
    12: [(2015, 2020), (2021, 2022), (2023, 2023), (2024, 2024), (2025, 2025)],
    13: [(2015, 2018), (2019, 2022), (2023, 2024), (2025, 2025)],
    15: [(2015, 2020), (2021, 2022), (2023, 2024), (2025, 2025)],
    16: [(2015, 2020), (2021, 2025)],
    17: [(2015, 2020), (2021, 2023), (2024, 2025)],
}

expected_files = sum(len(r) for r in SPLITS.values())   # 36
created_all = []

for sdg_num, ranges in SPLITS.items():
    nn = f"{sdg_num:02d}"
    print(f"\nSDG {nn} — {len(ranges)}-way year split:")
    try:
        paths = split_query_by_years(sdg_num, ranges)
        for p in paths:
            print(f"  Created: {Path(p).name}")
            created_all.append(p)
    except Exception as exc:
        print(f"  ERROR: {exc}")
        sys.exit(1)

print(f"\n{'='*50}")
print(f"Year-split files created : {len(created_all)} (expected {expected_files})")
if len(created_all) != expected_files:
    print("WARNING: count mismatch")
else:
    print("All expected files produced.")
