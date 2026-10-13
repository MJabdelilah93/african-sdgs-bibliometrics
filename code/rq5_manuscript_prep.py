"""rq5_manuscript_prep.py — RQ5 country table, forest plot and compact sensitivity tables.

Consumes only the promoted Stage 06 outputs (code/06_alignment_analysis.py). ISO3-based joins, no
hard-coded country counts; ordering by rho is for display only; outputs written to .tmp and promoted after
checks; manifest rows appended to provenance/v2/stage6_alignment_manifest.csv.

Run from the repository root:  python code/rq5_manuscript_prep.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ap = argparse.ArgumentParser()
ap.add_argument("--results-dir", type=Path, default=ROOT / "results")
ap.add_argument("--figures-dir", type=Path, default=ROOT / "figures")
ap.add_argument("--prov-dir", type=Path, default=ROOT / "provenance" / "v2")
ap.add_argument("--log", type=Path, default=ROOT / "provenance" / "v2" / "logs" / "rq5_manuscript_prep.log")
A = ap.parse_args()
R, F, P = A.results_dir, A.figures_dir, A.prov_dir
A.log.parent.mkdir(parents=True, exist_ok=True)
LOG = open(A.log, "w", encoding="utf-8")


def say(msg=""):
    print(msg)
    LOG.write(msg + "\n")


PENDING: list[Path] = []


def out(p: Path) -> Path:
    PENDING.append(p)
    return p.with_name(p.name + ".tmp")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


rd = dict(keep_default_na=False, na_values=[""])
corr = pd.read_csv(R / "rq5_country_correlations.csv", **rd)
quad = pd.read_csv(R / "rq5_quadrant_assignments.csv", **rd)
elig = pd.read_csv(R / "rq5_country_eligibility.csv", **rd)
msens = pd.read_csv(R / "rq5_method_sensitivity.csv", **rd)
temporal = pd.read_csv(P / "stage6_temporal_sensitivity.csv", **rd)
esens = pd.read_csv(P / "stage6_eligibility_sensitivity.csv", **rd)
n_elig = int(elig["eligible"].sum())
assert len(corr) == n_elig and set(corr.iso3) == set(elig.loc[elig.eligible, "iso3"]), "correlations != eligible set"
assert set(quad.iso3) == set(corr.iso3), "quadrant population != eligible set"

# ── 1. country table (ISO3 joins only) ─────────────────────────────────────
qc = quad.groupby(["iso3", "quadrant_median"]).size().unstack(fill_value=0).reindex(columns=["HH", "HL", "LH", "LL"], fill_value=0)
table = corr.merge(qc, left_on="iso3", right_index=True, how="left")
table = table.sort_values(["rho", "iso3"], ascending=[False, True]).reset_index(drop=True)   # display order only
table_out = pd.DataFrame({
    "Country": table.country_name, "ISO3": table.iso3, "Sub-region": table.subregion,
    "Paired SDGs (n)": table.n_pairs, "Zero research shares": table.n_zero_research,
    "Spearman rho": table.rho.round(3), "95% CI lower": table.ci_low.round(3), "95% CI upper": table.ci_high.round(3),
    "CI position": table.ci_position.str.replace("_", " "), "Bootstrap valid replicates": table.bootstrap_valid_reps,
    "Pairs HH": table.HH, "Pairs HL": table.HL, "Pairs LH": table.LH, "Pairs LL": table.LL,
})
table_out.to_csv(out(R / "rq5_table_for_manuscript.csv"), index=False, lineterminator="\n")

# ── 2. sub-regional descriptive summary ────────────────────────────────────
sub = corr.groupby("subregion")["rho"].agg(n="count", median_rho="median", q1_rho=lambda s: s.quantile(.25),
                                            q3_rho=lambda s: s.quantile(.75), n_negative=lambda s: int((s < 0).sum())).reset_index()
sub.to_csv(out(R / "rq5_subregion_summary.csv"), index=False, lineterminator="\n", float_format="%.6g")

# ── 3. compact supplementary sensitivity table ─────────────────────────────
rows = []
for _, r in msens.iterrows():
    rows.append({"analysis": f"counting/zero policy: {r.variant}", "n_eligible": r.n_eligible, "median_rho": r.median_rho,
                 "q1_rho": r.q1_rho, "q3_rho": r.q3_rho, "n_negative": r.n_negative, "n_ci_below_zero": r.n_ci_below_zero})
for _, r in temporal[temporal.row_type == "summary"].iterrows():
    rows.append({"analysis": f"window/endpoint: {r.variant}", "n_eligible": r.n_eligible, "median_rho": r.median_rho,
                 "q1_rho": r.q1_rho, "q3_rho": r.q3_rho, "n_negative": r.n_negative, "n_ci_below_zero": r.n_ci_below_zero})
for _, r in esens.iterrows():
    rows.append({"analysis": f"eligibility: research>={r.research_min}, implementation>={r.implementation_min}"
                             + (" (primary)" if str(r.primary_rule) == "True" else ""),
                 "n_eligible": r.n_eligible, "median_rho": r.median_rho, "q1_rho": r.q1_rho, "q3_rho": r.q3_rho,
                 "n_negative": r.n_negative, "n_ci_below_zero": r.n_ci_below_zero})
supp = pd.DataFrame(rows)
supp.to_csv(out(R / "rq5_supplementary_sensitivity_summary.csv"), index=False, lineterminator="\n", float_format="%.6g")

# ── 4. forest plot (sorted by rho for readability only) ────────────────────
COL = {"North Africa": "#E69F00", "East Africa": "#56B4E9", "West Africa": "#009E73",
       "Southern Africa": "#CC79A7", "Central Africa": "#D55E00"}
fp = table.iloc[::-1].reset_index(drop=True)
med = float(corr.rho.median())
fig, ax = plt.subplots(figsize=(8.5, max(6.0, 0.24 * len(fp) + 1.5)))
for i, r in fp.iterrows():
    c = COL.get(r.subregion, "#999999")
    ax.plot([r.ci_low, r.ci_high], [i, i], color=c, linewidth=1.2, zorder=2)
    ax.scatter(r.rho, i, color=c, s=26, zorder=3)
ax.axvline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)
ax.axvline(med, color="#999999", linewidth=0.8, linestyle=":", zorder=1)
ax.set_yticks(range(len(fp)))
ax.set_yticklabels(fp.country_name, fontsize=7.5)
ax.set_xlim(-1.05, 1.05)
ax.set_xlabel("Spearman ρ (research share vs implementation deficit), 95% pair-bootstrap CI", fontsize=9)
handles = [mpatches.Patch(color=v, label=k) for k, v in COL.items() if k in set(fp.subregion)]
handles.append(plt.Line2D([0], [0], color="#999999", linestyle=":", label=f"Median ρ across {len(fp)} countries ({med:.3f})"))
ax.legend(handles=handles, loc="lower right", fontsize=7, framealpha=0.85)
ax.set_ylim(-0.8, len(fp) - 0.2)
fig.text(0.01, 0.005, "Countries ordered by point estimate for display only; overlapping intervals do not support a ranking.",
         fontsize=7, color="#555555", ha="left", va="bottom")
ax.grid(axis="x", linewidth=0.4, alpha=0.4)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
fig.savefig(out(F / "F_rq5_country_rho_forestplot.png"), dpi=300, bbox_inches="tight", format="png")
plt.close(fig)

# ── promote + manifest ─────────────────────────────────────────────────────
for p in PENDING:
    t = p.with_name(p.name + ".tmp")
    assert t.stat().st_size > 0, f"empty {t}"
    t.replace(p)
    say(f"Promoted {p}")
man = P / "stage6_alignment_manifest.csv"
if man.exists():
    with open(man, encoding="utf-8", newline="") as f:
        mrows = [r for r in csv.DictReader(f) if r["produced_by"] != "rq5_manuscript_prep.py"]
    for p in PENDING + [Path(__file__).resolve()]:
        rel = p.resolve().relative_to(ROOT).as_posix() if ROOT in p.resolve().parents else str(p)
        mrows.append({"role": "code" if p.suffix == ".py" else "output", "relative_path": rel,
                      "size_bytes": p.stat().st_size, "sha256": sha(p), "produced_by": "rq5_manuscript_prep.py"})
    with open(man, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["role", "relative_path", "size_bytes", "sha256", "produced_by"], lineterminator="\n")
        w.writeheader()
        w.writerows(mrows)
say(f"Eligible countries: {n_elig}; median rho {med:.4f}; table rows {len(table_out)}")
say("\n" + supp.to_string(index=False))
say("\n" + sub.to_string(index=False))
LOG.close()
