"""08f_render_F11.py — render-only production export of manuscript Figure 11 (three-field Sankey).

Rebuilds the Plotly Sankey of code/08c_three_field_F11.py from FROZEN outputs only:
results/F11_three_field_flow_data.csv (flows) and provenance/v2/F11_three_field_provenance.json (top-15
country / keyword / journal lists in display order). Nothing is recounted from enriched.csv.
The rebuilt node labels, fixed node positions (arrangement="fixed"), colours and link source/target/value
must equal the figure spec embedded in the committed HTML (figures/F11_three_field_country_keyword_journal.html),
otherwise nothing is written. Production settings: larger fonts and a 600 dpi PNG at 180 mm width
plus an SVG. The interactive HTML is not rewritten.
Record: provenance/v2/F11_render.json; F11 rows in provenance/v2/network_collaboration_manifest.csv.

Run from the repository root:  .venv\\Scripts\\python.exe code/08f_render_F11.py
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import plotly
import plotly.graph_objects as go
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FLOWS = ROOT / "results/F11_three_field_flow_data.csv"
PROV = ROOT / "provenance/v2/F11_three_field_provenance.json"
HTML = ROOT / "figures/F11_three_field_country_keyword_journal.html"
PNG = ROOT / "figures/F11_three_field_country_keyword_journal.png"
SVG = ROOT / "figures/F11_three_field_country_keyword_journal.svg"
RECORD = ROOT / "provenance/v2/F11_render.json"
MANIFEST = ROOT / "provenance/v2/network_collaboration_manifest.csv"
W_PX, H_PX = 1600, 950                          # CSS canvas of 08c
TARGET_MM, DPI = 180, 600
SCALE = TARGET_MM / 25.4 * DPI / W_PX           # 4252 px wide = 180 mm at 600 dpi
NODE_FONT, HEADER_FONT = 24, 28                 # px on the 1600 px canvas = about 7.7 / 8.9 pt at 180 mm


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fail(msg):
    sys.exit(f"INVARIANCE FAILURE — nothing written: {msg}")


src_before = {p.name: sha(p) for p in (FLOWS, PROV, HTML)}
prov = json.load(open(PROV, encoding="utf-8"))
top_c = [c for c, _ in prov["top_countries"]]
top_k = [k for k, _ in prov["top_keywords"]]
top_j = [j for j, _ in prov["top_journals"]]
labels = top_c + top_k + top_j
nc, nk, nj = len(top_c), len(top_k), len(top_j)
idx_src = {**{c: i for i, c in enumerate(top_c)}, **{k: nc + i for i, k in enumerate(top_k)}}
idx_tgt = {**{k: nc + i for i, k in enumerate(top_k)}, **{j: nc + nk + i for i, j in enumerate(top_j)}}
flows = list(csv.DictReader(open(FLOWS, encoding="utf-8")))
src = [idx_src[f["source"]] for f in flows]
tgt = [idx_tgt[f["target"]] for f in flows]
val = [int(f["value"]) for f in flows]
node = dict(pad=20, thickness=25, line=dict(color="black", width=0.5), label=labels,
            color=["#2A6F7F"] * nc + ["#E67E22"] * nk + ["#27AE60"] * nj,
            x=[0.01] * nc + [0.50] * nk + [0.99] * nj,
            y=np.linspace(0.05, 0.95, nc).tolist() + np.linspace(0.05, 0.95, nk).tolist() + np.linspace(0.05, 0.95, nj).tolist())

# committed figure spec (exactly what the current Figure 11 shows)
html = HTML.read_text(encoding="utf-8")
m = re.search(r'Plotly\.newPlot\(\s*"f11-three-field",\s*', html)
spec, _ = json.JSONDecoder().raw_decode(html, m.end())
s0 = spec[0]
checks = {
    "country->keyword flows == 225": sum(f["flow"] == "country_to_keyword" for f in flows) == 225,
    "keyword->journal flows == 169": sum(f["flow"] == "keyword_to_journal" for f in flows) == 169,
    "15 / 15 / 15 nodes": (nc, nk, nj) == (15, 15, 15),
    "PLoS ONE present with no flows": "Plos One" in top_j and not any(f["target"] == "Plos One" for f in flows),
    "labels == committed HTML": s0["node"]["label"] == labels,
    "node x/y == committed HTML": np.allclose(s0["node"]["x"], node["x"]) and np.allclose(s0["node"]["y"], node["y"]),
    "node colours == committed HTML": s0["node"]["color"] == node["color"],
    "link source/target/value == committed HTML": (list(s0["link"]["source"]) == src and list(s0["link"]["target"]) == tgt
                                                   and list(s0["link"]["value"]) == val),
    "arrangement fixed": s0["arrangement"] == "fixed",
}
for k, v in checks.items():
    print(f"  [{'PASS' if v else 'FAIL'}] {k}")
if not all(checks.values()):
    fail("; ".join(k for k, v in checks.items() if not v))

fig = go.Figure(go.Sankey(arrangement="fixed", node=node,
                          textfont=dict(size=NODE_FONT, color="#222222", family="Arial"),
                          link=dict(source=src, target=tgt, value=val, color="rgba(180,180,180,0.35)")))
for x, t in ((0.01, "Countries"), (0.50, "Author Keywords"), (0.99, "Journals")):
    fig.add_annotation(x=x, y=1.075, text=t, showarrow=False, xref="paper", yref="paper",
                       font=dict(size=HEADER_FONT, color="#222222", family="Arial"))
fig.update_layout(font=dict(family="Arial", size=NODE_FONT, color="#222222"), width=W_PX, height=H_PX,
                  paper_bgcolor="white", plot_bgcolor="white", margin=dict(l=10, r=10, t=80, b=10))
tmp_png, tmp_svg = PNG.with_name(PNG.name + ".tmp"), SVG.with_name(SVG.name + ".tmp")
fig.write_image(str(tmp_png), width=W_PX, height=H_PX, scale=SCALE, format="png")
fig.write_image(str(tmp_svg), width=W_PX, height=H_PX, format="svg")
if {p.name: sha(p) for p in (FLOWS, PROV, HTML)} != src_before:
    fail("a source file changed during rendering")
blob = __import__("subprocess").run(["git", "show", "HEAD:figures/F11_three_field_country_keyword_journal.png"],
                                    cwd=ROOT, capture_output=True).stdout
old = {}
if blob:
    with Image.open(io.BytesIO(blob)) as im:
        old = {"px": list(im.size), "sha256": hashlib.sha256(blob).hexdigest()}
for t, final in ((tmp_png, PNG), (tmp_svg, SVG)):
    if t.stat().st_size == 0:
        fail(f"empty {t}")
    t.replace(final)
with Image.open(PNG) as im:
    new_px = list(im.size)
record = {
    "stage": "08 render-only production export (manuscript Figure 11)",
    "rendered": datetime.now().isoformat(timespec="seconds"),
    "script": "code/08f_render_F11.py",
    "scientific_note": "flows, top-15 sets, node positions and colours identical to the committed figure; nothing recounted",
    "source_sha256": src_before, "invariance_checks": checks,
    "old_png": old, "new_png": {"px": new_px, "sha256": sha(PNG)}, "svg": {"sha256": sha(SVG), "bytes": SVG.stat().st_size},
    "export": {"canvas_css_px": [W_PX, H_PX], "png_scale": SCALE, "png_dpi_at_180mm": DPI, "physical_mm": [TARGET_MM, round(TARGET_MM * H_PX / W_PX, 1)]},
    "settings": [f"node labels {NODE_FONT} px and column headers {HEADER_FONT} px on the 1600 x 950 canvas",
                 "PNG at 180 mm / 600 dpi and SVG; HTML not rewritten"],
    "versions": {"python": sys.version.split()[0], "plotly": plotly.__version__},
}
RECORD.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
raw = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else "role,relative_path,size_bytes,sha256\n"
eol = "\r\n" if "\r\n" in raw else "\n"
rows = list(csv.DictReader(io.StringIO(raw)))
by = {r["relative_path"]: r for r in rows}
for p, role in ((PNG, "output"), (SVG, "output"), (RECORD, "provenance"), (Path(__file__), "code")):
    rel = str(p.relative_to(ROOT)).replace("\\", "/")
    e = {"role": role, "relative_path": rel, "size_bytes": str(p.stat().st_size), "sha256": sha(p)}
    if rel in by:
        by[rel].update({k: v for k, v in e.items() if k != "role"})
    else:
        rows.append(e)
buf = io.StringIO()
w = csv.DictWriter(buf, fieldnames=["role", "relative_path", "size_bytes", "sha256"], lineterminator=eol)
w.writeheader()
w.writerows(rows)
MANIFEST.write_text(buf.getvalue(), encoding="utf-8", newline="")
print(f"  PNG {new_px}  SVG written  RENDER : PASS")
