"""06_render_F12_F13.py — render-only production export of Figures 12 and 13.

Reads only Stage 06 outputs and recomputes nothing:
  Figure 12: figures/F12_alignment_quadrant_data.csv (832 country-SDG pairs, SDG-specific medians,
             median quadrant per pair), as drawn by code/06_alignment_analysis.py STEP 11.
  Figure 13: results/rq5_country_correlations.csv (rho, bootstrap CI, subregion per country), in the
             display order of code/rq5_manuscript_prep.py (rho descending, ISO3; top = highest rho).
The scientific encoding follows Stage 06 (same points, colours, median lines, CI bars, zero/median
reference); this script sets the production page size, grid, typography, legend placement and export.
Before writing anything the invariants are checked against the Stage 06 results (quadrant assignments and
totals, thresholds, counts, order, rho/CI), and the source hashes are checked again after export. Outputs
are written as .tmp and promoted only after every check passes.
Record: provenance/v2/stage6_F12_F13_render.json; output rows updated in
provenance/v2/stage6_alignment_manifest.csv.

Run from the repository root:  python code/06_render_F12_F13.py
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.lines as mlines  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
from utils import rq5_methods as M  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MM = 1 / 25.4
F12_DATA = ROOT / "figures/F12_alignment_quadrant_data.csv"
CORR = ROOT / "results/rq5_country_correlations.csv"
QUAD = ROOT / "results/rq5_quadrant_assignments.csv"
SUMMARY = ROOT / "provenance/v2/stage6_alignment_summary.json"
TABLE = ROOT / "results/rq5_table_for_manuscript.csv"
SDG_NAMES = ROOT / "country_lists/sdg_names.csv"
MANIFEST = ROOT / "provenance/v2/stage6_alignment_manifest.csv"
RECORD = ROOT / "provenance/v2/stage6_F12_F13_render.json"
F12_PNG, F12_SVG = ROOT / "figures/F12_alignment_quadrant.png", ROOT / "figures/F12_alignment_quadrant.svg"
F13_PNG, F13_SVG = ROOT / "figures/F_rq5_country_rho_forestplot.png", ROOT / "figures/F_rq5_country_rho_forestplot.svg"
SOURCES = [F12_DATA, CORR, QUAD, SUMMARY, TABLE, SDG_NAMES]

F12_SIZE_MM = (180, 195)
F13_SIZE_MM = (178, 190)
QCOL = {"HH": "#2A6F7F", "LH": "#C0392B", "HL": "#888888", "LL": "#CCCCCC"}       # as in Stage 06 STEP 11
SUBCOL = {"North Africa": "#E69F00", "East Africa": "#56B4E9", "West Africa": "#009E73",
          "Southern Africa": "#CC79A7", "Central Africa": "#D55E00"}               # as in rq5_manuscript_prep


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fail(msg: str):
    sys.exit(f"INVARIANCE FAILURE — nothing promoted: {msg}")


src_before = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in SOURCES}
rd = dict(keep_default_na=False, na_values=[""])
f12 = pd.read_csv(F12_DATA, **rd)
corr = pd.read_csv(CORR, **rd)
quad = pd.read_csv(QUAD, **rd)
summ = json.load(open(SUMMARY, encoding="utf-8"))
table = pd.read_csv(TABLE, **rd)
sdg_names = pd.read_csv(SDG_NAMES)
SDG_NAME = dict(zip(sdg_names.sdg_number.astype(int), sdg_names.sdg_name))

# ── invariants (Figure 12) ──────────────────────────────────────────────────
checks = {}
checks["F12 rows == 832"] = len(f12) == 832
checks["F12 countries == 50"] = f12.iso3.nunique() == 50
checks["F12 SDGs == 17"] = sorted(f12.sdg_number.unique()) == list(range(1, 18))
key = ["iso3", "sdg_number"]
mq = f12.merge(quad, on=key, suffixes=("", "_q"), validate="one_to_one")
checks["F12 rows == quadrant assignments (1:1)"] = len(mq) == len(quad) == 832
checks["F12 quadrant per row == rq5_quadrant_assignments"] = bool((mq.quadrant_median == mq.quadrant_median_q).all())
checks["F12 research shares == assignments"] = bool(np.array_equal(mq.research_share.values, mq.research_share_q.values))
checks["F12 deficits == assignments"] = bool(np.array_equal(mq.implementation_deficit.values, mq.implementation_deficit_q.values))
checks["F12 median thresholds == assignments"] = bool(np.array_equal(mq.median_research_share.values, mq.median_research_share_q.values)
                                                      and np.array_equal(mq.median_deficit.values, mq.median_deficit_q.values))
reclass = [M.classify_quadrant(r, d, rt, dt) for r, d, rt, dt in
           zip(f12.research_share, f12.implementation_deficit, f12.median_research_share, f12.median_deficit)]
checks["F12 quadrant re-derivable from stored values/thresholds"] = reclass == list(f12.quadrant_median)
tot = f12.quadrant_median.value_counts().to_dict()
checks["F12 totals 222/195/195/220 == summary"] = (tot == summ["quadrants"]["totals"]["median"]
                                                   == {"HH": 222, "HL": 195, "LH": 195, "LL": 220})
checks["F12 SDG names == config"] = all(SDG_NAME[int(g)] == n for g, n in zip(f12.sdg_number, f12.sdg_name))
# ── invariants (Figure 13) ──────────────────────────────────────────────────
fp_table = corr.sort_values(["rho", "iso3"], ascending=[False, True]).reset_index(drop=True)
checks["F13 countries == 50"] = len(fp_table) == 50 and fp_table.iso3.nunique() == 50
checks["F13 order == rq5_table_for_manuscript (display order)"] = list(fp_table.iso3) == list(table.ISO3)
checks["F13 rho/CI == manuscript table (3 dp)"] = bool(
    np.allclose(fp_table.rho.round(3), table["Spearman rho"]) and np.allclose(fp_table.ci_low.round(3), table["95% CI lower"])
    and np.allclose(fp_table.ci_high.round(3), table["95% CI upper"]))
checks["F13 subregion == manuscript table"] = list(fp_table.subregion) == list(table["Sub-region"])
med = float(corr.rho.median())
checks["F13 median rho == Stage 06 summary"] = med == summ["primary"]["median_rho"]
checks["F13 subregions within colour map"] = set(fp_table.subregion) <= set(SUBCOL)
for k, v in checks.items():
    print(f"  [{'PASS' if v else 'FAIL'}] {k}")
if not all(checks.values()):
    fail("; ".join(k for k, v in checks.items() if not v))

plt.rcParams.update({"svg.hashsalt": "rq5-alignment", "svg.fonttype": "none", "font.family": "Arial"})


def save(fig, png: Path, svg: Path):
    tmp_png, tmp_svg = png.with_name(png.name + ".tmp"), svg.with_name(svg.name + ".tmp")
    fig.savefig(tmp_png, dpi=600, format="png", facecolor="white")
    fig.savefig(tmp_svg, format="svg", facecolor="white", metadata={"Date": None})
    plt.close(fig)
    return tmp_png, tmp_svg


# ── Figure 12: 4 columns x 5 rows, final-size typography ────────────────────
W12, H12 = F12_SIZE_MM
# explicit grid in mm: left (y title + ticks), right, bottom (ticks + x title), top (first-row titles),
# horizontal gap (next panel's tick labels), vertical gap (titles of up to 3 lines + tick labels)
L, R, B, T, GX, GY = 13.5, 3.0, 11.0, 8.5, 10.0, 14.5
PW, PH = (W12 - L - R - 3 * GX) / 4, (H12 - B - T - 4 * GY) / 5
fig = plt.figure(figsize=(W12 * MM, H12 * MM))
axes = []
for row in range(5):
    for col in range(4):
        x0, y0 = L + col * (PW + GX), H12 - T - (row + 1) * PH - row * GY
        axes.append(fig.add_axes((x0 / W12, y0 / H12, PW / W12, PH / H12)))
for k, g in enumerate(range(1, 18)):
    ax = axes[k]
    sub = f12[f12.sdg_number == g]
    for q, grp in sub.groupby("quadrant_median"):
        ax.scatter(grp.implementation_deficit, grp.research_share, c=QCOL[q], s=9, alpha=0.85, linewidths=0, zorder=3)
    ax.axvline(sub.median_deficit.iloc[0], color="#555555", linestyle="--", linewidth=0.6, zorder=2)
    ax.axhline(sub.median_research_share.iloc[0], color="#555555", linestyle="--", linewidth=0.6, zorder=2)
    ax.set_title(textwrap.fill(f"SDG {g}: {SDG_NAME[g]}", 20), fontsize=8.5, pad=3, linespacing=1.05)
    ax.tick_params(labelsize=7.5, length=2.5, pad=1.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
for ax in axes[17:]:
    ax.remove()
handles = [mpatches.Patch(color=QCOL[q], label=f"{q}: {M.QUADRANT_NAMES[q]}") for q in ("HH", "HL", "LH", "LL")]
handles.append(mlines.Line2D([], [], color="#555555", linestyle="--", linewidth=0.8, label="SDG-specific median"))
leg_x = (L + 1 * (PW + GX) + (L + 4 * PW + 3 * GX)) / 2 / W12          # centre of the three empty bottom cells
leg_y = (B + PH / 2) / H12
fig.legend(handles=handles, loc="center", bbox_to_anchor=(leg_x, leg_y), fontsize=8.5, frameon=False, ncol=1,
           handlelength=1.4, handletextpad=0.6, labelspacing=0.55, borderaxespad=0)
fig.text((L + (4 * PW + 3 * GX) / 2) / W12, 2.0 / H12, "Implementation deficit (100 − SDG Index 2025 goal score)",
         fontsize=9.5, ha="center", va="bottom")
fig.text(1.5 / W12, (B + (H12 - B - T) / 2) / H12,
         "Research share (country-fractional; share of the country's SDG research output)",
         fontsize=9.5, ha="left", va="center", rotation=90)
f12_tmp = save(fig, F12_PNG, F12_SVG)

# ── Figure 13: compact forest plot, same order/encoding ─────────────────────
fp = fp_table.iloc[::-1].reset_index(drop=True)       # bottom -> top, as rq5_manuscript_prep.py
fig, ax = plt.subplots(figsize=(F13_SIZE_MM[0] * MM, F13_SIZE_MM[1] * MM))
for i, r in fp.iterrows():
    c = SUBCOL[r.subregion]
    ax.plot([r.ci_low, r.ci_high], [i, i], color=c, linewidth=1.0, solid_capstyle="butt", zorder=2)
    ax.scatter(r.rho, i, color=c, s=13, zorder=3, linewidths=0)
ax.axvline(0, color="black", linewidth=0.7, linestyle="--", zorder=1)
ax.axvline(med, color="#999999", linewidth=0.8, linestyle=":", zorder=1)
ax.set_yticks(range(len(fp)))
ax.set_yticklabels(fp.country_name, fontsize=7.5)
ax.tick_params(axis="y", length=0, pad=2)
ax.tick_params(axis="x", labelsize=8)
ax.set_xlim(-1.05, 1.05)
ax.set_ylim(-0.7, len(fp) - 0.3)
ax.set_xlabel("Spearman ρ (research share vs implementation deficit), 95% pair-bootstrap CI", fontsize=8.5, labelpad=2)
h = [mpatches.Patch(color=v, label=k) for k, v in SUBCOL.items() if k in set(fp.subregion)]
h.append(mlines.Line2D([0], [0], color="#999999", linestyle=":", label=f"Median ρ across {len(fp)} countries ({med:.3f})"))
ax.legend(handles=h, loc="lower right", fontsize=7.5, framealpha=0.9, borderpad=0.4, labelspacing=0.3, handlelength=1.3)
ax.grid(axis="x", linewidth=0.4, alpha=0.4)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.text(0.005, 0.003, "Countries ordered by point estimate for display only; overlapping intervals do not support a ranking.",
         fontsize=7, color="#555555", ha="left", va="bottom")
fig.tight_layout(pad=0.3, rect=(0, 0.018, 1, 1))
f13_tmp = save(fig, F13_PNG, F13_SVG)

# ── post-export checks, promotion, provenance ───────────────────────────────
src_after = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in SOURCES}
if src_after != src_before:
    fail("a source file changed during rendering")
old = {}                                               # committed (HEAD) versions, recorded for reference
for p in (F12_PNG, F13_PNG):
    rel = str(p.relative_to(ROOT)).replace("\\", "/")
    blob = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True).stdout
    if blob:
        with Image.open(io.BytesIO(blob)) as im:
            old[rel] = {"px": list(im.size), "dpi": [round(float(x)) for x in im.info.get("dpi", (0, 0))],
                        "sha256": hashlib.sha256(blob).hexdigest()}
for t in (*f12_tmp, *f13_tmp):
    if t.stat().st_size == 0:
        fail(f"empty output {t}")
for t, final in zip((*f12_tmp, *f13_tmp), (F12_PNG, F12_SVG, F13_PNG, F13_SVG)):
    t.replace(final)
new = {}
for p in (F12_PNG, F12_SVG, F13_PNG, F13_SVG):
    rel = str(p.relative_to(ROOT)).replace("\\", "/")
    new[rel] = {"sha256": sha(p), "bytes": p.stat().st_size}
    if p.suffix == ".png":
        with Image.open(p) as im:
            new[rel]["px"] = list(im.size)

record = {
    "stage": "06 render-only production export (manuscript Figures 12 and 13)",
    "rendered": datetime.now().isoformat(timespec="seconds"),
    "script": "code/06_render_F12_F13.py",
    "scientific_note": "no analysis rerun; source data and alignment results unchanged (hashes before == after)",
    "source_sha256": src_before,
    "invariance_checks": checks,
    "quadrant_totals": tot,
    "median_rho": med,
    "old_outputs": old,
    "new_outputs": new,
    "export": {"font": "Arial", "png_dpi": 600, "F12_mm": F12_SIZE_MM, "F13_mm": F13_SIZE_MM, "svg_text": "svg.fonttype=none (text kept as text)"},
    "settings": {
        "F12": ["grid 5 rows x 4 columns, 17 panels; legend centred in the 3 empty bottom cells",
                "final-size typography; point area 9 pt^2 at final size", "PNG 600 dpi and SVG with text kept as text"],
        "F13": ["178 x 190 mm", "PNG 600 dpi and SVG with text kept as text"]},
    "versions": {"python": sys.version.split()[0], "matplotlib": matplotlib.__version__, "pandas": pd.__version__,
                 "numpy": np.__version__},
}
RECORD.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")

# manifest: update existing output rows in place, append new rows (established Stage 06 convention)
raw = MANIFEST.read_text(encoding="utf-8")
eol = "\r\n" if "\r\n" in raw else "\n"
rows = list(csv.DictReader(io.StringIO(raw)))
by_path = {r["relative_path"]: r for r in rows}
for p in (F12_PNG, F12_SVG, F13_PNG, F13_SVG, RECORD, Path(__file__)):
    rel = str(p.relative_to(ROOT)).replace("\\", "/")
    role = "code" if p.suffix == ".py" else ("render_record" if p == RECORD else "output")
    entry = {"role": role, "relative_path": rel, "size_bytes": str(p.stat().st_size), "sha256": sha(p),
             "produced_by": "06_render_F12_F13.py"}
    if rel in by_path:
        by_path[rel].update(entry)
    else:
        rows.append(entry)
buf = io.StringIO()
w = csv.DictWriter(buf, fieldnames=["role", "relative_path", "size_bytes", "sha256", "produced_by"], lineterminator=eol)
w.writeheader()
w.writerows(rows)
MANIFEST.write_text(buf.getvalue(), encoding="utf-8", newline="")
print("  promoted:", ", ".join(new))
print("  RENDER : PASS")
