"""06_alignment_analysis.py — RQ5 research-implementation alignment.

Asks whether African countries' SDG research portfolios are distributed towards the SDGs on which their
implementation deficits (100 - SDG Index goal score) are largest. Continuous country-level Spearman
alignment is the PRIMARY evidence; quadrants are secondary descriptive aids.

Methods:
  * country attribution from the direct, ROR-independent `au_countries` field (Stage 02);
  * SDG Index (Sustainable Development Report 2025) linked to countries by ISO3;
  * PRIMARY counting: record weight 1/(k SDGs x m unique AU countries); country full counting (1/k) is a
    sensitivity;
  * true zero research shares retained; positive-only is a sensitivity;
  * eligibility derived from the data (research coverage >= 10 positive SDGs AND >= 14 available SDG Index
    goal scores);
  * pair bootstrap with an order-independent per-country random stream; invalid replicates counted, never
    skipped silently or replaced;
  * quadrant medians computed on the primary-eligible population; the fixed 1/17 + 50 benchmark and the
    0.08 + 50 diagnostic threshold (scheme label legacy_0.08_50) as sensitivities;
  * Figure 12 drawn with SDG-specific median lines that match the classification;
  * sensitivities: eligibility grid, counting/zero policy, 2025 exclusion, backdated SDG Index endpoints.
All outputs are written to <name>.tmp and promoted only after internal checks.

Run from the repository root:  python code/06_alignment_analysis.py
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import platform
import subprocess
import sys
import textwrap
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import numpy as np  # noqa: E402
import openpyxl  # noqa: E402
import pandas as pd  # noqa: E402
import scipy  # noqa: E402
from scipy.stats import ConstantInputWarning  # noqa: E402

HERE = Path(__file__).resolve().parent
ARTICLE = HERE.parent
sys.path.insert(0, str(HERE))
from utils.config import cfg  # noqa: E402
from utils.checksums import sha256_file  # noqa: E402
from utils import rq5_methods as M  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_VERSION = "3.1.0"
V2_PROV = ARTICLE / cfg["paths"]["provenance"] / "v2"

_ap = argparse.ArgumentParser(description="Stage 06 — RQ5 research-implementation alignment")
_ap.add_argument("--input", type=Path, default=ARTICLE / "data" / "processed" / "enriched.csv")
_ap.add_argument("--sdg-index", type=Path, default=ARTICLE / "data" / "external" / "sdg_index" / "sdg_index_2025.xlsx")
_ap.add_argument("--au54", type=Path, default=ARTICLE / cfg["paths"]["country_list"])
_ap.add_argument("--sdg-names", type=Path, default=ARTICLE / cfg["paths"]["sdg_names"])
_ap.add_argument("--stage4-manifest", type=Path, default=V2_PROV / "stage4_performance_manifest.csv")
_ap.add_argument("--results-dir", type=Path, default=ARTICLE / cfg["paths"]["results"])
_ap.add_argument("--figures-dir", type=Path, default=ARTICLE / cfg["paths"]["figures"])
_ap.add_argument("--prov-dir", type=Path, default=V2_PROV)
_ap.add_argument("--log", type=Path, default=V2_PROV / "logs" / "06_alignment_analysis.log")
_ap.add_argument("--allow-global-python", action="store_true")
_ap.add_argument("--smoke-test", action="store_true",
                 help="synthetic --input; results/figures/prov dirs must lie outside the project")
ARGS = _ap.parse_args()
if ARGS.smoke_test:
    for _d in (ARGS.results_dir, ARGS.figures_dir, ARGS.prov_dir, ARGS.log.parent):
        if ARTICLE in Path(_d).resolve().parents or Path(_d).resolve() == ARTICLE:
            sys.exit("--smoke-test outputs must be written outside the project directory")

# ── frozen methodological settings (all recorded in the summary) ───────────
SETTINGS = {
    "sdg_fractionalisation": "1/k per tagged SDG (k unique valid SDG tags of the record)",
    "primary_country_counting": "fractional: 1/(k*m), m = unique AU countries in au_countries (direct affiliation-text attribution, Stage 02)",
    "sensitivity_country_counting": "full: 1/k to every involved AU country",
    "research_share": "country SDG weight / country total over all 17 SDGs; true zeros retained",
    "implementation_deficit": "100 - SDR 2025 goal score ('SDR2025 Data', 'Goal n Score'); no imputation",
    "join_key": "ISO3 (SDR 'Country Code ISO3' = country_lists/au54_countries.csv iso3)",
    "eligibility_research_min_positive_sdgs": 10,
    "eligibility_implementation_min_goal_scores": 14,
    "min_pairs_for_rho": 10,
    "rho": "scipy.stats.spearmanr (average ranks for ties); p-value reported, not used for inference",
    "bootstrap_unit": "country's paired (research share, deficit) SDG observations, resampled n with replacement",
    "bootstrap_reps_primary": 1000,
    "bootstrap_seed_primary": 42,
    "bootstrap_stream": "numpy default_rng(SeedSequence([seed, int.from_bytes(ISO3,'big')])) per country (order-independent)",
    "bootstrap_invalid": "replicates with constant resampled research or deficit vector have undefined rho; counted, excluded from percentiles, never replaced",
    "bootstrap_ci": "2.5/97.5 percentiles (numpy linear) of valid replicate rhos",
    "bootstrap_mc_reps": 10000,
    "bootstrap_seed_sensitivity": [1, 42, 2024],
    "quadrant_primary": "SDG-specific medians among primary-eligible countries with a deficit for that SDG; 'high' = value >= median",
    "quadrant_fixed_benchmark": {"research_share": 1 / 17, "deficit": 50.0},
    "quadrant_legacy_diagnostic": {"label": "legacy_0.08_50", "research_share": 0.08, "deficit": 50.0},
    "threshold_sensitive_flag": "SDG flagged threshold-sensitive when the LH count range across the three schemes exceeds 25% of countries with data for that SDG",
    "eligibility_grid": {"research_min": [8, 10, 12], "implementation_min": [12, 14, 16]},
    "exclusion_2025_window": "2015-2024 research portfolio vs SDR 2025 deficits",
    "temporal_backdated_years": [2015, 2018, 2021, 2024],
}
R_MIN = SETTINGS["eligibility_research_min_positive_sdgs"]
I_MIN = SETTINGS["eligibility_implementation_min_goal_scores"]
MIN_PAIRS = SETTINGS["min_pairs_for_rho"]
SEED = SETTINGS["bootstrap_seed_primary"]
REPS = SETTINGS["bootstrap_reps_primary"]
MC_REPS = SETTINGS["bootstrap_mc_reps"]
FIX_R, FIX_D = SETTINGS["quadrant_fixed_benchmark"]["research_share"], SETTINGS["quadrant_fixed_benchmark"]["deficit"]
LEG_R, LEG_D = 0.08, 50.0
EXPECTED_SDG_INDEX_SHA = "d506cb01758e8743deeaf3be03d648ac8fd9c02ec21a42119abedce7aff4d056"  # SDR 2025 workbook used

# ISO 3166-1 alpha-3 -> alpha-2 for the 54 AU members (identical to Stage 04)
ISO3_TO_ISO2 = {
    "DZA": "DZ", "AGO": "AO", "BEN": "BJ", "BWA": "BW", "BFA": "BF", "BDI": "BI",
    "CPV": "CV", "CMR": "CM", "CAF": "CF", "TCD": "TD", "COM": "KM", "COG": "CG",
    "CIV": "CI", "COD": "CD", "DJI": "DJ", "EGY": "EG", "GNQ": "GQ", "ERI": "ER",
    "SWZ": "SZ", "ETH": "ET", "GAB": "GA", "GMB": "GM", "GHA": "GH", "GIN": "GN",
    "GNB": "GW", "KEN": "KE", "LSO": "LS", "LBR": "LR", "LBY": "LY", "MDG": "MG",
    "MWI": "MW", "MLI": "ML", "MRT": "MR", "MUS": "MU", "MAR": "MA", "MOZ": "MZ",
    "NAM": "NA", "NER": "NE", "NGA": "NG", "RWA": "RW", "STP": "ST", "SEN": "SN",
    "SYC": "SC", "SLE": "SL", "SOM": "SO", "ZAF": "ZA", "SSD": "SS", "SDN": "SD",
    "TZA": "TZ", "TGO": "TG", "TUN": "TN", "UGA": "UG", "ZMB": "ZM", "ZWE": "ZW",
}
# ── logging / output helpers ───────────────────────────────────────────────
ARGS.log.parent.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("06_alignment_analysis")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
for _h in (logging.FileHandler(ARGS.log, mode="w", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
    _h.setFormatter(_fmt)
    log.addHandler(_h)

_PENDING: list[Path] = []


def _out(p: Path) -> Path:
    if p not in _PENDING:
        _PENDING.append(p)
    return p.with_name(p.name + ".tmp")


def _rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ARTICLE).as_posix()
    except ValueError:
        return str(p)


def _git(*args) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ARTICLE, capture_output=True, check=True).stdout.decode("utf-8")
    except (OSError, subprocess.CalledProcessError):
        return None


def _pinned(package: str) -> str | None:
    for line in (ARTICLE / "requirements.txt").read_text(encoding="utf-8").splitlines():
        name, _, ver = line.split("#")[0].strip().partition("==")
        if name.strip().lower() == package:
            return ver.strip()
    return None


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(_out(path), index=False, lineterminator="\n")   # full precision (exact round-trip)


def fail(msg: str) -> None:
    log.error(msg)
    sys.exit(2)


RUN_START = datetime.now()
IN_VENV = sys.prefix != sys.base_prefix
VERSIONS = {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
            "scipy": scipy.__version__, "matplotlib": matplotlib.__version__, "openpyxl": openpyxl.__version__}
GIT_HEAD = (_git("rev-parse", "HEAD") or "").strip()
GIT_DIRTY = bool((_git("status", "--porcelain", "--untracked-files=no") or "").strip())

log.info("=" * 70)
log.info(f"STAGE 06 — RQ5 research-implementation alignment — script v{SCRIPT_VERSION}")
log.info(f"Git HEAD : {GIT_HEAD} (tracked changes: {GIT_DIRTY})")
log.info(f"Python   : {VERSIONS['python']} (virtual environment: {IN_VENV})")
for _pkg in ("pandas", "numpy", "scipy", "matplotlib", "openpyxl"):
    log.info(f"{_pkg:<9}: {VERSIONS[_pkg]} (pin: {_pinned(_pkg)})")
    if _pinned(_pkg) and VERSIONS[_pkg] != _pinned(_pkg):
        fail(f"{_pkg} {VERSIONS[_pkg]} differs from the pinned {_pinned(_pkg)}")
if not IN_VENV and not ARGS.allow_global_python:
    fail("Not running inside a virtual environment — use .venv\\Scripts\\python.exe")

# ── input verification ─────────────────────────────────────────────────────
for _need in (ARGS.input, ARGS.sdg_index, ARGS.au54, ARGS.sdg_names, ARGS.stage4_manifest):
    if not _need.exists():
        fail(f"Required input missing: {_rel(_need)}")
_man = pd.read_csv(ARGS.stage4_manifest, dtype=str)
_exp = dict(zip(_man["relative_path"], _man["sha256"]))
_exp_rows = dict(zip(_man["relative_path"], _man["row_count"]))
INPUT_HASHES = {_rel(p): sha256_file(p) for p in (ARGS.input, ARGS.sdg_index, ARGS.au54, ARGS.sdg_names)}
EXPECTED = {_rel(ARGS.input): _exp.get(_rel(ARGS.input)), _rel(ARGS.au54): _exp.get(_rel(ARGS.au54)),
            _rel(ARGS.sdg_names): _exp.get(_rel(ARGS.sdg_names)), _rel(ARGS.sdg_index): EXPECTED_SDG_INDEX_SHA}
for _p, _d in INPUT_HASHES.items():
    log.info(f"Input    : {_p}  SHA-256 {_d}")
    if ARGS.smoke_test and _p == _rel(ARGS.input):
        log.warning("SMOKE TEST: synthetic research input; corpus hash/row expectations not enforced")
        continue
    if _d != EXPECTED[_p]:
        fail(f"Input hash mismatch for {_p}: expected {EXPECTED[_p]}")
EXPECTED_ROWS = None if ARGS.smoke_test else int(_exp_rows[_rel(ARGS.input)])
log.info(f"Input hashes match the frozen baseline (expected corpus rows: {EXPECTED_ROWS}).")
for _k, _v in SETTINGS.items():
    log.info(f"Setting  : {_k} = {_v}")

warnings.simplefilter("error", ConstantInputWarning)   # constant inputs must be handled explicitly

# =============================================================================
# STEP 1 — SDG Index check and ISO3 country crosswalk
# =============================================================================
log.info("STEP 1 — SDG Index workbook check and ISO3 crosswalk")
au = pd.read_csv(ARGS.au54, dtype=str, keep_default_na=False)
if len(au) != 54 or au["iso3"].duplicated().any():
    fail("au54_countries.csv must contain 54 unique ISO3 codes")
if set(au["iso3"]) != set(ISO3_TO_ISO2) or len(set(ISO3_TO_ISO2.values())) != 54:
    fail("ISO3->ISO2 table does not cover exactly the 54 AU ISO3 codes")
au = au.sort_values("iso3").reset_index(drop=True)
COUNTRIES = au["iso3"].tolist()
POS = {c: i for i, c in enumerate(COUNTRIES)}
ISO2_POS = {ISO3_TO_ISO2[c]: i for i, c in enumerate(COUNTRIES)}
AU_ISO2 = set(ISO2_POS)
NAME = dict(zip(au["iso3"], au["country_name_official"]))
SCOPUS_NAME = dict(zip(au["iso3"], au["country_name_scopus"]))
SUBREGION = dict(zip(au["iso3"], au["subregion"]))
sdg_names = pd.read_csv(ARGS.sdg_names)
SDG_NAME = dict(zip(sdg_names["sdg_number"].astype(int), sdg_names["sdg_name"]))
SDGS = list(range(1, 18))

_wb = openpyxl.load_workbook(ARGS.sdg_index, read_only=True)
SHEETS = _wb.sheetnames
_wb.close()
log.info(f"  Workbook sheets: {SHEETS}")
sdr = pd.read_excel(ARGS.sdg_index, sheet_name="SDR2025 Data", engine="openpyxl", keep_default_na=False,
                    na_values=[""])
GOAL_COLS = [f"Goal {g} Score" for g in SDGS]
if any(c not in sdr.columns for c in GOAL_COLS) or "Country Code ISO3" not in sdr.columns:
    fail("SDR2025 Data sheet lacks expected ISO3/goal-score columns")
if sdr["Country Code ISO3"].duplicated().any():
    fail("Duplicate ISO3 codes in SDR2025 Data")
sdr_by = sdr.set_index("Country Code ISO3")
bd = pd.read_excel(ARGS.sdg_index, sheet_name="Backdated SDG Index", engine="openpyxl", keep_default_na=False,
                   na_values=[""])
BD_GOALS = [f"goal{g}" for g in SDGS]
if bd.duplicated(["id", "year"]).any():
    fail("Duplicate (id, year) rows in Backdated SDG Index")

SCORE = np.full((54, 17), np.nan)
for c in COUNTRIES:
    if c in sdr_by.index:
        SCORE[POS[c]] = pd.to_numeric(sdr_by.loc[c, GOAL_COLS], errors="raise").to_numpy(float)
if np.nanmin(SCORE) < 0 or np.nanmax(SCORE) > 100:
    fail("SDG goal scores outside 0-100")
DEFICIT = 100.0 - SCORE
IMPL_COV = M.implementation_coverage(DEFICIT)


def backdated_scores(year: int) -> np.ndarray:
    s = np.full((54, 17), np.nan)
    sub = bd[bd["year"] == year].set_index("id")
    for c in COUNTRIES:
        if c in sub.index:
            s[POS[c]] = pd.to_numeric(sub.loc[c, BD_GOALS], errors="raise").to_numpy(float)
    return s


BD_YEARS = SETTINGS["temporal_backdated_years"]
BD_SCORE = {y: backdated_scores(y) for y in BD_YEARS}
_both = ~np.isnan(SCORE) & ~np.isnan(BD_SCORE[2024])
BD2024_IDENTITY = {
    "pairs_compared": int(_both.sum()),
    "max_abs_difference": float(np.abs(SCORE[_both] - BD_SCORE[2024][_both]).max()),
    "backdated_2024_only_cells": int((np.isnan(SCORE) & ~np.isnan(BD_SCORE[2024])).sum()),
    "sdr2025_only_cells": int((~np.isnan(SCORE) & np.isnan(BD_SCORE[2024])).sum()),
}
log.info(f"  Backdated 2024 vs SDR2025 goal scores: {BD2024_IDENTITY}")

cw_rows = []
for c in COUNTRIES:
    in_sdr = c in sdr_by.index
    n25 = int(IMPL_COV[POS[c]])
    n24 = int((~np.isnan(BD_SCORE[2024][POS[c]])).sum())
    missing = [g for g in SDGS if np.isnan(SCORE[POS[c], g - 1])]
    status = ("matched_iso3" if in_sdr else "not_in_sdg_index")
    notes = []
    if in_sdr and n25 == 0:
        notes.append("listed in SDR 2025 without goal-level scores (insufficient data); backdated series has goal scores")
    elif 0 < n25 < 17:
        notes.append(f"missing 2025 goal(s): {missing}")
    cw_rows.append({
        "country_name": NAME[c], "country_name_scopus": SCOPUS_NAME[c], "subregion": SUBREGION[c],
        "iso2": ISO3_TO_ISO2[c], "iso3": c, "research_identifier": f"au_countries ISO2 '{ISO3_TO_ISO2[c]}'",
        "sdg_index_identifier": c if in_sdr else "", "sdg_index_name": sdr_by.loc[c, "Country"] if in_sdr else "",
        "mapping_status": status, "sdr2025_goal_scores_available": n25,
        "sdr2025_missing_goals": ";".join(map(str, missing)), "backdated_2024_goal_scores_available": n24,
        "notes": "; ".join(notes),
    })
crosswalk = pd.DataFrame(cw_rows)
if len(crosswalk) != 54 or crosswalk["iso3"].duplicated().any() or crosswalk["iso2"].duplicated().any():
    fail("Crosswalk is not 54 unique rows")
if (crosswalk["sdg_index_identifier"] != "").sum() != (crosswalk["mapping_status"] == "matched_iso3").sum():
    fail("Ambiguous crosswalk mapping")
log.info(f"  Crosswalk: {len(crosswalk)} AU rows; matched by ISO3: {(crosswalk.mapping_status == 'matched_iso3').sum()}; "
         f"coverage distribution: {crosswalk.sdr2025_goal_scores_available.value_counts().sort_index().to_dict()}")

# =============================================================================
# STEP 2 — Research portfolios (one pass over enriched.csv)
# =============================================================================
log.info("STEP 2 — Research portfolios from enriched.csv")
W = {(w, s): np.zeros((54, 17)) for w in ("2015-2025", "2015-2024") for s in ("fractional", "full")}
REC = {"rows": 0, "attributed_2015_2025": 0, "attributed_2015_2024": 0, "no_au_country": 0, "no_valid_sdg": 0,
       "sum_m_2015_2025": 0, "sum_m_2015_2024": 0}
records_per_country = np.zeros(54, dtype=int)
eids = set()
years, dtypes = {}, {}
for chunk in pd.read_csv(ARGS.input, usecols=["EID", "Year", "Document Type", "sdg_tags", "au_countries"],
                         dtype=str, keep_default_na=False, chunksize=50_000):
    for eid, yr, dt, tags, mc in zip(chunk["EID"], chunk["Year"], chunk["Document Type"],
                                     chunk["sdg_tags"], chunk["au_countries"]):
        REC["rows"] += 1
        eids.add(eid)
        years[yr] = years.get(yr, 0) + 1
        dtypes[dt] = dtypes.get(dt, 0) + 1
        sdgs = M.parse_sdgs(tags)
        ccs = M.parse_countries(mc, AU_ISO2)
        if not ccs:
            REC["no_au_country"] += 1
            continue
        if not sdgs:
            REC["no_valid_sdg"] += 1
            continue
        windows = ["2015-2025"] + (["2015-2024"] if int(yr) <= 2024 else [])
        for c in ccs:
            records_per_country[ISO2_POS[c]] += 1
        for w in windows:
            REC[f"attributed_{w.replace('-', '_')}"] += 1
            REC[f"sum_m_{w.replace('-', '_')}"] += len(ccs)
            for scheme in ("fractional", "full"):
                arr = W[(w, scheme)]
                for c, s, wt in M.record_contributions(sdgs, ccs, scheme):
                    arr[ISO2_POS[c], s - 1] += wt
REC["unique_eids"] = len(eids)
REC["years"] = dict(sorted(years.items()))
REC["document_types"] = dtypes
del eids
log.info(f"  {REC}")
_yr = [int(y) for y in years]
CORPUS_CHECKS = {
    "rows_equal_manifest": ARGS.smoke_test or REC["rows"] == EXPECTED_ROWS,
    "eid_unique": REC["unique_eids"] == REC["rows"],
    "years_within_window": min(_yr) == cfg["corpus"]["year_min"] and max(_yr) == cfg["corpus"]["year_max"],
    "article_review_only": set(dtypes) <= {"Article", "Review"},
}
CONSERVATION = {
    "fractional_total_2015_2025": float(W[("2015-2025", "fractional")].sum()),
    "attributed_records_2015_2025": REC["attributed_2015_2025"],
    "fractional_total_2015_2024": float(W[("2015-2024", "fractional")].sum()),
    "attributed_records_2015_2024": REC["attributed_2015_2024"],
    "full_total_2015_2025": float(W[("2015-2025", "full")].sum()),
    "sum_unique_countries_2015_2025": REC["sum_m_2015_2025"],
}
CORPUS_CHECKS["fractional_conservation_2015_2025"] = abs(CONSERVATION["fractional_total_2015_2025"] - REC["attributed_2015_2025"]) < 1e-6
CORPUS_CHECKS["fractional_conservation_2015_2024"] = abs(CONSERVATION["fractional_total_2015_2024"] - REC["attributed_2015_2024"]) < 1e-6
CORPUS_CHECKS["full_total_equals_sum_m"] = abs(CONSERVATION["full_total_2015_2025"] - REC["sum_m_2015_2025"]) < 1e-6
for k, v in CORPUS_CHECKS.items():
    log.info(f"  [{'PASS' if v else 'FAIL'}] {k}")
if not all(CORPUS_CHECKS.values()):
    fail("Research-corpus checks failed")

SHARE = {key: M.shares_from_weights(arr) for key, arr in W.items()}
RES_COV = {w: M.research_coverage(W[(w, "fractional")]) for w in ("2015-2025", "2015-2024")}
if not (RES_COV["2015-2025"] == M.research_coverage(W[("2015-2025", "full")])).all():
    fail("Positive-SDG coverage differs between counting schemes")

# zero cells (all 54 countries; and those entering the primary analysis)
zero_cells = [(c, g) for c in COUNTRIES for g in SDGS
              if W[("2015-2025", "fractional")][POS[c], g - 1] == 0 and records_per_country[POS[c]] > 0]

# =============================================================================
# STEP 3 — Eligibility
# =============================================================================
log.info("STEP 3 — Country eligibility (research >= %d positive SDGs AND implementation >= %d goal scores)", R_MIN, I_MIN)
ELIG = M.eligibility(RES_COV["2015-2025"], IMPL_COV, R_MIN, I_MIN)
elig_rows = []
for c in COUNTRIES:
    i = POS[c]
    elig_rows.append({
        "country_name": NAME[c], "iso3": c, "iso2": ISO3_TO_ISO2[c], "subregion": SUBREGION[c],
        "records_attributed": int(records_per_country[i]),
        "fractional_research_total": round(float(W[("2015-2025", "fractional")][i].sum()), 6),
        "research_goals_positive": int(RES_COV["2015-2025"][i]),
        "implementation_goals_available": int(IMPL_COV[i]),
        "eligible": bool(ELIG[i]),
        "exclusion_reason": M.exclusion_reason(int(RES_COV["2015-2025"][i]), int(IMPL_COV[i]), R_MIN, I_MIN),
    })
elig_df = pd.DataFrame(elig_rows)
log.info(f"  Eligible: {int(ELIG.sum())} of 54")
for _, r in elig_df[~elig_df.eligible].iterrows():
    log.info(f"    excluded {r.iso3} {r.country_name:<28} {r.exclusion_reason}")
zero_primary = [(c, g) for c, g in zero_cells if ELIG[POS[c]] and not np.isnan(DEFICIT[POS[c], g - 1])]
log.info(f"  Zero research cells (countries with output): {len(zero_cells)} {zero_cells}")
log.info(f"  Zero cells entering primary pairs: {len(zero_primary)} {zero_primary}")


# =============================================================================
# STEP 4 — Country alignment engine
# =============================================================================
def country_alignment(shares: np.ndarray, deficits: np.ndarray, zero_policy: str, reps: int, seed: int,
                      countries=None) -> pd.DataFrame:
    """Per-country Spearman rho + pair bootstrap. Independent of which other countries are analysed."""
    rows = []
    for c in (countries or COUNTRIES):
        i = POS[c]
        sdg, x, y = M.country_pairs(shares[i], deficits[i], zero_policy)
        n = len(x)
        row = {"iso3": c, "country_name": NAME[c], "subregion": SUBREGION[c], "n_pairs": n,
               "sdgs_used": ";".join(map(str, sdg)), "n_zero_research": int((x == 0).sum()),
               "n_tied_research": M.n_tied(x), "n_tied_deficit": M.n_tied(y)}
        if n < MIN_PAIRS:
            row.update({"rho": np.nan, "p_value": np.nan, "status": f"insufficient pairs ({n} < {MIN_PAIRS})"})
            rows.append(row)
            continue
        try:
            rho, p = M.spearman(x, y)
        except ConstantInputWarning:
            rho, p = np.nan, np.nan
        b = M.pair_bootstrap(x, y, reps, seed, c)
        row.update({"rho": rho, "p_value": p, "status": "ok" if not np.isnan(rho) else "constant input"})
        row.update({f"boot_{k}": v for k, v in b.items()})
        row["ci_position"] = M.ci_position(b["ci_low"], b["ci_high"])
        rows.append(row)
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame, mask_iso3: set) -> dict:
    d = df[df["iso3"].isin(mask_iso3) & df["rho"].notna()]
    s = M.summarise_rhos(d["rho"].to_numpy(), d["boot_ci_low"].to_numpy(), d["boot_ci_high"].to_numpy())
    s["n_eligible"] = len(mask_iso3)
    s["median_pairs"] = float(d["n_pairs"].median()) if len(d) else np.nan
    s["countries_ci_below_zero"] = sorted(d.loc[d["boot_ci_high"] < 0, "iso3"])
    return s


ELIG_SET = {c for c in COUNTRIES if ELIG[POS[c]]}
SH_P = SHARE[("2015-2025", "fractional")]
SH_F = SHARE[("2015-2025", "full")]

log.info("STEP 4 — Primary alignment (country-fractional, zeros retained, ISO3, primary eligibility)")
ALL_WITH_DATA = [c for c in COUNTRIES if IMPL_COV[POS[c]] > 0 and records_per_country[POS[c]] > 0]
primary_all = country_alignment(SH_P, DEFICIT, "retain", REPS, SEED, ALL_WITH_DATA)
primary = primary_all[primary_all.iso3.isin(ELIG_SET)].reset_index(drop=True)
PRIMARY_SUMMARY = summarise(primary_all, ELIG_SET)
log.info(f"  Primary summary: {PRIMARY_SUMMARY}")
if primary["rho"].isna().any():
    fail("An eligible country has no defined primary rho")

# =============================================================================
# STEP 5 — Bootstrap diagnostics (MC stability, seed sensitivity)
# =============================================================================
log.info("STEP 5 — Bootstrap diagnostics")
ELIG_LIST = sorted(ELIG_SET)
boot_cfg = {("1000", 42): primary_all[primary_all.iso3.isin(ELIG_SET)]}
for reps, seed in ((MC_REPS, 42), (REPS, 1), (REPS, 2024)):
    boot_cfg[(str(reps), seed)] = country_alignment(SH_P, DEFICIT, "retain", reps, seed, ELIG_LIST)
bd_rows = []
for (reps, seed), df in boot_cfg.items():
    for _, r in df.iterrows():
        bd_rows.append({"config": f"reps{reps}_seed{seed}", "attempted_reps": int(reps), "seed": seed, "iso3": r.iso3,
                        "country_name": r.country_name, "n_pairs": r.n_pairs, "rho": r.rho,
                        **{k[5:]: r[k] for k in df.columns if k.startswith("boot_")}, "ci_position": r.ci_position})
boot_diag = pd.DataFrame(bd_rows)
ref = boot_cfg[("1000", 42)].set_index("iso3")
BOOT_STABILITY = {}
for key, df in boot_cfg.items():
    if key == ("1000", 42):
        continue
    d = df.set_index("iso3").loc[ref.index]
    BOOT_STABILITY[f"reps{key[0]}_seed{key[1]}_vs_reps1000_seed42"] = {
        "max_abs_ci_low_diff": float((d.boot_ci_low - ref.boot_ci_low).abs().max()),
        "max_abs_ci_high_diff": float((d.boot_ci_high - ref.boot_ci_high).abs().max()),
        "mean_abs_ci_endpoint_diff": float(pd.concat([(d.boot_ci_low - ref.boot_ci_low).abs(),
                                                       (d.boot_ci_high - ref.boot_ci_high).abs()]).mean()),
        "ci_position_changes": sorted(d.index[d.ci_position != ref.ci_position]),
        "n_ci_below_zero": int((d.boot_ci_high < 0).sum()),
    }
_seed_sets = [boot_cfg[(str(REPS), s)].set_index("iso3").loc[ref.index] for s in SETTINGS["bootstrap_seed_sensitivity"]]
BOOT_STABILITY["seed_sensitivity_1000reps_seeds_1_42_2024"] = {
    "max_abs_ci_endpoint_variation": float(max(
        (pd.concat([s.boot_ci_low for s in _seed_sets], axis=1).max(axis=1) - pd.concat([s.boot_ci_low for s in _seed_sets], axis=1).min(axis=1)).max(),
        (pd.concat([s.boot_ci_high for s in _seed_sets], axis=1).max(axis=1) - pd.concat([s.boot_ci_high for s in _seed_sets], axis=1).min(axis=1)).max())),
    "countries_with_ci_position_change_across_seeds": sorted(
        set().union(*[set(s.index[s.ci_position != ref.ci_position]) for s in _seed_sets])),
}
BOOT_TOTALS = {k: int(primary[f"boot_{k}"].sum()) for k in ("attempted", "valid", "invalid", "resamples_lt3_unique_pairs")}
log.info(f"  Primary bootstrap totals: {BOOT_TOTALS}")
log.info(f"  Stability: {json.dumps(BOOT_STABILITY)}")

# =============================================================================
# STEP 6 — Eligibility-threshold sensitivity grid
# =============================================================================
log.info("STEP 6 — Eligibility-threshold grid")
GRID_UNION = [c for c in COUNTRIES if RES_COV["2015-2025"][POS[c]] >= min(SETTINGS["eligibility_grid"]["research_min"])
              and IMPL_COV[POS[c]] >= min(SETTINGS["eligibility_grid"]["implementation_min"])]
grid_all = primary_all.set_index("iso3")
missing_grid = [c for c in GRID_UNION if c not in grid_all.index]
if missing_grid:
    fail(f"Grid countries without alignment: {missing_grid}")
eg_rows = []
for rmin in SETTINGS["eligibility_grid"]["research_min"]:
    for imin in SETTINGS["eligibility_grid"]["implementation_min"]:
        mask = {c for c in COUNTRIES if M.eligibility(RES_COV["2015-2025"][POS[c]], IMPL_COV[POS[c]], rmin, imin)}
        s = summarise(primary_all, mask)
        common = sorted(mask & ELIG_SET)
        # per-country rho/CI do not depend on the analysed population (per-country streams)
        same = bool((grid_all.loc[common, ["rho", "boot_ci_low", "boot_ci_high"]]
                     == primary.set_index("iso3").loc[common, ["rho", "boot_ci_low", "boot_ci_high"]]).all().all())
        eg_rows.append({
            "research_min": rmin, "implementation_min": imin, "primary_rule": (rmin, imin) == (R_MIN, I_MIN),
            "n_eligible": len(mask), "median_rho": s["median_rho"], "q1_rho": s["q1_rho"], "q3_rho": s["q3_rho"],
            "n_negative": s["n_negative"], "n_ci_below_zero": s["n_ci_below_zero"],
            "countries_added_vs_primary": ";".join(sorted(mask - ELIG_SET)),
            "countries_removed_vs_primary": ";".join(sorted(ELIG_SET - mask)),
            "common_country_rho_ci_identical_to_primary": same,
            "relative_order_of_common_countries": "unchanged (identical per-country values)" if same else "CHANGED",
        })
elig_sens = pd.DataFrame(eg_rows)
log.info("\n" + elig_sens.drop(columns=["countries_added_vs_primary", "countries_removed_vs_primary"]).to_string())

# =============================================================================
# STEP 7 — Counting / zero-share method sensitivity
# =============================================================================
log.info("STEP 7 — Counting / zero-share method sensitivities")
VARIANTS = {
    "PRIMARY": ("fractional", "retain"),
    "A_full_zeros_retained": ("full", "retain"),
    "B_fractional_positive_only": ("fractional", "positive_only"),
    "C_full_positive_only": ("full", "positive_only"),
}
var_res = {"PRIMARY": primary}
for name, (scheme, zp) in VARIANTS.items():
    if name != "PRIMARY":
        var_res[name] = country_alignment(SHARE[("2015-2025", scheme)], DEFICIT, zp, REPS, SEED, ELIG_LIST)
ms_rows, msc_rows = [], []
for name, df in var_res.items():
    s = summarise(df, ELIG_SET)
    j = df.set_index("iso3")["rho"].reindex(primary.iso3)
    diff = (j.to_numpy() - primary["rho"].to_numpy())
    ms_rows.append({"variant": name, "country_counting": VARIANTS[name][0], "zero_policy": VARIANTS[name][1],
                    "n_eligible": s["n_eligible"], "n_with_rho": s["n"], "median_rho": s["median_rho"],
                    "q1_rho": s["q1_rho"], "q3_rho": s["q3_rho"], "n_negative": s["n_negative"],
                    "n_ci_below_zero": s["n_ci_below_zero"], "median_pairs": s["median_pairs"],
                    "median_abs_rho_change_vs_primary": float(np.nanmedian(np.abs(diff))),
                    "max_abs_rho_change_vs_primary": float(np.nanmax(np.abs(diff))),
                    "countries_ci_below_zero": ";".join(s["countries_ci_below_zero"])})
    for _, r in df.iterrows():
        prow = primary.set_index("iso3").loc[r.iso3]
        msc_rows.append({"variant": name, "iso3": r.iso3, "country_name": r.country_name, "n_pairs": r.n_pairs,
                         "n_zero_research": r.n_zero_research, "rho": r.rho, "ci_low": r.get("boot_ci_low", np.nan),
                         "ci_high": r.get("boot_ci_high", np.nan), "ci_position": r.get("ci_position", ""),
                         "rho_change_vs_primary": r.rho - prow.rho})
method_sens = pd.DataFrame(ms_rows)
method_sens_country = pd.DataFrame(msc_rows)
log.info("\n" + method_sens.drop(columns=["countries_ci_below_zero"]).to_string())

# =============================================================================
# STEP 8 — 2025-exclusion and temporal (backdated SDG Index) sensitivities
# =============================================================================
log.info("STEP 8 — 2025 exclusion and backdated-endpoint sensitivities")
SH_24 = SHARE[("2015-2024", "fractional")]
temporal_rows, temporal_country = [], []


def run_temporal(label, shares, deficits, res_cov, restrict=None, note=""):
    impl = M.implementation_coverage(deficits)
    mask = {c for c in COUNTRIES if M.eligibility(res_cov[POS[c]], impl[POS[c]], R_MIN, I_MIN)
            and (restrict is None or c in restrict)}
    df = country_alignment(shares, deficits, "retain", REPS, SEED, sorted(mask))
    s = summarise(df, mask)
    j = df.set_index("iso3")["rho"]
    common = sorted(set(j.index) & set(primary.iso3))
    pj = primary.set_index("iso3")["rho"]
    d = (j.loc[common] - pj.loc[common])
    temporal_rows.append({
        "variant": label, "note": note, "n_available_countries": int(sum(1 for c in COUNTRIES if impl[POS[c]] > 0
                                                                          and (restrict is None or c in restrict))),
        "n_eligible": s["n_eligible"], "median_rho": s["median_rho"], "q1_rho": s["q1_rho"], "q3_rho": s["q3_rho"],
        "n_negative": s["n_negative"], "n_ci_below_zero": s["n_ci_below_zero"],
        "countries_ci_below_zero": ";".join(s["countries_ci_below_zero"]),
        "n_common_with_primary": len(common),
        "median_rho_change_common": float(d.median()) if len(d) else np.nan,
        "max_abs_rho_change_common": float(d.abs().max()) if len(d) else np.nan,
        "spearman_of_country_rhos_vs_primary": float(M.spearman(j.loc[common], pj.loc[common])[0]) if len(common) > 2 else np.nan,
        "countries_added_vs_primary": ";".join(sorted(mask - ELIG_SET)),
        "countries_removed_vs_primary": ";".join(sorted(ELIG_SET - mask)),
    })
    for _, r in df.iterrows():
        temporal_country.append({"variant": label, "iso3": r.iso3, "n_pairs": r.n_pairs, "rho": r.rho,
                                 "ci_low": r.get("boot_ci_low"), "ci_high": r.get("boot_ci_high"),
                                 "rho_change_vs_primary": r.rho - pj[r.iso3] if r.iso3 in pj.index else np.nan})
    return df


run_temporal("primary_2015_2025_research__sdr2025", SH_P, DEFICIT, RES_COV["2015-2025"], note="primary (reference)")
excl25 = run_temporal("exclude2025_2015_2024_research__sdr2025", SH_24, DEFICIT, RES_COV["2015-2024"],
                      note="2025 publications excluded; same SDR 2025 deficits")
SDR_LISTED = {c for c in COUNTRIES if IMPL_COV[POS[c]] > 0}
for y in BD_YEARS:
    run_temporal(f"research_2015_2024__backdated_{y}", SH_24, 100.0 - BD_SCORE[y], RES_COV["2015-2024"],
                 restrict=SDR_LISTED, note=f"backdated SDG Index year {y}; countries with published SDR 2025 goal scores")
bd24_all = run_temporal("research_2015_2024__backdated_2024_all_countries", SH_24, 100.0 - BD_SCORE[2024],
                        RES_COV["2015-2024"],
                        note="adds countries with backdated-only 2024 goal scores (no published SDR 2025 goal scores)")
temporal = pd.DataFrame(temporal_rows)
_t = temporal.set_index("variant")
TEMPORAL_IDENTITY_2024 = bool(
    np.isclose(_t.loc["research_2015_2024__backdated_2024", "median_rho"],
               _t.loc["exclude2025_2015_2024_research__sdr2025", "median_rho"])
    and _t.loc["research_2015_2024__backdated_2024", "n_eligible"] == _t.loc["exclude2025_2015_2024_research__sdr2025", "n_eligible"])
log.info("\n" + temporal.drop(columns=["countries_ci_below_zero", "note"]).to_string())
log.info(f"  2015-2024 x backdated-2024 identical to 2015-2024 x SDR2025 (published countries): {TEMPORAL_IDENTITY_2024}")

# =============================================================================
# STEP 9 — Quadrants (secondary, descriptive)
# =============================================================================
log.info("STEP 9 — Quadrants on the primary-eligible population")
q_rows = []
for c in ELIG_LIST:
    i = POS[c]
    for g in SDGS:
        if np.isnan(DEFICIT[i, g - 1]):
            continue
        q_rows.append({"iso3": c, "country_name": NAME[c], "subregion": SUBREGION[c], "sdg_number": g,
                       "sdg_name": SDG_NAME[g], "research_share": SH_P[i, g - 1], "research_zero": SH_P[i, g - 1] == 0,
                       "implementation_score": SCORE[i, g - 1], "implementation_deficit": DEFICIT[i, g - 1]})
quad = pd.DataFrame(q_rows)
med = quad.groupby("sdg_number").agg(median_research_share=("research_share", "median"),
                                     median_deficit=("implementation_deficit", "median"),
                                     n_countries=("iso3", "count"))
quad = quad.merge(med[["median_research_share", "median_deficit"]], left_on="sdg_number", right_index=True)
quad["quadrant_median"] = [M.classify_quadrant(r, d, mr, md) for r, d, mr, md in
                           zip(quad.research_share, quad.implementation_deficit, quad.median_research_share, quad.median_deficit)]
quad["quadrant_fixed_1_17_50"] = [M.classify_quadrant(r, d, FIX_R, FIX_D) for r, d in zip(quad.research_share, quad.implementation_deficit)]
quad["quadrant_legacy_0.08_50"] = [M.classify_quadrant(r, d, LEG_R, LEG_D) for r, d in zip(quad.research_share, quad.implementation_deficit)]
quad["research_at_median"] = quad.research_share == quad.median_research_share
quad["deficit_at_median"] = quad.implementation_deficit == quad.median_deficit
QUAD_TIES = {"research_values_equal_to_sdg_median": int(quad.research_at_median.sum()),
             "deficit_values_equal_to_sdg_median": int(quad.deficit_at_median.sum()),
             "rule": "value >= SDG median is classified high"}
SCHEMES = {"median": "quadrant_median", "fixed_1_17_50": "quadrant_fixed_1_17_50", "legacy_0.08_50": "quadrant_legacy_0.08_50"}
ts_rows = []
for g in SDGS:
    sub = quad[quad.sdg_number == g]
    row = {"sdg_number": g, "sdg_name": SDG_NAME[g], "n_countries": len(sub),
           "median_research_share": med.loc[g, "median_research_share"], "median_deficit": med.loc[g, "median_deficit"]}
    for sname, col in SCHEMES.items():
        vc = sub[col].value_counts()
        for q in ("HH", "HL", "LH", "LL"):
            row[f"{q}_{sname}"] = int(vc.get(q, 0))
    lh = [row[f"LH_{s}"] for s in SCHEMES]
    row["LH_range_across_schemes"] = max(lh) - min(lh)
    row["threshold_sensitive_LH"] = row["LH_range_across_schemes"] > 0.25 * len(sub)
    ts_rows.append(row)
thresh = pd.DataFrame(ts_rows)
tot = {"sdg_number": "all", "sdg_name": "all SDGs", "n_countries": int(thresh.n_countries.sum())}
for sname in SCHEMES:
    for q in ("HH", "HL", "LH", "LL"):
        tot[f"{q}_{sname}"] = int(thresh[f"{q}_{sname}"].sum())
thresh_out = pd.concat([thresh, pd.DataFrame([tot])], ignore_index=True)
QUAD_TOTALS = {s: {q: int(thresh[f"{q}_{s}"].sum()) for q in ("HH", "HL", "LH", "LL")} for s in SCHEMES}
log.info(f"  Quadrant pairs: {len(quad)}; ties: {QUAD_TIES}")
log.info(f"  Totals: {QUAD_TOTALS}")
log.info("\n" + thresh[["sdg_number", "n_countries", "LH_median", "LH_fixed_1_17_50", "LH_legacy_0.08_50",
                        "HL_median", "threshold_sensitive_LH"]].to_string(index=False))

# SDG 9 heterogeneity
s9 = quad[quad.sdg_number == 9].sort_values("research_share").reset_index(drop=True)
SDG9 = {
    "n_countries": len(s9),
    "research_share_quantiles": {q: float(s9.research_share.quantile(q)) for q in (0, 0.25, 0.5, 0.75, 1)},
    "deficit_quantiles": {q: float(s9.implementation_deficit.quantile(q)) for q in (0, 0.25, 0.5, 0.75, 1)},
    "median_thresholds": {"research_share": float(med.loc[9, "median_research_share"]), "deficit": float(med.loc[9, "median_deficit"])},
    "quadrant_counts": {s: s9[col].value_counts().reindex(["HH", "HL", "LH", "LL"], fill_value=0).astype(int).to_dict()
                        for s, col in SCHEMES.items()},
    "LH_median_countries": s9.loc[s9.quadrant_median == "LH", "country_name"].tolist(),
    "HL_median_countries": s9.loc[s9.quadrant_median == "HL", "country_name"].tolist(),
    "research_deficit_spearman_across_countries": float(M.spearman(s9.research_share, s9.implementation_deficit)[0]),
}
SDG9["heterogeneity_persists"] = SDG9["quadrant_counts"]["median"]["LH"] > 0 and SDG9["quadrant_counts"]["median"]["HL"] > 0
log.info(f"  SDG9: {json.dumps(SDG9)}")

# =============================================================================
# STEP 11 — Figure 12 (small multiples with SDG-specific median lines)
# =============================================================================
log.info("STEP 11 — Figure 12")
plt.rcParams["svg.hashsalt"] = "rq5-alignment"
QCOL = {"HH": "#2A6F7F", "LH": "#C0392B", "HL": "#888888", "LL": "#CCCCCC"}
fig, axes = plt.subplots(4, 5, figsize=(15, 12), dpi=300)
for k, g in enumerate(SDGS):
    ax = axes.flat[k]
    sub = quad[quad.sdg_number == g]
    for q, grp in sub.groupby("quadrant_median"):
        ax.scatter(grp.implementation_deficit, grp.research_share, c=QCOL[q], s=14, alpha=0.85, linewidths=0, zorder=3)
    ax.axvline(med.loc[g, "median_deficit"], color="#555555", linestyle="--", linewidth=0.7, zorder=2)
    ax.axhline(med.loc[g, "median_research_share"], color="#555555", linestyle="--", linewidth=0.7, zorder=2)
    ax.set_title(textwrap.fill(f"SDG {g}: {SDG_NAME[g]}", 30), fontsize=8)
    ax.tick_params(labelsize=6.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
fig.supxlabel("Implementation deficit (100 − SDG Index 2025 goal score)", fontsize=10)
fig.supylabel("Research share (country-fractional; share of the country's SDG research output)", fontsize=10)
for ax in axes.flat[17:]:
    ax.axis("off")
handles = [mpatches.Patch(color=QCOL[q], label=f"{q}: {M.QUADRANT_NAMES[q]}") for q in ("HH", "HL", "LH", "LL")]
axes.flat[17].legend(handles=handles, loc="center left", fontsize=8, frameon=False)
axes.flat[18].text(0, 0.5, (f"Each point: one country–SDG pair (n = {len(quad)} pairs, {len(ELIG_SET)} eligible countries).\n"
                            "Dashed lines: SDG-specific medians among eligible countries\n"
                            "(value ≥ median = high). Median splits are descriptive and\n"
                            "mechanically balance quadrant sizes. Research shares:\n"
                            "country-fractional counting, zero shares retained."),
                   fontsize=7.5, va="center", transform=axes.flat[18].transAxes)
fig.tight_layout()
F12_PNG, F12_SVG = ARGS.figures_dir / "F12_alignment_quadrant.png", ARGS.figures_dir / "F12_alignment_quadrant.svg"
fig.savefig(_out(F12_PNG), dpi=300, bbox_inches="tight", format="png")
fig.savefig(_out(F12_SVG), format="svg", bbox_inches="tight", metadata={"Date": None})
plt.close(fig)
f12_data = quad[["iso3", "country_name", "sdg_number", "sdg_name", "research_share", "implementation_deficit",
                 "median_research_share", "median_deficit", "quadrant_median"]]

# =============================================================================
# STEP 12 — Outputs, internal validation, provenance
# =============================================================================
log.info("STEP 12 — Writing outputs")
R, P = ARGS.results_dir, ARGS.prov_dir
grid_rows = []
for c in COUNTRIES:
    i = POS[c]
    for g in SDGS:
        grid_rows.append({
            "iso3": c, "sdg_number": g,
            "weight_fractional_2015_2025": W[("2015-2025", "fractional")][i, g - 1],
            "share_fractional_2015_2025": SH_P[i, g - 1],
            "weight_full_2015_2025": W[("2015-2025", "full")][i, g - 1], "share_full_2015_2025": SH_F[i, g - 1],
            "weight_fractional_2015_2024": W[("2015-2024", "fractional")][i, g - 1],
            "share_fractional_2015_2024": SH_24[i, g - 1],
            "research_zero_2015_2025": W[("2015-2025", "fractional")][i, g - 1] == 0,
            "sdr2025_score": SCORE[i, g - 1], "implementation_deficit": DEFICIT[i, g - 1],
            "eligible_primary": bool(ELIG[i]),
        })
grid_df = pd.DataFrame(grid_rows)
corr_out = primary.rename(columns={"boot_ci_low": "ci_low", "boot_ci_high": "ci_high", "boot_valid": "bootstrap_valid_reps",
                                   "boot_attempted": "bootstrap_attempted_reps", "boot_invalid": "bootstrap_invalid_reps",
                                   "boot_boot_median": "bootstrap_median_rho"})
corr_out = corr_out[["country_name", "iso3", "subregion", "n_pairs", "sdgs_used", "rho", "p_value", "ci_low", "ci_high",
                     "ci_position", "bootstrap_attempted_reps", "bootstrap_valid_reps", "bootstrap_invalid_reps",
                     "bootstrap_median_rho", "n_zero_research", "n_tied_research", "n_tied_deficit"]] \
    .sort_values("iso3").reset_index(drop=True)

write_csv(crosswalk, P / "rq5_country_crosswalk.csv")
write_csv(elig_df, R / "rq5_country_eligibility.csv")
write_csv(grid_df, R / "rq5_country_sdg_research_grid.csv")
write_csv(corr_out, R / "rq5_country_correlations.csv")
write_csv(quad.drop(columns=["research_at_median", "deficit_at_median"]), R / "rq5_quadrant_assignments.csv")
write_csv(thresh, R / "rq5_sdg_quadrant_summary.csv")
write_csv(s9, R / "rq5_sdg9_heterogeneity.csv")
write_csv(method_sens, R / "rq5_method_sensitivity.csv")
write_csv(method_sens_country, R / "rq5_method_sensitivity_country.csv")
write_csv(f12_data, ARGS.figures_dir / "F12_alignment_quadrant_data.csv")
write_csv(boot_diag, P / "stage6_bootstrap_diagnostics.csv")
write_csv(elig_sens, P / "stage6_eligibility_sensitivity.csv")
write_csv(thresh_out, P / "stage6_threshold_sensitivity.csv")
write_csv(pd.concat([temporal, pd.DataFrame(temporal_country).assign(row_type="country")], ignore_index=True)
          .assign(row_type=lambda d: d["row_type"].fillna("summary")), P / "stage6_temporal_sensitivity.csv")

# internal validation before promotion
INTERNAL = {
    "corpus_checks": all(CORPUS_CHECKS.values()),
    "crosswalk_54_unique": len(crosswalk) == 54 and not crosswalk.iso3.duplicated().any(),
    "shares_sum_to_one": bool(np.allclose(np.nansum(SH_P[records_per_country > 0], axis=1), 1.0)),
    "eligible_have_rho": bool(primary.rho.notna().all()),
    "bootstrap_attempted_equals_reps": bool((primary.boot_attempted == REPS).all()),
    "bootstrap_valid_plus_invalid": bool(((primary.boot_valid + primary.boot_invalid) == REPS).all()),
    "quadrant_population_equals_eligible": set(quad.iso3) == ELIG_SET,
    "quadrant_pairs_equal_primary_pairs": len(quad) == int(primary.n_pairs.sum()),
    "temporal_2024_identity": TEMPORAL_IDENTITY_2024,
    "inputs_unchanged": {p: sha256_file(Path(p) if Path(p).is_absolute() else ARTICLE / p) for p in INPUT_HASHES} == INPUT_HASHES,
    "no_empty_outputs": all(_p.with_name(_p.name + ".tmp").stat().st_size > 0 for _p in _PENDING),
}
for k, v in INTERNAL.items():
    log.info(f"  [{'PASS' if v else 'FAIL'}] {k}")
if not all(INTERNAL.values()):
    fail("Internal validation FAILED — .tmp outputs kept, final paths untouched")
for p in _PENDING:
    tmp = p.with_name(p.name + ".tmp")
    tmp.replace(p)
    log.info(f"  Promoted {_rel(p)}")
OUT_HASHES = {_rel(p): sha256_file(p) for p in _PENDING}


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_clean(v) for v in (sorted(o) if isinstance(o, set) else o)]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


summary = {
    "stage": "06 RQ5 research-implementation alignment",
    "script_version": SCRIPT_VERSION, "run_start": RUN_START.isoformat(timespec="seconds"),
    "run_end": datetime.now().isoformat(timespec="seconds"), "git_head": GIT_HEAD, "git_tracked_changes": GIT_DIRTY,
    "environment": {**VERSIONS, "virtual_environment": IN_VENV, "executable": sys.executable},
    "inputs_sha256": INPUT_HASHES, "corpus": REC, "corpus_checks": CORPUS_CHECKS, "conservation": CONSERVATION,
    "settings": SETTINGS,
    "sdg_index_audit": {
        "sheets": SHEETS, "score_sheet": "SDR2025 Data", "score_columns": "Goal 1 Score .. Goal 17 Score",
        "identifier_columns": {"iso3": "Country Code ISO3", "name": "Country"},
        "missing_value_convention": "empty cell (NaN); no sentinel values found",
        "au_score_range": [float(np.nanmin(SCORE)), float(np.nanmax(SCORE))],
        "au_deficit_range": [float(np.nanmin(DEFICIT)), float(np.nanmax(DEFICIT))],
        "au_goal_coverage_distribution": crosswalk.sdr2025_goal_scores_available.value_counts().sort_index().to_dict(),
        "au_without_2025_goal_scores": crosswalk.loc[crosswalk.sdr2025_goal_scores_available == 0, "iso3"].tolist(),
        "au_partial_coverage": dict(zip(crosswalk.loc[crosswalk.sdr2025_goal_scores_available.between(1, 16), "iso3"],
                                        crosswalk.loc[crosswalk.sdr2025_goal_scores_available.between(1, 16), "sdr2025_missing_goals"])),
        "drc_goal_scores_2025": int(IMPL_COV[POS["COD"]]),
        "backdated_sheet_years": [int(bd.year.min()), int(bd.year.max())],
        "backdated_2024_vs_sdr2025": BD2024_IDENTITY,
        "backdated_au_goal_coverage": {y: pd.Series(M.implementation_coverage(100 - BD_SCORE[y])).value_counts().sort_index().to_dict() for y in BD_YEARS},
    },
    "crosswalk": {"rows": 54, "matched_by_iso3": int((crosswalk.mapping_status == "matched_iso3").sum())},
    "zero_cells": {"all_countries": [f"{c}-SDG{g}" for c, g in zero_cells],
                   "in_primary_pairs": [f"{c}-SDG{g}" for c, g in zero_primary],
                   "countries_in_primary": sorted({c for c, _ in zero_primary})},
    "eligibility": {"rule": f"research_goals_positive >= {R_MIN} AND implementation_goals_available >= {I_MIN}",
                    "n_eligible": int(ELIG.sum()), "excluded": elig_df.loc[~elig_df.eligible, ["iso3", "exclusion_reason"]].to_dict("records"),
                    "drc_eligible": bool(ELIG[POS["COD"]])},
    "primary": PRIMARY_SUMMARY, "bootstrap_totals_primary": BOOT_TOTALS, "bootstrap_stability": BOOT_STABILITY,
    "eligibility_sensitivity": elig_sens.to_dict("records"),
    "method_sensitivity": method_sens.to_dict("records"),
    "temporal_sensitivity": temporal.to_dict("records"), "temporal_identity_2024": TEMPORAL_IDENTITY_2024,
    "quadrants": {"population": "primary-eligible countries", "pairs": len(quad), "ties": QUAD_TIES, "totals": QUAD_TOTALS,
                  "threshold_sensitive_sdgs_LH": thresh.loc[thresh.threshold_sensitive_LH, "sdg_number"].tolist(),
                  "note": "median thresholding mechanically encourages near-equal quadrant totals; quadrants are descriptive"},
    "sdg9": SDG9,
    "internal_validation": INTERNAL, "outputs_sha256": OUT_HASHES,
}
with open(P / "stage6_alignment_summary.json", "w", encoding="utf-8") as fh:
    json.dump(_clean(summary), fh, indent=1, ensure_ascii=False)
man_rows = [("input", p, d) for p, d in INPUT_HASHES.items()]
man_rows += [("code", _rel(p), sha256_file(p)) for p in (HERE / "06_alignment_analysis.py", HERE / "utils" / "rq5_methods.py")]
man_rows += [("output", p, d) for p, d in OUT_HASHES.items()]
man_rows += [("summary", _rel(P / "stage6_alignment_summary.json"), sha256_file(P / "stage6_alignment_summary.json"))]
with open(P / "stage6_alignment_manifest.csv", "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(["role", "relative_path", "size_bytes", "sha256", "produced_by"])
    for role, p, d in man_rows:
        w.writerow([role, p, (ARTICLE / p).stat().st_size, d, "06_alignment_analysis.py" if role != "input" else ""])
log.info(f"Summary  : {_rel(P / 'stage6_alignment_summary.json')}")
log.info(f"Manifest : {_rel(P / 'stage6_alignment_manifest.csv')}")
log.info("STAGE 06 COMPLETE — VALIDATION PASS")
