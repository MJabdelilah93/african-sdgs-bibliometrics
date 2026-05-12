"""measure_fixes.py
Targeted measurement of Fix-A (hyphen normalisation) and Fix-B
(country-preferred tiebreak) against the 2,264 AU-54 unresolved
strings from stage3_african_affiliations_to_review.csv.

Run from article08/:
    python code/utils/measure_fixes.py
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

from utils.config import cfg
from rapidfuzz import fuzz, process as rfprocess

# ── paths ──────────────────────────────────────────────────────────────────
ROR_JSON   = ARTICLE / "data" / "external" / "ror" / "ror_africa_v2.json"
REVIEW_CSV = ARTICLE / "provenance" / "stage3_african_affiliations_to_review.csv"
CLIST      = ARTICLE / cfg["paths"]["country_list"]

FUZZY_THRESHOLD = int(cfg["cleaning"]["affiliation_fuzzy_threshold"] * 100)
FUZZY_GAP       = 5

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
AU54_ISO2 = set(ISO3_TO_ISO2.values())

# ── helpers (mirrors 02_affiliation_standardisation.py) ───────────────────

def normalize(s):
    s = s.lower()
    s = re.sub(r"[^\w\s-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_ARTICLES = [
    " of the ", " of a ", " de la ", " de las ", " du ", " des ",
    " der ", " van de ", " van den ",
]

def normalize_for_exact(s):
    s = normalize(s)
    padded = " " + s + " "
    for art in _ARTICLES:
        padded = padded.replace(art, " ")
    padded = re.sub(r"\s+", " ", padded).strip()
    padded = re.sub(r"(?<=\w)-(?=\w)", " ", padded)   # Fix-A
    return re.sub(r"\s+", " ", padded).strip()


# OLD version (before Fix-A) for comparison
def normalize_for_exact_old(s):
    s = normalize(s)
    padded = " " + s + " "
    for art in _ARTICLES:
        padded = padded.replace(art, " ")
    return re.sub(r"\s+", " ", padded).strip()


_UNIT_PREFIXES = (
    "faculty of", "department of", "school of", "college of",
    "institute of", "division of", "centre for", "center for",
    "section of", "unit of", "laboratory of", "lab of",
    "department", "faculty", "school", "college", "institute",
    "division", "programme", "program", "clinic", "ward",
    "national", "regional", "provincial",
)

def strip_unit_prefix(segment):
    lower = segment.lower().strip()
    for prefix in _UNIT_PREFIXES:
        if lower.startswith(prefix):
            comma_idx = segment.find(",")
            if comma_idx > 0:
                stripped = segment[comma_idx + 1:].strip()
                if len(stripped) > 10:
                    return stripped
    return None


# ── build ROR lookups (new, with Fix-A applied to index) ──────────────────
print("Loading ROR lookups (new + old indices for comparison) ...")

with open(ROR_JSON, encoding="utf-8") as f:
    ror_records = json.load(f)

exact_lookup_new: dict[str, str] = {}   # Fix-A index
exact_lookup_old: dict[str, str] = {}   # baseline index
acronym_lookup: dict[str, dict] = defaultdict(dict)
ror_by_country: dict[str, list] = defaultdict(list)
ror_metadata:   dict[str, dict] = {}

for rec in ror_records:
    ror_id   = rec["id"]
    names    = rec.get("names", [])
    locs     = rec.get("locations", [])
    countries = [
        (loc.get("geonames_details") or {}).get("country_code", "")
        for loc in locs
    ]
    countries = [c for c in countries if c in AU54_ISO2]

    display = next(
        (n["value"] for n in names if "ror_display" in n.get("types", [])),
        names[0]["value"] if names else ror_id,
    )
    norm_display = normalize(display)
    ror_metadata[ror_id] = {"display": display, "countries": countries}

    for cc in countries:
        ror_by_country[cc].append((ror_id, norm_display))

    for n in names:
        val   = n["value"]
        types = n.get("types", [])
        if "acronym" in types:
            for cc in countries:
                acronym_lookup[cc][val] = ror_id
        else:
            key_new = normalize_for_exact(val)
            key_old = normalize_for_exact_old(val)
            if key_new and key_new not in exact_lookup_new:
                exact_lookup_new[key_new] = ror_id
            if key_old and key_old not in exact_lookup_old:
                exact_lookup_old[key_old] = ror_id

print(f"  exact_lookup_new keys : {len(exact_lookup_new):,}")
print(f"  exact_lookup_old keys : {len(exact_lookup_old):,}")


# ── load review strings ────────────────────────────────────────────────────
review_rows = []
with open(REVIEW_CSV, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        review_rows.append(row)

print(f"  AU-54 unresolved strings: {len(review_rows):,}\n")


# ── match function (new, with both fixes) ─────────────────────────────────
def match_new(raw_seg, hints_override=None):
    """Returns (ror_id, method, score)."""
    parts    = [p.strip() for p in raw_seg.split(",")]
    hints    = hints_override or []
    norm_seg = normalize(raw_seg)

    for n in range(len(parts), 0, -1):
        key = normalize_for_exact(", ".join(parts[:n]))
        if key in exact_lookup_new:
            return exact_lookup_new[key], "exact", 100.0

    fallback = strip_unit_prefix(raw_seg)
    if fallback is not None:
        fb_parts = [p.strip() for p in fallback.split(",")]
        for n in range(len(fb_parts), 0, -1):
            key = normalize_for_exact(", ".join(fb_parts[:n]))
            if key in exact_lookup_new:
                return exact_lookup_new[key], "exact_stripped", 100.0

    first = parts[0].strip()
    if re.match(r"^[A-Z]{2,10}$", first):
        for cc in (hints or list(acronym_lookup.keys())):
            if cc in acronym_lookup and first in acronym_lookup[cc]:
                return acronym_lookup[cc][first], "acronym", 100.0

    if not hints:
        return "", "unresolved", 0.0

    seen = set()
    candidates = []
    for cc in hints:
        for ror_id, norm_disp in ror_by_country.get(cc, []):
            if ror_id not in seen:
                seen.add(ror_id)
                candidates.append((ror_id, norm_disp))

    if not candidates:
        return "", "unresolved", 0.0

    cand_names = [c[1] for c in candidates]
    top2 = rfprocess.extract(norm_seg, cand_names, scorer=fuzz.partial_ratio,
                             limit=2, score_cutoff=0)

    if not top2 or top2[0][1] < FUZZY_THRESHOLD:
        return "", "unresolved", float(top2[0][1]) if top2 else 0.0

    _best_name, best_score, best_idx = top2[0]
    gap = best_score - (top2[1][1] if len(top2) > 1 else 0)

    if gap >= FUZZY_GAP:
        return candidates[best_idx][0], "fuzzy", float(best_score)

    if best_score == 100.0:
        perfect_all = rfprocess.extract(norm_seg, cand_names,
                                        scorer=fuzz.partial_ratio, score_cutoff=99)
        perfect_candidates = [candidates[idx] for _n, sc, idx in perfect_all
                               if sc == 100.0]
        hint_set = set(hints)
        country_filtered = [
            c for c in perfect_candidates
            if any(cc in hint_set
                   for cc in ror_metadata.get(c[0], {}).get("countries", []))
        ]
        if len(country_filtered) == 1:
            return country_filtered[0][0], "fuzzy_tiebreak", 100.0
        elif len(country_filtered) > 1:
            return country_filtered[0][0], "fuzzy_tiebreak_first", 100.0

    # Fix-B
    if gap > 0 and len(top2) > 1:
        _t1n, t1_score, t1_idx = top2[0]
        _t2n, t2_score, t2_idx = top2[1]
        hint_set = set(hints)
        t1_cc_ok = any(cc in hint_set
                       for cc in ror_metadata.get(candidates[t1_idx][0], {}).get("countries", []))
        t2_cc_ok = any(cc in hint_set
                       for cc in ror_metadata.get(candidates[t2_idx][0], {}).get("countries", []))
        if not t1_cc_ok and t2_cc_ok and t2_score >= FUZZY_THRESHOLD:
            return candidates[t2_idx][0], "fuzzy_country_preferred", float(t2_score)

    return "", "unresolved", float(best_score)


# ── old match (baseline, only for Fix-A attribution) ──────────────────────
def match_old_exact_only(raw_seg, hints_override=None):
    """Runs only Step A with the OLD index, to isolate Fix-A impact."""
    parts = [p.strip() for p in raw_seg.split(",")]
    for n in range(len(parts), 0, -1):
        key = normalize_for_exact_old(", ".join(parts[:n]))
        if key in exact_lookup_old:
            return exact_lookup_old[key]
    fallback = strip_unit_prefix(raw_seg)
    if fallback is not None:
        fb_parts = [p.strip() for p in fallback.split(",")]
        for n in range(len(fb_parts), 0, -1):
            key = normalize_for_exact_old(", ".join(fb_parts[:n]))
            if key in exact_lookup_old:
                return exact_lookup_old[key]
    return None


# ── run measurement ────────────────────────────────────────────────────────
fix_a_new = []   # resolved by Fix-A (hyphen) only
fix_b_new = []   # resolved by Fix-B (country preferred)
still_unresolved = []

for row in review_rows:
    seg   = row["segment_raw"]
    freq  = int(row["frequency"])
    hints = [h for h in row.get("hint_countries", "").split(";") if h]

    ror_id, method, score = match_new(seg, hints_override=hints)

    if ror_id:
        # Was it resolved by Fix-A specifically?
        old_exact = match_old_exact_only(seg, hints_override=hints)
        if method in ("exact", "exact_stripped") and old_exact is None:
            fix_a_new.append((seg, freq, hints, method, ror_id, score))
        elif method == "fuzzy_country_preferred":
            fix_b_new.append((seg, freq, hints, method, ror_id, score))
    else:
        still_unresolved.append((seg, freq, hints))

SEP = "-" * 70
print(f"\n{'='*70}")
print(" MEASUREMENT RESULTS")
print(f"{'='*70}")

total_new = len(fix_a_new) + len(fix_b_new)

print(f"\n{SEP}\nA. FIX IMPACT\n{SEP}")
print(f"  Fix-A (hyphen normalisation)  : {len(fix_a_new):>5} newly resolved")
print(f"  Fix-B (country preferred)     : {len(fix_b_new):>5} newly resolved")
print(f"  Combined new resolutions      : {total_new:>5}")
print(f"  AU-54 unresolved before fixes : {len(review_rows):>5}")
print(f"  AU-54 unresolved after fixes  : {len(still_unresolved):>5}")

n_fixA_weighted = sum(f for _,f,*_ in fix_a_new)
n_fixB_weighted = sum(f for _,f,*_ in fix_b_new)
print(f"\n  Weighted occurrences newly resolved:")
print(f"    Fix-A : {n_fixA_weighted:,}")
print(f"    Fix-B : {n_fixB_weighted:,}")

print(f"\n{SEP}\nB. EXAMPLES – Fix-A (hyphen)\n{SEP}")
for seg, freq, hints, method, ror_id, score in fix_a_new[:5]:
    disp = ror_metadata.get(ror_id, {}).get("display", "")
    print(f"  [{freq:>4}x]  {seg[:90]}")
    print(f"          -> {disp}  ({method}, {score:.1f})")
    print()

print(f"\n{SEP}\nC. EXAMPLES – Fix-B (country preferred)\n{SEP}")
for seg, freq, hints, method, ror_id, score in fix_b_new[:5]:
    disp = ror_metadata.get(ror_id, {}).get("display", "")
    print(f"  [{freq:>4}x]  {seg[:90]}")
    print(f"          -> {disp}  ({method}, {score:.1f}, hints={hints})")
    print()

print(f"\n{SEP}\nD. RECOMMENDATION\n{SEP}")
if total_new > 200:
    print(f"  {total_new} new resolutions — RECOMMEND FULL RE-RUN (worth the ~23 minutes)")
elif total_new >= 50:
    print(f"  {total_new} new resolutions — RECOMMEND MANUAL OVERRIDES instead (faster)")
else:
    print(f"  {total_new} new resolutions — SKIP FIXES, proceed to manual overrides only")

print(f"\n{'='*70}\n")
