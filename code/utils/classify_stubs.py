"""classify_stubs.py
Auto-generate stub entries for stage3_manual_overrides.csv from the
2,264 AU-54 unresolved strings in stage3_african_affiliations_to_review.csv.

Run from article08/:
    python code/utils/classify_stubs.py
"""

import csv
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

from utils.config import cfg

REVIEW_IN   = ARTICLE / "provenance" / "stage3_african_affiliations_to_review.csv"
OVERRIDES   = ARTICLE / "provenance" / "stage3_manual_overrides.csv"
INST_OUT    = ARTICLE / "provenance" / "stage3_institutions_to_review.csv"
CLIST       = ARTICLE / cfg["paths"]["country_list"]

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

# ── build country name set ─────────────────────────────────────────────────
country_names: set[str] = set()

with open(CLIST, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        iso3 = row.get("iso3", "").strip()
        if iso3 not in ISO3_TO_ISO2:
            continue
        for field in ("country_name_scopus", "country_name_official"):
            n = row.get(field, "").strip()
            if n:
                country_names.add(n.lower())

# add common Scopus aliases
_COUNTRY_ALIASES = {
    "south africa", "nigeria", "kenya", "egypt", "ethiopia", "ghana",
    "tanzania", "uganda", "morocco", "algeria", "cameroon", "tunisia",
    "dr congo", "democratic republic of congo", "republic of congo", "congo",
    "ivory coast", "cote d ivoire", "burkina faso", "sierra leone",
    "liberia", "zimbabwe", "zambia", "senegal", "mali", "malawi",
    "mozambique", "botswana", "namibia", "rwanda", "benin", "angola",
    "sudan", "south sudan", "somalia", "niger", "chad", "guinea",
    "guinea-bissau", "equatorial guinea", "gabon", "togo", "mauritius",
    "madagascar", "eritrea", "djibouti", "comoros", "cabo verde",
    "eswatini", "swaziland", "lesotho", "gambia", "burundi",
    "mauritania", "seychelles", "central african republic",
    "sao tome and principe", "libya", "côte d'ivoire",
    "democratic republic of the congo", "republic of the congo",
}
country_names.update(_COUNTRY_ALIASES)

# institution keywords — presence means segment is NOT a stub
_INST_KW = re.compile(
    r"\b(university|universit[eéè]|universidade|universite|universite|"
    r"college|institut[eo]?|hospital|centre|center|school|academy|"
    r"ministry|department|conseil|council|authority|foundation|"
    r"laboratory|laboratoire|clinic|research|national|regional|"
    r"polytechnic|faculty|facult[eé]|municipalit|government|"
    r"agenc[yi]|bureau|commission|organisation|organization|"
    r"programme|program|office|division|unit|board|trust|"
    r"association|society|network|forum|alliance|coalition|"
    r"project|initiative|enterprise|corps|service)\b",
    re.IGNORECASE,
)

# stub generic descriptors (rule 4)
_GENERIC = {
    "private practice", "freelance", "independent researcher",
    "self-employed", "consultant", "retired",
}

# postal-code patterns (rule 3)
_POSTCODE = re.compile(r"\b(p\.?o\.?\s*box|\d{4,6})\b", re.IGNORECASE)


def classify_stub(raw: str):
    """Return (rule_num, reason) or (None, None) if not a stub."""
    stripped = raw.strip()
    lower    = stripped.lower()
    parts    = [p.strip() for p in stripped.split(",")]
    parts_lo = [p.lower() for p in parts]

    # Rule 1 — country-only
    core = re.sub(r"\s+", " ", lower).strip()
    if core in country_names:
        return 1, "Stub — country name only"

    # Rule 2 — city + country only (exactly 2 tokens, second is country)
    if len(parts) == 2 and parts_lo[1].strip() in country_names:
        # first token must not contain institution keywords
        if not _INST_KW.search(parts[0]):
            return 2, "Stub — city and country only"

    # Rule 3 — postal address stub (contains postcode/PO box but no inst keyword)
    if _POSTCODE.search(stripped) and not _INST_KW.search(stripped):
        return 3, "Stub — postal address without institution name"

    # Rule 4 — generic descriptor
    # strip trailing country suffix for comparison
    core_no_country = parts_lo[0].strip() if parts else lower
    if core_no_country in _GENERIC:
        return 4, "Stub — generic descriptor"

    return None, None


# ── load review rows ───────────────────────────────────────────────────────
review_rows = []
with open(REVIEW_IN, encoding="utf-8") as f:
    review_fieldnames = list((csv.DictReader(f)).fieldnames or [])

with open(REVIEW_IN, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        review_rows.append(row)

stubs       = []   # (row, rule_num, reason)
institutions = []  # row

for row in review_rows:
    rule, reason = classify_stub(row["segment_raw"])
    if rule is not None:
        stubs.append((row, rule, reason))
    else:
        institutions.append(row)

# ── write overrides CSV (append if exists, create header otherwise) ────────
override_fields = ["raw_string", "ror_id", "reviewer_initials", "date", "decision_reason"]
override_exists = False  # always overwrite to avoid carrying forward false positives

with open(OVERRIDES, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=override_fields)
    writer.writeheader()
    for row, rule, reason in stubs:
        writer.writerow({
            "raw_string"       : row["segment_raw"],
            "ror_id"           : "",
            "reviewer_initials": "AUTO",
            "date"             : "2026-05-08",
            "decision_reason"  : reason,
        })

# ── write institutions-to-review CSV ──────────────────────────────────────
with open(INST_OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=review_fieldnames)
    writer.writeheader()
    writer.writerows(institutions)  # already sorted by frequency descending

# ── report ─────────────────────────────────────────────────────────────────
SEP  = "-" * 70
SEP2 = "=" * 70

rule_counts = {1: 0, 2: 0, 3: 0, 4: 0}
for _, rule, _ in stubs:
    rule_counts[rule] += 1

print(f"\n{SEP2}")
print(" STUB CLASSIFICATION REPORT")
print(SEP2)

print(f"\n{SEP}\nA. CLASSIFICATION SUMMARY\n{SEP}")
print(f"  Total rows in review file  : {len(review_rows):>6,}")
print(f"  Classified as stubs        : {len(stubs):>6,}  ({100*len(stubs)/len(review_rows):.1f}%)")
print(f"  Remaining for manual review: {len(institutions):>6,}")
print(f"\n  Breakdown by rule:")
print(f"    Rule 1 (country-only)        : {rule_counts[1]:>4,}")
print(f"    Rule 2 (city + country)      : {rule_counts[2]:>4,}")
print(f"    Rule 3 (postal address)      : {rule_counts[3]:>4,}")
print(f"    Rule 4 (generic descriptor)  : {rule_counts[4]:>4,}")

print(f"\n{SEP}\nB. TOP 10 STUBS BY FREQUENCY\n{SEP}")
top_stubs = sorted(stubs, key=lambda x: -int(x[0]["frequency"]))[:10]
print(f"  {'Freq':>5}  {'Rule':>4}  {'Segment':<60}  {'Reason'}")
print(f"  {'----':>5}  {'----':>4}  {'-'*60}  {'------'}")
for row, rule, reason in top_stubs:
    seg = row["segment_raw"][:60]
    print(f"  {int(row['frequency']):>5,}  R{rule:<3}  {seg:<60}  {reason}")

print(f"\n{SEP}\nC. TOP 30 GENUINE INSTITUTIONS FOR MANUAL REVIEW\n{SEP}")
hdr = (f"  {'Segment (100c)':<100}  {'Freq':>5}  "
       f"{'Hints':<10}  {'Top-1 display':<45}  {'Sc':>5}")
print(hdr)
print("  " + "-" * (len(hdr) - 2))
for row in institutions[:30]:
    seg  = row["segment_raw"][:100]
    freq = int(row["frequency"])
    hint = row.get("hint_countries", "")
    t1   = row.get("top1_display", "")[:45]
    s1   = row.get("top1_score", "0")
    try:
        s1f = float(s1)
    except ValueError:
        s1f = 0.0
    print(f"  {seg:<100}  {freq:>5,}  {hint:<10}  {t1:<45}  {s1f:>5.1f}")

print(f"\n{SEP}\nD. FILES WRITTEN\n{SEP}")
print(f"  provenance/stage3_manual_overrides.csv")
print(f"    created (overwritten) {len(stubs):,} stub rows")
print(f"  provenance/stage3_institutions_to_review.csv")
print(f"    {len(institutions):,} rows for genuine manual review")

print(f"\n{SEP2}\n")
