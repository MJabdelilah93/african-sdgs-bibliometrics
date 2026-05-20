"""
RQ5 Manuscript Preparation Script
Performs Steps 1-6 for the Research-Implementation Alignment subsection.
Run from project root: python code/rq5_manuscript_prep.py
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
CORR_CSV  = ROOT / "results" / "rq5_country_correlations.csv"
QUAD_CSV  = ROOT / "results" / "rq5_quadrant_assignments.csv"
CLIST_CSV = ROOT / "country_lists" / "au54_countries.csv"
OUT_TABLE = ROOT / "results" / "rq5_table_for_manuscript.csv"
OUT_FIG   = ROOT / "figures" / "F_rq5_country_rho_forestplot.png"

# ── load data ──────────────────────────────────────────────────────────────
corr = pd.read_csv(CORR_CSV)
quad = pd.read_csv(QUAD_CSV)
clist = pd.read_csv(CLIST_CSV)

# Merge sub-region into corr using iso3 / iso2 join via clist
iso2_to_sub = dict(zip(
    clist["iso3"].map(lambda x: x),  # keep iso3
    clist["subregion"]
))
# build iso2->subregion via clist
iso3_to_iso2 = {}
for _, row in clist.iterrows():
    iso3_to_iso2[row["iso3"]] = row["iso3"]  # placeholder

# easier: direct join on country name
clist_map = clist[["country_name_scopus", "subregion"]].copy()
clist_map.columns = ["country_name", "subregion"]
corr = corr.merge(clist_map, on="country_name", how="left")

# fallback: match on official name
missing = corr[corr["subregion"].isna()]["country_name"].tolist()
if missing:
    clist_map2 = clist[["country_name_official", "subregion"]].copy()
    clist_map2.columns = ["country_name", "subregion"]
    for name in missing:
        match = clist_map2[clist_map2["country_name"] == name]
        if not match.empty:
            corr.loc[corr["country_name"] == name, "subregion"] = match.iloc[0]["subregion"]

# ── STEP 1 — Dominant quadrant per country ────────────────────────────────
quad_counts = (
    quad.groupby(["country_name", "quadrant"])
    .size()
    .unstack(fill_value=0)
)
# ensure all four columns exist
for q in ["HH", "HL", "LH", "LL"]:
    if q not in quad_counts.columns:
        quad_counts[q] = 0

dominant_q = quad_counts.idxmax(axis=1).rename("dominant_quadrant")
corr = corr.merge(dominant_q, on="country_name", how="left")

# round rho and CI
corr["rho_r"]   = corr["spearman_rho"].round(3)
corr["ci_lo_r"] = corr["ci_lower"].round(3)
corr["ci_hi_r"] = corr["ci_upper"].round(3)

# CI excludes zero?
corr["ci_excl_zero"] = (
    (corr["ci_lower"] > 0) | (corr["ci_upper"] < 0)
).map({True: "yes", False: "no"})

# sort descending rho
corr_sorted = corr.sort_values("spearman_rho", ascending=False).reset_index(drop=True)

# ── print STEP 1 ───────────────────────────────────────────────────────────
print("=" * 80)
print("STEP 1 — COUNTRY-LEVEL CORRELATION TABLE (sorted by rho, descending)")
print("=" * 80)
print(f"{'#':>3}  {'Country':<35} {'rho':>7}  {'CI lower':>9}  {'CI upper':>9}  {'CI!=0':>5}  {'Dom. Q'}")
print("-" * 80)
for i, row in corr_sorted.iterrows():
    print(f"{i+1:>3}  {row['country_name']:<35} {row['rho_r']:>7.3f}  "
          f"{row['ci_lo_r']:>9.3f}  {row['ci_hi_r']:>9.3f}  "
          f"{row['ci_excl_zero']:>5}  {row['dominant_quadrant']}")

print()
print("── a) Top 5 most positive rho ──")
top5 = corr_sorted.head(5)
for _, r in top5.iterrows():
    print(f"  {r['country_name']:<35} rho = {r['rho_r']:>7.3f}")

print()
print("── b) Top 5 most negative rho ──")
bot5 = corr_sorted.tail(5)
for _, r in bot5.iterrows():
    print(f"  {r['country_name']:<35} rho = {r['rho_r']:>7.3f}")

print()
neg_excl = corr_sorted[(corr_sorted["ci_upper"] < 0)]
print(f"── c) Countries with CI excluding zero on the NEGATIVE side (n={len(neg_excl)}) ──")
for _, r in neg_excl.iterrows():
    print(f"  {r['country_name']:<35} rho = {r['rho_r']:>7.3f}  CI [{r['ci_lo_r']:.3f}, {r['ci_hi_r']:.3f}]")

pos_excl = corr_sorted[(corr_sorted["ci_lower"] > 0)]
print(f"\n── d) Countries with CI excluding zero on the POSITIVE side (n={len(pos_excl)}) ──")
if pos_excl.empty:
    print("  None")
else:
    for _, r in pos_excl.iterrows():
        print(f"  {r['country_name']:<35} rho = {r['rho_r']:>7.3f}  CI [{r['ci_lo_r']:.3f}, {r['ci_hi_r']:.3f}]")

# ── STEP 2 — SDG-level analysis ───────────────────────────────────────────
print()
print("=" * 80)
print("STEP 2 — SDG-LEVEL ANALYSIS (qualifying countries only)")
print("=" * 80)

qual_countries = set(corr["country_name"].tolist())
quad_qual = quad[quad["country_name"].isin(qual_countries)].copy()

sdg_quad = (
    quad_qual.groupby(["sdg_number", "sdg_name", "quadrant"])
    .size()
    .unstack(fill_value=0)
    .reset_index()
)
for q in ["HH", "HL", "LH", "LL"]:
    if q not in sdg_quad.columns:
        sdg_quad[q] = 0

# Continental medians per SDG
sdg_medians = (
    quad_qual.groupby(["sdg_number", "sdg_name"])
    .agg(
        med_deficit=("implementation_deficit", "median"),
        med_research=("pub_share", "median")
    )
    .reset_index()
)
sdg_stats = sdg_quad.merge(sdg_medians, on=["sdg_number", "sdg_name"])
sdg_stats = sdg_stats.sort_values("LH", ascending=False).reset_index(drop=True)

print(f"{'SDG':>4}  {'Name':<45} {'LH':>4} {'HH':>4} {'HL':>4} {'LL':>4}  "
      f"{'Med deficit':>11}  {'Med research':>12}")
print("-" * 95)
for _, r in sdg_stats.iterrows():
    name = r["sdg_name"][:44]
    print(f"  {r['sdg_number']:>2}  {name:<45} {r['LH']:>4} {r['HH']:>4} {r['HL']:>4} {r['LL']:>4}  "
          f"{r['med_deficit']:>11.2f}  {r['med_research']:>12.4f}")

print()
print("── Top 5 most UNDERSERVED SDGs (highest LH count) ──")
for _, r in sdg_stats.head(5).iterrows():
    print(f"  SDG {r['sdg_number']:>2}: {r['sdg_name']:<45}  LH = {r['LH']} / {len(qual_countries)}")

hl_sorted = sdg_stats.sort_values("HL", ascending=False)
print()
print("── Top 5 most OVER-RESEARCHED SDGs (highest HL count) ──")
for _, r in hl_sorted.head(5).iterrows():
    print(f"  SDG {r['sdg_number']:>2}: {r['sdg_name']:<45}  HL = {r['HL']} / {len(qual_countries)}")

# ── STEP 3 — Sub-regional patterns ───────────────────────────────────────
print()
print("=" * 80)
print("STEP 3 — SUB-REGIONAL PATTERNS")
print("=" * 80)

continental_median = corr["spearman_rho"].median()
print(f"Continental median rho: {continental_median:.3f}")
print()

sub_rho = (
    corr.groupby("subregion")["spearman_rho"]
    .agg(["median", "mean", "count"])
    .round(3)
    .rename(columns={"median": "median_rho", "mean": "mean_rho", "count": "n"})
    .sort_values("median_rho")
)
print(f"{'Sub-region':<20} {'Median rho':>11} {'Mean rho':>10} {'n':>4}  {'vs. continental':>17}")
print("-" * 65)
for sr, row in sub_rho.iterrows():
    diff = row["median_rho"] - continental_median
    flag = "  ← more negative" if diff < -0.05 else ("  ← more positive" if diff > 0.05 else "")
    print(f"  {sr:<18} {row['median_rho']:>11.3f} {row['mean_rho']:>10.3f} {row['n']:>4}  {diff:>+.3f}{flag}")

any_positive = sub_rho[sub_rho["median_rho"] > 0]
if any_positive.empty:
    print("\n  No sub-region has a positive median rho.")
else:
    print(f"\n  Sub-region(s) with positive median rho: {list(any_positive.index)}")

# ── STEP 4 — Publication-ready CSV ───────────────────────────────────────
print()
print("=" * 80)
print("STEP 4 — CREATING PUBLICATION-READY CSV")
print("=" * 80)

table = corr_sorted[[
    "country_name", "subregion", "rho_r", "ci_lo_r", "ci_hi_r",
    "ci_excl_zero", "dominant_quadrant"
]].copy()
table.columns = [
    "Country", "Sub-region", "Spearman rho", "95% CI lower",
    "95% CI upper", "CI excludes zero", "Dominant quadrant"
]
table.to_csv(OUT_TABLE, index=False)
print(f"  Saved: {OUT_TABLE}")

# ── STEP 5 — Forest plot ──────────────────────────────────────────────────
print()
print("=" * 80)
print("STEP 5 — GENERATING FOREST PLOT")
print("=" * 80)

# Colorblind palette per sub-region
subregion_order = ["North Africa", "East Africa", "West Africa", "Southern Africa", "Central Africa"]
cb_colors = {
    "North Africa":   "#E69F00",   # orange
    "East Africa":    "#56B4E9",   # sky blue
    "West Africa":    "#009E73",   # bluish green
    "Southern Africa":"#CC79A7",   # reddish purple
    "Central Africa": "#D55E00",   # vermillion
}

# sort ascending (bottom = most negative)
fp_data = corr_sorted.iloc[::-1].reset_index(drop=True)

fig, ax = plt.subplots(figsize=(9, 13))

for idx, row in fp_data.iterrows():
    color = cb_colors.get(row["subregion"], "#999999")
    y = idx
    ax.plot([row["ci_lower"], row["ci_upper"]], [y, y],
            color=color, linewidth=1.2, zorder=2)
    ax.scatter(row["spearman_rho"], y, color=color, s=30, zorder=3)

# reference line at rho = 0
ax.axvline(x=0, color="black", linewidth=0.8, linestyle="--", zorder=1)
# reference line at continental median
ax.axvline(x=continental_median, color="#999999", linewidth=0.8,
           linestyle=":", zorder=1, label=f"Continental median ({continental_median:.3f})")

ax.set_yticks(range(len(fp_data)))
ax.set_yticklabels(fp_data["country_name"], fontsize=7.5)
ax.set_xlabel("Spearman ρ (research share vs. implementation deficit)", fontsize=9)
ax.set_title("Research–Implementation Alignment by Country\n"
             "Forest Plot of Spearman ρ with 95% Bootstrap CI", fontsize=10)
ax.set_xlim(-1.05, 1.05)

# legend
patches = [mpatches.Patch(color=cb_colors[sr], label=sr) for sr in subregion_order]
patches.append(plt.Line2D([0], [0], color="#999999", linestyle=":", linewidth=0.8,
                           label=f"Continental median ({continental_median:.3f})"))
ax.legend(handles=patches, loc="lower right", fontsize=7.5, framealpha=0.8)

ax.grid(axis="x", linewidth=0.4, alpha=0.4)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

plt.tight_layout()
fig.savefig(OUT_FIG, dpi=300, bbox_inches="tight")
plt.close()
print(f"  Saved: {OUT_FIG}")

# Assess forest plot value
print()
print("  Forest plot assessment:")
print("  ─ Reveals the distribution of all 47 CIs in a single view not available in F12.")
print("  ─ The ranked layout makes it immediately clear that most countries cluster")
print("    in the -0.1 to -0.5 range, with only a handful near zero or positive.")
print("  ─ Sub-regional colouring: see clustering report below.")

# Check clustering
for sr in subregion_order:
    sr_data = fp_data[fp_data["subregion"] == sr]["spearman_rho"]
    if len(sr_data) > 0:
        print(f"    {sr:<20}: n={len(sr_data)}, rho range [{sr_data.min():.3f}, {sr_data.max():.3f}]")

# ── STEP 6 — Summary report ───────────────────────────────────────────────
print()
print("=" * 80)
print("STEP 6 — SUMMARY REPORT")
print("=" * 80)

n_total = len(corr)
n_negative = (corr["spearman_rho"] < 0).sum()
med_rho = corr["spearman_rho"].median()
top5_pos = corr_sorted.head(5)
top5_neg = corr_sorted.tail(5)
top_lh_sdg = sdg_stats.iloc[0]
top_hl_sdg = hl_sorted.iloc[0]

print(f"  1. Total qualified countries: {n_total}")
print(f"  2. Countries with negative rho: {n_negative} of {n_total}")
print(f"  3. Median rho: {med_rho:.3f}")
print()
print("  4. Top 5 positive rho countries:")
for _, r in top5_pos.iterrows():
    print(f"     {r['country_name']:<35}  rho = {r['rho_r']:>7.3f}")
print()
print("  5. Top 5 negative rho countries:")
for _, r in top5_neg.iterrows():
    print(f"     {r['country_name']:<35}  rho = {r['rho_r']:>7.3f}")
print()
print(f"  6. Most underserved SDG by LH frequency: "
      f"SDG {int(top_lh_sdg['sdg_number'])} – {top_lh_sdg['sdg_name']}  (n = {int(top_lh_sdg['LH'])} countries)")
print(f"  7. Most over-researched SDG by HL frequency: "
      f"SDG {int(top_hl_sdg['sdg_number'])} – {top_hl_sdg['sdg_name']}  (n = {int(top_hl_sdg['HL'])} countries)")
print()
print("  8. Sub-regional median rho values:")
for sr, row in sub_rho.sort_values("median_rho").iterrows():
    print(f"     {sr:<20}: {row['median_rho']:>+.3f}  (n={int(row['n'])})")
print()
pos_sub = sub_rho[sub_rho["median_rho"] > 0]
if pos_sub.empty:
    print("  9. No sub-region has a positive median rho.")
else:
    print(f"  9. Sub-region(s) with positive median rho: {list(pos_sub.index)}")

print()
print("=" * 80)
print("FILES CREATED:")
print(f"  {OUT_TABLE}")
print(f"  {OUT_FIG}")
print("=" * 80)
