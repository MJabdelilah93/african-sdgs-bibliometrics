"""07_render_figure1.py — Figure 1: six-stage auditable data pipeline.

Draws the six workflow stages (query specification, data acquisition, cleaning, enrichment, analysis,
reporting) with the tool, action and artefact of each stage. Record counts are read from
provenance/corpus_flow.json and checked for internal consistency before drawing; nothing is recomputed.

Outputs: figures/F1_auditable_pipeline.png (600 dpi) and figures/F1_auditable_pipeline.svg
(text kept as text). Deterministic: fixed SVG hash salt, no creation date in the metadata.

Run from the repository root:  python code/07_render_figure1.py
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "provenance" / "corpus_flow.json"
OUT = ROOT / "figures" / "F1_auditable_pipeline"

flow = json.loads(FLOW.read_text(encoding="utf-8"))
c = flow["counts"]
checks = {
    "consolidated - eligibility exclusions == final analytical records":
        c["consolidated_records"] - c["eligibility_exclusions"] == c["final_analytical_records"],
    "records with a resolved AU affiliation <= final analytical records":
        c["records_with_au_affiliation"] <= c["final_analytical_records"],
    "17 SDG query specifications": flow["query_specifications"] == 17,
}
for name, ok in checks.items():
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
if not all(checks.values()):
    sys.exit("STOP: corpus_flow.json is inconsistent; nothing drawn")

n = lambda x: f"{x:,}"
STAGES = [
    ("1.  Query\n     specification", "Aurora SDG\nQueries v5.0.3",
     "Prepare search specifications for all\n17 SDGs and adapt syntax for Scopus",
     "17 SDG specifications + AU-54 affiliation\nscope + 2015–2025 + articles and reviews",
     "Original and\nexecuted query\nstrings", None),
    ("2.  Data\n     acquisition", "Scopus",
     "Retrieve African SDG records\nfor 2015–2025",
     "17 SDG searches, AU-54 affiliation filter,\narticles and reviews",
     "Acquisition manifest", None),
    ("3.  Cleaning", "Python · ROR",
     "Deduplicate records, apply eligibility criteria,\nresolve countries and standardise affiliations",
     f"{n(c['consolidated_records'])} records before eligibility screening\n"
     f"{n(c['final_analytical_records'])} final analytical records",
     "Deduplication and affiliation logs", None),
    ("4.  Enrichment", "Python",
     "Harmonise keywords and consolidate SDG tags",
     f"n = {n(c['final_analytical_records'])} records",
     "Keyword thesaurus and mapping rules", None),
    ("5.  Analysis", "R · Python ·\nVOSviewer",
     "Compute indicators, themes, networks,\ncollaboration and research–implementation\nalignment",
     f"n = {n(c['final_analytical_records'])} records",
     "Parameter files and result tables", "SDG Index 2025"),
    ("6.  Reporting", "Python",
     "Generate tables, figures, validation records\nand provenance records",
     f"n = {n(c['final_analytical_records'])} records",
     "Reproducibility package", None),
]
NOTE = (f"Country-level collaboration and alignment analyses used {n(c['records_with_au_affiliation'])} records "
        "with a resolved African Union affiliation.")

MM = 1 / 25.4
W, H = 180 * MM, 210 * MM
plt.rcParams.update({"svg.hashsalt": "figure1-pipeline", "svg.fonttype": "none", "font.family": "DejaVu Sans",
                     "font.size": 7.5})
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 180)
ax.set_ylim(0, 210)
ax.axis("off")
DARK, MID, LIGHT, ACC = "#1F3B4D", "#5B7A8C", "#E8EEF2", "#2A6F7F"
top, row_h, gap = 202, 28.5, 3.2
cols = {"stage": (4, 31), "tool": (38, 30), "action": (71, 73), "artefact": (147, 29)}
ax.text(cols["tool"][0] + cols["tool"][1] / 2, top + 3.5, "TOOL", ha="center", va="center", fontsize=7, color=MID, weight="bold")
ax.text(cols["action"][0] + cols["action"][1] / 2, top + 3.5, "ACTION", ha="center", va="center", fontsize=7, color=MID, weight="bold")
ax.text(cols["artefact"][0] + cols["artefact"][1] / 2, top + 3.5, "ARTEFACT", ha="center", va="center", fontsize=7, color=MID,
        weight="bold")
for i, (title, tool, action, detail, artefact, external) in enumerate(STAGES):
    y1 = top - i * (row_h + gap)
    y0 = y1 - row_h
    ax.add_patch(FancyBboxPatch((cols["stage"][0], y0), cols["stage"][1], row_h, boxstyle="round,pad=0,rounding_size=2",
                                fc=DARK, ec="none"))
    ax.text(cols["stage"][0] + 3, (y0 + y1) / 2, title, ha="left", va="center", fontsize=8.5, color="white", weight="bold",
            linespacing=1.25)
    for key in ("tool", "action", "artefact"):
        x, w = cols[key]
        ax.add_patch(FancyBboxPatch((x, y0), w, row_h, boxstyle="round,pad=0,rounding_size=1.5", fc=LIGHT, ec="#C9D4DB",
                                    lw=0.6))
    ax.text(cols["tool"][0] + cols["tool"][1] / 2, (y0 + y1) / 2, tool, ha="center", va="center", fontsize=7.5, color=DARK,
            weight="bold", linespacing=1.3)
    ax.text(cols["action"][0] + 2.5, y1 - 4.0, action, ha="left", va="top", fontsize=7.1, color=DARK, linespacing=1.3)
    ax.text(cols["action"][0] + 2.5, y0 + 3.0 + (4.2 if external else 0), detail, ha="left", va="bottom", fontsize=6.9,
            color=ACC, linespacing=1.3, weight="bold")
    if external:
        ax.text(cols["action"][0] + 2.5, y0 + 2.2, f"External input: {external}", ha="left", va="bottom", fontsize=6.8,
                color=MID, style="italic")
    ax.text(cols["artefact"][0] + cols["artefact"][1] / 2, (y0 + y1) / 2, artefact.replace(" and ", "\nand ").replace("Reproducibility package", "Reproducibility\npackage")
            if len(artefact) > 20 and "\n" not in artefact else artefact, ha="center", va="center", fontsize=7.2, color=DARK, linespacing=1.3)
    if i < len(STAGES) - 1:
        xm = cols["stage"][0] + cols["stage"][1] / 2
        ax.annotate("", xy=(xm, y0 - gap + 0.3), xytext=(xm, y0 - 0.3),
                    arrowprops=dict(arrowstyle="-|>", color=MID, lw=0.9, shrinkA=0, shrinkB=0))
ax.text(4, 5.5, NOTE, ha="left", va="center", fontsize=6.8, color=MID, style="italic")
OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT.with_suffix(".png"), dpi=600, metadata={"Software": None})
fig.savefig(OUT.with_suffix(".svg"), metadata={"Date": None, "Creator": None})
plt.close(fig)
print(f"written: {OUT.with_suffix('.png').relative_to(ROOT).as_posix()}, {OUT.with_suffix('.svg').relative_to(ROOT).as_posix()}")
