"""
00_year_split_queries.py
Produce year-range split variants of composed SDG queries whose Scopus
result counts exceed the 20,000-record CSV export cap.

Splits chosen based on actual Scopus result counts retrieved 2026-05-07.
Adjust year_ranges below and re-run if counts differ on a later retrieval.

SDGs requiring splits:
  SDG 1  : >24,000 results  → 2-way split  [2015-2020, 2021-2025]
  SDG 6  : ~22,000 results  → 2-way split  [2015-2020, 2021-2025]
  SDG 13 : ~50,000 results  → 3-way split  [2015-2018, 2019-2022, 2023-2025]
  SDG 15 : ~23,000 results  → 2-way split  [2015-2020, 2021-2025]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "utils"))

from year_split_query import split_query_by_years

SPLITS = {
    1:  [(2015, 2020), (2021, 2025)],
    6:  [(2015, 2020), (2021, 2025)],
    13: [(2015, 2018), (2019, 2022), (2023, 2025)],
    15: [(2015, 2020), (2021, 2025)],
}

expected_files = 9   # 2 + 2 + 3 + 2
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

# Quick sanity check — print first 200 chars of SDG13_full_2019-2022.txt
BASE     = Path(__file__).resolve().parent.parent
COMPOSED = BASE / "sdg_queries" / "composed"
check    = COMPOSED / "SDG13_full_2019-2022.txt"
if check.exists():
    sample = check.read_text(encoding="utf-8")
    print(f"\nFirst 200 chars of SDG13_full_2019-2022.txt:")
    print(sample[:200])
    print("...")
