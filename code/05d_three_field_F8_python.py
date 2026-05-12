"""
Stage 5d - Figure F8: Three-Field Sankey Plot (Python/Plotly)
Countries (left) -> Author Keywords (middle) -> Journals (right)
Input : data/processed/enriched.csv
Output: figures/F8_three_field.html
        figures/F8_three_field_static.png
Run from: article08/
"""

import re
import sys
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

csv.field_size_limit(10_000_000)

ROOT    = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures"
FIGURES.mkdir(exist_ok=True)

ENRICHED = ROOT / "data/processed/enriched.csv"

# ── ISO-2 -> full country name (AU-54 only) ────────────────────────────────────
ISO2_NAME = {
    "DZ": "Algeria",        "AO": "Angola",          "BJ": "Benin",
    "BW": "Botswana",       "BF": "Burkina Faso",     "BI": "Burundi",
    "CV": "Cabo Verde",     "CM": "Cameroon",         "CF": "Cent. Afr. Rep.",
    "TD": "Chad",           "KM": "Comoros",          "CG": "Congo",
    "CD": "DR Congo",       "CI": "Cote d'Ivoire",   "DJ": "Djibouti",
    "EG": "Egypt",          "GQ": "Eq. Guinea",       "ER": "Eritrea",
    "SZ": "Eswatini",       "ET": "Ethiopia",         "GA": "Gabon",
    "GM": "Gambia",         "GH": "Ghana",            "GN": "Guinea",
    "GW": "Guinea-Bissau",  "KE": "Kenya",            "LS": "Lesotho",
    "LR": "Liberia",        "LY": "Libya",            "MG": "Madagascar",
    "MW": "Malawi",         "ML": "Mali",             "MR": "Mauritania",
    "MU": "Mauritius",      "MA": "Morocco",          "MZ": "Mozambique",
    "NA": "Namibia",        "NE": "Niger",            "NG": "Nigeria",
    "RW": "Rwanda",         "ST": "Sao Tome & Pr.",   "SN": "Senegal",
    "SC": "Seychelles",     "SL": "Sierra Leone",     "SO": "Somalia",
    "ZA": "South Africa",   "SS": "South Sudan",      "SD": "Sudan",
    "TZ": "Tanzania",       "TG": "Togo",             "TN": "Tunisia",
    "UG": "Uganda",         "ZM": "Zambia",           "ZW": "Zimbabwe",
}
AU54_ISO2 = set(ISO2_NAME.keys())

# Country flag emojis for top-15 countries
FLAG_MAP = {
    "South Africa": "\U0001f1ff\U0001f1e6",
    "Egypt":        "\U0001f1ea\U0001f1ec",
    "Nigeria":      "\U0001f1f3\U0001f1ec",
    "Ethiopia":     "\U0001f1ea\U0001f1f9",
    "Ghana":        "\U0001f1ec\U0001f1ed",
    "Kenya":        "\U0001f1f0\U0001f1ea",
    "Morocco":      "\U0001f1f2\U0001f1e6",
    "Tunisia":      "\U0001f1f9\U0001f1f3",
    "Uganda":       "\U0001f1fa\U0001f1ec",
    "Tanzania":     "\U0001f1f9\U0001f1ff",
    "Algeria":      "\U0001f1e9\U0001f1ff",
    "Cameroon":     "\U0001f1e8\U0001f1f2",
    "Malawi":       "\U0001f1f2\U0001f1fc",
    "Zimbabwe":     "\U0001f1ff\U0001f1fc",
    "Zambia":       "\U0001f1ff\U0001f1f2",
}

# Geographic terms to strip from keywords
GEO_TERMS = {
    "africa", "south africa", "nigeria", "ethiopia", "kenya", "ghana",
    "uganda", "tanzania", "egypt", "morocco", "algeria", "tunisia",
    "sub-saharan africa", "developing countries", "developing country",
    "west africa", "east africa", "north africa", "southern africa",
}

# ── Accumulators ───────────────────────────────────────────────────────────────
country_freq  = defaultdict(int)
keyword_freq  = defaultdict(int)
journal_freq  = defaultdict(int)

co_ck = defaultdict(lambda: defaultdict(int))   # country  -> keyword
co_kj = defaultdict(lambda: defaultdict(int))   # keyword  -> journal

# ── Chunked read ───────────────────────────────────────────────────────────────
print("Reading enriched.csv in chunks of 50,000 ...")
chunk_n = 0
total_recs = 0

for chunk in pd.read_csv(
    ENRICHED,
    chunksize=50_000,
    usecols=["match_countries", "keywords_harmonised", "Source title"],
    dtype=str,
    keep_default_na=False,
):
    chunk_n += 1
    total_recs += len(chunk)

    for _, row in chunk.iterrows():
        mc  = row["match_countries"].strip()
        kw  = row["keywords_harmonised"].strip()
        jrn = row["Source title"].strip()

        # ── Country: first AU-54 ISO-2 code ──────────────────────────────────
        country = None
        if mc:
            first_code = mc.split(";")[0].strip()
            if first_code in AU54_ISO2:
                country = ISO2_NAME[first_code]

        # ── Keywords ─────────────────────────────────────────────────────────
        kw_list = []
        if kw:
            for k in kw.split(";"):
                k = k.strip()
                if k and k.lower() not in GEO_TERMS:
                    kw_list.append(k)

        # ── Journal ──────────────────────────────────────────────────────────
        journal = None
        if jrn:
            jrn = jrn.rstrip(".,;").title()
            journal = jrn

        # ── Frequencies ──────────────────────────────────────────────────────
        if country:
            country_freq[country] += 1
        for k in kw_list:
            keyword_freq[k] += 1
        if journal:
            journal_freq[journal] += 1

        # ── Co-occurrences (only if all three present) ────────────────────
        if country and kw_list and journal:
            for k in kw_list:
                co_ck[country][k] += 1
                co_kj[k][journal] += 1

    if chunk_n % 4 == 0:
        print(f"  Chunk {chunk_n}: {total_recs:,} records processed")

print(f"Done. Total records: {total_recs:,}")

# ── Select top 15 ─────────────────────────────────────────────────────────────
def top_n(freq_dict, n=15):
    return [item for item, _ in sorted(freq_dict.items(),
                                       key=lambda x: x[1], reverse=True)[:n]]

top_countries = top_n(country_freq)
top_keywords  = top_n(keyword_freq)
top_journals  = top_n(journal_freq)

# ── Journal name corrections ──────────────────────────────────────────────────
JOURNAL_FIX = {
    "Bmc Public Health":                                          "BMC Public Health",
    "Bmj Open":                                                   "BMJ Open",
    "Bmc Pregnancy And Childbirth":                               "BMC Pregnancy and Childbirth",
    "Bmc Health Services Research":                               "BMC Health Services Research",
    "Environmental Science And Pollution Research":               "Environmental Science and Pollution Research",
    "International Journal Of Environmental Research And Public Health":
                                                                  "Int. J. Environmental Research and Public Health",
    "Science Of The Total Environment":                           "Science of the Total Environment",
    "Water (Switzerland)":                                        "Water",
    "Sustainability (Switzerland)":                               "Sustainability",
}

def fix_journal(name):
    return JOURNAL_FIX.get(name, name)

top_journals_fixed = [fix_journal(j) for j in top_journals]
# Remap co_kj keys so links still resolve after label correction
journal_remap = {j: fix_journal(j) for j in top_journals}

# ── Build node list ───────────────────────────────────────────────────────────
# Countries: indices 0-14, Keywords: 15-29, Journals: 30-44
country_labels = list(top_countries)   # plain country name, no prefix
node_labels = country_labels + top_keywords + top_journals_fixed
n_c = len(top_countries)   # 15
n_k = len(top_keywords)    # 15
n_j = len(top_journals)    # 15

c_idx = {c: i            for i, c in enumerate(top_countries)}
k_idx = {k: i + n_c      for i, k in enumerate(top_keywords)}
j_idx = {j: i + n_c + n_k for i, j in enumerate(top_journals_fixed)}

node_colors = (
    ["#2A6F7F"] * n_c +   # teal  — countries
    ["#E67E22"] * n_k +   # orange — keywords
    ["#27AE60"] * n_j     # green  — journals
)

# Evenly spaced y positions within each column
y_c = np.linspace(0.05, 0.95, n_c).tolist()
y_k = np.linspace(0.05, 0.95, n_k).tolist()
y_j = np.linspace(0.05, 0.95, n_j).tolist()
x_positions = [0.01] * n_c + [0.50] * n_k + [0.99] * n_j
y_positions = y_c + y_k + y_j

# ── Build links ───────────────────────────────────────────────────────────────
sources, targets, values = [], [], []

# Country -> Keyword
for c in top_countries:
    for k in top_keywords:
        v = co_ck[c].get(k, 0)
        if v > 0:
            sources.append(c_idx[c])
            targets.append(k_idx[k])
            values.append(v)

# Keyword -> Journal  (look up original key; resolve to fixed label index)
for k in top_keywords:
    for orig_j, fixed_j in zip(top_journals, top_journals_fixed):
        v = co_kj[k].get(orig_j, 0)
        if v > 0:
            sources.append(k_idx[k])
            targets.append(j_idx[fixed_j])
            values.append(v)

print(f"Links: country->keyword: {sum(1 for s in sources if s < n_c)}  "
      f"keyword->journal: {sum(1 for s in sources if s >= n_c)}")

# ── Build figure ──────────────────────────────────────────────────────────────
fig = go.Figure(go.Sankey(
    arrangement="fixed",
    node=dict(
        pad=20,
        thickness=25,
        line=dict(color="black", width=0.5),
        label=node_labels,
        color=node_colors,
        x=x_positions,
        y=y_positions,
    ),
    link=dict(
        source=sources,
        target=targets,
        value=values,
        color="rgba(180,180,180,0.35)",
    ),
))

fig.add_annotation(x=0.01, y=1.08, text="Countries",
                   showarrow=False, xref="paper", yref="paper",
                   font=dict(size=14, color="#333333", family="Arial"))
fig.add_annotation(x=0.50, y=1.08, text="Author Keywords",
                   showarrow=False, xref="paper", yref="paper",
                   font=dict(size=14, color="#333333", family="Arial"))
fig.add_annotation(x=0.99, y=1.08, text="Journals",
                   showarrow=False, xref="paper", yref="paper",
                   font=dict(size=14, color="#333333", family="Arial"))

fig.update_layout(
    font=dict(family="Arial", size=13, color="#333333"),
    width=1600, height=950,
    paper_bgcolor="white",
    plot_bgcolor="white",
    margin=dict(l=10, r=10, t=80, b=10),
)

# ── Save ──────────────────────────────────────────────────────────────────────
html_path = FIGURES / "F8_three_field.html"
png_path  = FIGURES / "F8_three_field_static.png"

fig.write_html(str(html_path))

fig.write_image(str(png_path), width=1600, height=950, scale=3)

# ── Report ────────────────────────────────────────────────────────────────────
print()
print("=" * 65)
print(" FIGURE F8 — THREE-FIELD SANKEY REPORT")
print("=" * 65)
print()

print(f"  Top 15 countries:")
for i, c in enumerate(top_countries, 1):
    print(f"    {i:2d}. {c:<30} {country_freq[c]:,}")

print()
print(f"  Top 15 keywords:")
for i, k in enumerate(top_keywords, 1):
    print(f"    {i:2d}. {k:<40} {keyword_freq[k]:,}")

print()
print(f"  Top 15 journals (after name corrections):")
for i, (orig, fixed) in enumerate(zip(top_journals, top_journals_fixed), 1):
    changed = "  *" if orig != fixed else ""
    print(f"    {i:2d}. {fixed[:55]:<55} {journal_freq[orig]:,}{changed}")

print()
print(f"  Journal label changes applied:")
changed_any = False
for orig, fixed in zip(top_journals, top_journals_fixed):
    if orig != fixed:
        print(f"    '{orig}'")
        print(f"      -> '{fixed}'")
        changed_any = True
if not changed_any:
    print(f"    (none)")

print()
n_ck = sum(1 for s in sources if s < n_c)
n_kj = sum(1 for s in sources if s >= n_c)
print(f"  Co-occurrence links  country->keyword : {n_ck}")
print(f"  Co-occurrence links  keyword->journal : {n_kj}")
print(f"  Total links                           : {n_ck + n_kj}")
print()
print(f"  HTML : {html_path}  ({html_path.stat().st_size:,} bytes)")
print(f"  PNG  : {png_path}  ({png_path.stat().st_size:,} bytes)")
print()
print("=" * 65)
print(" STAGE 5D COMPLETE")
print("=" * 65)
