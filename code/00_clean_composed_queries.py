"""
00_clean_composed_queries.py
Apply scopus_query_clean.clean_for_scopus() to all 17 Aurora composed
queries in sdg_queries/composed/SDG{nn}_full.txt.

Actions:
  1. Archive original (pre-clean) files to
     sdg_queries/composed/_pre_clean_archive/SDG{nn}_full_original.txt
  2. Overwrite each SDG{nn}_full.txt with the cleaned version
  3. Write provenance/stage1_query_cleaning_log.csv
"""

import csv
import sys
from pathlib import Path

# Add code/utils/ directly so we can import as a plain module
sys.path.insert(0, str(Path(__file__).resolve().parent / "utils"))

from scopus_query_clean import clean_for_scopus, count_by_rule

BASE     = Path(__file__).resolve().parent.parent
COMPOSED = BASE / "sdg_queries" / "composed"
ARCHIVE  = COMPOSED / "_pre_clean_archive"
PROV_DIR = BASE / "provenance"

ARCHIVE.mkdir(exist_ok=True)
PROV_DIR.mkdir(exist_ok=True)

CSV_COLS = [
    "sdg_number",
    "original_length",
    "cleaned_length",
    "length_delta",
    "rule_A_count",
    "rule_B_count",
    "rule_C_count",
    "rule_D_count",
    "rule_E_count",
    "rule_F_count",
    "rule_G_count",
    "total_transformations",
]

records = []
all_logs = {}   # sdg_number -> log list

print(f"{'SDG':>4}  {'Orig':>8}  {'Clean':>8}  {'Delta':>6}  "
      f"{'A':>4}  {'B':>4}  {'C':>4}  {'D':>4}  {'E':>4}  {'F':>4}  {'G':>4}  {'Total':>6}")
print("-" * 80)

for n in range(1, 18):
    nn  = f"{n:02d}"
    src = COMPOSED / f"SDG{nn}_full.txt"

    if not src.exists():
        print(f"  SDG{nn}: NOT FOUND — skipping")
        continue

    archive_path = ARCHIVE / f"SDG{nn}_full_original.txt"

    # 1. Archive original (first run) or restore from archive (re-runs).
    # Re-runs always start from the pre-cleaning original so rules are
    # applied idempotently from a known baseline.
    if archive_path.exists():
        original = archive_path.read_text(encoding="utf-8")
        src.write_text(original, encoding="utf-8")
    else:
        original = src.read_text(encoding="utf-8")
        archive_path.write_text(original, encoding="utf-8")

    # 2. Clean
    cleaned, log = clean_for_scopus(original)

    # 3. Overwrite
    src.write_text(cleaned, encoding="utf-8")

    all_logs[nn] = log
    by_rule = count_by_rule(log)

    rec = {
        "sdg_number":         nn,
        "original_length":    len(original),
        "cleaned_length":     len(cleaned),
        "length_delta":       len(cleaned) - len(original),
        "rule_A_count":       by_rule.get("A", 0),
        "rule_B_count":       by_rule.get("B", 0),
        "rule_C_count":       by_rule.get("C", 0),
        "rule_D_count":       by_rule.get("D", 0),
        "rule_E_count":       by_rule.get("E", 0),
        "rule_F_count":       by_rule.get("F", 0),
        "rule_G_count":       by_rule.get("G", 0),
        "total_transformations": sum(by_rule.values()),
    }
    records.append(rec)

    print(f"  {nn}  {rec['original_length']:>8,}  {rec['cleaned_length']:>8,}  "
          f"{rec['length_delta']:>+6,}  "
          f"{rec['rule_A_count']:>4}  {rec['rule_B_count']:>4}  "
          f"{rec['rule_C_count']:>4}  {rec['rule_D_count']:>4}  "
          f"{rec['rule_E_count']:>4}  {rec['rule_F_count']:>4}  "
          f"{rec['rule_G_count']:>4}  "
          f"{rec['total_transformations']:>6}")

print("-" * 80)

# 4. Write CSV
with open(PROV_DIR / "stage1_query_cleaning_log.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=CSV_COLS)
    w.writeheader()
    w.writerows(records)

# 5. Aggregate report
total_A = sum(r["rule_A_count"]          for r in records)
total_B = sum(r["rule_B_count"]          for r in records)
total_C = sum(r["rule_C_count"]          for r in records)
total_D = sum(r["rule_D_count"]          for r in records)
total_E = sum(r["rule_E_count"]          for r in records)
total_F = sum(r["rule_F_count"]          for r in records)
total_G = sum(r["rule_G_count"]          for r in records)
total   = sum(r["total_transformations"] for r in records)

print(f"\nAggregate transformations across all 17 SDGs:")
print(f"  Rule A (unquote single-token wildcard)  : {total_A:>4}")
print(f"  Rule B (strip wildcard from phrase)     : {total_B:>4}")
print(f"  Rule C (curly-brace wildcard)           : {total_C:>4}")
print(f"  Rule D (remove leading wildcard)        : {total_D:>4}")
print(f"  Rule E (multi-wildcard -> W/1 proximity): {total_E:>4}")
print(f"  Rule F (unhyphenate wildcard compound)  : {total_F:>4}")
print(f"  Rule G (W/n+wildcard -> AND)            : {total_G:>4}")
print(f"  Total                                   : {total:>4}")
print()

most_common = max(["A", "B", "C", "D", "E", "F", "G"],
                  key=lambda r: {"A": total_A, "B": total_B, "C": total_C,
                                 "D": total_D, "E": total_E, "F": total_F,
                                 "G": total_G}[r])
print(f"Most common rule: {most_common}")

sdgs_with_transforms = [r["sdg_number"] for r in records if r["total_transformations"] > 0]
sdgs_sorted_by_total = sorted(records, key=lambda r: r["total_transformations"], reverse=True)
print(f"\nSDGs with most transformations (top 5):")
for r in sdgs_sorted_by_total[:5]:
    print(f"  SDG {r['sdg_number']}: {r['total_transformations']} total  "
          f"(A={r['rule_A_count']}, B={r['rule_B_count']}, "
          f"C={r['rule_C_count']}, D={r['rule_D_count']})")

# Confirm SDG 01, 03, 11 were transformed (originally failing)
print()
for target in ["01", "03", "11"]:
    rec = next((r for r in records if r["sdg_number"] == target), None)
    if rec:
        flag = "TRANSFORMED" if rec["total_transformations"] > 0 else "NO CHANGE -- INVESTIGATE"
        print(f"  SDG {target} (originally failing): {rec['total_transformations']} transformations  [{flag}]")

print(f"\nArchive written to : {ARCHIVE}")
print(f"Cleaning log CSV   : {PROV_DIR / 'stage1_query_cleaning_log.csv'}")
