"""01c_validate_corpus.py — validation of the consolidated corpus (Stage 01a) and the analytical corpus (Stage 01b).

Read-only. Checks, for data/interim/consolidated.csv and data/interim/scoped_2015_2025.csv:
  * row counts and record-level field digests equal those of the published analysis
    (provenance/corpus_validation.json);
  * EIDs present and unique;
  * the analytical corpus contains only publication years 2015-2025 and the document types Article / Review;
  * the number of records per SDG in the analytical corpus.
Exit status 0 only if every check passes.

Run from the repository root:  python code/01c_validate_corpus.py
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--consolidated", type=Path, default=ROOT / "data/interim/consolidated.csv")
ap.add_argument("--scoped", type=Path, default=ROOT / "data/interim/scoped_2015_2025.csv")
ap.add_argument("--expected", type=Path, default=ROOT / "provenance/corpus_validation.json")
A = ap.parse_args()
EXP = json.loads(A.expected.read_text(encoding="utf-8"))
FS, RS = "\x1f", "\x1e"                                   # field / record separators of the digest
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail != "" else ""))


def scan(path, tally=False):
    h, n, eids, years, dts, sdg = hashlib.sha256(), 0, set(), Counter(), Counter(), Counter()
    dup = blank = 0
    header = pd.read_csv(path, nrows=0, dtype=str, encoding="utf-8-sig").columns.tolist()
    for ch in pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig", chunksize=20000):
        for row in ch[header].itertuples(index=False, name=None):
            h.update((FS.join(row) + RS).encode("utf-8"))
        e = ch["EID"].str.strip()
        blank += int((e == "").sum())
        before = len(eids)
        eids.update(e)
        dup += len(e) - (len(eids) - before)
        n += len(ch)
        if tally:
            years.update(ch["Year"])
            dts.update(ch["Document Type"])
            for t in ch["sdg_tags"]:
                sdg.update(int(x) for x in t.split(",") if x.strip().isdigit())
    return {"rows": n, "digest": h.hexdigest(), "duplicate_eids": dup, "blank_eids": blank,
            "years": years, "doctypes": dts, "sdg": sdg}


for label, path, tally in (("consolidated", A.consolidated, False), ("analytical", A.scoped, True)):
    if not path.exists():
        check(f"{label} corpus present ({path.name})", False)
        continue
    r = scan(path, tally)
    e = EXP[label]
    check(f"{label} corpus: {e['rows']:,} records", r["rows"] == e["rows"], r["rows"])
    check(f"{label} corpus: field digest = published analysis", r["digest"] == e["field_digest"], r["digest"][:16])
    check(f"{label} corpus: EIDs present and unique", r["duplicate_eids"] == 0 and r["blank_eids"] == 0,
          f"duplicates {r['duplicate_eids']}, blank {r['blank_eids']}")
    if tally:
        yrs = sorted(int(y) for y in r["years"])
        check("analytical corpus: publication years 2015-2025", yrs[0] >= 2015 and yrs[-1] <= 2025, f"{yrs[0]}-{yrs[-1]}")
        check("analytical corpus: Article / Review only", set(r["doctypes"]) <= {"Article", "Review"}, dict(r["doctypes"]))
        got = {str(k): v for k, v in sorted(r["sdg"].items())}
        check("analytical corpus: records per SDG = published analysis", got == e["records_per_sdg"], got.get("2"))
n_fail = sum(not ok for _, ok in CHECKS)
print(f"{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
sys.exit(1 if n_fail else 0)
