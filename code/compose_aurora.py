"""
compose_aurora.py
Stage 1 – Parse Aurora SDG XML files and compose Scopus-ready queries
restricted to the 54 African Union member states.

Framework: Vanderfeesten, Otten & Spielberg (2020), Zenodo 10.5281/zenodo.4883250 v5.0.3
"""

import csv
import re
import sys
from datetime import date
from pathlib import Path

try:
    from lxml import etree as ET
    PARSER = "lxml"
except ImportError:
    import xml.etree.ElementTree as ET
    PARSER = "stdlib-ElementTree"

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE   = Path(__file__).resolve().parent.parent
AURORA = BASE / "sdg_queries" / "aurora"
OUT    = BASE / "sdg_queries" / "composed"
CSV_IN = BASE / "country_lists" / "au54_countries.csv"

NS = {
    "aqd": "http://aurora-network.global/queries/namespace/",
    "dc":  "http://dublincore.org/documents/dcmi-namespace/",
}

AURORA_CITATION = (
    'Vanderfeesten, M., Otten, R., & Spielberg, E. (2020).\n'
    '  Search queries for "mapping research output to the SDGs" v5.0.3.\n'
    '  Zenodo. https://doi.org/10.5281/zenodo.4883250'
)

SUFFIX = (
    "AND PUBYEAR > 2014 AND PUBYEAR < 2026\n"
    "AND ( DOCTYPE ( ar ) OR DOCTYPE ( re ) )"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def collapse(text: str) -> str:
    """Strip and collapse all internal whitespace to single spaces."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def find_text(elem, xpath: str) -> str:
    hit = elem.find(xpath, NS)
    return collapse(hit.text) if (hit is not None and hit.text) else ""


def affil_clause(names: list[str]) -> str:
    inner = " OR ".join(f'AFFILCOUNTRY ( "{n}" )' for n in sorted(names))
    return f"AND ( {inner} )"


# ── Step 1 – Load AU-54 countries ─────────────────────────────────────────────

with open(CSV_IN, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

all_names = sorted(r["country_name_scopus"] for r in rows)
part1_names = sorted(
    r["country_name_scopus"] for r in rows
    if r["subregion"] in ("North Africa", "East Africa")
)
part2_names = sorted(
    r["country_name_scopus"] for r in rows
    if r["subregion"] in ("West Africa", "Central Africa", "Southern Africa")
)

AFFIL_FULL = affil_clause(all_names)
AFFIL_P1   = affil_clause(part1_names)
AFFIL_P2   = affil_clause(part2_names)


# ── Step 2 – Verify 17 XML files ──────────────────────────────────────────────

xml_map: dict[int, Path] = {}
missing = []
for n in range(1, 18):
    p = AURORA / f"query_SDG{n}.xml"
    if p.exists():
        xml_map[n] = p
    else:
        missing.append(str(p))

if missing:
    print("ERROR – Missing Aurora XML files:")
    for m in missing:
        print(f"  {m}")
    sys.exit(1)

print(f"[OK] All 17 Aurora XML files found in {AURORA}")
print(f"  Parser: {PARSER}")
print(f"  Countries: {len(all_names)} (Part1={len(part1_names)}, Part2={len(part2_names)})")
print()


# ── Step 3–9 – Parse, compose, write ─────────────────────────────────────────

records = []

for sdg_num in range(1, 18):
    nn = f"{sdg_num:02d}"
    xml_path = xml_map[sdg_num]

    tree = ET.parse(str(xml_path))
    root = tree.getroot()

    # Metadata
    sdg_title = find_text(root, ".//dc:title")
    version   = find_text(root, ".//dc:identifier[@type='version']")
    doi       = find_text(root, ".//dc:identifier[@type='doi']")

    # Walk query-definitions (all, in document order, including 1.a, 1.b etc.)
    query_defs = root.findall(".//aqd:query-definition", NS)
    all_lines: list[str] = []
    for qd in query_defs:
        for ql in qd.findall(".//aqd:query-line[@field='TITLE-ABS-KEY']", NS):
            text = collapse(ql.text or "")
            if text:
                all_lines.append(f"TITLE-ABS-KEY( {text} )")

    # Build Aurora query content (outer parens ensure correct precedence)
    aurora_content = "( " + " OR ".join(all_lines) + " )"

    # Composed query: aurora content + affil clause + year/doctype suffix
    composed = f"{aurora_content}\n{AFFIL_FULL}\n{SUFFIX}"

    # Lengths
    aurora_len   = len(aurora_content)
    composed_len = len(composed)
    over25k      = "yes" if composed_len > 25_000 else "no"

    # Write full composed file
    (OUT / f"SDG{nn}_full.txt").write_text(composed, encoding="utf-8")

    # Sub-region splits if over limit
    if over25k == "yes":
        q1 = f"{aurora_content}\n{AFFIL_P1}\n{SUFFIX}"
        q2 = f"{aurora_content}\n{AFFIL_P2}\n{SUFFIX}"
        (OUT / f"SDG{nn}_full_part1_NorthEast.txt").write_text(q1, encoding="utf-8")
        (OUT / f"SDG{nn}_full_part2_Rest.txt").write_text(q2, encoding="utf-8")

    records.append({
        "sdg_number":                   nn,
        "sdg_title":                    sdg_title,
        "source_xml_file":              xml_path.name,
        "n_query_definitions":          len(query_defs),
        "n_query_lines":                len(all_lines),
        "aurora_version":               version,
        "aurora_doi":                   doi,
        "aurora_content_length_chars":  aurora_len,
        "composed_length_chars":        composed_len,
        "warning_over_25k_chars":       over25k,
    })


# ── Step 7 – _query_lengths.csv ───────────────────────────────────────────────

csv_cols = [
    "sdg_number", "sdg_title", "source_xml_file",
    "n_query_definitions", "n_query_lines",
    "aurora_content_length_chars", "composed_length_chars",
    "warning_over_25k_chars",
]
with open(OUT / "_query_lengths.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(records)


# ── Step 9 – _aurora_provenance.txt ───────────────────────────────────────────

prov = [
    "Aurora SDG Search Query Framework – Composition Provenance",
    "=" * 62,
    "",
    "Citation:",
    f"  {AURORA_CITATION}",
    "",
    f"Composition date : {date.today().isoformat()}",
    f"Parser used      : {PARSER}",
    f"Countries        : {len(all_names)} AU member states",
    f"Year window      : PUBYEAR > 2014 AND PUBYEAR < 2026",
    f"Document types   : ar (article), re (review)",
    "",
    "Per-SDG details:",
    "-" * 62,
]

for r in records:
    prov += [
        f"SDG {r['sdg_number']} – {r['sdg_title']}",
        f"  Source XML         : {r['source_xml_file']}",
        f"  Aurora version     : {r['aurora_version']}",
        f"  Aurora DOI         : https://doi.org/{r['aurora_doi']}",
        f"  Query definitions  : {r['n_query_definitions']}",
        f"  Query lines        : {r['n_query_lines']}",
        f"  Aurora content len : {r['aurora_content_length_chars']:,} chars",
        f"  Composed length    : {r['composed_length_chars']:,} chars",
        f"  Over 25k warning   : {r['warning_over_25k_chars']}",
        "",
    ]

(OUT / "_aurora_provenance.txt").write_text("\n".join(prov), encoding="utf-8")


# ── Step 10 – Terminal report ─────────────────────────────────────────────────

HDR = f"{'SDG':>4}  {'Title':<32}  {'QDef':>4}  {'QL':>4}  {'Aurora':>7}  {'Composed':>8}  {'>25k':>6}"
SEP = "-" * len(HDR)
print(HDR)
print(SEP)
for r in records:
    flag = "*** YES" if r["warning_over_25k_chars"] == "yes" else "no"
    print(
        f"{r['sdg_number']:>4}  {r['sdg_title'][:32]:<32}  "
        f"{r['n_query_definitions']:>4}  {r['n_query_lines']:>4}  "
        f"{r['aurora_content_length_chars']:>7,}  {r['composed_length_chars']:>8,}  "
        f"{flag:>7}"
    )

total_lines = sum(r["n_query_lines"] for r in records)
avg_comp    = sum(r["composed_length_chars"] for r in records) / len(records)
max_rec     = max(records, key=lambda r: r["composed_length_chars"])
min_rec     = min(records, key=lambda r: r["composed_length_chars"])
splits      = [r["sdg_number"] for r in records if r["warning_over_25k_chars"] == "yes"]

print(SEP)
print(f"\nTotal query-lines (17 SDGs)  : {total_lines}")
print(f"Average composed length      : {avg_comp:,.0f} chars")
print(f"Max composed length          : {max_rec['composed_length_chars']:,} chars  (SDG {max_rec['sdg_number']})")
print(f"Min composed length          : {min_rec['composed_length_chars']:,} chars  (SDG {min_rec['sdg_number']})")

if splits:
    print(f"\nSub-region splits generated  : {', '.join('SDG' + s for s in splits)}")
else:
    print("\nNo queries exceeded 25,000 characters – no splits needed.")

# Visual verification – first 200 chars of SDG 02
sdg2_text = (OUT / "SDG02_full.txt").read_text(encoding="utf-8")
print(f"\n--- First 200 chars of SDG 02 composed query ---")
print(sdg2_text[:200])
print("...")

print(f"\n[DONE] Output files written to {OUT}")
print(f"  {len(records)} _full.txt files")
split_count = len(splits)
print(f"  {split_count * 2} split files ({split_count} SDGs × 2 parts)")
print(f"  _query_lengths.csv")
print(f"  _aurora_provenance.txt")
