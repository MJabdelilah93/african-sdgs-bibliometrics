"""04_performance_indicators.py
Stage 04 – bibliometric performance indicators: Tables T1-T6, Figures F2-F5 and the bibliometrix-compatible
export.

AU-country attribution (T3, T6, country/subregion figures, SDG x country matrix, fractional counts) reads the
direct affiliation-derived `au_countries` column. Institutions (T4) use the country-consistent `ror_ids`.
The T1 "Time span" label is derived from the data. Paths can be overridden on the command line; inputs are
hashed; every output is written to .tmp and promoted only after internal validation; a log, summary and
manifest are written to provenance/v2/; the run is refused outside a virtual environment.

Run from the repository root:
    python code/04_performance_indicators.py
"""

import argparse
import csv
import json
import logging
import math
import os
import platform
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from time import perf_counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns
import tqdm as _tqdm_pkg
from tqdm import tqdm

# ── bootstrap ──────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parent
sys.path.insert(0, str(HERE))

from utils.config import cfg
from utils.checksums import sha256_file

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_VERSION = "2.1.0"
V2_PROV = ARTICLE / cfg["paths"]["provenance"] / "v2"

_ap = argparse.ArgumentParser(description="Stage 04 / pipeline Stage 5a – performance indicators")
_ap.add_argument("--input",       type=Path, default=ARTICLE / "data" / "processed" / "enriched.csv")
_ap.add_argument("--ror",         type=Path, default=ARTICLE / "data" / "external" / "ror" / "ror_africa_v2.json")
_ap.add_argument("--au54",        type=Path, default=ARTICLE / "country_lists" / "au54_countries.csv")
_ap.add_argument("--sdg-names",   type=Path, default=ARTICLE / "country_lists" / "sdg_names.csv")
_ap.add_argument("--results-dir", type=Path, default=ARTICLE / "results")
_ap.add_argument("--figures-dir", type=Path, default=ARTICLE / "figures")
_ap.add_argument("--biblio-out",  type=Path, default=ARTICLE / "data" / "processed" / "bibliometrix_input.csv")
_ap.add_argument("--summary",     type=Path, default=V2_PROV / "stage4_performance_summary.json")
_ap.add_argument("--manifest",    type=Path, default=V2_PROV / "stage4_performance_manifest.csv")
_ap.add_argument("--log",         type=Path, default=V2_PROV / "logs" / "04_performance_indicators.log")
_ap.add_argument("--overwrite",   action="store_true",
                 help="replace an existing bibliometrix_input.csv (default: refuse)")
_ap.add_argument("--allow-global-python", action="store_true",
                 help="run outside a virtual environment (default: refuse; use .venv)")
ARGS = _ap.parse_args()

# ── paths ──────────────────────────────────────────────────────────────────
ENRICHED_CSV     = ARGS.input
ROR_JSON         = ARGS.ror
AU54_CSV         = ARGS.au54
SDG_NAMES_CSV    = ARGS.sdg_names
RESULTS          = ARGS.results_dir
FIGURES          = ARGS.figures_dir
BIBLIO_CSV       = ARGS.biblio_out

RESULTS.mkdir(parents=True, exist_ok=True)
FIGURES.mkdir(parents=True, exist_ok=True)

_PENDING: list[Path] = []      # final output paths, written to <name>.tmp until validation passes


def _tmp(p: Path) -> Path:
    return p.with_name(p.name + ".tmp")


def _out(p: Path) -> Path:
    """Register a final output path and return the temporary path to write."""
    if p not in _PENDING:
        _PENDING.append(p)
    return _tmp(p)


def _rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ARTICLE).as_posix()
    except ValueError:
        return str(p)


def _pinned(package: str) -> str | None:
    req = ARTICLE / "requirements.txt"
    if not req.exists():
        return None
    for line in req.read_text(encoding="utf-8").splitlines():
        name, _, ver = line.split("#")[0].strip().partition("==")
        if name.strip().lower() == package:
            return ver.strip()
    return None


def _git(*args) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ARTICLE, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


ARGS.log.parent.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("04_performance_indicators")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
for _h in (logging.FileHandler(ARGS.log, mode="w", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
    _h.setFormatter(_fmt)
    log.addHandler(_h)

RUN_START = datetime.now()
IN_VENV = sys.prefix != sys.base_prefix
VERSIONS = {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
            "matplotlib": matplotlib.__version__, "seaborn": sns.__version__, "tqdm": _tqdm_pkg.__version__}
GIT_HEAD = _git("rev-parse", "HEAD")
GIT_DIRTY = bool(_git("status", "--porcelain", "--untracked-files=no"))
log.info("=" * 62)
log.info(f"STAGE 04 / pipeline Stage 5a – script v{SCRIPT_VERSION}")
log.info(f"Git HEAD   : {GIT_HEAD} (tracked changes: {GIT_DIRTY})")
log.info(f"Python     : {VERSIONS['python']}  (virtual environment: {IN_VENV})")
for _pkg in ("pandas", "numpy", "matplotlib", "seaborn", "tqdm"):
    log.info(f"{_pkg:<10} : {VERSIONS[_pkg]}  (requirements.txt pin: {_pinned(_pkg)})")
    if _pinned(_pkg) and VERSIONS[_pkg] != _pinned(_pkg):
        log.warning(f"{_pkg} {VERSIONS[_pkg]} differs from the pinned {_pinned(_pkg)}")
if not IN_VENV and not ARGS.allow_global_python:
    log.error("Not running inside a virtual environment – use .venv\\Scripts\\python.exe "
              "(or pass --allow-global-python deliberately).")
    sys.exit(2)
for _need in (ENRICHED_CSV, ROR_JSON, AU54_CSV, SDG_NAMES_CSV):
    if not _need.exists():
        log.error(f"Required input missing: {_rel(_need)}")
        sys.exit(2)
if BIBLIO_CSV.resolve() == ENRICHED_CSV.resolve():
    log.error("bibliometrix output path equals the input path – refusing to run.")
    sys.exit(2)
if BIBLIO_CSV.exists() and not ARGS.overwrite:
    log.error(f"Output already exists: {_rel(BIBLIO_CSV)} (use --overwrite to replace).")
    sys.exit(2)
INPUT_HASHES = {_rel(p): sha256_file(p) for p in (ENRICHED_CSV, ROR_JSON, AU54_CSV, SDG_NAMES_CSV)}
for _p, _d in INPUT_HASHES.items():
    log.info(f"Input      : {_p}  SHA-256 {_d}")

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
au54_df = pd.read_csv(AU54_CSV, dtype=str, keep_default_na=False)
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
sdg_df = pd.read_csv(SDG_NAMES_CSV, dtype=str, keep_default_na=False)
sdg_num_to_name: dict[int, str] = {
    int(r["sdg_number"]): r["sdg_name"]
    for _, r in sdg_df.iterrows()
}

# Detect enriched.csv column names (case-insensitive)
all_cols = pd.read_csv(ENRICHED_CSV, nrows=0, encoding="utf-8-sig").columns.tolist()

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
# Country publication attribution uses the direct, ROR-independent `au_countries` field from
# Stage 02; the ROR-derived `match_countries` field is kept for reference only. Institutions
# use `ror_ids`.
cc_col     = find_col(all_cols, r"au_countries")
if cc_col is None:
    log.error("enriched.csv lacks the direct-country column 'au_countries' (Stage 02 output required).")
    sys.exit(2)
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

def _time_span_label() -> str:
    """Time-span label derived from the data."""
    lo, hi = int(cfg["corpus"]["year_min"]), int(cfg["corpus"]["year_max"])
    years = sorted(annual_counts)
    outside = sum(n for y, n in annual_counts.items() if not lo <= y <= hi)
    label = f"{years[0]}–{years[-1]}" if years else "N/A"
    if outside:
        label += f" ({outside:,} records outside {lo}–{hi} retained in corpus)"
    return label


avg_cpp   = total_citations / total_records if total_records > 0 else 0.0
n_countries_with_pubs = sum(1 for cc in AU54_ISO2 if country_pubs.get(cc, 0) > 0)
cagr_str  = f"{total_cagr:.1f}%" if total_cagr is not None else "N/A"

t1_rows = [
    {"metric": "Total publications",              "value": f"{total_records:,}"},
    {"metric": "Unique sources (journals/venues)","value": f"{len(unique_sources):,}"},
    {"metric": "Total citations",                 "value": f"{int(total_citations):,}"},
    {"metric": "Average citations per paper (CPP)","value": f"{avg_cpp:.2f}"},
    {"metric": "Time span",                       "value": _time_span_label()},
    {"metric": "AU-54 countries with ≥1 pub",     "value": f"{n_countries_with_pubs} / 54"},
    {"metric": "CAGR 2015–2024 (total output)",   "value": cagr_str},
    {"metric": "Most cited paper (title)",        "value": str(most_cited_title)[:200]},
    {"metric": "Most cited paper (citations)",    "value": f"{int(most_cited_cites):,}"},
    {"metric": "Most cited paper (year)",         "value": str(most_cited_year)},
]
with open(_out(RESULTS / "table_T1_corpus_overview.csv"), "w", newline="", encoding="utf-8") as fh:
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
with open(_out(RESULTS / "table_T2_publications_by_SDG.csv"), "w", newline="", encoding="utf-8") as fh:
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
with open(_out(RESULTS / "table_T3_top_countries.csv"), "w", newline="", encoding="utf-8") as fh:
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
with open(_out(RESULTS / "table_T4_top_institutions.csv"), "w", newline="", encoding="utf-8") as fh:
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
with open(_out(RESULTS / "table_T5_top_journals.csv"), "w", newline="", encoding="utf-8") as fh:
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
with open(_out(RESULTS / "table_T6_subregional_summary.csv"), "w", newline="", encoding="utf-8") as fh:
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
    fig.savefig(_out(FIGURES / f"F2_annual_growth_subregion.{ext}"), format=ext,
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
    fig.savefig(_out(FIGURES / f"F3_sdg_country_heatmap.{ext}"), format=ext,
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
    fig.savefig(_out(FIGURES / f"F4_top_countries_bar.{ext}"), format=ext,
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
    fig.savefig(_out(FIGURES / f"F5_subregional_share.{ext}"), format=ext,
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
bib_eids: list[str] = []
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
        _out(BIBLIO_CSV),
        mode="a" if bib_header else "w",
        index=False, header=not bib_header, encoding="utf-8",
    )
    bib_header  = True
    bib_written += len(chunk)
    bib_eids.extend(chunk["UT"])

log.info(f"  Written (temporary): bibliometrix_input.csv  ({bib_written:,} rows)")

# ══════════════════════════════════════════════════════════════════════════
# STEP 15 — INTERNAL VALIDATION, PROMOTION, MANIFEST, SUMMARY
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 15 – Internal validation ...")
_ylo, _yhi = int(cfg["corpus"]["year_min"]), int(cfg["corpus"]["year_max"])
checks = {
    "bibliometrix rows == records aggregated":   bib_written == total_records,
    "bibliometrix UT (EID) unique":              len(set(bib_eids)) == len(bib_eids),
    "no blank EIDs":                             all(e.strip() for e in bib_eids),
    "annual counts sum == records":              sum(annual_counts.values()) == total_records,
    "all years inside study window":             all(_ylo <= y <= _yhi for y in annual_counts),
    "all temporary outputs written":             all(_tmp(p).exists() and _tmp(p).stat().st_size > 0 for p in _PENDING),
    "inputs unchanged (SHA-256)":                {_rel(p): sha256_file(p) for p in
                                                  (ENRICHED_CSV, ROR_JSON, AU54_CSV, SDG_NAMES_CSV)} == INPUT_HASHES,
}
for _name, _ok in checks.items():
    log.info(f"  [{'PASS' if _ok else 'FAIL'}] {_name}")
if not all(checks.values()):
    log.error("Validation FAILED – temporary (.tmp) outputs kept for inspection; final paths untouched.")
    sys.exit(4)
for _final in _PENDING:
    os.replace(_tmp(_final), _final)
    log.info(f"  Promoted : {_rel(_final)}")

log.info("Hashing outputs and writing manifest ...")
_row_counts = {"table_T1_corpus_overview.csv": len(t1_rows), "table_T2_publications_by_SDG.csv": len(t2_rows),
               "table_T3_top_countries.csv": len(t3_rows), "table_T4_top_institutions.csv": len(t4_rows),
               "table_T5_top_journals.csv": len(t5_rows), "table_T6_subregional_summary.csv": len(t6_rows),
               BIBLIO_CSV.name: bib_written}
_out_hashes = {}
with open(ARGS.manifest, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(["role", "relative_path", "size_bytes", "row_count", "sha256"])
    w.writerow(["input_enriched", _rel(ENRICHED_CSV), ENRICHED_CSV.stat().st_size, total_records,
                INPUT_HASHES[_rel(ENRICHED_CSV)]])
    for _p in (ROR_JSON, AU54_CSV, SDG_NAMES_CSV):
        w.writerow(["input_reference", _rel(_p), _p.stat().st_size, "", INPUT_HASHES[_rel(_p)]])
    for _p in _PENDING:
        _d = sha256_file(_p)
        _out_hashes[_rel(_p)] = _d
        _role = ("output_bibliometrix_input" if _p == BIBLIO_CSV else
                 "output_table" if _p.suffix == ".csv" else "output_figure")
        w.writerow([_role, _rel(_p), _p.stat().st_size, _row_counts.get(_p.name, ""), _d])
        log.info(f"  {_role:<26} {_rel(_p)}  {_p.stat().st_size:,} bytes  {_d}")

_ranked_journal_counts = [n for _s, n in source_pubs.most_common()]
summary = {
    "stage": "04_performance_indicators; pipeline-internal name Stage 5a",
    "script_version": SCRIPT_VERSION,
    "input_path": _rel(ENRICHED_CSV), "input_sha256": INPUT_HASHES[_rel(ENRICHED_CSV)],
    "reference_input_sha256": {k: v for k, v in INPUT_HASHES.items() if k != _rel(ENRICHED_CSV)},
    "total_records": total_records,
    "year_min": min(annual_counts), "year_max": max(annual_counts),
    "annual_counts": {str(y): annual_counts[y] for y in sorted(annual_counts)},
    "cagr_2015_2024_pct": total_cagr, "cagr_definition": "((N2024/N2015)^(1/9) - 1) * 100",
    "subregion_cagr_2015_2024_pct": subregion_cagr,
    "annual_subregion_full_counts": {str(y): dict(sorted(annual_subregion[y].items())) for y in sorted(annual_subregion)},
    "total_citations": total_citations, "cpp": avg_cpp, "unique_sources": len(unique_sources),
    "au54_countries_with_publications": n_countries_with_pubs,
    "most_cited": {"title": str(most_cited_title)[:200], "citations": most_cited_cites, "year": most_cited_year},
    "sdg_fractional_counts": {str(k): sdg_frac_counts[k] for k in sorted(sdg_frac_counts)},
    "sdg_fractional_total": total_sdg_frac,
    "country_full_counts": dict(sorted(country_pubs.items())),
    "country_full_count_total": sum(country_pubs.values()),
    "country_h_index": dict(sorted(country_h.items())),
    "institutions_with_publications": len(institution_pubs),
    "subregion_full_count_total": total_all_pubs,
    "top30_cutoffs": {"countries": t3_rows[-1]["total_pubs"], "institutions": t4_rows[-1]["total_pubs"],
                      "journals": t5_rows[-1]["total_pubs"],
                      "journals_tied_at_cutoff": sum(1 for n in _ranked_journal_counts if n == t5_rows[-1]["total_pubs"])},
    "not_stage04_metrics": ["document-type counts/shares", "international collaboration", "co-authorship"],
    "bibliometrix_input_rows": bib_written, "bibliometrix_columns": bib_cols_out + ["DB"],
    "output_sha256": _out_hashes,
    "validation": {k: bool(v) for k, v in checks.items()},
    "versions": VERSIONS, "python_in_virtualenv": IN_VENV,
    "git_commit_at_start": GIT_HEAD, "git_tracked_changes_at_start": GIT_DIRTY,
    "run_started": RUN_START.isoformat(timespec="seconds"),
    "run_finished": datetime.now().isoformat(timespec="seconds"),
}
ARGS.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
log.info(f"Summary    : {_rel(ARGS.summary)}")
log.info(f"RESULT     : records {total_records:,} | years {min(annual_counts)}–{max(annual_counts)} | citations "
         f"{int(total_citations):,} | CPP {avg_cpp:.2f} | CAGR {cagr_str} | SDG frac total {total_sdg_frac:,.1f} "
         f"| countries {n_countries_with_pubs}/54 | bibliometrix rows {bib_written:,}")
log.info("VALIDATION : PASS")

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
bib_lines = bib_written   # counted while writing (abstracts may contain embedded newlines)
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
