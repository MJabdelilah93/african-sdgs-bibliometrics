"""08c_three_field_F11.py — Figure 11: country -> author keyword -> journal three-field plot.

Top 15 countries / author keywords / journals by frequency (ties in first-seen file order), a 19-term
geographic keyword filter, journal title-casing and display labels, country->keyword and
keyword->journal flows counted on records that have all three fields.
  * Country field: the first AU country in affiliation-segment order from the Stage 02 normaliser
    (utils/country_normalisation.py); it is always a member of the record's `au_countries` (checked).
  * input hash guard (Stage 04 manifest), virtual-environment guard, .tmp writing + promotion, flow data
    CSV, provenance JSON, deterministic HTML div id.

Run from the repository root:  python code/08c_three_field_F11.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import plotly
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from utils.checksums import sha256_file  # noqa: E402
from utils.country_normalisation import CountryNormaliser  # noqa: E402
from utils import collab_methods as C  # noqa: E402

csv.field_size_limit(2**31 - 1)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ap = argparse.ArgumentParser()
ap.add_argument("--input", type=Path, default=ROOT / "data/processed/enriched.csv")
ap.add_argument("--figures-dir", type=Path, default=ROOT / "figures")
ap.add_argument("--results-dir", type=Path, default=ROOT / "results")
ap.add_argument("--prov-dir", type=Path, default=ROOT / "provenance/v2")
ap.add_argument("--smoke-test", action="store_true")
A = ap.parse_args()
if A.smoke_test and any(ROOT in Path(d).resolve().parents for d in (A.figures_dir, A.results_dir, A.prov_dir)):
    sys.exit("--smoke-test outputs must be outside the project")
if sys.prefix == sys.base_prefix:
    sys.exit("use the project .venv")
IN_SHA = sha256_file(A.input)
EXP = {r["relative_path"]: r["sha256"] for r in csv.DictReader(open(ROOT / "provenance/v2/stage4_performance_manifest.csv", encoding="utf-8"))}["data/processed/enriched.csv"]
if not A.smoke_test and IN_SHA != EXP:
    sys.exit(f"enriched.csv hash {IN_SHA} differs from the Stage 04 manifest {EXP}")
NORM = CountryNormaliser(ROOT / "country_lists/country_names_iso2.csv", ROOT / "country_lists/au54_countries.csv")

# ── preserved from 05d ──────────────────────────────────────────────────────
ISO2_NAME = {
    "DZ": "Algeria", "AO": "Angola", "BJ": "Benin", "BW": "Botswana", "BF": "Burkina Faso", "BI": "Burundi",
    "CV": "Cabo Verde", "CM": "Cameroon", "CF": "Cent. Afr. Rep.", "TD": "Chad", "KM": "Comoros", "CG": "Congo",
    "CD": "DR Congo", "CI": "Cote d'Ivoire", "DJ": "Djibouti", "EG": "Egypt", "GQ": "Eq. Guinea", "ER": "Eritrea",
    "SZ": "Eswatini", "ET": "Ethiopia", "GA": "Gabon", "GM": "Gambia", "GH": "Ghana", "GN": "Guinea",
    "GW": "Guinea-Bissau", "KE": "Kenya", "LS": "Lesotho", "LR": "Liberia", "LY": "Libya", "MG": "Madagascar",
    "MW": "Malawi", "ML": "Mali", "MR": "Mauritania", "MU": "Mauritius", "MA": "Morocco", "MZ": "Mozambique",
    "NA": "Namibia", "NE": "Niger", "NG": "Nigeria", "RW": "Rwanda", "ST": "Sao Tome & Pr.", "SN": "Senegal",
    "SC": "Seychelles", "SL": "Sierra Leone", "SO": "Somalia", "ZA": "South Africa", "SS": "South Sudan", "SD": "Sudan",
    "TZ": "Tanzania", "TG": "Togo", "TN": "Tunisia", "UG": "Uganda", "ZM": "Zambia", "ZW": "Zimbabwe",
}
assert set(ISO2_NAME) == NORM.au
GEO_TERMS = {
    "africa", "south africa", "nigeria", "ethiopia", "kenya", "ghana", "uganda", "tanzania", "egypt", "morocco",
    "algeria", "tunisia", "sub-saharan africa", "developing countries", "developing country", "west africa",
    "east africa", "north africa", "southern africa",
}
JOURNAL_FIX = {
    "Bmc Public Health": "BMC Public Health", "Bmj Open": "BMJ Open",
    "Bmc Pregnancy And Childbirth": "BMC Pregnancy and Childbirth",
    "Bmc Health Services Research": "BMC Health Services Research",
    "Environmental Science And Pollution Research": "Environmental Science and Pollution Research",
    "International Journal Of Environmental Research And Public Health": "Int. J. Environmental Research and Public Health",
    "Science Of The Total Environment": "Science of the Total Environment",
    "Water (Switzerland)": "Water", "Sustainability (Switzerland)": "Sustainability",
}


def first_au_country(aff):   # direct text attribution; ROR never used
    return C.first_au_country(NORM, aff)


country_freq, keyword_freq, journal_freq = defaultdict(int), defaultdict(int), defaultdict(int)
co_ck = defaultdict(lambda: defaultdict(int))
co_kj = defaultdict(lambda: defaultdict(int))
total, not_member = 0, 0
with open(A.input, encoding="utf-8", newline="") as f:
    rd = csv.reader(f)
    h = next(rd)
    ia, iau, ik, ij = h.index("Affiliations"), h.index("au_countries"), h.index("keywords_harmonised"), h.index("Source title")
    for row in rd:
        total += 1
        code = first_au_country(row[ia])
        if code and code not in row[iau].split(";"):
            not_member += 1
        country = ISO2_NAME[code] if code else None
        kw = row[ik].strip()
        kw_list = [k.strip() for k in kw.split(";") if k.strip() and k.strip().lower() not in GEO_TERMS] if kw else []
        jrn = row[ij].strip()
        journal = jrn.rstrip(".,;").title() if jrn else None
        if country:
            country_freq[country] += 1
        for k in kw_list:
            keyword_freq[k] += 1
        if journal:
            journal_freq[journal] += 1
        if country and kw_list and journal:
            for k in kw_list:
                co_ck[country][k] += 1
                co_kj[k][journal] += 1
if not_member:
    sys.exit(f"{not_member} records: first-country not in au_countries — inconsistent with Stage 02")


def top_n(d, n=15):
    return [k for k, _ in sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]]


top_c, top_k, top_j = top_n(country_freq), top_n(keyword_freq), top_n(journal_freq)
top_j_fixed = [JOURNAL_FIX.get(j, j) for j in top_j]
labels = top_c + top_k + top_j_fixed
nc, nk, nj = len(top_c), len(top_k), len(top_j)
c_idx = {c: i for i, c in enumerate(top_c)}
k_idx = {k: i + nc for i, k in enumerate(top_k)}
src, tgt, val, flows = [], [], [], []
for c in top_c:
    for k in top_k:
        v = co_ck[c].get(k, 0)
        if v > 0:
            src.append(c_idx[c]); tgt.append(k_idx[k]); val.append(v)
            flows.append({"flow": "country_to_keyword", "source": c, "target": k, "value": v})
for k in top_k:
    for i, (oj, fj) in enumerate(zip(top_j, top_j_fixed)):
        v = co_kj[k].get(oj, 0)
        if v > 0:
            src.append(k_idx[k]); tgt.append(nc + nk + i); val.append(v)
            flows.append({"flow": "keyword_to_journal", "source": k, "target": fj, "value": v})
fig = go.Figure(go.Sankey(
    arrangement="fixed",
    node=dict(pad=20, thickness=25, line=dict(color="black", width=0.5), label=labels,
              color=["#2A6F7F"] * nc + ["#E67E22"] * nk + ["#27AE60"] * nj,
              x=[0.01] * nc + [0.50] * nk + [0.99] * nj,
              y=np.linspace(0.05, 0.95, nc).tolist() + np.linspace(0.05, 0.95, nk).tolist() + np.linspace(0.05, 0.95, nj).tolist()),
    link=dict(source=src, target=tgt, value=val, color="rgba(180,180,180,0.35)")))
for x, t in ((0.01, "Countries"), (0.50, "Author Keywords"), (0.99, "Journals")):
    fig.add_annotation(x=x, y=1.08, text=t, showarrow=False, xref="paper", yref="paper",
                       font=dict(size=14, color="#333333", family="Arial"))
fig.update_layout(font=dict(family="Arial", size=13, color="#333333"), width=1600, height=950,
                  paper_bgcolor="white", plot_bgcolor="white", margin=dict(l=10, r=10, t=80, b=10))

png = A.figures_dir / "F11_three_field_country_keyword_journal.png"
html = A.figures_dir / "F11_three_field_country_keyword_journal.html"
flow_csv = A.results_dir / "F11_three_field_flow_data.csv"
for p in (png, html, flow_csv):
    p.parent.mkdir(parents=True, exist_ok=True)
tmp = {p: p.with_name(p.name + ".tmp") for p in (png, html, flow_csv)}
fig.write_image(str(tmp[png]), width=1600, height=950, scale=3, format="png")
fig.write_html(str(tmp[html]), div_id="f11-three-field", include_plotlyjs=True, full_html=True)
with open(tmp[flow_csv], "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["flow", "source", "target", "value"], lineterminator="\n")
    w.writeheader()
    w.writerows(flows)
checks = {"top 15 per field (or all available)": (nc, nk, nj) == (min(15, len(country_freq)), min(15, len(keyword_freq)), min(15, len(journal_freq))),
          "flows reference top sets": all(fl["source"] in labels and fl["target"] in labels for fl in flows),
          "country->keyword flow total <= keyword occurrences": all(
              sum(fl["value"] for fl in flows if fl["flow"] == "country_to_keyword" and fl["target"] == k) <= keyword_freq[k] for k in top_k),
          "non-empty outputs": all(t.stat().st_size > 0 for t in tmp.values())}
if not all(checks.values()):
    sys.exit(f"Figure 11 checks failed: {checks}")
for p, t in tmp.items():
    t.replace(p)
prov = {"figure": "manuscript Figure 11 (three-field: country -> author keyword -> journal)", "script": "code/08c_three_field_F11.py",
        "run": datetime.now().isoformat(timespec="seconds"),
        "input_sha256": IN_SHA, "plotly": plotly.__version__, "records": total,
        "country_field": "first AU country in affiliation-segment order (direct attribution)",
        "top_countries": [(c, country_freq[c]) for c in top_c], "top_keywords": [(k, keyword_freq[k]) for k in top_k],
        "top_journals": [(fj, journal_freq[oj]) for oj, fj in zip(top_j, top_j_fixed)],
        "flows": {"country_to_keyword": sum(1 for x in flows if x["flow"] == "country_to_keyword"),
                  "keyword_to_journal": sum(1 for x in flows if x["flow"] == "keyword_to_journal"),
                  "total_value": sum(val)},
        "checks": checks, "outputs_sha256": {str(p.relative_to(A.figures_dir.parent) if not A.smoke_test else p): sha256_file(p) for p in tmp}}
A.prov_dir.mkdir(parents=True, exist_ok=True)
json.dump(prov, open(A.prov_dir / "F11_three_field_provenance.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps({k: prov[k] for k in ("top_countries", "top_keywords", "top_journals", "flows", "checks")}, indent=1, ensure_ascii=False))
