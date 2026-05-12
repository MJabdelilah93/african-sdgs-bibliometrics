"""analyse_review.py – one-off analysis of stage3_manual_review.csv.
Filters for genuinely unresolved African affiliations (segments that had
an AU-54 country hint but still couldn't be matched to a ROR record).

Run from article08/:
    python code/utils/analyse_review.py
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

from utils.config import cfg

AU54_ISO2 = {
    "DZ","AO","BJ","BW","BF","BI","CV","CM","CF","TD","KM","CG","CI","CD","DJ",
    "EG","GQ","ER","SZ","ET","GA","GM","GH","GN","GW","KE","LS","LR","LY","MG",
    "MW","ML","MR","MU","MA","MZ","NA","NE","NG","RW","ST","SN","SC","SL","SO",
    "ZA","SS","SD","TZ","TG","TN","UG","ZM","ZW",
}

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

country_name_to_iso2: dict[str, str] = {}
CLIST = ARTICLE / cfg["paths"]["country_list"]
with open(CLIST, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        iso3 = row.get("iso3", "").strip()
        if iso3 not in ISO3_TO_ISO2:
            continue
        iso2 = ISO3_TO_ISO2[iso3]
        for field in ("country_name_scopus", "country_name_official"):
            name = row.get(field, "").strip()
            if name:
                country_name_to_iso2[name.lower()] = iso2

_EXTRA = {
    "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "egypt": "EG",
    "ethiopia": "ET", "ghana": "GH", "tanzania": "TZ", "uganda": "UG",
    "morocco": "MA", "algeria": "DZ", "cameroon": "CM", "tunisia": "TN",
    "dr congo": "CD", "democratic republic of congo": "CD",
    "republic of congo": "CG", "congo": "CG",
    "ivory coast": "CI", "cote d ivoire": "CI",
    "burkina faso": "BF", "sierra leone": "SL", "liberia": "LR",
    "zimbabwe": "ZW", "zambia": "ZM", "senegal": "SN", "mali": "ML",
    "malawi": "MW", "mozambique": "MZ", "botswana": "BW", "namibia": "NA",
    "rwanda": "RW", "benin": "BJ", "angola": "AO", "sudan": "SD",
    "south sudan": "SS", "somalia": "SO", "niger": "NE", "chad": "TD",
    "guinea": "GN", "guinea-bissau": "GW", "equatorial guinea": "GQ",
    "gabon": "GA", "togo": "TG", "mauritius": "MU", "madagascar": "MG",
    "eritrea": "ER", "djibouti": "DJ", "comoros": "KM", "cabo verde": "CV",
    "eswatini": "SZ", "swaziland": "SZ", "lesotho": "LS", "gambia": "GM",
    "burundi": "BI", "mauritania": "MR", "seychelles": "SC",
    "central african republic": "CF", "sao tome and principe": "ST",
    "libya": "LY",
}
country_name_to_iso2.update(_EXTRA)


def extract_country_hints(segment: str) -> list[str]:
    parts = [p.strip().lower() for p in segment.split(",")]
    hints = []
    for p in reversed(parts[-3:]):
        code = country_name_to_iso2.get(p)
        if code:
            hints.append(code)
    return list(dict.fromkeys(hints))


REVIEW = ARTICLE / "provenance" / "stage3_manual_review.csv"
OUT    = ARTICLE / "provenance" / "stage3_african_affiliations_to_review.csv"
SEP    = "-" * 70

rows_all: list[dict] = []
fieldnames: list[str] = []

with open(REVIEW, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    fieldnames = list(reader.fieldnames or [])
    for row in reader:
        hints = extract_country_hints(row["segment_raw"])
        row["hint_countries"] = ";".join(hints)
        rows_all.append(row)

total   = len(rows_all)
african = [r for r in rows_all if r["hint_countries"]]
intl    = [r for r in rows_all if not r["hint_countries"]]

print(f"\n{'='*70}")
print(" MANUAL REVIEW ANALYSIS")
print(f"{'='*70}")

print(f"\n{SEP}\nA. TOTALS\n{SEP}")
print(f"  Total rows in manual_review.csv           : {total:>8,}")
print(f"  Rows with AU-54 hint (African, to review) : {len(african):>8,}")
print(f"  Rows with no hint (international, OK)     : {len(intl):>8,}")

# weighted frequencies
total_freq_african = sum(int(r["frequency"]) for r in african)
total_freq_intl    = sum(int(r["frequency"]) for r in intl)
total_freq_all     = sum(int(r["frequency"]) for r in rows_all)
print(f"\n  Weighted occurrence counts:")
print(f"    African (hint)      : {total_freq_african:>8,}  ({100*total_freq_african/total_freq_all:.1f}% of unresolved)")
print(f"    International (no hint) : {total_freq_intl:>8,}  ({100*total_freq_intl/total_freq_all:.1f}% of unresolved)")
print(f"    Total unresolved    : {total_freq_all:>8,}")

print(f"\n{SEP}\nB. PER-COUNTRY BREAKDOWN (unique-segment count)\n{SEP}")
cc_seg_counts: dict[str, int] = defaultdict(int)
cc_freq_counts: dict[str, int] = defaultdict(int)
for r in african:
    for cc in r["hint_countries"].split(";"):
        if cc:
            cc_seg_counts[cc] += 1
            cc_freq_counts[cc] += int(r["frequency"])

print(f"  {'ISO2':<6}  {'Unique segs':>12}  {'Total occurrences':>18}")
print(f"  {'----':<6}  {'------------':>12}  {'------------------':>18}")
for cc, cnt in sorted(cc_seg_counts.items(), key=lambda x: -x[1]):
    print(f"  {cc:<6}  {cnt:>12,}  {cc_freq_counts[cc]:>18,}")

print(f"\n{SEP}\nC. TOP 30 AFRICAN UNRESOLVED SEGMENTS (by frequency)\n{SEP}")
african_sorted = sorted(african, key=lambda r: -int(r["frequency"]))

hdr = (
    f"{'Segment (100 chars)':<100}  "
    f"{'Freq':>6}  "
    f"{'Hints':<10}  "
    f"{'Top-1 ROR display':<45}  "
    f"{'Sc1':>5}  "
    f"{'Top-2 ROR display':<45}  "
    f"{'Sc2':>5}"
)
print(hdr)
print("-" * len(hdr))
for r in african_sorted[:30]:
    seg  = r["segment_raw"][:100]
    freq = int(r["frequency"])
    hint = r["hint_countries"]
    t1   = r.get("top1_display", "")[:45]
    s1   = float(r.get("top1_score", 0))
    t2   = r.get("top2_display", "")[:45]
    s2   = float(r.get("top2_score", 0))
    print(
        f"{seg:<100}  "
        f"{freq:>6,}  "
        f"{hint:<10}  "
        f"{t1:<45}  "
        f"{s1:>5.1f}  "
        f"{t2:<45}  "
        f"{s2:>5.1f}"
    )

# Write output file
out_fields = ["hint_countries"] + [f for f in fieldnames if f != "hint_countries"]
with open(OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=out_fields)
    writer.writeheader()
    writer.writerows(african_sorted)

print(f"\n{SEP}")
print(f"Written: {OUT.name}  ({len(african):,} rows)")
print(f"{'='*70}\n")
