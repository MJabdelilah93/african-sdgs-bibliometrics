"""
RQ5 Research-Implementation Alignment Analysis
Determines whether African countries research the SDGs on which
they perform worst (research-implementation alignment).
Run from: article08/
"""

import sys
import warnings
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy.stats import spearmanr
from matplotlib.lines import Line2D
try:
    from adjustText import adjust_text as _adjust_text
    HAS_ADJUST_TEXT = True
except ImportError:
    HAS_ADJUST_TEXT = False
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.logger import get_logger

warnings.filterwarnings("ignore")

# ── Paths & config ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]

with open(ROOT / "config.yaml") as f:
    CFG = yaml.safe_load(f)

log = get_logger("06_alignment_analysis")

ENRICHED      = ROOT / "data/processed/enriched.csv"
SDG_INDEX     = ROOT / "data/external/sdg_index/sdg_index_2025.xlsx"
AU54_CSV      = ROOT / CFG["paths"]["country_list"]
SDG_NAMES_CSV = ROOT / CFG["paths"]["sdg_names"]
RESULTS       = ROOT / CFG["paths"]["results"]
FIGURES       = ROOT / CFG["paths"]["figures"]
RESULTS.mkdir(exist_ok=True)
FIGURES.mkdir(exist_ok=True)

# ── Hardcoded ISO-2 → ISO-3 for all 54 AU members ────────────────────────────
ISO2_ISO3 = {
    "DZ": "DZA", "AO": "AGO", "BJ": "BEN", "BW": "BWA", "BF": "BFA",
    "BI": "BDI", "CV": "CPV", "CM": "CMR", "CF": "CAF", "TD": "TCD",
    "KM": "COM", "CG": "COG", "CD": "COD", "CI": "CIV", "DJ": "DJI",
    "EG": "EGY", "GQ": "GNQ", "ER": "ERI", "SZ": "SWZ", "ET": "ETH",
    "GA": "GAB", "GM": "GMB", "GH": "GHA", "GN": "GIN", "GW": "GNB",
    "KE": "KEN", "LS": "LSO", "LR": "LBR", "LY": "LBY", "MG": "MDG",
    "MW": "MWI", "ML": "MLI", "MR": "MRT", "MU": "MUS", "MA": "MAR",
    "MZ": "MOZ", "NA": "NAM", "NE": "NER", "NG": "NGA", "RW": "RWA",
    "ST": "STP", "SN": "SEN", "SC": "SYC", "SL": "SLE", "SO": "SOM",
    "ZA": "ZAF", "SS": "SSD", "SD": "SDN", "TZ": "TZA", "TG": "TGO",
    "TN": "TUN", "UG": "UGA", "ZM": "ZMB", "ZW": "ZWE",
}
AU54_ISO2 = set(ISO2_ISO3.keys())

SDG_NAMES = {
    1: "No Poverty", 2: "Zero Hunger", 3: "Good Health",
    4: "Quality Education", 5: "Gender Equality", 6: "Clean Water",
    7: "Clean Energy", 8: "Decent Work", 9: "Industry & Innovation",
    10: "Reduced Inequalities", 11: "Sustainable Cities",
    12: "Responsible Consumption", 13: "Climate Action",
    14: "Life Below Water", 15: "Life on Land",
    16: "Peace & Justice", 17: "Partnerships",
}

NAME_MAP = {
    "Egypt, Arab Rep."          : "Egypt",
    "Gambia, The"               : "Gambia",
    "Congo, Rep."               : "Congo",
    "Congo, Dem. Rep."          : "Democratic Republic of Congo",
    "Cote d’Ivoire"        : "Cote d'Ivoire",   # curly apostrophe
    "Côte d'Ivoire"        : "Cote d'Ivoire",   # ô variant
}

GOAL_COLS = [f"Goal {i} Score" for i in range(1, 18)]

# =============================================================================
# STEP 1 — Load SDG Index
# =============================================================================
log.info("STEP 1 — Loading SDG Index")

au54 = pd.read_csv(AU54_CSV)
# build iso3 → country_name_scopus and iso3 → subregion lookups
iso3_to_name    = dict(zip(au54["iso3"], au54["country_name_scopus"]))
iso3_to_sub     = dict(zip(au54["iso3"], au54["subregion"]))
au54_names      = set(au54["country_name_scopus"])

sdg_names_df    = pd.read_csv(SDG_NAMES_CSV)
SDG_NAMES_FULL  = dict(zip(sdg_names_df["sdg_number"], sdg_names_df["sdg_name"]))

sdr = pd.read_excel(SDG_INDEX, sheet_name="SDR2025 Data", engine="openpyxl")
log.info(f"  SDR raw rows: {len(sdr)}")

# Normalise country names
sdr["Country"] = sdr["Country"].replace(NAME_MAP)

# Filter to AU-54 only
sdr_au = sdr[sdr["Country"].isin(au54_names)].copy()
log.info(f"  AU countries in SDG Index: {len(sdr_au)} of 54")

# Build ISO3 → SDG scores from SDR (use Country Code ISO3 column)
# Also cross-check: join on country_name_scopus → get iso3
name_to_iso3 = {v: k for k, v in iso3_to_name.items()}
sdr_au["iso3"] = sdr_au["Country"].map(name_to_iso3)

# Check available goal columns
missing_goal_cols = [c for c in GOAL_COLS if c not in sdr_au.columns]
if missing_goal_cols:
    log.warning(f"  Missing goal columns: {missing_goal_cols}")
    GOAL_COLS = [c for c in GOAL_COLS if c in sdr_au.columns]

# Compute deficit (100 − score)
deficit_df = sdr_au[["Country", "iso3"] + GOAL_COLS].copy()
for c in GOAL_COLS:
    deficit_df[c.replace("Score", "Deficit")] = 100.0 - deficit_df[c]
DEFICIT_COLS = [c.replace("Score", "Deficit") for c in GOAL_COLS]

# Countries with complete 17-goal scores
n_complete = (deficit_df[GOAL_COLS].notna().sum(axis=1) == 17).sum()
score_min   = sdr_au[GOAL_COLS].min().min()
score_max   = sdr_au[GOAL_COLS].max().max()

log.info(f"  AU countries with complete 17-goal scores: {n_complete}")
log.info(f"  African score range: {score_min:.2f} – {score_max:.2f}")

# iso3 → deficit series dict
deficit_by_iso3 = {}
for _, row in deficit_df.iterrows():
    iso3 = row["iso3"]
    if pd.notna(iso3):
        deficit_by_iso3[iso3] = {
            i + 1: row[DEFICIT_COLS[i]]
            for i in range(len(DEFICIT_COLS))
        }

# =============================================================================
# STEP 2 — Publication shares per country per SDG
# =============================================================================
log.info("STEP 2 — Computing publication shares from enriched.csv")

pub_frac  = defaultdict(lambda: defaultdict(float))   # iso2 → sdg → weight
chunk_n   = 0
total_recs = 0
matched_recs = 0

for chunk in pd.read_csv(
    ENRICHED,
    chunksize=50_000,
    usecols=["match_countries", "sdg_tags", "sdg_tag_count"],
    keep_default_na=False,
    dtype=str,
):
    chunk_n += 1
    total_recs += len(chunk)

    for _, row in chunk.iterrows():
        mc  = str(row["match_countries"]).strip()
        st  = str(row["sdg_tags"]).strip()
        cnt = str(row["sdg_tag_count"]).strip()

        if not mc or not st or not cnt:
            continue
        try:
            n_sdgs = int(cnt)
        except ValueError:
            continue
        if n_sdgs == 0:
            continue

        # Parse AU-54 countries in this record
        iso2_list = [c.strip() for c in mc.split(";") if c.strip() in AU54_ISO2]
        if not iso2_list:
            continue

        # Parse SDG tags
        sdg_list = []
        for s in st.split(","):
            s = s.strip()
            if s.isdigit():
                sdg_no = int(s)
                if 1 <= sdg_no <= 17:
                    sdg_list.append(sdg_no)
        if not sdg_list:
            continue

        weight = 1.0 / n_sdgs
        matched_recs += 1

        for iso2 in iso2_list:
            for sdg_no in sdg_list:
                pub_frac[iso2][sdg_no] += weight

    if chunk_n % 4 == 0:
        log.info(f"  Chunk {chunk_n}: {total_recs:,} records processed")

log.info(f"  Total records: {total_recs:,}  |  AU-matched: {matched_recs:,}")

# Normalise to publication share per country
pub_share   = {}
total_fracs = {}
for iso2, sdg_dict in pub_frac.items():
    total = sum(sdg_dict.values())
    total_fracs[iso2] = total
    pub_share[iso2] = {sdg: w / total for sdg, w in sdg_dict.items()}

log.info(f"  Countries with publications: {len(pub_share)}")

# =============================================================================
# STEP 3 — Inclusion criteria
# =============================================================================
log.info("STEP 3 — Applying inclusion criteria")

inclusion_rows = []
for iso2, iso3 in ISO2_ISO3.items():
    name    = iso3_to_name.get(iso3, iso3)
    ps_dict = pub_share.get(iso2, {})
    n_sdgs_pub  = sum(1 for v in ps_dict.values() if v > 0)
    scores_avail = sum(
        1 for i in range(1, 18)
        if pd.notna(deficit_by_iso3.get(iso3, {}).get(i, np.nan))
    )
    total_p = total_fracs.get(iso2, 0.0)

    qualifies = (n_sdgs_pub >= 10) and (scores_avail >= 14)
    reason    = ""
    if n_sdgs_pub < 10:
        reason = f"only {n_sdgs_pub} SDGs with publications"
    elif scores_avail < 14:
        reason = f"only {scores_avail} SDG Index scores available"

    inclusion_rows.append({
        "country_name"        : name,
        "iso2"                : iso2,
        "iso3"                : iso3,
        "total_frac_pubs"     : round(total_p, 4),
        "sdgs_with_pubs"      : n_sdgs_pub,
        "sdg_scores_available": scores_avail,
        "qualifies"           : qualifies,
        "exclusion_reason"    : reason,
    })

inc_df = pd.DataFrame(inclusion_rows).sort_values(
    ["qualifies", "total_frac_pubs"], ascending=[False, False]
)
inc_df.to_csv(RESULTS / "rq5_inclusion_table.csv", index=False)

qualified = inc_df[inc_df["qualifies"]].copy()
log.info(f"  Qualified countries: {len(qualified)} of 54")
log.info(f"  Excluded: {len(inc_df) - len(qualified)}")

# =============================================================================
# STEP 4 — Spearman correlation per country
# =============================================================================
log.info("STEP 4 — Computing Spearman correlations")

corr_rows   = []
rng         = np.random.default_rng(42)

for _, row in qualified.iterrows():
    iso2 = row["iso2"]
    iso3 = row["iso3"]
    name = row["country_name"]

    ps_dict  = pub_share.get(iso2, {})
    def_dict = deficit_by_iso3.get(iso3, {})

    # Build paired vectors, drop NaN
    pairs = []
    for sdg in range(1, 18):
        ps  = ps_dict.get(sdg, np.nan)
        dft = def_dict.get(sdg, np.nan)
        if pd.notna(ps) and pd.notna(dft) and ps > 0:
            pairs.append((ps, dft))

    if len(pairs) < 10:
        corr_rows.append({
            "country_name"  : name, "iso2": iso2,
            "spearman_rho"  : np.nan, "p_value": np.nan,
            "ci_lower"      : np.nan, "ci_upper": np.nan,
            "n_sdgs_used"   : len(pairs), "interpretation": "excluded",
            "note"          : f"only {len(pairs)} valid pairs",
        })
        continue

    ps_vec  = np.array([p[0] for p in pairs])
    dft_vec = np.array([p[1] for p in pairs])

    rho, pval = spearmanr(ps_vec, dft_vec)

    # Bootstrap 95% CI
    boot_rhos = []
    n = len(pairs)
    for _ in range(1_000):
        idx = rng.integers(0, n, size=n)
        if len(set(idx)) < 3:
            continue
        r, _ = spearmanr(ps_vec[idx], dft_vec[idx])
        if not np.isnan(r):
            boot_rhos.append(r)
    ci_lo = float(np.percentile(boot_rhos, 2.5))  if boot_rhos else np.nan
    ci_hi = float(np.percentile(boot_rhos, 97.5)) if boot_rhos else np.nan

    if rho > 0.3 and ci_lo > 0:
        interp = "Aligned"
    elif rho < -0.3 and ci_hi < 0:
        interp = "Misaligned"
    else:
        interp = "Neutral"

    corr_rows.append({
        "country_name"  : name, "iso2": iso2,
        "spearman_rho"  : round(rho,  4),
        "p_value"       : round(pval, 6),
        "ci_lower"      : round(ci_lo, 4),
        "ci_upper"      : round(ci_hi, 4),
        "n_sdgs_used"   : len(pairs),
        "interpretation": interp,
        "note"          : "",
    })

corr_df = pd.DataFrame(corr_rows)
corr_df.to_csv(RESULTS / "rq5_country_correlations.csv", index=False)
log.info(f"  Correlations written: {len(corr_df)} rows")

# =============================================================================
# STEP 5 — Quadrant assignment
# =============================================================================
log.info("STEP 5 — Assigning quadrants")

quad_rows = []
for iso2, iso3 in ISO2_ISO3.items():
    name    = iso3_to_name.get(iso3, iso3)
    ps_dict = pub_share.get(iso2, {})
    def_dict = deficit_by_iso3.get(iso3, {})
    for sdg in range(1, 18):
        ps  = ps_dict.get(sdg, np.nan)
        dft = def_dict.get(sdg, np.nan)
        if pd.notna(ps) and pd.notna(dft):
            quad_rows.append({
                "country_name"          : name,
                "iso2"                  : iso2,
                "iso3"                  : iso3,
                "sdg_number"            : sdg,
                "sdg_name"              : SDG_NAMES_FULL.get(sdg, f"SDG{sdg}"),
                "pub_share"             : ps,
                "implementation_deficit": dft,
                "quadrant"              : None,
            })

quad_df = pd.DataFrame(quad_rows)

# Continental medians per SDG
pub_med = quad_df.groupby("sdg_number")["pub_share"].median()
def_med = quad_df.groupby("sdg_number")["implementation_deficit"].median()

def assign_quadrant(row):
    pm = pub_med[row["sdg_number"]]
    dm = def_med[row["sdg_number"]]
    hi_pub = row["pub_share"]             >= pm
    hi_def = row["implementation_deficit"] >= dm
    if hi_pub and hi_def:   return "HH"
    if hi_pub and not hi_def: return "HL"
    if not hi_pub and hi_def: return "LH"
    return "LL"

quad_df["quadrant"] = quad_df.apply(assign_quadrant, axis=1)
quad_df.to_csv(RESULTS / "rq5_quadrant_assignments.csv", index=False)

# ── Sensitivity: tertiles ────────────────────────────────────────────────────
def tertile_quad(row):
    pm = quad_df.groupby("sdg_number")["pub_share"].quantile(0.667)[row["sdg_number"]]
    dm = quad_df.groupby("sdg_number")["implementation_deficit"].quantile(0.667)[row["sdg_number"]]
    hi_pub = row["pub_share"]             >= pm
    hi_def = row["implementation_deficit"] >= dm
    if hi_pub and hi_def:    return "HH"
    if hi_pub and not hi_def: return "HL"
    if not hi_pub and hi_def: return "LH"
    return "LL"

quad_df_t = quad_df.copy()
quad_df_t["quadrant"] = quad_df_t.apply(tertile_quad, axis=1)
quad_df_t.to_csv(RESULTS / "rq5_sensitivity_tertiles.csv", index=False)

# ── Sensitivity: absolute thresholds ────────────────────────────────────────
def abs_quad(row):
    hi_pub = row["pub_share"]             >= 0.08
    hi_def = row["implementation_deficit"] >= 50
    if hi_pub and hi_def:    return "HH"
    if hi_pub and not hi_def: return "HL"
    if not hi_pub and hi_def: return "LH"
    return "LL"

quad_df_a = quad_df.copy()
quad_df_a["quadrant"] = quad_df_a.apply(abs_quad, axis=1)
quad_df_a.to_csv(RESULTS / "rq5_sensitivity_absolute.csv", index=False)
log.info(f"  Quadrant rows: {len(quad_df)}")

# =============================================================================
# STEP 6 — Figure F12: Alignment Quadrant Plot
# =============================================================================
log.info("STEP 6 — Drawing Figure F12")

QUAD_COLOURS = {
    "HH": "#2A6F7F",
    "LH": "#C0392B",
    "HL": "#888888",
    "LL": "#CCCCCC",
}

fig, ax = plt.subplots(figsize=(10, 8), dpi=300)
ax.set_facecolor("white")
fig.patch.set_facecolor("white")

# Plot points
for quad, grp in quad_df.groupby("quadrant"):
    ax.scatter(
        grp["implementation_deficit"],
        grp["pub_share"],
        c=QUAD_COLOURS[quad],
        s=20, alpha=0.6, linewidths=0, zorder=3,
    )

# Median threshold lines
overall_pub_med = quad_df["pub_share"].median()
overall_def_med = quad_df["implementation_deficit"].median()
ax.axvline(overall_def_med, color="#888888", linestyle="--", linewidth=0.8, zorder=2)
ax.axhline(overall_pub_med, color="#888888", linestyle="--", linewidth=0.8, zorder=2)

# Quadrant labels
x_lo = quad_df["implementation_deficit"].min()
x_hi = quad_df["implementation_deficit"].max()
y_lo = quad_df["pub_share"].min()
y_hi = quad_df["pub_share"].max()
xr   = x_hi - x_lo
yr   = y_hi - y_lo

quad_labels = {
    "HH": (x_hi - 0.04 * xr, y_hi - 0.04 * yr, "HH", "right", "top"),
    "HL": (x_lo + 0.04 * xr, y_hi - 0.04 * yr, "HL", "left",  "top"),
    "LH": (x_hi - 0.04 * xr, y_lo + 0.04 * yr, "LH", "right", "bottom"),
    "LL": (x_lo + 0.04 * xr, y_lo + 0.04 * yr, "LL", "left",  "bottom"),
}
for _q, (qx, qy, qlbl, ha, va) in quad_labels.items():
    ax.text(qx, qy, qlbl, ha=ha, va=va, fontsize=10,
            color="#999999", style="italic", zorder=1)

# Identify 5 most extreme LH points
lh = quad_df[quad_df["quadrant"] == "LH"].copy()
lh["extremity"] = (
    lh["implementation_deficit"] / lh["implementation_deficit"].max()
    - lh["pub_share"] / (lh["pub_share"].max() + 1e-9)
)
top5_lh = lh.nlargest(5, "extremity")

# Per-point highlight colours, keyed as "{country_name}_{sdg_number}"
HIGHLIGHT_COLORS = {
    "South Sudan_9": "#E67E22",   # Orange
    "South Sudan_1": "#8E44AD",   # Purple
    "South Sudan_7": "#F1C40F",   # Yellow
    "Madagascar_1":  "#27AE60",   # Green
    "Niger_4":       "#DC143C",   # Crimson
}

HIGHLIGHT_ITEMS = [
    ("South Sudan", "Industry, Innovation and Infrastructure", "#E67E22"),
    ("South Sudan", "No Poverty",                             "#8E44AD"),
    ("South Sudan", "Affordable and Clean Energy",            "#F1C40F"),
    ("Madagascar",  "No Poverty",                             "#27AE60"),
    ("Niger",       "Quality Education",                      "#DC143C"),
]

# Overlay highlighted points (no text annotations)
lh_label_positions = []
for _, pt in top5_lh.iterrows():
    key   = f"{pt['country_name']}_{pt['sdg_number']}"
    color = HIGHLIGHT_COLORS.get(key, "#C0392B")
    ax.scatter(
        pt["implementation_deficit"], pt["pub_share"],
        c=color, s=60, alpha=1.0, zorder=5,
        edgecolors="black", linewidths=0.5,
    )
    lh_label_positions.append(
        (pt["country_name"], pt["sdg_name"],
         pt["implementation_deficit"], pt["pub_share"], color)
    )

# Legend 1 — quadrant colours
legend_patches = [
    mpatches.Patch(color=QUAD_COLOURS["HH"], label="HH: high research, high deficit"),
    mpatches.Patch(color=QUAD_COLOURS["LH"], label="LH: low research, high deficit"),
    mpatches.Patch(color=QUAD_COLOURS["HL"], label="HL: high research, low deficit"),
    mpatches.Patch(color=QUAD_COLOURS["LL"], label="LL: low research, low deficit"),
]
legend1 = ax.legend(
    handles=legend_patches,
    loc="upper left",
    bbox_to_anchor=(0.01, 0.99),
    framealpha=0.9,
    edgecolor="#CCCCCC",
    fontsize=9,
    title_fontsize=9,
)
ax.add_artist(legend1)

# Measure legend1 height to place legend2 directly below it
fig.canvas.draw()
renderer   = fig.canvas.get_renderer()
bbox       = legend1.get_window_extent(renderer=renderer)
bbox_axes  = bbox.transformed(ax.transAxes.inverted())
legend2_y  = bbox_axes.y0 - 0.01   # 1% gap below legend1

# Legend 2 — highlighted extreme LH points
highlight_handles = [
    Line2D([0], [0], marker="o", color="w",
           markerfacecolor=color, markersize=9,
           markeredgecolor="black", markeredgewidth=0.5,
           label=f"{country} — {sdg_name}")
    for country, sdg_name, color in HIGHLIGHT_ITEMS
]
legend2 = ax.legend(
    handles=highlight_handles,
    title="Most Underserved: LH quadrant",
    title_fontsize=9,
    loc="upper left",
    bbox_to_anchor=(0.01, legend2_y),
    fontsize=9,
    framealpha=0.9,
    edgecolor="#CCCCCC",
    handletextpad=0.5,
    borderpad=0.5,
)

# Annotation box
n_qual = len(corr_df[corr_df["interpretation"] != "excluded"])
ax.text(
    0.99, 0.01,
    f"Thresholds: continental medians\nn = {n_qual} qualified countries\n"
    f"Bootstrap 95% CIs in rq5_country_correlations.csv",
    transform=ax.transAxes, ha="right", va="bottom",
    fontsize=8, color="#888888",
)

ax.set_xlabel("Implementation Deficit  (100 − SDG Index Score)", fontsize=11, fontweight="normal")
ax.set_ylabel("Research Share  (fraction of country SDG output)", fontsize=11, fontweight="normal")
ax.set_title("")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.tick_params(labelsize=9)

plt.tight_layout(rect=[0, 0, 1, 1])
png_path = FIGURES / "F12_alignment_quadrant.png"
svg_path = FIGURES / "F12_alignment_quadrant.svg"
fig.savefig(png_path, dpi=300, bbox_inches="tight")
fig.savefig(svg_path, format="svg", bbox_inches="tight")
plt.close(fig)
log.info(f"  Saved PNG: {png_path.stat().st_size:,} bytes")
log.info(f"  Saved SVG: {svg_path.stat().st_size:,} bytes")

# =============================================================================
# STEP 7 — Report
# =============================================================================
log.info("=" * 65)
log.info("STEP 7 — FINAL REPORT")
log.info("=" * 65)

# A — SDG Index coverage
n_full     = (deficit_df[GOAL_COLS].notna().sum(axis=1) == 17).sum()
n_partial  = ((deficit_df[GOAL_COLS].notna().sum(axis=1) > 0) &
              (deficit_df[GOAL_COLS].notna().sum(axis=1) < 17)).sum()
n_exc_sdr  = 54 - len(sdr_au)
log.info("\n--- A. SDG Index coverage ---")
log.info(f"  AU countries in SDG Index       : {len(sdr_au)} of 54")
log.info(f"  With complete 17-goal scores    : {n_full}")
log.info(f"  With partial scores             : {n_partial}")
log.info(f"  Not in SDG Index (no data)      : {n_exc_sdr}")

# B — Publication share coverage
pubs_all17 = sum(1 for iso2 in AU54_ISO2 if
                 sum(1 for v in pub_share.get(iso2,{}).values() if v>0) == 17)
pubs_10_16 = sum(1 for iso2 in AU54_ISO2 if
                 10 <= sum(1 for v in pub_share.get(iso2,{}).values() if v>0) <= 16)
pubs_lt10  = sum(1 for iso2 in AU54_ISO2 if
                 sum(1 for v in pub_share.get(iso2,{}).values() if v>0) < 10)
log.info("\n--- B. Publication share coverage ---")
log.info(f"  Countries with pubs in all 17 SDGs : {pubs_all17}")
log.info(f"  Countries with pubs in 10–16 SDGs  : {pubs_10_16}")
log.info(f"  Countries with pubs in <10 SDGs    : {pubs_lt10}")

# C — Inclusion
excl_df = inc_df[~inc_df["qualifies"]]
log.info("\n--- C. Inclusion/exclusion ---")
log.info(f"  Qualified for Spearman : {len(qualified)}")
log.info(f"  Excluded               : {len(excl_df)}")
for _, er in excl_df.iterrows():
    log.info(f"    {er['country_name']:<35} {er['exclusion_reason']}")

# D — Spearman results
valid_corr = corr_df[corr_df["interpretation"] != "excluded"].copy()
if len(valid_corr) > 0:
    med_rho  = valid_corr["spearman_rho"].median()
    n_pos    = (valid_corr["spearman_rho"] > 0).sum()
    n_neg    = (valid_corr["spearman_rho"] < 0).sum()
    n_ci_ex  = ((valid_corr["ci_lower"] > 0) | (valid_corr["ci_upper"] < 0)).sum()
    top5_hi  = valid_corr.nlargest(5, "spearman_rho")[["country_name","spearman_rho","interpretation"]]
    top5_lo  = valid_corr.nsmallest(5, "spearman_rho")[["country_name","spearman_rho","interpretation"]]
    log.info("\n--- D. Spearman results ---")
    log.info(f"  Median rho across qualified countries: {med_rho:.4f}")
    log.info(f"  Countries with positive rho           : {n_pos}")
    log.info(f"  Countries with negative rho           : {n_neg}")
    log.info(f"  Countries with CI excluding zero      : {n_ci_ex}")
    log.info("  Top 5 highest rho (most aligned):")
    for _, r in top5_hi.iterrows():
        log.info(f"    {r['country_name']:<35} rho={r['spearman_rho']:+.4f}  {r['interpretation']}")
    log.info("  Top 5 lowest rho (most misaligned):")
    for _, r in top5_lo.iterrows():
        log.info(f"    {r['country_name']:<35} rho={r['spearman_rho']:+.4f}  {r['interpretation']}")

# E — Quadrant summary
quad_counts = quad_df["quadrant"].value_counts()
n_total_q   = len(quad_df)
log.info("\n--- E. Quadrant summary ---")
for q in ["HH", "HL", "LH", "LL"]:
    n = quad_counts.get(q, 0)
    log.info(f"  {q}: {n:>5} pairs ({100*n/n_total_q:.1f}%)")

# Most neglected SDG (high deficit, low research)
lh_sdg = quad_df[quad_df["quadrant"] == "LH"].groupby("sdg_number").agg(
    med_def  =("implementation_deficit", "median"),
    med_ps   =("pub_share", "median"),
    n_countries=("country_name", "count"),
).reset_index()
if len(lh_sdg) > 0:
    lh_sdg["neglect_score"] = lh_sdg["med_def"] - lh_sdg["med_ps"] * 1000
    worst_sdg = lh_sdg.loc[lh_sdg["neglect_score"].idxmax()]
    log.info(f"  Most neglected SDG  : SDG{int(worst_sdg['sdg_number'])} — "
             f"{SDG_NAMES_FULL.get(int(worst_sdg['sdg_number']),'?')} "
             f"(med deficit={worst_sdg['med_def']:.1f}, n={int(worst_sdg['n_countries'])} countries)")

hl_sdg = quad_df[quad_df["quadrant"] == "HL"].groupby("sdg_number").agg(
    n_countries=("country_name", "count")
).reset_index()
if len(hl_sdg) > 0:
    over_sdg = hl_sdg.loc[hl_sdg["n_countries"].idxmax()]
    log.info(f"  Most over-researched: SDG{int(over_sdg['sdg_number'])} — "
             f"{SDG_NAMES_FULL.get(int(over_sdg['sdg_number']),'?')} "
             f"(n={int(over_sdg['n_countries'])} countries)")

# F — Figure confirmation
log.info("\n--- F. Figure F12 ---")
log.info(f"  PNG: {png_path}  ({png_path.stat().st_size:,} bytes)")
log.info(f"  SVG: {svg_path}  ({svg_path.stat().st_size:,} bytes)")
log.info(f"  Points plotted  : {len(quad_df)}")
log.info(f"  Highlighted extreme LH points: {len(lh_label_positions)}")
for country, sdg_name, def_val, ps_val, color in lh_label_positions:
    log.info(f"    {country:<15} {sdg_name:<42} deficit={def_val:.1f}  ps={ps_val:.4f}  {color}")

log.info("=" * 65)
log.info("STAGE 6 COMPLETE")
log.info("=" * 65)
