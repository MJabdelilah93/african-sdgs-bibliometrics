"""01_stage2_acquisition_manifest.py
Stage 2 – Build acquisition manifest, checksums, and verification report
from raw Scopus CSV exports in data/raw/.
"""

import sys
import re
import hashlib
import warnings
from collections import defaultdict
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

# ensure Unicode output works on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── paths ─────────────────────────────────────────────────────────────────────
ARTICLE  = Path(__file__).resolve().parent.parent
RAW      = ARTICLE / "data" / "raw"
COMPOSED = ARTICLE / "sdg_queries" / "composed"
PROV     = ARTICLE / "provenance"
LOGS     = PROV / "logs"
CLIST    = ARTICLE / "country_lists"

MANIFEST_PATH  = PROV  / "stage2_acquisition_manifest.csv"
CHECKSUMS_PATH = PROV  / "stage2_checksums.txt"
VERIFY_PATH    = LOGS  / "stage2_verification.md"
SDG_NAMES_PATH = CLIST / "sdg_names.csv"

# ── constants ─────────────────────────────────────────────────────────────────
SDG_NAMES = {
     1: "No Poverty",
     2: "Zero Hunger",
     3: "Good Health and Well-being",
     4: "Quality Education",
     5: "Gender Equality",
     6: "Clean Water and Sanitation",
     7: "Affordable and Clean Energy",
     8: "Decent Work and Economic Growth",
     9: "Industry, Innovation and Infrastructure",
    10: "Reduced Inequalities",
    11: "Sustainable Cities and Communities",
    12: "Responsible Consumption and Production",
    13: "Climate Action",
    14: "Life Below Water",
    15: "Life on Land",
    16: "Peace, Justice and Strong Institutions",
    17: "Partnerships for the Goals",
}

REQUIRED_COLS = [
    "Authors", "Title", "Year", "Source title", "DOI", "Affiliations",
    "Author Keywords", "Index Keywords", "Abstract", "Document Type", "Cited by",
]

FRAMEWORK = "Aurora_v5.0.3"
EXPECTED  = 41

FILE_RE = re.compile(
    r"^SDG(\d{2})_AU54_(\d{4}-\d{2}-\d{2})(?:_(\d{4})-(\d{4}))?\.csv$"
)

SEP = "─" * 62


# ── helpers ───────────────────────────────────────────────────────────────────

def parse_filename(name):
    m = FILE_RE.match(name)
    if not m:
        return None
    return int(m.group(1)), m.group(2), \
           (int(m.group(3)) if m.group(3) else None), \
           (int(m.group(4)) if m.group(4) else None)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_safe(path):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
            return df, enc
        except Exception:
            continue
    raise RuntimeError(f"Cannot decode {path.name} with any supported encoding")


def query_file_for(sdg, y1, y2):
    nn = f"{sdg:02d}"
    if y1 is not None:
        return COMPOSED / f"SDG{nn}_full_{y1}-{y2}.txt"
    return COMPOSED / f"SDG{nn}_full.txt"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – Collect CSV files
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*62}")
print(" STAGE 2 – ACQUISITION MANIFEST & VERIFICATION")
print(f"{'='*62}")

csv_files = sorted(
    [f for f in RAW.iterdir() if FILE_RE.match(f.name)],
    key=lambda f: f.name,
)
bad_names = [
    f.name for f in RAW.iterdir()
    if f.suffix == ".csv" and not FILE_RE.match(f.name)
]

print(f"\nStep 1 – CSV inventory")
print(f"  Files matching pattern : {len(csv_files)}  (expected {EXPECTED})")
if bad_names:
    print(f"  ⚠  Skipped (name mismatch): {bad_names}")
if len(csv_files) != EXPECTED:
    print(f"  ⚠  COUNT MISMATCH — expected {EXPECTED}, got {len(csv_files)}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – Load AU54 country list
# ─────────────────────────────────────────────────────────────────────────────
au54_df = pd.read_csv(CLIST / "au54_countries.csv", dtype=str).dropna(
    subset=["country_name_scopus"]
)
country_names = sorted(
    [c.strip() for c in au54_df["country_name_scopus"] if c.strip()],
    key=len, reverse=True,   # longest first → "Democratic Republic Congo" before "Congo"
)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – Read every CSV: checksum, row count, schema, aggregates
# ─────────────────────────────────────────────────────────────────────────────
print(f"\nStep 3 – Reading {len(csv_files)} CSV files …")

file_info     = {}                  # fname -> dict
schema_flags  = []                  # (fname, [missing cols])
query_flags   = []                  # (fname, missing query file name)
bad_parse     = []
checksums     = {}
year_counts   = defaultdict(int)    # pub year  -> record count
country_counts = defaultdict(int)   # country   -> record count (≥1 author)
sdg_records   = defaultdict(int)    # sdg_num   -> total records

col_report = {}   # from first file only

for f in csv_files:
    parsed = parse_filename(f.name)
    if parsed is None:
        bad_parse.append(f.name)
        continue
    sdg, date, y1, y2 = parsed

    # checksum
    cksum = sha256(f)
    checksums[f.name] = cksum

    # read
    try:
        df, enc = read_csv_safe(f)
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    n = len(df)
    actual_cols  = list(df.columns)
    actual_lower = {c.lower(): c for c in actual_cols}

    # schema check (case-insensitive)
    missing_req = []
    found_req   = {}
    for req in REQUIRED_COLS:
        key = req.lower()
        if key in actual_lower:
            found_req[req] = actual_lower[key]
        else:
            missing_req.append(req)
    if missing_req:
        schema_flags.append((f.name, missing_req))
    if not col_report:
        col_report = {
            "all_columns": actual_cols,
            "missing_required": missing_req,
            "found_required": found_req,
        }

    # query file existence
    qf = query_file_for(sdg, y1, y2)
    if not qf.exists():
        query_flags.append((f.name, qf.name))

    # publication year distribution
    year_col = found_req.get("Year")
    if year_col:
        for v in df[year_col].dropna():
            try:
                year_counts[int(v)] += 1
            except ValueError:
                pass

    # country contribution (distinct countries per record)
    aff_col = found_req.get("Affiliations")
    if aff_col:
        for affil_str in df[aff_col].dropna():
            affil_lower = affil_str.lower()
            seen = set()
            for part in affil_str.split(";"):
                part_lower = part.lower()
                for cname in country_names:
                    if cname.lower() in part_lower:
                        seen.add(cname)
                        break   # one country per affiliation entry
            for c in seen:
                country_counts[c] += 1

    sdg_records[sdg] += n

    file_info[f.name] = {
        "sdg": sdg, "date": date, "y1": y1, "y2": y2,
        "count": n, "query_file": qf, "cksum": cksum,
    }
    yr_tag = f"{y1}-{y2}" if y1 else "full"
    print(f"  SDG{sdg:02d} [{yr_tag:<9}]  {n:>6,} rows   {f.name}")

total_records = sum(sdg_records.values())

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – SDG names CSV
# ─────────────────────────────────────────────────────────────────────────────
pd.DataFrame(
    [{"sdg_number": k, "sdg_name": v} for k, v in sorted(SDG_NAMES.items())]
).to_csv(SDG_NAMES_PATH, index=False)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 – Build manifest (sort by sdg_number, then y1)
# ─────────────────────────────────────────────────────────────────────────────
sdg_parts = defaultdict(list)
for fname, info in file_info.items():
    sdg_parts[info["sdg"]].append((fname, info))
for sdg in sdg_parts:
    sdg_parts[sdg].sort(key=lambda x: x[1]["y1"] or 0)

manifest_rows = []
for sdg in sorted(sdg_parts.keys()):
    parts  = sdg_parts[sdg]
    n_parts = len(parts)
    for idx, (fname, info) in enumerate(parts, 1):
        manifest_rows.append({
            "sdg_number":        sdg,
            "sdg_name":          SDG_NAMES[sdg],
            "export_date":       info["date"],
            "raw_record_count":  info["count"],
            "query_string_file": info["query_file"].name,
            "export_filename":   fname,
            "split_reason":      "year_split_20k_cap" if n_parts > 1 else "",
            "framework":         FRAMEWORK,
            "notes":             f"part {idx} of {n_parts}" if n_parts > 1 else "",
        })

pd.DataFrame(manifest_rows).to_csv(MANIFEST_PATH, index=False)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 – Checksums
# ─────────────────────────────────────────────────────────────────────────────
with open(CHECKSUMS_PATH, "w", encoding="utf-8") as fh:
    for fname in sorted(checksums):
        fh.write(f"{checksums[fname]}  {fname}\n")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 – SDG coverage
# ─────────────────────────────────────────────────────────────────────────────
detected_sdgs = set(sdg_parts.keys())
missing_sdgs  = set(range(1, 18)) - detected_sdgs

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 – Year coverage for split SDGs
# ─────────────────────────────────────────────────────────────────────────────
year_gaps     = {}
year_overlaps = {}

for sdg, parts in sdg_parts.items():
    if len(parts) <= 1:
        continue
    ranges = sorted(
        [(info["y1"], info["y2"]) for _, info in parts if info["y1"] is not None]
    )
    if not ranges:
        continue
    expected = 2015
    gaps, overlaps = [], []
    for y1, y2 in ranges:
        if y1 > expected:
            gaps.append((expected, y1 - 1))
        elif y1 < expected:
            overlaps.append((y1, expected - 1))
        expected = y2 + 1
    if expected <= 2025:
        gaps.append((expected, 2025))
    if gaps:
        year_gaps[sdg] = gaps
    if overlaps:
        year_overlaps[sdg] = overlaps

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 – Top 15 countries
# ─────────────────────────────────────────────────────────────────────────────
top15 = sorted(country_counts.items(), key=lambda x: -x[1])[:15]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 10 – Write verification report
# ─────────────────────────────────────────────────────────────────────────────
lines = []
A = lines.append

A("# Stage 2 Verification Report\n")
A("Generated: 2026-05-08  \n")
A("Script: `code/01_stage2_acquisition_manifest.py`\n")

A("\n## File inventory\n")
A(f"- CSV files found: **{len(file_info)}** (expected {EXPECTED})")
if len(file_info) != EXPECTED:
    A(f"- ⚠ COUNT MISMATCH")
if bad_parse:
    A(f"- ⚠ Unparseable filenames: {bad_parse}")
A("")
A("| # | File | SDG | Year range | Records |")
A("|---|------|-----|-----------|---------|")
for i, (fname, info) in enumerate(sorted(file_info.items()), 1):
    yr = f"{info['y1']}-{info['y2']}" if info["y1"] else "full"
    A(f"| {i} | `{fname}` | SDG{info['sdg']:02d} | {yr} | {info['count']:,} |")

A("\n## Records summary\n")
A(f"**Total raw records: {total_records:,}**\n")
A("| SDG | Name | Records |")
A("|-----|------|---------|")
for sdg in sorted(sdg_records.keys()):
    A(f"| SDG{sdg:02d} | {SDG_NAMES[sdg]} | {sdg_records[sdg]:,} |")

A("\n## Schema validation\n")
if col_report:
    all_c = col_report["all_columns"]
    A(f"First file checked has **{len(all_c)} columns**.")
    A("")
    A("**All Scopus columns found:**")
    A(", ".join(f"`{c}`" for c in all_c))
    A("")
    found_names = sorted(col_report["found_required"].keys())
    A(f"**Required columns — found ({len(found_names)}/{len(REQUIRED_COLS)}):** "
      + ", ".join(f"`{c}`" for c in found_names))
if schema_flags:
    A("\n⚠ **Missing required columns:**")
    for fname, miss in schema_flags:
        A(f"  - `{fname}`: {miss}")
else:
    A("\n✓ All required columns present across all files.")

A("\n## SDG coverage\n")
if missing_sdgs:
    A(f"⚠ Missing SDGs: {sorted(missing_sdgs)}")
else:
    A("✓ All SDGs 1–17 represented.")

A("\n## Year coverage\n")
cover_ok = not year_gaps and not year_overlaps
if cover_ok:
    A("✓ All split SDGs cover 2015–2025 with no gaps or overlaps.")
if year_gaps:
    A("⚠ **Year gaps detected:**")
    for sdg, g in year_gaps.items():
        A(f"  - SDG{sdg:02d}: {g}")
if year_overlaps:
    A("⚠ **Year overlaps detected:**")
    for sdg, o in year_overlaps.items():
        A(f"  - SDG{sdg:02d}: {o}")

for sdg, parts in sorted(sdg_parts.items()):
    if len(parts) > 1:
        ranges = [(info["y1"], info["y2"]) for _, info in parts if info["y1"]]
        status = "✓" if sdg not in year_gaps and sdg not in year_overlaps else "⚠"
        A(f"  {status} SDG{sdg:02d}: " + ", ".join(f"{a}-{b}" for a, b in ranges))

A("\n## Aggregates\n")
A("### Records per publication year\n")
A("| Year | Records |")
A("|------|---------|")
for yr in sorted(year_counts.keys()):
    A(f"| {yr} | {year_counts[yr]:,} |")

A("\n## Top 15 countries\n")
A("*(Raw counts — papers with ≥1 author from that country; before deduplication)*\n")
A("| Rank | Country | Papers |")
A("|------|---------|--------|")
for rank, (c, cnt) in enumerate(top15, 1):
    A(f"| {rank} | {c} | {cnt:,} |")

A("\n## Flags / warnings\n")
flags = []
if schema_flags:
    flags.append(f"- ⚠ Schema issues: {len(schema_flags)} file(s)")
if query_flags:
    flags.append(f"- ⚠ Missing query files: {[q[1] for q in query_flags]}")
if missing_sdgs:
    flags.append(f"- ⚠ Missing SDGs: {sorted(missing_sdgs)}")
if year_gaps:
    flags.append(f"- ⚠ Year gaps: SDGs {sorted(year_gaps.keys())}")
if year_overlaps:
    flags.append(f"- ⚠ Year overlaps: SDGs {sorted(year_overlaps.keys())}")
if bad_parse:
    flags.append(f"- ⚠ Unparseable filenames: {bad_parse}")
if not flags:
    flags.append("- ✓ No flags — all checks passed.")
lines.extend(flags)

VERIFY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL REPORT
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("A. FILE INVENTORY")
print(SEP)
print(f"   CSV files found   : {len(file_info)}")
print(f"   Expected          : {EXPECTED}")
print(f"   Distinct SDGs     : {sorted(detected_sdgs)}")

print(f"\n{SEP}")
print("B. RECORDS SUMMARY")
print(SEP)
print(f"   Total raw records : {total_records:,}\n")
print("   Per-SDG totals (descending by count):")
for sdg, cnt in sorted(sdg_records.items(), key=lambda x: -x[1]):
    bar = "█" * min(40, cnt // 2000)
    print(f"     SDG{sdg:02d}  {SDG_NAMES[sdg]:<42}  {cnt:>7,}  {bar}")

print()
all_sorted = sorted(file_info.items(), key=lambda x: -x[1]["count"])
print("   Top 5 largest exports:")
for fname, info in all_sorted[:5]:
    print(f"     {info['count']:>7,}   {fname}")
print("   Smallest 5 exports:")
for fname, info in all_sorted[-5:]:
    print(f"     {info['count']:>7,}   {fname}")

print(f"\n{SEP}")
print("C. VALIDATION FLAGS")
print(SEP)
ok = "✓"
print(f"   Missing required columns : {ok if not schema_flags  else f'⚠  {schema_flags}'}")
print(f"   Missing query files      : {ok if not query_flags   else f'⚠  {[q[1] for q in query_flags]}'}")
print(f"   SDG coverage gaps        : {ok if not missing_sdgs  else f'⚠  {sorted(missing_sdgs)}'}")
print(f"   Year coverage gaps       : {ok if not year_gaps     else f'⚠  {year_gaps}'}")
print(f"   Year overlaps            : {ok if not year_overlaps else f'⚠  {year_overlaps}'}")
print(f"   Filename parse errors    : {ok if not bad_parse     else f'⚠  {bad_parse}'}")

print(f"\n{SEP}")
print("D. TOP 15 CONTRIBUTING COUNTRIES  (raw, pre-dedup)")
print(SEP)
for rank, (c, cnt) in enumerate(top15, 1):
    print(f"   {rank:>2}.  {c:<35}  {cnt:>7,}")

print(f"\n{SEP}")
print("E. FILES GENERATED")
print(SEP)
print(f"   {MANIFEST_PATH.relative_to(ARTICLE)}")
print(f"   {CHECKSUMS_PATH.relative_to(ARTICLE)}")
print(f"   {VERIFY_PATH.relative_to(ARTICLE)}")
print(f"   {SDG_NAMES_PATH.relative_to(ARTICLE)}")

print(f"\n{'='*62}")
print(" STAGE 2 COMPLETE – DO NOT COMMIT YET")
print(f"{'='*62}\n")
