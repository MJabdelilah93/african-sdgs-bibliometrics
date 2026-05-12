"""04_performance_indicators.py
Stage 5a – Bibliometric performance indicators: Tables T1-T6, Figures F2-F5,
and Bibliometrix-compatible export.

Run from article08/:
    python code/04_performance_indicators.py
"""

import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns
from tqdm import tqdm

# ── bootstrap ──────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parent
sys.path.insert(0, str(HERE))

from utils.config import cfg
from utils.logger import get_logger

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

log = get_logger("stage5a_indicators")

# ── paths ──────────────────────────────────────────────────────────────────
ENRICHED_CSV     = ARTICLE / "data" / "processed" / "enriched.csv"
ROR_JSON         = ARTICLE / "data" / "external" / "ror" / "ror_africa_v2.json"
AU54_CSV         = ARTICLE / "country_lists" / "au54_countries.csv"
SDG_NAMES_CSV    = ARTICLE / "country_lists" / "sdg_names.csv"
RESULTS          = ARTICLE / "results"
FIGURES          = ARTICLE / "figures"
BIBLIO_CSV       = ARTICLE / "data" / "processed" / "bibliometrix_input.csv"

RESULTS.mkdir(parents=True, exist_ok=True)
FIGURES.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 50_000
SEP  = "-" * 62
SEP2 = "=" * 62

# ── ISO3 → ISO2 ────────────────────────────────────────────────────────────
ISO3_TO_ISO2 = {
    "DZA":"DZ","AGO":"AO","BEN":"BJ","BWA":"BW","BFA":"BF","BDI":"BI",
    "CPV":"CV","CMR":"CM","CAF":"CF","TCD":"TD","COM":"KM","COG":"CG",
    "CIV":"CI","COD":"CD","DJI":"DJ","EGY":"EG","GNQ":"GQ","ERI":"ER",
    "SWZ":"SZ","ETH":"ET","GAB":"GA","GMB":"GM","GHA":"GH","GIN":"GN",
    "GNB":"GW","KEN":"KE","LSO":"LS","LBR":"LR","LBY":"LY","MDG":"MG",
    "MWI":"MW","MLI":"ML","MRT":"MR","MUS":"MU","MAR":"MA","MOZ":"MZ",
    "NAM":"NA","NER":"NE","NGA":"NG","RWA":"RW","STP":"ST","SEN":"SN",
    "SYC":"SC","SLE":"SL","SOM":"SO","ZAF":"ZA","SSD":"SS","SDN":"SD",
    "TZA":"TZ","TGO":"TG","TUN":"TN","UGA":"UG","ZMB":"ZM","ZWE":"ZW",
}
AU54_ISO2 = set(ISO3_TO_ISO2.values())

# ══════════════════════════════════════════════════════════════════════════
# LOAD REFERENCE DATA
# ══════════════════════════════════════════════════════════════════════════
t0 = perf_counter()
log.info(SEP2)
log.info("STAGE 5A – PERFORMANCE INDICATORS")
log.info(SEP2)
log.info("Loading reference data ...")

# ROR JSON → display name + country per ROR ID
with open(ROR_JSON, encoding="utf-8") as f:
    ror_records = json.load(f)

ror_display: dict[str, str] = {}
ror_country: dict[str, str] = {}
for rec in ror_records:
    rid = rec["id"]
    names = rec.get("names", [])
    display = next(
        (n["value"] for n in names if "ror_display" in n.get("types", [])),
        names[0]["value"] if names else rid,
    )
    locs = rec.get("locations", [])
    cc = next(
        (
            (loc.get("geonames_details") or {}).get("country_code", "")
            for loc in locs
            if (loc.get("geonames_details") or {}).get("country_code", "") in AU54_ISO2
        ),
        "",
    )
    ror_display[rid] = display
    ror_country[rid]  = cc

log.info(f"  ROR records loaded: {len(ror_display):,}")

# AU54 CSV → iso2_to_name, iso2_to_subregion
au54_df = pd.read_csv(AU54_CSV, dtype=str)
iso2_to_name      = {}
iso2_to_subregion = {}
for _, row in au54_df.iterrows():
    iso3 = row.get("iso3", "").strip()
    iso2 = ISO3_TO_ISO2.get(iso3, "")
    if not iso2:
        continue
    iso2_to_name[iso2]      = row.get("country_name_official", row.get("country_name_scopus", iso2)).strip()
    iso2_to_subregion[iso2] = row.get("subregion", "Unknown").strip()

SUBREGIONS = sorted(set(iso2_to_subregion.values()))
log.info(f"  Sub-regions: {SUBREGIONS}")

# SDG names
sdg_df = pd.read_csv(SDG_NAMES_CSV, dtype=str)
sdg_num_to_name: dict[int, str] = {
    int(r["sdg_number"]): r["sdg_name"]
    for _, r in sdg_df.iterrows()
}

# Detect enriched.csv column names (case-insensitive)
all_cols = pd.read_csv(ENRICHED_CSV, nrows=0).columns.tolist()

def find_col(cols, *patterns):
    for pat in patterns:
        for c in cols:
            if re.fullmatch(pat, c.strip(), re.IGNORECASE):
                return c
    return None

year_col   = find_col(all_cols, r"year", r"py")
auth_col   = find_col(all_cols, r"authors?", r"au")
title_col  = find_col(all_cols, r"title")
src_col    = find_col(all_cols, r"source.title", r"so")
doi_col    = find_col(all_cols, r"doi", r"di")
cite_col   = find_col(all_cols, r"cited.by", r"tc")
dt_col     = find_col(all_cols, r"document.type", r"dt")
eid_col    = find_col(all_cols, r"eid", r"ut")
abs_col    = find_col(all_cols, r"abstract", r"ab")
affil_col  = find_col(all_cols, r"affiliations?", r"c1")
sdgtag_col = find_col(all_cols, r"sdg_tags")
sdgcnt_col = find_col(all_cols, r"sdg_tag_count")
cc_col     = find_col(all_cols, r"match_countries", r"standardised_countries")
ror_col    = find_col(all_cols, r"ror_ids", r"standardised_affiliations")
kwharm_col = find_col(all_cols, r"keywords_harmonised", r"de")
idxharm_col = find_col(all_cols, r"index_keywords_harmonised", r"id")

log.info(f"  Key columns: year={year_col}, cite={cite_col}, sdg_tags={sdgtag_col}, "
         f"cc={cc_col}, ror={ror_col}")

# ══════════════════════════════════════════════════════════════════════════
# STEP 1 — SINGLE-PASS AGGREGATION
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 1 – Single-pass aggregation ...")

# Accumulators
annual_counts:      Counter         = Counter()          # year → int
sdg_frac_counts:    defaultdict     = defaultdict(float) # sdg_num → float
sdg_citations:      defaultdict     = defaultdict(float) # sdg_num → float
country_pubs:       Counter         = Counter()          # iso2 → int
country_frac_pubs:  defaultdict     = defaultdict(float) # iso2 → float
country_total_cites:defaultdict     = defaultdict(float) # iso2 → float
country_cites:      defaultdict     = defaultdict(list)  # iso2 → [cites]
source_pubs:        Counter         = Counter()          # source → int
source_citations:   defaultdict     = defaultdict(float) # source → float
institution_pubs:   Counter         = Counter()          # ror_id → int
institution_citations:defaultdict   = defaultdict(float) # ror_id → float
kw_counts:          Counter         = Counter()          # keyword → int
annual_subregion:   defaultdict     = defaultdict(lambda: defaultdict(int))
                                                         # year → subregion → int
sdg_country_frac:   defaultdict     = defaultdict(lambda: defaultdict(float))
                                                         # sdg_num → iso2 → float
country_annual:     defaultdict     = defaultdict(lambda: defaultdict(int))
                                                         # iso2 → year → int

total_records       = 0
total_citations     = 0.0
most_cited_cites    = -1
most_cited_title    = ""
most_cited_year     = ""
unique_sources:     set = set()

read_cols = [c for c in [
    year_col, auth_col, title_col, src_col, cite_col, dt_col, eid_col,
    sdgtag_col, sdgcnt_col, cc_col, ror_col, kwharm_col,
] if c is not None]

t1_pass = perf_counter()
for chunk in tqdm(
    pd.read_csv(
        ENRICHED_CSV, usecols=read_cols, dtype=str,
        chunksize=CHUNK_SIZE, low_memory=False, keep_default_na=False,
    ),
    desc="aggregating", unit="chunk", ncols=72,
):
    # ── numeric cite column ───────────────────────────────────────────────
    chunk["_cites"] = pd.to_numeric(chunk[cite_col], errors="coerce").fillna(0.0)
    n = len(chunk)
    total_records    += n
    total_citations  += chunk["_cites"].sum()

    # ── most cited record ─────────────────────────────────────────────────
    max_idx = chunk["_cites"].idxmax()
    if chunk.at[max_idx, "_cites"] > most_cited_cites:
        most_cited_cites = chunk.at[max_idx, "_cites"]
        most_cited_title = chunk.at[max_idx, title_col] if title_col else ""
        most_cited_year  = chunk.at[max_idx, year_col]  if year_col  else ""

    # ── annual counts ─────────────────────────────────────────────────────
    yc = chunk[year_col].fillna("").str.strip()
    for yr, cnt in yc.value_counts().items():
        try:
            annual_counts[int(yr)] += int(cnt)
        except ValueError:
            pass

    # ── source titles ─────────────────────────────────────────────────────
    if src_col:
        for src, cnt in chunk[src_col].fillna("").str.strip().value_counts().items():
            if src:
                key = src.strip().rstrip(".")
                source_pubs[key] += int(cnt)
                unique_sources.add(key)
        src_cite = chunk.groupby(chunk[src_col].fillna("").str.strip())["_cites"].sum()
        for src, cites in src_cite.items():
            if src:
                source_citations[src.rstrip(".")] += float(cites)

    # ── keywords ──────────────────────────────────────────────────────────
    if kwharm_col:
        for cell in chunk[kwharm_col].fillna(""):
            if cell:
                for kw in cell.split("; "):
                    kw = kw.strip()
                    if kw:
                        kw_counts[kw] += 1

    # ── SDG fractional (+ SDG×country matrix) ─────────────────────────────
    chunk_s = chunk[[sdgtag_col, sdgcnt_col, cc_col, "_cites"]].copy()
    chunk_s = chunk_s[chunk_s[sdgtag_col] != ""]

    if not chunk_s.empty:
        chunk_s["_sdg_list"]  = chunk_s[sdgtag_col].str.split(",")
        chunk_s["_sdg_cnt"]   = pd.to_numeric(chunk_s[sdgcnt_col], errors="coerce").fillna(1).clip(lower=1)
        chunk_s["_weight"]    = 1.0 / chunk_s["_sdg_cnt"]
        sdg_exp = chunk_s.explode("_sdg_list")
        sdg_exp = sdg_exp[sdg_exp["_sdg_list"].str.strip() != ""]
        try:
            sdg_exp["_sdg_num"] = sdg_exp["_sdg_list"].str.strip().astype(int)
        except (ValueError, TypeError):
            sdg_exp = sdg_exp.copy()
            sdg_exp["_sdg_num"] = pd.to_numeric(sdg_exp["_sdg_list"].str.strip(), errors="coerce")
            sdg_exp = sdg_exp.dropna(subset=["_sdg_num"])
            sdg_exp["_sdg_num"] = sdg_exp["_sdg_num"].astype(int)

        for sdg_num, grp in sdg_exp.groupby("_sdg_num"):
            sdg_frac_counts[sdg_num] += grp["_weight"].sum()
            sdg_citations[sdg_num]   += (grp["_weight"] * grp["_cites"]).sum()

        # SDG × country fractional matrix
        sdg_cc = sdg_exp.copy()
        sdg_cc["_cc_list"] = sdg_cc[cc_col].str.split(";")
        sdg_cc_exp = sdg_cc.explode("_cc_list")
        sdg_cc_exp = sdg_cc_exp[sdg_cc_exp["_cc_list"].str.strip() != ""]
        sdg_cc_exp["_cc"] = sdg_cc_exp["_cc_list"].str.strip()
        sdg_cc_exp = sdg_cc_exp[sdg_cc_exp["_cc"].isin(AU54_ISO2)]
        sc_agg = sdg_cc_exp.groupby(["_sdg_num", "_cc"])["_weight"].sum()
        for (sdg_num, cc), val in sc_agg.items():
            sdg_country_frac[sdg_num][cc] += float(val)

    # ── country full counting ─────────────────────────────────────────────
    if cc_col:
        cc_exp = (chunk[[cc_col, "_cites", year_col]]
                  .assign(_cc_list=chunk[cc_col].str.split(";"))
                  .explode("_cc_list"))
        cc_exp["_cc"] = cc_exp["_cc_list"].str.strip()
        cc_exp = cc_exp[cc_exp["_cc"].isin(AU54_ISO2)]
        if not cc_exp.empty:
            cc_pubs  = cc_exp.groupby("_cc").size()
            cc_cites = cc_exp.groupby("_cc")["_cites"].sum()
            for cc, cnt in cc_pubs.items():
                country_pubs[cc]         += int(cnt)
                country_total_cites[cc]  += float(cc_cites.get(cc, 0))
            # h-index list
            cc_cites_list = cc_exp.groupby("_cc")["_cites"].apply(list)
            for cc, lst in cc_cites_list.items():
                country_cites[cc].extend([int(x) for x in lst])
            # annual per country
            if year_col:
                cc_yr = cc_exp.groupby(["_cc", year_col]).size()
                for (cc, yr), cnt in cc_yr.items():
                    try:
                        country_annual[cc][int(yr)] += int(cnt)
                    except (ValueError, TypeError):
                        pass
            # sub-region annual
            cc_exp["_sr"] = cc_exp["_cc"].map(iso2_to_subregion)
            valid_sr = cc_exp[cc_exp["_sr"].notna()]
            if year_col and not valid_sr.empty:
                sr_yr = valid_sr.groupby([year_col, "_sr"]).size()
                for (yr, sr), cnt in sr_yr.items():
                    try:
                        annual_subregion[int(yr)][sr] += int(cnt)
                    except (ValueError, TypeError):
                        pass

    # ── country fractional ────────────────────────────────────────────────
    if cc_col:
        cf_raw = chunk[[cc_col]].copy()
        cf_raw["_cc_list"] = cf_raw[cc_col].str.split(";")
        cf_raw["_n_cc"]    = cf_raw["_cc_list"].apply(lambda x: max(len([c for c in x if c.strip() in AU54_ISO2]), 1))
        cf_exp = cf_raw.explode("_cc_list")
        cf_exp["_cc"] = cf_exp["_cc_list"].str.strip()
        cf_exp = cf_exp[cf_exp["_cc"].isin(AU54_ISO2)]
        if not cf_exp.empty:
            cf_exp["_frac"] = 1.0 / cf_exp["_n_cc"]
            cf_agg = cf_exp.groupby("_cc")["_frac"].sum()
            for cc, frac in cf_agg.items():
                country_frac_pubs[cc] += float(frac)

    # ── institutions ──────────────────────────────────────────────────────
    if ror_col:
        ror_exp = (chunk[[ror_col, "_cites"]]
                   .assign(_ror_list=chunk[ror_col].str.split(";"))
                   .explode("_ror_list"))
        ror_exp["_rid"] = ror_exp["_ror_list"].str.strip()
        ror_exp = ror_exp[ror_exp["_rid"] != ""]
        if not ror_exp.empty:
            rp = ror_exp.groupby("_rid").size()
            rc = ror_exp.groupby("_rid")["_cites"].sum()
            for rid, cnt in rp.items():
                institution_pubs[rid]         += int(cnt)
                institution_citations[rid]    += float(rc.get(rid, 0))

t1_pass_end = perf_counter()
log.info(f"  Pass complete: {total_records:,} records, {t1_pass_end - t1_pass:.1f}s")

# ══════════════════════════════════════════════════════════════════════════
# STEP 2 — h-INDEX PER COUNTRY
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 2 – Computing h-index per country ...")

def h_index(cites: list[int]) -> int:
    if not cites:
        return 0
    s = sorted(cites, reverse=True)
    h = 0
    for i, c in enumerate(s, 1):
        if c >= i:
            h = i
        else:
            break
    return h

country_h: dict[str, int] = {
    cc: h_index(country_cites[cc]) for cc in AU54_ISO2
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 3 — CAGR
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 3 – Computing CAGR ...")

def cagr(start: float, end: float, years: int = 10) -> float | None:
    if start <= 0 or end <= 0:
        return None
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0

total_cagr = cagr(annual_counts.get(2015, 0), annual_counts.get(2024, 0), years=9)

subregion_cagr: dict[str, float | None] = {}
for sr in SUBREGIONS:
    start_sr = annual_subregion.get(2015, {}).get(sr, 0)
    end_sr   = annual_subregion.get(2024, {}).get(sr, 0)
    subregion_cagr[sr] = cagr(start_sr, end_sr, years=9)

# ══════════════════════════════════════════════════════════════════════════
# STEP 4 — TABLE T1 — CORPUS OVERVIEW
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 4 – Writing Table T1 ...")

avg_cpp   = total_citations / total_records if total_records > 0 else 0.0
n_countries_with_pubs = sum(1 for cc in AU54_ISO2 if country_pubs.get(cc, 0) > 0)
cagr_str  = f"{total_cagr:.1f}%" if total_cagr is not None else "N/A"

t1_rows = [
    {"metric": "Total publications",              "value": f"{total_records:,}"},
    {"metric": "Unique sources (journals/venues)","value": f"{len(unique_sources):,}"},
    {"metric": "Total citations",                 "value": f"{int(total_citations):,}"},
    {"metric": "Average citations per paper (CPP)","value": f"{avg_cpp:.2f}"},
    {"metric": "Time span",                       "value": "2015–2025 (42 records with 2026 publication year retained in corpus but excluded from annual trend analysis)"},
    {"metric": "AU-54 countries with ≥1 pub",     "value": f"{n_countries_with_pubs} / 54"},
    {"metric": "CAGR 2015–2024 (total output)",   "value": cagr_str},
    {"metric": "Most cited paper (title)",        "value": str(most_cited_title)[:200]},
    {"metric": "Most cited paper (citations)",    "value": f"{int(most_cited_cites):,}"},
    {"metric": "Most cited paper (year)",         "value": str(most_cited_year)},
]
with open(RESULTS / "table_T1_corpus_overview.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["metric", "value"])
    w.writeheader(); w.writerows(t1_rows)
log.info("  Written: table_T1_corpus_overview.csv")

# ══════════════════════════════════════════════════════════════════════════
# STEP 5 — TABLE T2 — PUBLICATIONS BY SDG
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 5 – Writing Table T2 ...")

total_sdg_frac = sum(sdg_frac_counts.values())
t2_rows = []
for sdg_num in sorted(sdg_frac_counts, key=lambda x: sdg_frac_counts[x], reverse=True):
    frac   = sdg_frac_counts[sdg_num]
    pct    = 100.0 * frac / total_sdg_frac if total_sdg_frac > 0 else 0.0
    cites  = sdg_citations[sdg_num]
    avg_c  = cites / frac if frac > 0 else 0.0
    t2_rows.append({
        "sdg_number":                    sdg_num,
        "sdg_name":                      sdg_num_to_name.get(sdg_num, ""),
        "fractional_pub_count":          round(frac, 1),
        "pct_of_total_fractional_corpus":round(pct, 2),
        "total_citations":               round(cites, 1),
        "avg_citations_per_frac_pub":    round(avg_c, 2),
    })
with open(RESULTS / "table_T2_publications_by_SDG.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(t2_rows[0].keys()))
    w.writeheader(); w.writerows(t2_rows)
log.info("  Written: table_T2_publications_by_SDG.csv")

# ══════════════════════════════════════════════════════════════════════════
# STEP 6 — TABLE T3 — TOP 30 COUNTRIES
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 6 – Writing Table T3 ...")

t3_rows = []
for cc, pubs in country_pubs.most_common():
    if cc not in AU54_ISO2:
        continue
    cites = country_total_cites.get(cc, 0.0)
    cpp   = cites / pubs if pubs > 0 else 0.0
    t3_rows.append({
        "iso2":            cc,
        "country":         iso2_to_name.get(cc, cc),
        "subregion":       iso2_to_subregion.get(cc, ""),
        "total_pubs":      pubs,
        "total_citations": round(cites, 0),
        "cpp":             round(cpp, 2),
        "h_index":         country_h.get(cc, 0),
    })
t3_rows = t3_rows[:30]
with open(RESULTS / "table_T3_top_countries.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(t3_rows[0].keys()))
    w.writeheader(); w.writerows(t3_rows)
log.info("  Written: table_T3_top_countries.csv")

# ══════════════════════════════════════════════════════════════════════════
# STEP 7 — TABLE T4 — TOP 30 INSTITUTIONS
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 7 – Writing Table T4 ...")

t4_rows = []
for rid, pubs in institution_pubs.most_common():
    if rid not in ror_display:
        continue
    cites = institution_citations.get(rid, 0.0)
    cpp   = cites / pubs if pubs > 0 else 0.0
    t4_rows.append({
        "ror_id":          rid,
        "canonical_name":  ror_display[rid],
        "country":         iso2_to_name.get(ror_country.get(rid, ""), ror_country.get(rid, "")),
        "total_pubs":      pubs,
        "total_citations": round(cites, 0),
        "cpp":             round(cpp, 2),
    })
    if len(t4_rows) == 30:
        break
with open(RESULTS / "table_T4_top_institutions.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(t4_rows[0].keys()))
    w.writeheader(); w.writerows(t4_rows)
log.info("  Written: table_T4_top_institutions.csv")

# ══════════════════════════════════════════════════════════════════════════
# STEP 8 — TABLE T5 — TOP 30 JOURNALS
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 8 – Writing Table T5 ...")

t5_rows = []
for src, pubs in source_pubs.most_common(30):
    cites = source_citations.get(src, 0.0)
    cpp   = cites / pubs if pubs > 0 else 0.0
    t5_rows.append({
        "source_title":    src,
        "total_pubs":      pubs,
        "total_citations": round(cites, 0),
        "cpp":             round(cpp, 2),
    })
with open(RESULTS / "table_T5_top_journals.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(t5_rows[0].keys()))
    w.writeheader(); w.writerows(t5_rows)
log.info("  Written: table_T5_top_journals.csv")

# ══════════════════════════════════════════════════════════════════════════
# STEP 9 — TABLE T6 — SUB-REGIONAL SUMMARY
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 9 – Writing Table T6 ...")

total_all_pubs = sum(country_pubs.values())
t6_rows = []
for sr in SUBREGIONS:
    sr_countries  = [cc for cc, s in iso2_to_subregion.items() if s == sr and cc in AU54_ISO2]
    sr_pubs       = sum(country_pubs.get(cc, 0) for cc in sr_countries)
    sr_cites      = sum(country_total_cites.get(cc, 0.0) for cc in sr_countries)
    sr_share      = 100.0 * sr_pubs / total_all_pubs if total_all_pubs > 0 else 0.0
    sr_cpp        = sr_cites / sr_pubs if sr_pubs > 0 else 0.0
    top_cc        = max(sr_countries, key=lambda cc: country_pubs.get(cc, 0), default="")
    top_cc_name   = iso2_to_name.get(top_cc, top_cc)
    sr_cagr       = subregion_cagr.get(sr)
    cagr_str_sr   = f"{sr_cagr:.1f}%" if sr_cagr is not None else "N/A"
    t6_rows.append({
        "subregion":           sr,
        "total_pubs":          sr_pubs,
        "share_of_africa_pct": round(sr_share, 1),
        "cagr_2015_2024":      cagr_str_sr,
        "top_country":         top_cc_name,
        "total_citations":     round(sr_cites, 0),
        "avg_cpp":             round(sr_cpp, 2),
    })

# Sort by total_pubs descending
t6_rows.sort(key=lambda r: r["total_pubs"], reverse=True)
with open(RESULTS / "table_T6_subregional_summary.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(t6_rows[0].keys()))
    w.writeheader(); w.writerows(t6_rows)
log.info("  Written: table_T6_subregional_summary.csv")

# ══════════════════════════════════════════════════════════════════════════
# STEP 10 — FIGURE F2 — ANNUAL GROWTH BY SUB-REGION
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 10 – Figure F2: annual growth by sub-region ...")

years_range = list(range(2015, 2026))
palette5    = sns.color_palette("colorblind", 5)

fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

for i, sr in enumerate(SUBREGIONS):
    counts = [annual_subregion.get(yr, {}).get(sr, 0) for yr in years_range]
    ax.plot(years_range, counts, color=palette5[i], linewidth=1.5,
            marker="o", markersize=4, label=sr)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.yaxis.grid(True, color="#DDDDDD", linewidth=0.5)
ax.set_axisbelow(True)
ax.set_xlim(2015, 2025)
ax.set_xticks(years_range)
ax.set_xlabel("Year")
ax.set_ylabel("Publications")
ax.set_ylim(bottom=0)
ax.legend(loc="upper left", frameon=False, fontsize=8)

plt.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(FIGURES / f"F2_annual_growth_subregion.{ext}",
                dpi=300, bbox_inches="tight")
plt.close(fig)
log.info("  Saved: F2_annual_growth_subregion.png / .svg")

# ══════════════════════════════════════════════════════════════════════════
# STEP 11 — FIGURE F3 — SDG × COUNTRY HEATMAP
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 11 – Figure F3: SDG × country heatmap ...")

top30_countries = [cc for cc, _ in country_pubs.most_common(30) if cc in AU54_ISO2]
sdg_nums_sorted = list(range(1, 18))

# Build matrix (rows = countries, cols = SDGs)
matrix = np.zeros((len(top30_countries), len(sdg_nums_sorted)))
for j, sdg_num in enumerate(sdg_nums_sorted):
    for i, cc in enumerate(top30_countries):
        frac = sdg_country_frac.get(sdg_num, {}).get(cc, 0.0)
        matrix[i, j] = math.log10(frac + 1)

row_labels = [iso2_to_name.get(cc, cc) for cc in top30_countries]
col_labels = [f"SDG{n}" for n in sdg_nums_sorted]

fig, ax = plt.subplots(figsize=(12, 10), dpi=300)
fig.patch.set_facecolor("white")
sns.heatmap(
    matrix, ax=ax, cmap="YlOrRd", annot=False,
    xticklabels=col_labels, yticklabels=row_labels,
    linewidths=0, linecolor="white",
    cbar_kws={"label": "log₁₀(fractional publications + 1)"},
)
ax.tick_params(axis="x", labelsize=8, rotation=45)
ax.tick_params(axis="y", labelsize=8)
plt.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(FIGURES / f"F3_sdg_country_heatmap.{ext}",
                dpi=300, bbox_inches="tight")
plt.close(fig)
log.info("  Saved: F3_sdg_country_heatmap.png / .svg")

# ══════════════════════════════════════════════════════════════════════════
# STEP 12 — FIGURE F4 — TOP 20 COUNTRIES BAR CHART
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 12 – Figure F4: top 20 countries bar chart ...")

top20_cc    = [cc for cc, _ in country_pubs.most_common(20) if cc in AU54_ISO2][:20]
top20_names = [iso2_to_name.get(cc, cc) for cc in top20_cc]
top20_pubs  = [country_pubs[cc] for cc in top20_cc]

# Reverse so highest is at top
top20_names.reverse()
top20_pubs.reverse()

fig, ax = plt.subplots(figsize=(10, 8), dpi=300)
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

bars = ax.barh(top20_names, top20_pubs, color="#2A6F7F")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.spines["left"].set_visible(False)
ax.tick_params(left=False)
ax.set_xlabel("Publications")
ax.set_xlim(0, max(top20_pubs) * 1.15)

for bar, val in zip(bars, top20_pubs):
    ax.text(bar.get_width() + max(top20_pubs) * 0.01, bar.get_y() + bar.get_height() / 2,
            f"{val:,}", va="center", ha="left", fontsize=7.5)

plt.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(FIGURES / f"F4_top_countries_bar.{ext}",
                dpi=300, bbox_inches="tight")
plt.close(fig)
log.info("  Saved: F4_top_countries_bar.png / .svg")

# ══════════════════════════════════════════════════════════════════════════
# STEP 13 — FIGURE F5 — SUB-REGIONAL SHARE PIE
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 13 – Figure F5: sub-regional share pie ...")

sr_totals = {sr: sum(country_pubs.get(cc, 0)
                     for cc, s in iso2_to_subregion.items()
                     if s == sr and cc in AU54_ISO2)
             for sr in SUBREGIONS}
sr_labels_sorted = sorted(sr_totals, key=sr_totals.get, reverse=True)
sr_values        = [sr_totals[sr] for sr in sr_labels_sorted]
sr_grand_total   = sum(sr_values)

hatch_map = {
    "North Africa":    "",
    "West Africa":     "//",
    "East Africa":     "\\\\",
    "Central Africa":  "xx",
    "Southern Africa": "..",
}
pie_labels = [
    f"{sr}\n{100*v/sr_grand_total:.1f}%" if sr_grand_total > 0 else sr
    for sr, v in zip(sr_labels_sorted, sr_values)
]
hatches = [hatch_map.get(sr, "") for sr in sr_labels_sorted]

fig, ax = plt.subplots(figsize=(8, 8), dpi=300)
fig.patch.set_facecolor("white")
patches, texts = ax.pie(
    sr_values, labels=pie_labels, colors=palette5[:len(sr_values)],
    startangle=90, labeldistance=1.1,
)
for patch, hatch in zip(patches, hatches):
    patch.set_hatch(hatch)
    patch.set_linewidth(0.5)
    patch.set_edgecolor("white")

plt.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(FIGURES / f"F5_subregional_share.{ext}",
                dpi=300, bbox_inches="tight")
plt.close(fig)
log.info("  Saved: F5_subregional_share.png / .svg")

# ══════════════════════════════════════════════════════════════════════════
# STEP 14 — BIBLIOMETRIX EXPORT
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 14 – Bibliometrix export ...")

# Column mapping: enriched_col → bibliometrix_col
bib_map = {
    auth_col:    "AU",
    title_col:   "TI",
    src_col:     "SO",
    abs_col:     "AB",
    kwharm_col:  "DE",
    idxharm_col: "ID",
    affil_col:   "C1",
    cite_col:    "TC",
    year_col:    "PY",
    doi_col:     "DI",
    dt_col:      "DT",
    eid_col:     "UT",
}
bib_map = {k: v for k, v in bib_map.items() if k is not None}
bib_cols_in = list(bib_map.keys())
bib_cols_out = [bib_map[c] for c in bib_cols_in]

bib_written  = 0
bib_header   = False
for chunk in tqdm(
    pd.read_csv(
        ENRICHED_CSV, usecols=bib_cols_in, dtype=str,
        chunksize=CHUNK_SIZE, low_memory=False, keep_default_na=False,
    ),
    desc="bib-export", unit="chunk", ncols=72,
):
    chunk = chunk[bib_cols_in].copy()
    chunk.columns = bib_cols_out
    chunk["DB"] = "SCOPUS"
    chunk = chunk[bib_cols_out + ["DB"]]
    chunk.to_csv(
        BIBLIO_CSV,
        mode="a" if bib_header else "w",
        index=False, header=not bib_header, encoding="utf-8",
    )
    bib_header  = True
    bib_written += len(chunk)

log.info(f"  Written: bibliometrix_input.csv  ({bib_written:,} rows)")

# ══════════════════════════════════════════════════════════════════════════
# TERMINAL REPORT
# ══════════════════════════════════════════════════════════════════════════
t_total = perf_counter() - t0

def file_info(p: Path) -> str:
    if p.exists():
        return f"{p.stat().st_size/1e6:.1f} MB"
    return "missing"

print(f"\n{SEP2}")
print(" STAGE 5A – PERFORMANCE INDICATORS REPORT")
print(SEP2)

print(f"\n{SEP}\nA. AGGREGATION SUMMARY\n{SEP}")
print(f"   Total records processed     : {total_records:,}")
print(f"   Years covered               : {min(annual_counts):}–{max(annual_counts):}")
print(f"   Total citations             : {int(total_citations):,}")
print(f"   Unique source titles        : {len(unique_sources):,}")
print(f"   AU-54 countries with pubs   : {n_countries_with_pubs}/54")

print(f"\n{SEP}\nB. TABLE T1 — CORPUS OVERVIEW\n{SEP}")
for row in t1_rows:
    print(f"   {row['metric']:<42}  {row['value']}")

print(f"\n{SEP}\nC. TABLE T2 — TOP 5 SDGs BY FRACTIONAL OUTPUT\n{SEP}")
print(f"   {'SDG':>4}  {'Name':<40}  {'Frac Count':>10}  {'%':>6}")
print(f"   {'-'*4}  {'-'*40}  {'-'*10}  {'-'*6}")
for r in t2_rows[:5]:
    print(f"   {r['sdg_number']:>4}  {r['sdg_name']:<40}  "
          f"{r['fractional_pub_count']:>10,.1f}  {r['pct_of_total_fractional_corpus']:>5.1f}%")

print(f"\n{SEP}\nD. TABLE T3 — TOP 10 COUNTRIES\n{SEP}")
print(f"   {'Country':<26}  {'Pubs':>8}  {'Cites':>9}  {'CPP':>7}  {'h':>5}")
print(f"   {'-'*26}  {'-'*8}  {'-'*9}  {'-'*7}  {'-'*5}")
for r in t3_rows[:10]:
    print(f"   {r['country']:<26}  {r['total_pubs']:>8,}  "
          f"{int(r['total_citations']):>9,}  {r['cpp']:>7.1f}  {r['h_index']:>5}")

print(f"\n{SEP}\nE. TABLE T4 — TOP 10 INSTITUTIONS\n{SEP}")
print(f"   {'Institution':<46}  {'Ctry':>6}  {'Pubs':>7}  {'Cites':>9}")
print(f"   {'-'*46}  {'-'*6}  {'-'*7}  {'-'*9}")
for r in t4_rows[:10]:
    name = r['canonical_name'][:44]
    print(f"   {name:<46}  {r['country'][:6]:>6}  {r['total_pubs']:>7,}  "
          f"{int(r['total_citations']):>9,}")

print(f"\n{SEP}\nF. TABLE T5 — TOP 10 JOURNALS\n{SEP}")
print(f"   {'Source title':<50}  {'Pubs':>7}  {'Cites':>9}  {'CPP':>7}")
print(f"   {'-'*50}  {'-'*7}  {'-'*9}  {'-'*7}")
for r in t5_rows[:10]:
    print(f"   {r['source_title'][:48]:<50}  {r['total_pubs']:>7,}  "
          f"{int(r['total_citations']):>9,}  {r['cpp']:>7.1f}")

print(f"\n{SEP}\nG. TABLE T6 — SUB-REGIONAL SUMMARY\n{SEP}")
print(f"   {'Sub-region':<22}  {'Pubs':>8}  {'Share':>7}  {'CAGR':>7}  {'Top country'}")
print(f"   {'-'*22}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*20}")
for r in t6_rows:
    print(f"   {r['subregion']:<22}  {r['total_pubs']:>8,}  "
          f"{r['share_of_africa_pct']:>6.1f}%  {r['cagr_2015_2024']:>7}  {r['top_country']}")

print(f"\n{SEP}\nH. FIGURES GENERATED\n{SEP}")
for fname in [
    "F2_annual_growth_subregion.png", "F2_annual_growth_subregion.svg",
    "F3_sdg_country_heatmap.png",     "F3_sdg_country_heatmap.svg",
    "F4_top_countries_bar.png",        "F4_top_countries_bar.svg",
    "F5_subregional_share.png",        "F5_subregional_share.svg",
]:
    p = FIGURES / fname
    size_str = f"{p.stat().st_size/1024:.0f} KB" if p.exists() else "missing"
    print(f"   figures/{fname:<42}  {size_str}")

print(f"\n{SEP}\nI. BIBLIOMETRIX EXPORT\n{SEP}")
bib_size = BIBLIO_CSV.stat().st_size / 1e9 if BIBLIO_CSV.exists() else 0
bib_lines = sum(1 for _ in open(BIBLIO_CSV, encoding="utf-8")) - 1 if BIBLIO_CSV.exists() else 0
match_str = "✓ MATCH" if bib_lines == total_records else f"✗ MISMATCH (expected {total_records:,})"
print(f"   data/processed/bibliometrix_input.csv")
print(f"   Size     : {bib_size:.3f} GB")
print(f"   Rows     : {bib_lines:,}  {match_str}")

print(f"\n{SEP}\nJ. TIMING\n{SEP}")
t_pass  = t1_pass_end - t1_pass
print(f"   Step 1  Single-pass aggregation   : {t_pass:>6.1f} s")
print(f"   Steps 2-9  Compute + write tables : {perf_counter()-t1_pass_end-t_total*0.0:>6.1f} s  (included in total)")
print(f"   Total (all steps)                 : {t_total:>6.1f} s  ({t_total/60:.1f} min)")

print(f"\n{SEP2}")
print(" STAGE 5A COMPLETE – DO NOT COMMIT YET")
print(SEP2)
