"""09_validate_release.py — validation of the released derived outputs.

Read-only; needs no restricted data. Checks:
  * headline results in the released result tables (corpus, alignment, collaboration, SDG distribution,
    sensitivity analyses) against the values reported for the analysis;
  * the VOSviewer networks of Figures 8-10: the saved VOSviewer exports (results/vosviewer/*.json) contain exactly
    the items, item weights, links and link weights of the network input files, and the Figure 10 display map
    differs from the scientific map only in the label field;
  * every file listed in provenance/output_checksums.sha256 is present with the recorded SHA-256.
Exit status 0 only if every check passes.

Run from the repository root:  python code/09_validate_release.py
"""
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail != "" else ""))


def rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


num = lambda s: float(str(s).replace(",", "").replace("%", ""))

# ── corpus ────────────────────────────────────────────────────────────────────
t1 = {r["metric"]: r["value"] for r in rows(R / "table_T1_corpus_overview.csv")}
check("publications 345,025", num(t1["Total publications"]) == 345025)
check("source titles 18,269", num(t1["Unique sources (journals/venues)"]) == 18269)
check("citations 7,132,248", num(t1["Total citations"]) == 7132248)
check("citations per paper 20.67", num(t1["Average citations per paper (CPP)"]) == 20.67)
check("CAGR 2015-2024 16.2%", num(t1["CAGR 2015–2024 (total output)"]) == 16.2)
annual = {int(r["year"]): int(r["publications"]) for r in rows(R / "annual_publications.csv")}
check("2015 output 12,697; 2025 output 60,917", annual[2015] == 12697 and annual[2025] == 60917)
check("annual output sums to the corpus", sum(annual.values()) == 345025)
# ── SDG distribution ──────────────────────────────────────────────────────────
t2 = rows(R / "table_T2_publications_by_SDG.csv")
share = {int(r["sdg_number"]): float(r["pct_of_total_fractional_corpus"]) for r in t2}
rank = {int(r["sdg_number"]): i + 1 for i, r in enumerate(t2)}
for g, v in ((3, 15.82), (12, 9.88), (15, 9.32), (13, 9.26), (2, 4.27), (7, 3.79)):
    check(f"SDG {g} share {v}%", share[g] == v)
check("SDG 2 rank 10", rank[2] == 10)
# ── alignment ─────────────────────────────────────────────────────────────────
cc = rows(R / "rq5_country_correlations.csv")
rho = [float(r["rho"]) for r in cc]
below = sorted(r["country_name"] for r in cc if float(r["ci_high"]) < 0)
check("50 eligible countries", len(cc) == 50)
check("median Spearman rho -0.251", round(statistics.median(rho), 3) == -0.251)
check("44 negative / 6 positive", sum(x < 0 for x in rho) == 44 and sum(x > 0 for x in rho) == 6)
check("bootstrap CIs entirely below zero: Botswana and Comoros only", below == ["Botswana", "Comoros"], below)
check("no bootstrap CI entirely above zero", not any(float(r["ci_low"]) > 0 for r in cc))
sens = {r["analysis"]: r for r in rows(R / "rq5_supplementary_sensitivity_summary.csv")}
ex = sens["window/endpoint: exclude2025_2015_2024_research__sdr2025"]
check("excluding 2025: median rho -0.231, 44 negative", round(float(ex["median_rho"]), 3) == -0.231 and int(ex["n_negative"]) == 44)
q = {r["sdg_number"]: r for r in rows(R / "rq5_sdg_quadrant_summary.csv")}
check("median split: SDG 9 LH 15, SDG 7 LH 12", int(q["9"]["LH_median"]) == 15 and int(q["7"]["LH_median"]) == 12)
check("equal-allocation benchmark: SDG 9 LH 42, SDG 7 LH 38",
      int(q["9"]["LH_fixed_1_17_50"]) == 42 and int(q["7"]["LH_fixed_1_17_50"]) == 38)
# ── collaboration ─────────────────────────────────────────────────────────────
cs = {r["metric"]: r for r in rows(R / "collaboration_summary.csv")}
pct = lambda m: round(float(cs[m]["pct_of_denominator"]), 1)
check("international collaboration 58.0%", pct("international") == 58.0)
check("at least two AU countries 12.3%", pct("multi_au") == 12.3)
check("AU and non-AU countries 53.9%", pct("au_and_non_au") == 53.9)
check("intra-African link share 14.41% (full) / 12.73% (fractional)",
      round(100 * float(cs["intra_african_link_share_full"]["value"]), 2) == 14.41
      and round(100 * float(cs["intra_african_link_share_fractional"]["value"]), 2) == 12.73)
# ── VOSviewer networks (Figures 8-10) ─────────────────────────────────────────
V = R / "vosviewer"


def vmap(p):
    lines = [ln for ln in p.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]


def vnet(p):
    return {tuple(sorted(ln.split("\t")[:2])): float(ln.split("\t")[2])
            for ln in p.read_text(encoding="utf-8-sig").splitlines() if ln.strip()}


NETS = {"Figure 8": ("F8_keyword_min1000", "F8_keyword_cooccurrence_network.json", None, "Occurrences", (67, 1648, 37318)),
        "Figure 9": ("F9_country_africa_involved_top50", "F9_country_coauthorship_network.json", None, "Documents", (50, 994, 523013)),
        "Figure 10": ("F10_institution_ror_top50", "F10_african_institution_coauthorship_network.json",
                      "F10_institution_ror_top50_map_shortlabels.txt", "Documents", (50, 1211, 88190))}
for fig, (stem, js, disp, wkey, exp) in NETS.items():
    m, n = vmap(V / f"{stem}_map.txt"), vnet(V / f"{stem}_network.txt")
    net = json.loads((V / js).read_bytes().decode("utf-8-sig"))["network"]
    items, links = net["items"], net["links"]
    labels = {r["id"]: r["label"] for r in (vmap(V / disp) if disp else m)}
    weights = {r["id"]: float(r[f"weight<{wkey}>"]) for r in m}
    jl = {tuple(sorted((str(l["source_id"]), str(l["target_id"])))): float(l["strength"]) for l in links}
    got = (len(m), len(n), round(sum(n.values())))
    check(f"{fig}: network input {exp[0]} items / {exp[1]:,} links / total link strength {exp[2]:,}", got == exp, got)
    check(f"{fig}: VOSviewer export = network input (items, weights, labels, links, link weights)",
          {str(i["id"]) for i in items} == set(weights) and all(float(i["weights"][wkey]) == weights[str(i["id"])] for i in items)
          and all(i["label"] == labels[str(i["id"])] for i in items) and jl == n,
          f"{len({i['cluster'] for i in items})} clusters")
    if disp:
        d = vmap(V / disp)
        check(f"{fig}: display map differs from the scientific map only in the label field",
              [{k: v for k, v in r.items() if k != "label"} for r in d] == [{k: v for k, v in r.items() if k != "label"} for r in m])
# ── checksums ─────────────────────────────────────────────────────────────────
bad, listed = [], 0
for line in (ROOT / "provenance" / "output_checksums.sha256").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    digest, rel = line.split("  ", 1)
    listed += 1
    p = ROOT / rel
    if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
        bad.append(rel)
check(f"output checksums: {listed} files present with the recorded SHA-256", not bad, bad[:5])
n_fail = sum(not ok for _, ok in CHECKS)
print(f"{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
sys.exit(1 if n_fail else 0)
