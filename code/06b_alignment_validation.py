"""06b_alignment_validation.py — independent validation of the Stage 06 (RQ5) outputs.

Deliberately does NOT import code/06_alignment_analysis.py or code/utils/rq5_methods.py.
Re-derives everything from the raw inputs with a separate code path:
  * enriched.csv read with the csv module (not pandas);
  * SDG Index read cell-by-cell with openpyxl (not pandas.read_excel);
  * Spearman rho via scipy.stats.spearmanr per country and per bootstrap replicate
    (Stage 06 uses a vectorised rank implementation for the bootstrap);
  * medians via statistics.median.
Then compares with the promoted Stage 06 outputs.

Run from the repository root:  .venv\\Scripts\\python.exe code/06b_alignment_validation.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import openpyxl
from scipy.stats import spearmanr

csv.field_size_limit(2**31 - 1)
ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ap = argparse.ArgumentParser()
ap.add_argument("--input", type=Path, default=ROOT / "data/processed/enriched.csv")
ap.add_argument("--sdg-index", type=Path, default=ROOT / "data/external/sdg_index/sdg_index_2025.xlsx")
ap.add_argument("--au54", type=Path, default=ROOT / "country_lists/au54_countries.csv")
ap.add_argument("--results-dir", type=Path, default=ROOT / "results")
ap.add_argument("--figures-dir", type=Path, default=ROOT / "figures")
ap.add_argument("--prov-dir", type=Path, default=ROOT / "provenance/v2")
ap.add_argument("--log", type=Path, default=ROOT / "provenance/v2/logs/06b_alignment_validation.log")
A = ap.parse_args()
A.log.parent.mkdir(parents=True, exist_ok=True)
LOG = open(A.log, "w", encoding="utf-8")


def say(msg=""):
    print(msg)
    LOG.write(msg + "\n")


CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "pass": bool(ok), "detail": str(detail)})
    say(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def rcsv(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def fnum(s):
    return float("nan") if s in ("", None) else float(s)


# independent literal ISO2 -> ISO3 table (written separately from Stage 06)
ISO2_ISO3 = dict(p.split(":") for p in (
    "DZ:DZA AO:AGO BJ:BEN BW:BWA BF:BFA BI:BDI CV:CPV CM:CMR CF:CAF TD:TCD KM:COM CG:COG CD:COD CI:CIV "
    "DJ:DJI EG:EGY GQ:GNQ ER:ERI SZ:SWZ ET:ETH GA:GAB GM:GMB GH:GHA GN:GIN GW:GNB KE:KEN LS:LSO LR:LBR "
    "LY:LBY MG:MDG MW:MWI ML:MLI MR:MRT MU:MUS MA:MAR MZ:MOZ NA:NAM NE:NER NG:NGA RW:RWA ST:STP SN:SEN "
    "SC:SYC SL:SLE SO:SOM ZA:ZAF SS:SSD SD:SDN TZ:TZA TG:TGO TN:TUN UG:UGA ZM:ZMB ZW:ZWE").split())
au = rcsv(A.au54)
AU3 = sorted(r["iso3"] for r in au)
check("V00 ISO table covers the 54 AU ISO3 codes", sorted(ISO2_ISO3.values()) == AU3 and len(set(ISO2_ISO3)) == 54)

# ── SDG Index via openpyxl ─────────────────────────────────────────────────
wb = openpyxl.load_workbook(A.sdg_index, read_only=True, data_only=True)
rows = wb["SDR2025 Data"].iter_rows(values_only=True)
hdr = list(next(rows))
ci = hdr.index("Country Code ISO3")
cn = hdr.index("Country")
gcol = [hdr.index(f"Goal {g} Score") for g in range(1, 18)]
SCORE, SDRNAME = {}, {}
for r in rows:
    if r[ci] in AU3:
        SCORE[r[ci]] = [None if r[j] in (None, "") else float(r[j]) for j in gcol]
        SDRNAME[r[ci]] = r[cn]
wb.close()
DEF = {c: [None if s is None else 100.0 - s for s in SCORE.get(c, [None] * 17)] for c in AU3}
IMPL = {c: sum(d is not None for d in DEF[c]) for c in AU3}

cw = {r["iso3"]: r for r in rcsv(A.prov_dir / "rq5_country_crosswalk.csv")}
check("V05 ISO3 joins: crosswalk 54 unique rows, ISO2/ISO3 and SDR names agree",
      len(cw) == 54 and all(cw[ISO2_ISO3[i2]]["iso2"] == i2 for i2 in ISO2_ISO3)
      and all(cw[c]["sdg_index_name"] == (SDRNAME.get(c) or "") for c in AU3)
      and all(int(cw[c]["sdr2025_goal_scores_available"]) == IMPL[c] for c in AU3))

# ── research pass with csv module ──────────────────────────────────────────
Wf = defaultdict(float)
Wfull = defaultdict(float)
attributed = 0
with open(A.input, encoding="utf-8", newline="") as f:
    rd = csv.reader(f)
    h = next(rd)
    it, im = h.index("sdg_tags"), h.index("au_countries")   # direct affiliation countries (Stage 02)
    for row in rd:
        cs = {x.strip() for x in row[im].split(";")} & set(ISO2_ISO3)
        ss = {int(x) for x in row[it].split(",") if x.strip().isdigit() and 1 <= int(x) <= 17}
        if not cs or not ss:
            continue
        attributed += 1
        for c in cs:
            for s in ss:
                Wf[(ISO2_ISO3[c], s)] += 1.0 / (len(ss) * len(cs))
                Wfull[(ISO2_ISO3[c], s)] += 1.0 / len(ss)
check("V02 country-fractional conservation (total weight = attributed records)",
      abs(sum(Wf.values()) - attributed) < 1e-6, f"{sum(Wf.values()):.6f} vs {attributed}")
grid = rcsv(A.results_dir / "rq5_country_sdg_research_grid.csv")
gmax = max(abs(fnum(g["weight_fractional_2015_2025"]) - Wf.get((g["iso3"], int(g["sdg_number"])), 0.0)) for g in grid)
gmax_full = max(abs(fnum(g["weight_full_2015_2025"]) - Wfull.get((g["iso3"], int(g["sdg_number"])), 0.0)) for g in grid)
check("V01 country x SDG primary weighted counts reproduced", gmax < 1e-6 and gmax_full < 1e-6, f"max diff {gmax:.2e} / full {gmax_full:.2e}")
TOT = {c: sum(Wf.get((c, s), 0.0) for s in range(1, 18)) for c in AU3}
SH = {c: [Wf.get((c, s), 0.0) / TOT[c] if TOT[c] > 0 else None for s in range(1, 18)] for c in AU3}
check("V03 research shares sum to 1 per country with output",
      all(abs(sum(SH[c]) - 1) < 1e-9 for c in AU3 if TOT[c] > 0))
ZERO = sorted(f"{c}-SDG{s}" for c in AU3 if TOT[c] > 0 for s in range(1, 18) if Wf.get((c, s), 0.0) == 0)
summ = json.load(open(A.prov_dir / "stage6_alignment_summary.json", encoding="utf-8"))
check("V04 zero research cells", ZERO == sorted(summ["zero_cells"]["all_countries"]), f"{len(ZERO)}: {ZERO}")
gd = max((abs(fnum(g["implementation_deficit"]) - DEF[g["iso3"]][int(g["sdg_number"]) - 1])
          for g in grid if DEF[g["iso3"]][int(g["sdg_number"]) - 1] is not None), default=0)
gmiss = all((g["implementation_deficit"] == "") == (DEF[g["iso3"]][int(g["sdg_number"]) - 1] is None) for g in grid)
dvals = [d for c in AU3 for d in DEF[c] if d is not None]
check("V06 implementation deficits = 100 - score; missing kept missing; range 0-100",
      gd < 1e-9 and gmiss and min(dvals) >= 0 and max(dvals) <= 100, f"range {min(dvals):.3f}-{max(dvals):.3f}")

# ── eligibility ────────────────────────────────────────────────────────────
RCOV = {c: sum(Wf.get((c, s), 0.0) > 0 for s in range(1, 18)) for c in AU3}
ELIG = sorted(c for c in AU3 if RCOV[c] >= 10 and IMPL[c] >= 14)
el = {r["iso3"]: r for r in rcsv(A.results_dir / "rq5_country_eligibility.csv")}
check("V07 country eligibility re-derived", ELIG == sorted(c for c in AU3 if el[c]["eligible"] == "True")
      and all(int(el[c]["research_goals_positive"]) == RCOV[c] and int(el[c]["implementation_goals_available"]) == IMPL[c] for c in AU3),
      f"n={len(ELIG)}")
check("V08 DR Congo status", ("COD" in ELIG) == (el["COD"]["eligible"] == "True") and IMPL["COD"] == 17,
      f"COD eligible={'COD' in ELIG}, 2025 goal scores={IMPL['COD']}, research goals={RCOV['COD']}")

# ── Spearman per country (scipy directly) ──────────────────────────────────
corr = {r["iso3"]: r for r in rcsv(A.results_dir / "rq5_country_correlations.csv")}
RHO, PAIRS = {}, {}
for c in ELIG:
    pr = [(SH[c][s], DEF[c][s]) for s in range(17) if DEF[c][s] is not None]
    PAIRS[c] = pr
    RHO[c] = spearmanr([p[0] for p in pr], [p[1] for p in pr]).statistic
rd_max = max(abs(RHO[c] - fnum(corr[c]["rho"])) for c in ELIG)
check("V09 country-level Spearman rho", set(corr) == set(ELIG) and rd_max < 1e-9, f"max diff {rd_max:.2e}")
med = statistics.median(RHO.values())
check("V10 continental median rho", abs(med - summ["primary"]["median_rho"]) < 1e-12, f"{med:.6f}")
neg = int(sum(bool(r < 0) for r in RHO.values()))
check("V11 negative-rho count", neg == summ["primary"]["n_negative"], f"{neg}")

# bootstrap CIs re-derived with an independent loop (scipy per replicate) on the documented stream
bmax, inval = 0.0, 0
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for c in ELIG:
        x = np.array([p[0] for p in PAIRS[c]])
        y = np.array([p[1] for p in PAIRS[c]])
        rng = np.random.default_rng(np.random.SeedSequence([42, int.from_bytes(c.encode("ascii"), "big")]))
        idx = rng.integers(0, len(x), size=(1000, len(x)))
        bs = []
        for k in range(1000):
            r = spearmanr(x[idx[k]], y[idx[k]]).statistic
            if math.isnan(r):
                inval += 1
            else:
                bs.append(r)
        lo, hi = np.percentile(bs, [2.5, 97.5])
        bmax = max(bmax, abs(lo - fnum(corr[c]["ci_low"])), abs(hi - fnum(corr[c]["ci_high"])))
ci_neg = int(sum(fnum(corr[c]["ci_high"]) < 0 for c in ELIG))
check("V09b bootstrap CIs (independent per-replicate scipy loop)", bmax < 1e-9 and
      inval == sum(int(corr[c]["bootstrap_invalid_reps"]) for c in ELIG), f"max CI diff {bmax:.2e}; invalid {inval}; CI<0 {ci_neg}")

# ── quadrants ──────────────────────────────────────────────────────────────
qa = rcsv(A.results_dir / "rq5_quadrant_assignments.csv")
TH, CNT = {}, defaultdict(lambda: defaultdict(int))
for s in range(17):
    pts = [(c, SH[c][s], DEF[c][s]) for c in ELIG if DEF[c][s] is not None]
    mr = statistics.median(p[1] for p in pts)
    md = statistics.median(p[2] for p in pts)
    TH[s + 1] = (mr, md)
    for c, r, d in pts:
        q = ("H" if r >= mr else "L") + ("H" if d >= md else "L")
        CNT[s + 1][q] += 1
qsum = {r["sdg_number"]: r for r in rcsv(A.results_dir / "rq5_sdg_quadrant_summary.csv")}
check("V12 quadrant thresholds (SDG medians on eligible population)",
      all(abs(TH[s][0] - fnum(qsum[str(s)]["median_research_share"])) < 1e-12 and abs(TH[s][1] - fnum(qsum[str(s)]["median_deficit"])) < 1e-12
          for s in TH))
check("V13 quadrant counts per SDG", all(CNT[s][q] == int(qsum[str(s)][f"{q}_median"]) for s in TH for q in ("HH", "HL", "LH", "LL"))
      and len(qa) == sum(sum(v.values()) for v in CNT.values()),
      f"totals {dict((q, sum(CNT[s][q] for s in CNT)) for q in ('HH', 'HL', 'LH', 'LL'))}")
check("V14 SDG 9 quadrant counts", dict(CNT[9]) == {k: v for k, v in summ["sdg9"]["quadrant_counts"]["median"].items() if v},
      f"{dict(CNT[9])}")
c7 = {q: int(qsum["7"][f"{q}_median"]) for q in ("HH", "HL", "LH", "LL")}
leg7 = sum(1 for c in ELIG if DEF[c][6] is not None and SH[c][6] < 0.08 and DEF[c][6] >= 50)
fix7 = sum(1 for c in ELIG if DEF[c][6] is not None and SH[c][6] < 1 / 17 and DEF[c][6] >= 50)
check("V15 SDG 7 counts (median, fixed 1/17+50, legacy 0.08+50)",
      dict(CNT[7]) == {k: v for k, v in c7.items() if v} and leg7 == int(qsum["7"]["LH_legacy_0.08_50"])
      and fix7 == int(qsum["7"]["LH_fixed_1_17_50"]), f"median {dict(CNT[7])}; LH fixed {fix7}; LH legacy {leg7}")

# Figure 12 data consistent with quadrant assignments
f12 = rcsv(A.figures_dir / "F12_alignment_quadrant_data.csv")
check("V16 Figure 12 point data = primary quadrant pairs", len(f12) == len(qa) and
      sorted((r["iso3"], r["sdg_number"], r["quadrant_median"]) for r in f12) ==
      sorted((r["iso3"], r["sdg_number"], r["quadrant_median"]) for r in qa))

npass = sum(c["pass"] for c in CHECKS)
say(f"\nSUMMARY: {npass}/{len(CHECKS)} PASS")
out = {"validator": "code/06b_alignment_validation.py", "independent_of": ["code/06_alignment_analysis.py", "code/utils/rq5_methods.py"],
       "inputs_sha256": {str(p.relative_to(ROOT)) if ROOT in p.resolve().parents else str(p): sha(p) for p in (A.input, A.sdg_index, A.au54)},
       "checks": CHECKS, "n_pass": npass, "n_checks": len(CHECKS),
       "independent_values": {"eligible": len(ELIG), "median_rho": med, "negative": neg, "ci_below_zero": ci_neg,
                              "zero_cells": ZERO, "sdg9_median_counts": dict(CNT[9]), "sdg7_median_counts": dict(CNT[7]),
                              "sdg7_LH_fixed": fix7, "sdg7_LH_legacy": leg7}}
with open(A.prov_dir / "stage6_independent_validation.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
LOG.close()
sys.exit(0 if npass == len(CHECKS) else 1)
