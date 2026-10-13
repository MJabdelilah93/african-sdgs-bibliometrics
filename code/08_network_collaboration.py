"""08_network_collaboration.py — collaboration metrics and VOSviewer-ready network data.

Manuscript Figures 8 (keyword co-occurrence), 9 (country co-authorship) and 10 (institution
co-authorship) are drawn MANUALLY in VOSviewer. This script only computes and validates the
underlying data and writes VOSviewer map/network files; it draws nothing.

Inputs (frozen, hash-checked): data/processed/enriched.csv (direct country attribution),
data/external/ror/ror_africa_v2.json, country_lists/*, code/05a_thematic_map_F6.R (geographic
filter terms, as validated in Stage 05).

Country sets: the Stage 02 normaliser (utils/country_normalisation.py) applied to the raw
`Affiliations` text — the same implementation that produced `affiliation_countries` /
`au_countries`; ROR is never used for countries.

Run from the repository root:  .venv\\Scripts\\python.exe code/08_network_collaboration.py
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import platform
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ARTICLE = HERE.parent
sys.path.insert(0, str(HERE))
from utils.checksums import sha256_file  # noqa: E402
from utils.config import cfg  # noqa: E402
from utils.country_normalisation import CountryNormaliser  # noqa: E402
from utils import collab_methods as C  # noqa: E402

csv.field_size_limit(2**31 - 1)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SCRIPT_VERSION = "1.0.0"
V2 = ARTICLE / "provenance" / "v2"
ap = argparse.ArgumentParser()
ap.add_argument("--input", type=Path, default=ARTICLE / "data/processed/enriched.csv")
ap.add_argument("--ror", type=Path, default=ARTICLE / "data/external/ror/ror_africa_v2.json")
ap.add_argument("--results-dir", type=Path, default=ARTICLE / "results")
ap.add_argument("--work-dir", type=Path, default=ARTICLE / "data/processed/network")
ap.add_argument("--prov-dir", type=Path, default=V2)
ap.add_argument("--log", type=Path, default=V2 / "logs/08_network_collaboration.log")
ap.add_argument("--smoke-test", action="store_true", help="synthetic input; outputs must be outside the project")
ap.add_argument("--allow-global-python", action="store_true")
A = ap.parse_args()
if A.smoke_test:
    for d in (A.results_dir, A.work_dir, A.prov_dir, A.log.parent):
        if ARTICLE in Path(d).resolve().parents:
            sys.exit("--smoke-test outputs must be outside the project")

A.log.parent.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("08_network")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
for _h in (logging.FileHandler(A.log, mode="w", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
    _h.setFormatter(_fmt)
    log.addHandler(_h)


def git(*a):
    try:
        return subprocess.run(["git", *a], cwd=ARTICLE, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def rel(p):
    try:
        return Path(p).resolve().relative_to(ARTICLE).as_posix()
    except ValueError:
        return str(p)


RUN_START = datetime.now()
IN_VENV = sys.prefix != sys.base_prefix
log.info("=" * 70)
log.info(f"STAGE 08 network/collaboration data — v{SCRIPT_VERSION}")
log.info(f"Git HEAD : {git('rev-parse', 'HEAD')} (tracked changes: {bool(git('status', '--porcelain', '--untracked-files=no'))})")
log.info(f"Python {platform.python_version()} (venv {IN_VENV}); pandas {pd.__version__}")
if not IN_VENV and not A.allow_global_python:
    sys.exit("use the project .venv")

# ── input guard ─────────────────────────────────────────────────────────────
man4 = {r["relative_path"]: r["sha256"] for r in csv.DictReader(open(V2 / "stage4_performance_manifest.csv", encoding="utf-8"))}
man2 = {r["relative_path"]: r["sha256"] for r in csv.DictReader(open(V2 / "stage2_affiliation_manifest.csv", encoding="utf-8"))}
GEO_SRC = ARTICLE / "code/05a_thematic_map_F6.R"
INPUTS = {rel(A.input): sha256_file(A.input), rel(A.ror): sha256_file(A.ror),
          "country_lists/country_names_iso2.csv": sha256_file(ARTICLE / "country_lists/country_names_iso2.csv"),
          "country_lists/au54_countries.csv": sha256_file(ARTICLE / "country_lists/au54_countries.csv"),
          rel(GEO_SRC): sha256_file(GEO_SRC)}
EXPECT = {rel(A.input): man4.get("data/processed/enriched.csv"), rel(A.ror): man2.get("data/external/ror/ror_africa_v2.json"),
          "country_lists/country_names_iso2.csv": man2.get("country_lists/country_names_iso2.csv"),
          "country_lists/au54_countries.csv": man4.get("country_lists/au54_countries.csv")}
for k, v in INPUTS.items():
    log.info(f"Input    : {k}  {v}")
    if A.smoke_test and k == rel(A.input):
        continue
    if k in EXPECT and EXPECT[k] and v != EXPECT[k]:
        sys.exit(f"input hash mismatch for {k}")

NORM = CountryNormaliser(ARTICLE / "country_lists/country_names_iso2.csv", ARTICLE / "country_lists/au54_countries.csv")
AU = NORM.au
NAME = NORM.name
_geo = re.search(r"GEO_TERMS\s*<-\s*tolower\(c\((.*?)\)\)", GEO_SRC.read_text(encoding="utf-8"), re.S).group(1)
GEO = {t.lower() for t in re.findall(r'"([^"]*)"', _geo)}
if len(GEO) != 67:
    sys.exit(f"expected the 67 validated Stage 05 geographic terms, found {len(GEO)}")
ror_recs = json.load(open(A.ror, encoding="utf-8"))
ROR_NAME, ROR_CC = {}, {}
for r in ror_recs:
    names = r.get("names", [])
    ROR_NAME[r["id"]] = next((n["value"] for n in names if "ror_display" in n.get("types", [])), names[0]["value"] if names else r["id"])
    ROR_CC[r["id"]] = sorted({(l.get("geonames_details") or {}).get("country_code", "") for l in r.get("locations", [])} & AU)
SETTINGS = {
    "country_source": "utils/country_normalisation.py on raw Affiliations (identical implementation to Stage 02)",
    "africa_definition": "African Union member states (AU-54, country_lists/au54_countries.csv); other African territories count as non-AU",
    "international_collaboration": ">= 2 distinct countries on the record",
    "full_pair_counting": "each unordered pair of distinct countries on a record = 1",
    "fractional_pair_counting": "each of the p pairs on a record = 1/p (record total 1)",
    "intra_african_link_share": "AA / (AA + AN)",
    "keyword_source": "keywords_harmonised (Stage 03; identical to bibliometrix DE)",
    "keyword_geo_filter": "67 terms parsed from code/05a_thematic_map_F6.R (Stage 05 validated list), case-insensitive exact term",
    "keyword_edges_stored_for": "keywords with >= 2 document occurrences (pairs involving single-occurrence keywords cannot appear at any threshold >= 2; their count is reported)",
    "institution_source": "ror_ids (Stage 02; African ROR subset; country-consistent, ambiguity-safe; fuzzy matches gated by institutional core)",
    "display_cap_country": 50, "display_cap_institution": 50,
    "keyword_candidate_thresholds": [250, 500, 750, 1000, 1250, 1500, 2000, 3000],
}

# ── single pass ─────────────────────────────────────────────────────────────
log.info("Pass 1 — countries, institutions, keyword occurrences")
W = A.work_dir
W.mkdir(parents=True, exist_ok=True)
rc_path = W / "record_countries.csv"
pairs_full, pairs_frac = Counter(), defaultdict(float)
ctry_pubs, ctry_collab = Counter(), Counter()
paper = Counter()
inst_pubs, inst_collab = Counter(), Counter()
inst_pairs_full, inst_pairs_frac = Counter(), defaultdict(float)
kw_occ = Counter()
agree = Counter()
stat = Counter()
records = []          # (eid, sorted kw list) for pass 2
with open(A.input, encoding="utf-8", newline="") as f, open(rc_path, "w", encoding="utf-8", newline="") as g:
    rd = csv.reader(f)
    h = next(rd)
    ix = {c: h.index(c) for c in ("EID", "Year", "Affiliations", "affiliation_countries", "au_countries", "ror_ids", "keywords_harmonised")}
    w = csv.writer(g, lineterminator="\n")
    w.writerow(["EID", "countries", "au_countries", "non_au_countries", "n_countries", "n_au", "n_non_au",
                "n_segments", "n_unresolved_segments", "n_ambiguous_segments"])
    for row in rd:
        stat["records"] += 1
        eid = row[ix["EID"]]
        rc = NORM.record(row[ix["Affiliations"]])
        cs, au = rc.countries, rc.au
        non = cs - au
        stat["segments"] += rc.n_segments
        stat["segments_unresolved"] += rc.n_unresolved
        stat["segments_ambiguous"] += rc.n_country_ambiguous
        stat["segments_us_state_terminated"] += rc.n_us_state_terminated
        agree["au_equal_stage02"] += au == set(filter(None, row[ix["au_countries"]].split(";")))
        agree["all_equal_stage02"] += cs == set(filter(None, row[ix["affiliation_countries"]].split(";")))
        w.writerow([eid, ";".join(sorted(cs)), ";".join(sorted(au)), ";".join(sorted(non)), len(cs), len(au), len(non),
                    rc.n_segments, rc.n_unresolved, rc.n_country_ambiguous])
        stat["records_with_country"] += bool(cs)
        stat["records_with_au"] += bool(au)
        prof = C.paper_profile(cs, AU)
        if au:
            for k in ("domestic", "international", "multi_au", "au_and_non_au", "multi_au_and_non_au",
                      "intra_african_only", "africa_non_africa_only"):
                paper[k] += prof[k]
            paper["africa_involved"] += 1
            paper["single_country"] += len(cs) == 1
        for c in cs:
            ctry_pubs[c] += 1
            if len(cs) >= 2:
                ctry_collab[c] += 1
        for a, b, wt in C.pair_weights(cs, "full"):
            pairs_full[(a, b)] += wt
        for a, b, wt in C.pair_weights(cs, "fractional"):
            pairs_frac[(a, b)] += wt
        stat["records_with_pairs"] += len(cs) >= 2
        rors = C.unique_items(row[ix["ror_ids"]])
        stat["records_with_ror"] += bool(rors)
        for r in rors:
            inst_pubs[r] += 1
            if len(rors) >= 2:
                inst_collab[r] += 1
        ip = C.cooccurrence_pairs(rors)
        for a, b in ip:
            inst_pairs_full[(a, b)] += 1
            inst_pairs_frac[(a, b)] += 1 / len(ip)
        kws = C.unique_items(row[ix["keywords_harmonised"]], drop=GEO)
        stat["records_with_keywords"] += bool(kws)
        kw_occ.update(kws)
        records.append(kws)
log.info(f"  {dict(stat)}")
log.info(f"  agreement with Stage 02: {dict(agree)}")

# ── collaboration metrics ───────────────────────────────────────────────────
def typed_totals(pairs):
    t = Counter()
    for (a, b), wt in pairs.items():
        t[C.pair_type(a, b, AU)] += wt
    return t


TF, TR = typed_totals(pairs_full), typed_totals(pairs_frac)
FULL_SHARE = TF["AA"] / (TF["AA"] + TF["AN"])
FRAC_SHARE = TR["AA"] / (TR["AA"] + TR["AN"])
CONSERV = {"fractional_total": sum(pairs_frac.values()), "records_with_pairs": stat["records_with_pairs"]}
log.info(f"  full pairs {dict(TF)} share {FULL_SHARE:.4f}; fractional {dict(TR)} share {FRAC_SHARE:.4f}; {CONSERV}")
n_inv = paper["africa_involved"]
n_int = paper["international"]
paper_rows = [
    ("africa_involved_records", n_inv, "records with >=1 AU country", stat["records"]),
    ("single_country", paper["single_country"], "records with exactly one country (an AU country)", n_inv),
    ("international", n_int, "records with >=2 distinct countries", n_inv),
    ("multi_au", paper["multi_au"], ">=2 AU countries", n_inv),
    ("au_and_non_au", paper["au_and_non_au"], ">=1 AU and >=1 non-AU country", n_inv),
    ("multi_au_and_non_au", paper["multi_au_and_non_au"], ">=2 AU and >=1 non-AU country", n_inv),
    ("intra_african_only", paper["intra_african_only"], "international: only AU countries", n_int),
    ("africa_non_africa_only", paper["africa_non_africa_only"], "international: exactly one AU country + >=1 non-AU", n_int),
    ("mixed_intra_and_external", paper["multi_au_and_non_au"], "international: >=2 AU + >=1 non-AU", n_int),
]
summary_rows = [{"metric": k, "value": v, "definition": d, "denominator": den,
                 "pct_of_denominator": round(100 * v / den, 3) if den else None} for k, v, d, den in paper_rows]
for typ in ("AA", "AN", "NN"):
    summary_rows.append({"metric": f"pair_weight_full_{typ}", "value": TF[typ], "definition": "full pair counting", "denominator": "", "pct_of_denominator": ""})
    summary_rows.append({"metric": f"pair_weight_fractional_{typ}", "value": round(TR[typ], 6), "definition": "fractional pair counting", "denominator": "", "pct_of_denominator": ""})
summary_rows += [{"metric": "intra_african_link_share_full", "value": round(FULL_SHARE, 6), "definition": "AA/(AA+AN), full pairs", "denominator": TF["AA"] + TF["AN"], "pct_of_denominator": round(100 * FULL_SHARE, 3)},
                 {"metric": "intra_african_link_share_fractional", "value": round(FRAC_SHARE, 6), "definition": "AA/(AA+AN), fractional pairs", "denominator": round(TR["AA"] + TR["AN"], 6), "pct_of_denominator": round(100 * FRAC_SHARE, 3)}]

# ── country nodes / edges ───────────────────────────────────────────────────
nodes = []
strength = defaultdict(lambda: Counter())
partners = defaultdict(set)
for (a, b), wt in pairs_full.items():
    t = C.pair_type(a, b, AU)
    for x, y in ((a, b), (b, a)):
        strength[x]["total"] += wt
        strength[x]["AA" if t == "AA" else "AN" if t == "AN" else "NN"] += wt
        partners[x].add(y)
for c in sorted(ctry_pubs):
    s = strength[c]
    inv = s["AA"] + s["AN"]
    nodes.append({"iso2": c, "country": NAME.get(c, c), "au_member": c in AU, "publications": ctry_pubs[c],
                  "international_publications": ctry_collab[c], "total_link_strength": s["total"],
                  "intra_african_link_strength": s["AA"] if c in AU else 0,
                  "africa_non_africa_link_strength": s["AN"], "non_africa_link_strength": s["NN"],
                  "africa_involved_link_strength": inv, "distinct_partners": len(partners[c]),
                  "au_partner_share": round(s["AA"] / inv, 6) if c in AU and inv else None,
                  "non_au_partner_share": round(s["AN"] / inv, 6) if c in AU and inv else None})
nodes_df = pd.DataFrame(nodes).sort_values(["africa_involved_link_strength", "iso2"], ascending=[False, True])
edges_df = pd.DataFrame([{"iso2_a": a, "iso2_b": b, "country_a": NAME.get(a, a), "country_b": NAME.get(b, b),
                          "pair_type": C.pair_type(a, b, AU), "weight_full": wt, "weight_fractional": round(pairs_frac[(a, b)], 6)}
                         for (a, b), wt in pairs_full.items()]).sort_values(["weight_full", "iso2_a", "iso2_b"], ascending=[False, True, True])

# ── keyword pass 2: co-occurrence among keywords with >= 2 occurrences ─────
log.info("Pass 2 — keyword co-occurrence")
keep = {k for k, v in kw_occ.items() if v >= 2}
kw_pairs = Counter()
pairs_dropped = 0
for kws in records:
    kk = [k for k in kws if k in keep]
    pairs_dropped += len(kws) * (len(kws) - 1) // 2 - len(kk) * (len(kk) - 1) // 2
    for a, b in C.cooccurrence_pairs(kk):
        kw_pairs[(a, b)] += 1
del records
kw_link = Counter()
for (a, b), wt in kw_pairs.items():
    kw_link[a] += wt
    kw_link[b] += wt
log.info(f"  keywords {len(kw_occ):,}; with >=2 occurrences {len(keep):,}; edges stored {len(kw_pairs):,}; pairs with a single-occurrence keyword {pairs_dropped:,}")
cand = []
for T in SETTINGS["keyword_candidate_thresholds"]:
    sel = {k for k, v in kw_occ.items() if v >= T}
    ne = sum(1 for (a, b) in kw_pairs if a in sel and b in sel)
    cand.append({"min_occurrences": T, "nodes": len(sel), "edges_among_nodes": ne,
                 "smallest_selected_occurrence": min((kw_occ[k] for k in sel), default=None)})
cand_df = pd.DataFrame(cand)
log.info("\n" + cand_df.to_string(index=False))

# ── institution nodes / edges ───────────────────────────────────────────────
ilink = Counter()
ipart = defaultdict(set)
for (a, b), wt in inst_pairs_full.items():
    ilink[a] += wt
    ilink[b] += wt
    ipart[a].add(b)
    ipart[b].add(a)
inst_nodes = pd.DataFrame([{"ror_id": r, "name": ROR_NAME.get(r, ""), "country_iso2": ";".join(ROR_CC.get(r, [])),
                            "publications": inst_pubs[r], "multi_institution_publications": inst_collab[r],
                            "total_link_strength": ilink[r], "distinct_partners": len(ipart[r])} for r in inst_pubs]) \
    .sort_values(["total_link_strength", "ror_id"], ascending=[False, True])
inst_edges = pd.DataFrame([{"ror_id_a": a, "ror_id_b": b, "name_a": ROR_NAME.get(a, ""), "name_b": ROR_NAME.get(b, ""),
                            "country_a": ";".join(ROR_CC.get(a, [])), "country_b": ";".join(ROR_CC.get(b, [])),
                            "weight_full": wt, "weight_fractional": round(inst_pairs_frac[(a, b)], 6)}
                           for (a, b), wt in inst_pairs_full.items()]).sort_values(["weight_full", "ror_id_a", "ror_id_b"], ascending=[False, True, True])
unknown_ror = sorted(set(inst_pubs) - set(ROR_NAME))

# ── outputs ─────────────────────────────────────────────────────────────────
R = A.results_dir
VD = R / "vosviewer"
VD.mkdir(parents=True, exist_ok=True)
OUT = []


def wcsv(df, p):
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, lineterminator="\n")
    OUT.append(p)


def vos(prefix, node_rows, edge_rows, cols):
    """VOSviewer map (id, label, weight<...>) and network (id1, id2, weight) files, tab-separated."""
    mp, nw = VD / f"{prefix}_map.txt", VD / f"{prefix}_network.txt"
    with open(mp, "w", encoding="utf-8", newline="") as f:
        f.write("id\tlabel\t" + "\t".join(f"weight<{c}>" for c in cols) + "\n")
        for i, lab, wts in node_rows:
            f.write(f"{i}\t{lab}\t" + "\t".join(str(wts[c]) for c in cols) + "\n")
    with open(nw, "w", encoding="utf-8", newline="") as f:
        for a, b, wt in edge_rows:
            f.write(f"{a}\t{b}\t{wt}\n")
    OUT.extend([mp, nw])


wcsv(pd.DataFrame(summary_rows, dtype=object), R / "collaboration_summary.csv")   # object dtype keeps integer counts as integers
wcsv(nodes_df, R / "country_collaboration_nodes.csv")
wcsv(edges_df, R / "country_collaboration_edges.csv")
# Figure 9: Africa-involved network (AA + AN edges); full and recommended display subset (top 50 by Africa-involved strength)
inv_edges = edges_df[edges_df.pair_type.isin(["AA", "AN"])]
cid = {c: i + 1 for i, c in enumerate(nodes_df.iso2)}
inv_nodes = nodes_df[nodes_df.africa_involved_link_strength > 0]
vos("F9_country_africa_involved_full",
    [(cid[r.iso2], r.country, {"Documents": r.publications}) for r in inv_nodes.itertuples()],
    [(cid[r.iso2_a], cid[r.iso2_b], r.weight_full) for r in inv_edges.itertuples()], ["Documents"])
top9 = list(inv_nodes.iso2[:SETTINGS["display_cap_country"]])
vos("F9_country_africa_involved_top50",
    [(cid[r.iso2], r.country, {"Documents": r.publications}) for r in inv_nodes.itertuples() if r.iso2 in top9],
    [(cid[r.iso2_a], cid[r.iso2_b], r.weight_full) for r in inv_edges.itertuples() if r.iso2_a in top9 and r.iso2_b in top9], ["Documents"])
# Figure 8: keyword occurrence table (full: work dir; results: >= smallest candidate threshold)
kw_nodes = pd.DataFrame([{"keyword": k, "occurrences": v, "total_link_strength": kw_link[k]} for k, v in kw_occ.items()]) \
    .sort_values(["occurrences", "keyword"], ascending=[False, True])
wcsv(kw_nodes, W / "keyword_occurrences_full.csv")
pd.DataFrame([{"keyword_a": a, "keyword_b": b, "cooccurrences": v} for (a, b), v in kw_pairs.items()]).to_csv(
    W / "keyword_cooccurrence_full.csv", index=False, lineterminator="\n")
OUT.append(W / "keyword_cooccurrence_full.csv")
Tmin = min(SETTINGS["keyword_candidate_thresholds"])
kn = kw_nodes[kw_nodes.occurrences >= Tmin]
ks = set(kn.keyword)
ke = pd.DataFrame([{"keyword_a": a, "keyword_b": b, "cooccurrences": v} for (a, b), v in kw_pairs.items() if a in ks and b in ks]) \
    .sort_values(["cooccurrences", "keyword_a", "keyword_b"], ascending=[False, True, True])
wcsv(kn, R / "keyword_network_nodes.csv")
wcsv(ke, R / "keyword_network_edges.csv")
wcsv(cand_df, R / "keyword_threshold_candidates.csv")
kid = {k: i + 1 for i, k in enumerate(kn.keyword)}
for T in (500, 1000, 1500):
    sel = kn[kn.occurrences >= T]
    ss = set(sel.keyword)
    vos(f"F8_keyword_min{T}", [(kid[r.keyword], r.keyword, {"Occurrences": r.occurrences}) for r in sel.itertuples()],
        [(kid[r.keyword_a], kid[r.keyword_b], r.cooccurrences) for r in ke.itertuples() if r.keyword_a in ss and r.keyword_b in ss],
        ["Occurrences"])
# Figure 10: institutions
wcsv(inst_nodes, R / "institution_network_nodes.csv")
wcsv(inst_edges, R / "institution_network_edges.csv")
iid = {r: i + 1 for i, r in enumerate(inst_nodes.ror_id)}
vos("F10_institution_ror_full", [(iid[r.ror_id], r.name, {"Documents": r.publications}) for r in inst_nodes.itertuples()],
    [(iid[r.ror_id_a], iid[r.ror_id_b], r.weight_full) for r in inst_edges.itertuples()], ["Documents"])
top10 = set(inst_nodes.ror_id[:SETTINGS["display_cap_institution"]])
vos("F10_institution_ror_top50", [(iid[r.ror_id], r.name, {"Documents": r.publications}) for r in inst_nodes.itertuples() if r.ror_id in top10],
    [(iid[r.ror_id_a], iid[r.ror_id_b], r.weight_full) for r in inst_edges.itertuples() if r.ror_id_a in top10 and r.ror_id_b in top10],
    ["Documents"])

# descriptive tables
au_nodes = nodes_df[nodes_df.au_member & (nodes_df.africa_involved_link_strength > 0)].copy()
rev = {
    "leading_external_partners": nodes_df[~nodes_df.au_member].nlargest(15, "africa_non_africa_link_strength")[["iso2", "country", "africa_non_africa_link_strength", "publications"]].to_dict("records"),
    "strongest_intra_african_pairs": edges_df[edges_df.pair_type == "AA"].head(15)[["country_a", "country_b", "weight_full"]].to_dict("records"),
    "strongest_africa_non_africa_pairs": edges_df[edges_df.pair_type == "AN"].head(15)[["country_a", "country_b", "weight_full"]].to_dict("records"),
    "au_highest_au_partner_share_min100": au_nodes[au_nodes.africa_involved_link_strength >= 100].nlargest(10, "au_partner_share")[["iso2", "country", "au_partner_share", "africa_involved_link_strength"]].to_dict("records"),
    "au_highest_external_partner_share_min100": au_nodes[au_nodes.africa_involved_link_strength >= 100].nlargest(10, "non_au_partner_share")[["iso2", "country", "non_au_partner_share", "africa_involved_link_strength"]].to_dict("records"),
}
au_nodes["rank_intra"] = au_nodes.intra_african_link_strength.rank(ascending=False)
au_nodes["rank_external"] = au_nodes.africa_non_africa_link_strength.rank(ascending=False)
from scipy.stats import spearmanr  # noqa: E402
rev["coexistence"] = {
    "spearman_intra_vs_external_link_strength_AU": float(spearmanr(au_nodes.intra_african_link_strength, au_nodes.africa_non_africa_link_strength).statistic),
    "AU_in_top10_of_both": sorted(au_nodes[(au_nodes.rank_intra <= 10) & (au_nodes.rank_external <= 10)].country),
}
CHECKS = {
    "country sets equal Stage 02 affiliation_countries for every record": agree["all_equal_stage02"] == stat["records"],
    "AU sets equal Stage 02 au_countries for every record": agree["au_equal_stage02"] == stat["records"],
    "fractional pair conservation": abs(CONSERV["fractional_total"] - CONSERV["records_with_pairs"]) < 1e-6,
    "full AA+AN+NN = total pairs": sum(TF.values()) == sum(pairs_full.values()),
    "edge table total = full pair total": int(edges_df.weight_full.sum()) == int(sum(TF.values())),
    "node TLS sum = 2 x edge total": int(nodes_df.total_link_strength.sum()) == 2 * int(edges_df.weight_full.sum()),
    "all ROR ids known": not unknown_ror,
    "geo terms absent from keyword table": not (set(kw_nodes.keyword.str.lower()) & GEO),
}
for k, v in CHECKS.items():
    log.info(f"  [{'PASS' if v else 'FAIL'}] {k}")
if not all(CHECKS.values()):
    sys.exit("internal validation FAILED")
summary = {"stage": "08 network/collaboration data", "script_version": SCRIPT_VERSION, "git_head": git("rev-parse", "HEAD"),
           "run_start": RUN_START.isoformat(timespec="seconds"), "inputs_sha256": INPUTS, "settings": SETTINGS,
           "country_extraction": dict(stat), "agreement_with_stage02": dict(agree),
           "pairs_full": dict(TF), "pairs_fractional": {k: round(v, 6) for k, v in TR.items()},
           "intra_african_link_share": {"full": FULL_SHARE, "fractional": FRAC_SHARE}, "fractional_conservation": CONSERV,
           "paper_level": summary_rows[:len(paper_rows)], "countries": {"nodes": len(nodes_df), "edges": len(edges_df),
           "au_nodes": int(nodes_df.au_member.sum()), "africa_involved_nodes": len(inv_nodes), "africa_involved_edges": len(inv_edges)},
           "keywords": {"distinct": len(kw_occ), "with_ge2_occurrences": len(keep), "edges_stored": len(kw_pairs),
                        "pairs_with_single_occurrence_keyword": pairs_dropped, "candidates": cand},
           "institutions": {"nodes": len(inst_nodes), "edges": len(inst_edges), "records_with_ror": stat["records_with_ror"]},
           "descriptive_tables": rev, "internal_checks": CHECKS,
           "outputs_sha256": {rel(p): sha256_file(p) for p in OUT}}
json.dump(summary, open(A.prov_dir / "network_collaboration_summary.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
log.info(f"intra-African link share: full {FULL_SHARE:.4%}, fractional {FRAC_SHARE:.4%}")
log.info("STAGE 08 COMPLETE — VALIDATION PASS")
