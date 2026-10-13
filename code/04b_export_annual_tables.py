"""04b_export_annual_tables.py — annual publication tables from the Stage 04 run record.

Reads provenance/v2/stage4_performance_summary.json (written by code/04_performance_indicators.py) and writes
  results/annual_publications.csv               year, publications (records per publication year)
  results/annual_publications_by_subregion.csv  year, subregion, publications_full_count (data behind Figure 2:
                                                a record counts once in every sub-region of its AU countries)
No recomputation from the corpus; the totals are checked against the run record.

Run from the repository root:  python code/04b_export_annual_tables.py
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "provenance" / "v2" / "stage4_performance_summary.json"
OUT_TOTAL = ROOT / "results" / "annual_publications.csv"
OUT_SUBREGION = ROOT / "results" / "annual_publications_by_subregion.csv"

s = json.loads(SUMMARY.read_text(encoding="utf-8"))
annual = {int(y): int(n) for y, n in s["annual_counts"].items()}
by_sr = {int(y): {sr: int(n) for sr, n in d.items()} for y, d in s["annual_subregion_full_counts"].items()}
if sum(annual.values()) != int(s["total_records"]):
    sys.exit("annual counts do not sum to the number of records")
if sorted(annual) != list(range(int(s["year_min"]), int(s["year_max"]) + 1)) or sorted(by_sr) != sorted(annual):
    sys.exit("year coverage differs from the study window")

with open(OUT_TOTAL, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["year", "publications"])
    w.writerows([y, annual[y]] for y in sorted(annual))
with open(OUT_SUBREGION, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["year", "subregion", "publications_full_count"])
    w.writerows([y, sr, by_sr[y][sr]] for y in sorted(by_sr) for sr in sorted(by_sr[y]))
print(f"{OUT_TOTAL.relative_to(ROOT).as_posix()}: {len(annual)} years, {sum(annual.values()):,} publications")
print(f"{OUT_SUBREGION.relative_to(ROOT).as_posix()}: {sum(len(d) for d in by_sr.values())} rows")
