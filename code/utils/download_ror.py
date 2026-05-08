"""download_ror.py
Stage 3b – Download the latest ROR data dump from Zenodo, extract the
v2 JSON, filter to the 54 AU member states, and write provenance files.

Run from article08/:
    python code/utils/download_ror.py
"""

import csv
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

# ── bootstrap ─────────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent          # code/utils/
ARTICLE = HERE.parents[1]                          # article08/
sys.path.insert(0, str(HERE.parent))               # adds code/ so utils.x works

from utils.config import cfg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── paths ─────────────────────────────────────────────────────────────────────
ROR_RAW   = ARTICLE / "data" / "external" / "ror" / "raw"
ROR_DIR   = ARTICLE / "data" / "external" / "ror"
PROV      = ARTICLE / cfg["paths"]["provenance"]
CLIST     = ARTICLE / cfg["paths"]["country_list"]

ROR_AFRICA_JSON   = ROR_DIR  / "ror_africa_v2.json"
SNAPSHOT_TXT      = PROV     / "stage3_ror_snapshot.txt"
COUNTRY_COUNTS    = PROV     / "stage3_ror_country_counts.csv"

ROR_RAW.mkdir(parents=True, exist_ok=True)
ROR_DIR.mkdir(parents=True, exist_ok=True)

# ── AU-54 ISO-2 set ───────────────────────────────────────────────────────────
AU54_ISO2 = {
    "DZ","AO","BJ","BW","BF","BI","CV","CM","CF","TD",
    "KM","CG","CI","CD","DJ","EG","GQ","ER","SZ","ET",
    "GA","GM","GH","GN","GW","KE","LS","LR","LY","MG",
    "MW","ML","MR","MU","MA","MZ","NA","NE","NG","RW",
    "ST","SN","SC","SL","SO","ZA","SS","SD","TZ","TG",
    "TN","UG","ZM","ZW",
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – Query Zenodo for latest ROR release
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
print(" STAGE 3b – ROR DATA DOWNLOAD & AFRICA FILTER")
print("=" * 62)

print("\nStep 1 – Querying Zenodo for latest ROR release …")
resp = requests.get(
    "https://zenodo.org/api/records/6347574/versions/latest",
    headers={"Accept": "application/json"},
    timeout=30,
)
resp.raise_for_status()
data = resp.json()

zenodo_id    = data["id"]
pub_date     = data["metadata"]["publication_date"]
zenodo_doi   = data["doi"]

print(f"  Zenodo record ID : {zenodo_id}")
print(f"  Publication date : {pub_date}")
print(f"  DOI              : {zenodo_doi}")

# Find the ZIP file entry
zip_entry = next(
    (f for f in data["files"] if f["key"].endswith(".zip")),
    None,
)
if zip_entry is None:
    print("ERROR: No .zip file found in Zenodo record. Files available:")
    for f in data["files"]:
        print(f"  {f['key']}")
    sys.exit(1)

zip_key      = zip_entry["key"]
zip_url      = zip_entry["links"]["self"]
zip_size     = zip_entry["size"]
zip_path     = ROR_RAW / zip_key

print(f"  ZIP file         : {zip_key}  ({zip_size/1e6:.1f} MB)")
print(f"  Download URL     : {zip_url}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – Download ZIP with progress bar
# ─────────────────────────────────────────────────────────────────────────────
print(f"\nStep 2 – Downloading {zip_key} …")

if zip_path.exists() and zip_path.stat().st_size == zip_size:
    print(f"  Already present and size matches — skipping download.")
else:
    with requests.get(zip_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as fh, tqdm(
            total=zip_size,
            unit="B", unit_scale=True,
            desc=zip_key,
            ncols=70,
        ) as bar:
            for chunk in r.iter_content(chunk_size=65536):
                fh.write(chunk)
                bar.update(len(chunk))
    print(f"  Downloaded: {zip_path.stat().st_size/1e6:.1f} MB")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – Locate v2 JSON inside the ZIP
# ─────────────────────────────────────────────────────────────────────────────
print(f"\nStep 3 – Inspecting ZIP contents …")
with zipfile.ZipFile(zip_path, "r") as zf:
    members = zf.namelist()
    v2_members = [m for m in members if "v2" in m and m.endswith(".json")]
    print(f"  Total ZIP members : {len(members)}")
    print(f"  v2 JSON candidates: {v2_members}")

    if not v2_members:
        print("ERROR: No v2 JSON found. All members:")
        for m in members:
            print(f"  {m}")
        sys.exit(1)

    v2_member = v2_members[0]
    print(f"  Selected          : {v2_member}")

    # Derive version string from filename, e.g. "v2.1-2025-07"
    stem = Path(v2_member).stem   # e.g. "v2.1-2025-07-29-ror-data"
    # Extract the v2.x-YYYY-MM part
    import re
    ver_match = re.search(r"(v2[\w.-]+?\d{4}-\d{2})", stem)
    ror_version = ver_match.group(1) if ver_match else stem

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – Extract v2 JSON to ROR_DIR
# ─────────────────────────────────────────────────────────────────────────────
print(f"\nStep 4 – Extracting {v2_member} …")
ror_json_path = ROR_DIR / "ror_data_v2_latest.json"

with zipfile.ZipFile(zip_path, "r") as zf:
    with zf.open(v2_member) as src, open(ror_json_path, "wb") as dst:
        while True:
            chunk = src.read(65536)
            if not chunk:
                break
            dst.write(chunk)

json_size_mb = ror_json_path.stat().st_size / 1e6
print(f"  Extracted to      : {ror_json_path.name}  ({json_size_mb:.1f} MB)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 – SHA-256 and provenance snapshot
# ─────────────────────────────────────────────────────────────────────────────
print(f"\nStep 5 – Computing SHA-256 …")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

ror_sha256    = sha256(ror_json_path)
dl_timestamp  = datetime.now(timezone.utc).isoformat()

snapshot_lines = [
    f"zenodo_record_id     : {zenodo_id}",
    f"zenodo_doi           : {zenodo_doi}",
    f"ror_version          : {ror_version}",
    f"release_date         : {pub_date}",
    f"sha256_json          : {ror_sha256}",
    f"json_size_mb         : {json_size_mb:.2f}",
    f"zip_size_mb          : {zip_size/1e6:.2f}",
    f"download_timestamp   : {dl_timestamp}",
    f"source_url           : {zip_url}",
]
SNAPSHOT_TXT.write_text("\n".join(snapshot_lines) + "\n", encoding="utf-8")
print(f"  Snapshot written  : {SNAPSHOT_TXT.name}")
print(f"  SHA-256           : {ror_sha256[:16]}…")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 – Parse and filter to AU-54
# ─────────────────────────────────────────────────────────────────────────────
print(f"\nStep 7 – Parsing ROR JSON and filtering to AU-54 …")

with open(ror_json_path, encoding="utf-8") as f:
    all_records = json.load(f)

total_records = len(all_records)
print(f"  Total records     : {total_records:,}")

africa_records = []
country_code_map = {}   # record_id -> set of country codes

for rec in all_records:
    codes = set()
    for loc in rec.get("locations", []):
        cc = (loc.get("geonames_details") or {}).get("country_code")
        if cc:
            codes.add(cc)
    country_code_map[rec["id"]] = codes
    if codes & AU54_ISO2:
        africa_records.append(rec)

n_africa = len(africa_records)
print(f"  Africa records    : {n_africa:,}  ({100*n_africa/total_records:.2f}% of full dump)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 – Write Africa JSON
# ─────────────────────────────────────────────────────────────────────────────
print(f"\nStep 8 – Writing ror_africa_v2.json …")
with open(ROR_AFRICA_JSON, "w", encoding="utf-8") as f:
    json.dump(africa_records, f, ensure_ascii=False, indent=2)
print(f"  Written: {ROR_AFRICA_JSON.stat().st_size/1e6:.1f} MB  ({n_africa:,} records)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 – Per-country counts and CSV
# ─────────────────────────────────────────────────────────────────────────────
print(f"\nStep 9 – Computing per-country ROR counts …")

# Load au54 country list (iso3 -> iso2 not directly available; we have iso3)
# au54_countries.csv has: iso3, country_name_scopus, country_name_official, subregion
# We need iso2. Build from our AU54_ISO2 set paired with the CSV.
# The CSV doesn't have iso2; map from the known AU54 iso2 list.

ISO3_TO_ISO2 = {
    "DZA":"DZ","AGO":"AO","BEN":"BJ","BWA":"BW","BFA":"BF","BDI":"BI",
    "CPV":"CV","CMR":"CM","CAF":"CF","TCD":"TD","COM":"KM","COG":"CG",
    "CIV":"CI","COD":"CD","DJI":"DJ","EGY":"EG","GNQ":"GQ","ERI":"ER",
    "SWZ":"SZ","ETH":"ET","GAB":"GA","GMB":"GM","GHA":"GH","GIN":"GN",
    "GNB":"GW","KEN":"KE","LSO":"LS","LBR":"LR","LBY":"LY","MDG":"MG",
    "MWI":"MW","MLI":"ML","MRT":"MR","MUS":"MU","MAR":"MA","MOZ":"MZ",
    "NAM":"NA","NER":"NE","NGA":"NG","RWA":"RW","STP":"ST","SEN":"SN",
    "SYC":"SC","SLE":"SL","SOM":"SO","ZAF":"ZA","SSD":"SS","SDN":"SD",
    "TZA":"TZ","TGO":"TG","TUN":"TN","UGA":"UG","ZMB":"ZM","ZWE":"ZW",
}

# Count ROR records per iso2
iso2_counts = {iso2: 0 for iso2 in AU54_ISO2}
for rec in africa_records:
    codes = set()
    for loc in rec.get("locations", []):
        cc = (loc.get("geonames_details") or {}).get("country_code")
        if cc and cc in AU54_ISO2:
            codes.add(cc)
    for cc in codes:
        iso2_counts[cc] += 1

# Load scopus country names from CSV
scopus_names = {}   # iso2 -> country_name_scopus
with open(CLIST, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        iso3 = row.get("iso3", "").strip()
        name = row.get("country_name_scopus", "").strip()
        if iso3 in ISO3_TO_ISO2:
            scopus_names[ISO3_TO_ISO2[iso3]] = name

# Build rows sorted by count descending
count_rows = sorted(
    [{"iso2": iso2,
      "country_name_scopus": scopus_names.get(iso2, iso2),
      "ror_record_count": cnt}
     for iso2, cnt in iso2_counts.items()],
    key=lambda r: -r["ror_record_count"],
)

with open(COUNTRY_COUNTS, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["iso2","country_name_scopus","ror_record_count"])
    writer.writeheader()
    writer.writerows(count_rows)
print(f"  Written: {COUNTRY_COUNTS.name}")

# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL REPORT
# ─────────────────────────────────────────────────────────────────────────────
SEP  = "─" * 62
SEP2 = "=" * 62

print(f"\n{SEP2}")
print(" REPORT")
print(SEP2)

print(f"\n{SEP}\nA. DOWNLOAD\n{SEP}")
print(f"   Zenodo record ID : {zenodo_id}")
print(f"   ROR version      : {ror_version}")
print(f"   Release date     : {pub_date}")
print(f"   ZIP size         : {zip_size/1e6:.1f} MB")
print(f"   JSON size        : {json_size_mb:.1f} MB")

print(f"\n{SEP}\nB. COVERAGE\n{SEP}")
print(f"   Total records (full dump) : {total_records:,}")
print(f"   Africa subset records     : {n_africa:,}")
print(f"   Africa % of full dump     : {100*n_africa/total_records:.2f}%")

print(f"\n{SEP}\nC. PER-COUNTRY ROR COUNTS (all 54)\n{SEP}")
zero_countries = []
print(f"   {'ISO2':<5}  {'Country':<35}  {'ROR records':>11}")
print(f"   {'----':<5}  {'-------':<35}  {'-----------':>11}")
for r in count_rows:
    flag = "  *** ZERO" if r["ror_record_count"] == 0 else ""
    print(f"   {r['iso2']:<5}  {r['country_name_scopus']:<35}  {r['ror_record_count']:>11,}{flag}")
    if r["ror_record_count"] == 0:
        zero_countries.append(r["iso2"])

if zero_countries:
    print(f"\n   *** Countries with 0 ROR records: {zero_countries}")
else:
    print(f"\n   All 54 countries have at least 1 ROR record.")

print(f"\n{SEP}\nD. TOP 10 COUNTRIES BY ROR RECORD COUNT\n{SEP}")
for r in count_rows[:10]:
    print(f"   {r['iso2']}  {r['country_name_scopus']:<35}  {r['ror_record_count']:>7,}")

print(f"\n{SEP2}\n STAGE 3b COMPLETE\n{SEP2}\n")
