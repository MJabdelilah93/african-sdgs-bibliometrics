"""02_affiliation_standardisation.py
Stage 3C – Match Scopus affiliation strings to ROR institution identifiers.

Three-step cascade per segment:
  1. Exact  – normalised comma-prefix walk against all ROR name variants
  2. Acronym – all-caps token matched against country-restricted acronym dict
  3. Fuzzy  – partial_ratio >= threshold, gap >= 5 between best and 2nd best

Run from article08/:
    python code/02_affiliation_standardisation.py
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process as rfprocess
from tqdm import tqdm

# ── bootstrap ──────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent       # code/
ARTICLE = HERE.parent                           # article08/
sys.path.insert(0, str(HERE))

from utils.config import cfg
from utils.logger import get_logger

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

log = get_logger("stage3c_affiliation")

# ── config ─────────────────────────────────────────────────────────────────
FUZZY_THRESHOLD  = int(cfg["cleaning"]["affiliation_fuzzy_threshold"] * 100)  # 92
FUZZY_GAP        = 5
REVIEW_MIN_FREQ  = 5
CHUNK_SIZE       = 50_000

# ── paths ──────────────────────────────────────────────────────────────────
ROR_JSON   = ARTICLE / "data" / "external" / "ror" / "ror_africa_v2.json"
DEDUP_CSV  = ARTICLE / "data" / "interim" / "deduplicated.csv"
SLIM_CSV   = ARTICLE / "data" / "interim" / "slim_affil.csv"
STD_CSV    = ARTICLE / "data" / "interim" / "standardised.csv"
PROV       = ARTICLE / cfg["paths"]["provenance"]
AFFIL_LOG  = PROV / "stage3_affiliation_log.csv"
REVIEW_CSV    = PROV / "stage3_manual_review.csv"
OVERRIDES_CSV = PROV / "stage3_manual_overrides.csv"
RESULTS    = ARTICLE / cfg["paths"]["results"]
RESULTS_CSV = RESULTS / "stage3_affiliation_results.csv"
CLIST      = ARTICLE / cfg["paths"]["country_list"]

RESULTS.mkdir(parents=True, exist_ok=True)

# ── ISO3 → ISO2 ────────────────────────────────────────────────────────────
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

SEP  = "-" * 62
SEP2 = "=" * 62


# ──────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────

def normalize(s: str) -> str:
    """Lowercase, strip punctuation (keep hyphens), collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^\w\s-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Bug-2 fix: articles to strip for exact matching
_ARTICLES = [
    " of the ", " of a ", " de la ", " de las ", " du ", " des ",
    " der ", " van de ", " van den ",
]


def normalize_for_exact(s: str) -> str:
    """normalize() plus article stripping and hyphen normalisation for exact-match lookups."""
    s = normalize(s)
    padded = " " + s + " "
    for art in _ARTICLES:
        padded = padded.replace(art, " ")
    padded = re.sub(r"\s+", " ", padded).strip()
    # Fix-A: intra-word hyphens → space ("North-West" → "North West")
    padded = re.sub(r"(?<=\w)-(?=\w)", " ", padded)
    return re.sub(r"\s+", " ", padded).strip()


# Bug-3 fix: unit-prefix labels that precede the institution name
_UNIT_PREFIXES = (
    "faculty of", "department of", "school of", "college of",
    "institute of", "division of", "centre for", "center for",
    "section of", "unit of", "laboratory of", "lab of",
    "department", "faculty", "school", "college", "institute",
    "division", "programme", "program", "clinic", "ward",
    "national", "regional", "provincial",
)


def strip_unit_prefix(segment: str):
    """Return segment with leading unit-label stripped, or None if no prefix."""
    lower = segment.lower().strip()
    for prefix in _UNIT_PREFIXES:
        if lower.startswith(prefix):
            comma_idx = segment.find(",")
            if comma_idx > 0:
                stripped = segment[comma_idx + 1:].strip()
                if len(stripped) > 10:
                    return stripped
    return None


# ──────────────────────────────────────────────────────────────────────────
# STEP 1 – Build ROR lookup structures
# ──────────────────────────────────────────────────────────────────────────
log.info(SEP2)
log.info("STAGE 3C – AFFILIATION STANDARDISATION")
log.info(SEP2)
log.info("Step 1 – Loading ROR Africa subset and building lookups ...")

with open(ROR_JSON, encoding="utf-8") as f:
    ror_records = json.load(f)

exact_lookup  : dict[str, str]             = {}   # norm_name -> ror_id
acronym_lookup: dict[str, dict[str, str]]  = defaultdict(dict)  # cc -> {acro -> ror_id}
ror_by_country: dict[str, list]            = defaultdict(list)   # cc -> [(ror_id, norm_disp)]
ror_metadata  : dict[str, dict]            = {}   # ror_id -> {display, countries}

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
            key = normalize_for_exact(val)
            if key and key not in exact_lookup:
                exact_lookup[key] = ror_id

# flat list of all candidates (for no-hint fuzzy fallback)
all_candidates = [(ror_id, meta["display"], normalize(meta["display"]))
                  for ror_id, meta in ror_metadata.items()]

log.info(f"  ROR records loaded : {len(ror_records):,}")
log.info(f"  Exact-lookup keys  : {len(exact_lookup):,}")
log.info(f"  Acronym entries    : {sum(len(v) for v in acronym_lookup.values()):,}")
log.info(f"  Countries covered  : {len(ror_by_country)}")

# ──────────────────────────────────────────────────────────────────────────
# STEP 2 – Build country-name → ISO2 map (for hint extraction)
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 2 – Building country-hint map from AU54 country list ...")

country_name_to_iso2: dict[str, str] = {}
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

# add common Scopus variants not in the CSV
_EXTRA = {
    "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "egypt": "EG",
    "ethiopia": "ET", "ghana": "GH", "tanzania": "TZ", "uganda": "UG",
    "morocco": "MA", "algeria": "DZ", "cameroon": "CM", "tunisia": "TN",
    "dr congo": "CD", "democratic republic of congo": "CD",
    "republic of congo": "CG", "congo": "CG",
    "ivory coast": "CI", "cote d ivoire": "CI", "coted ivoire": "CI",
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
log.info(f"  Country-hint entries : {len(country_name_to_iso2)}")


def extract_country_hints(segment: str) -> list[str]:
    """Return AU54 ISO2 codes found in the trailing comma-parts of a segment."""
    parts = [p.strip().lower() for p in segment.split(",")]
    hints = []
    for p in reversed(parts[-3:]):   # check last 3 parts
        code = country_name_to_iso2.get(p)
        if code:
            hints.append(code)
    return list(dict.fromkeys(hints))   # deduplicate, preserve order


# ──────────────────────────────────────────────────────────────────────────
# STEP 2.5 – Load manual overrides
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 2.5 – Loading manual overrides ...")

override_lookup: dict[str, tuple[str, str]] = {}  # norm_raw -> (ror_id, reason)

if OVERRIDES_CSV.exists():
    with open(OVERRIDES_CSV, encoding="utf-8") as _f:
        for _row in csv.DictReader(_f):
            _raw = _row.get("raw_string", "").strip()
            _ror = _row.get("ror_id", "").strip()
            _rsn = _row.get("decision_reason", "").strip()
            if _raw:
                override_lookup[normalize(_raw)] = (_ror, _rsn)

_n_ov_with    = sum(1 for r, _ in override_lookup.values() if r)
_n_ov_without = sum(1 for r, _ in override_lookup.values() if not r)
log.info(f"  Override entries loaded : {len(override_lookup):,}")
log.info(f"    with ROR ID           : {_n_ov_with:,}")
log.info(f"    without ROR ID        : {_n_ov_without:,}")


# ──────────────────────────────────────────────────────────────────────────
# STEP 3 – Load deduplicated.csv (slim: EID + Affiliations)
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 3 – Loading slim corpus (EID + Affiliations) ...")

all_cols   = pd.read_csv(DEDUP_CSV, nrows=0).columns.tolist()
eid_col    = next((c for c in all_cols if c.upper() == "EID"), "EID")
affil_col  = next((c for c in all_cols
                   if c.lower() in ("affiliations", "affiliation")), "Affiliations")

slim_df = pd.read_csv(
    DEDUP_CSV,
    usecols=[eid_col, affil_col],
    dtype=str,
    encoding="utf-8-sig",
    low_memory=False,
)
slim_df.rename(columns={eid_col: "EID", affil_col: "Affiliations"}, inplace=True)
slim_df["Affiliations"] = slim_df["Affiliations"].fillna("")

log.info(f"  Records loaded : {len(slim_df):,}")


# ──────────────────────────────────────────────────────────────────────────
# STEP 4 – Build segment frequency table & process unique segments
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 4 – Exploding affiliation segments and matching ...")

# Collect all (eid, segment_raw) pairs
eid_seg_pairs = []
seg_counter   = Counter()

for _, row in slim_df.iterrows():
    eid    = row["EID"]
    raw    = row["Affiliations"]
    if not raw:
        continue
    for seg in raw.split(";"):
        seg = seg.strip()
        if seg:
            eid_seg_pairs.append((eid, seg))
            seg_counter[seg] += 1

log.info(f"  Total (EID, segment) pairs : {len(eid_seg_pairs):,}")
log.info(f"  Unique segments            : {len(seg_counter):,}")


def match_segment(raw_seg: str) -> tuple[str, str, float]:
    """
    Returns (ror_id, method, score) or ("", "unresolved", 0.0).
    method: manual_override | manual_unresolvable |
            exact | exact_stripped | acronym | fuzzy |
            fuzzy_tiebreak | fuzzy_tiebreak_first |
            fuzzy_country_preferred | unresolved
    """
    parts    = [p.strip() for p in raw_seg.split(",")]
    hints    = extract_country_hints(raw_seg)
    norm_seg = normalize(raw_seg)

    # ── Step 0: Manual override ────────────────────────────────────────────
    _ov = override_lookup.get(norm_seg)
    if _ov is not None:
        _ov_ror, _ = _ov
        if _ov_ror:
            return _ov_ror, "manual_override", 1.0
        else:
            return "", "manual_unresolvable", 0.0

    # ── Step A: Exact – article-normalised comma-prefix walk ───────────────
    for n in range(len(parts), 0, -1):
        key = normalize_for_exact(", ".join(parts[:n]))
        if key in exact_lookup:
            return exact_lookup[key], "exact", 100.0

    # ── Step A1b: Exact with unit-prefix stripped (Bug-3) ──────────────────
    fallback = strip_unit_prefix(raw_seg)
    if fallback is not None:
        fb_parts = [p.strip() for p in fallback.split(",")]
        for n in range(len(fb_parts), 0, -1):
            key = normalize_for_exact(", ".join(fb_parts[:n]))
            if key in exact_lookup:
                return exact_lookup[key], "exact_stripped", 100.0

    # ── Step B: Acronym – all-caps token in first comma-part ───────────────
    first = parts[0].strip()
    if re.match(r"^[A-Z]{2,10}$", first):
        search_cc = hints if hints else list(acronym_lookup.keys())
        for cc in search_cc:
            if cc in acronym_lookup and first in acronym_lookup[cc]:
                return acronym_lookup[cc][first], "acronym", 100.0

    # ── Step C: Fuzzy – only when an AU54 country hint is present ─────────
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
    top2 = rfprocess.extract(
        norm_seg, cand_names,
        scorer=fuzz.partial_ratio,
        limit=2,
        score_cutoff=0,
    )

    if not top2 or top2[0][1] < FUZZY_THRESHOLD:
        return "", "unresolved", float(top2[0][1]) if top2 else 0.0

    _best_name, best_score, best_idx = top2[0]
    gap = best_score - (top2[1][1] if len(top2) > 1 else 0)

    if gap >= FUZZY_GAP:
        return candidates[best_idx][0], "fuzzy", float(best_score)

    # Gap too small — check for perfect-score tie-break (Bug-1)
    if best_score == 100.0:
        perfect_all = rfprocess.extract(
            norm_seg, cand_names,
            scorer=fuzz.partial_ratio,
            score_cutoff=99,
        )
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

    # Fix-B: imperfect gap, non-perfect score — check if top1 is wrong country
    # and top2 is the right country (country-preferred tiebreak)
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


# Process unique segments (cache to avoid redundant work)
seg_results: dict[str, tuple[str, str, float]] = {}

log.info(f"  Processing {len(seg_counter):,} unique segments ...")
for seg, _ in tqdm(seg_counter.most_common(), desc="matching", unit="seg", ncols=72):
    seg_results[seg] = match_segment(seg)

# Tally methods
method_counts: Counter = Counter()
for ror_id, method, _ in seg_results.values():
    method_counts[method] += 1

log.info(f"  manual_override         : {method_counts['manual_override']:,}")
log.info(f"  manual_unresolvable     : {method_counts['manual_unresolvable']:,}")
log.info(f"  exact               : {method_counts['exact']:,}")
log.info(f"  exact_stripped      : {method_counts['exact_stripped']:,}")
log.info(f"  acronym             : {method_counts['acronym']:,}")
log.info(f"  fuzzy               : {method_counts['fuzzy']:,}")
log.info(f"  fuzzy_tiebreak      : {method_counts['fuzzy_tiebreak']:,}")
log.info(f"  fuzzy_tiebreak_first    : {method_counts['fuzzy_tiebreak_first']:,}")
log.info(f"  fuzzy_country_preferred : {method_counts['fuzzy_country_preferred']:,}")
log.info(f"  unresolved              : {method_counts['unresolved']:,}")


# ──────────────────────────────────────────────────────────────────────────
# STEP 5 – Write slim_affil.csv  (one row per EID-segment)
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 5 – Writing slim_affil.csv ...")

slim_fields = ["eid", "segment_raw", "segment_norm",
               "ror_id", "ror_display", "country_code", "method", "score"]

with open(SLIM_CSV, "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=slim_fields)
    writer.writeheader()
    buf = []
    for eid, raw_seg in tqdm(eid_seg_pairs, desc="writing slim", unit="row", ncols=72):
        ror_id, method, score = seg_results.get(raw_seg, ("", "unresolved", 0.0))
        meta     = ror_metadata.get(ror_id, {})
        display  = meta.get("display", "")
        cc_list  = meta.get("countries", [])
        cc       = cc_list[0] if cc_list else ""
        buf.append({
            "eid"          : eid,
            "segment_raw"  : raw_seg,
            "segment_norm" : normalize(raw_seg),
            "ror_id"       : ror_id,
            "ror_display"  : display,
            "country_code" : cc,
            "method"       : method,
            "score"        : f"{score:.2f}",
        })
        if len(buf) >= 10_000:
            writer.writerows(buf)
            buf.clear()
    if buf:
        writer.writerows(buf)

log.info(f"  Written: {SLIM_CSV.name}  ({len(eid_seg_pairs):,} rows)")


# ──────────────────────────────────────────────────────────────────────────
# STEP 6 – Aggregate per-EID results
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 6 – Aggregating per-EID affiliation results ...")

eid_agg: dict[str, dict] = {}

for eid, raw_seg in eid_seg_pairs:
    ror_id, method, score = seg_results.get(raw_seg, ("", "unresolved", 0.0))
    if eid not in eid_agg:
        eid_agg[eid] = {
            "n_segments" : 0,
            "n_matched"  : 0,
            "ror_ids"    : [],
            "methods"    : [],
            "countries"  : [],
        }
    rec = eid_agg[eid]
    rec["n_segments"] += 1
    if ror_id:
        rec["n_matched"] += 1
        if ror_id not in rec["ror_ids"]:
            rec["ror_ids"].append(ror_id)
            meta    = ror_metadata.get(ror_id, {})
            cc_list = meta.get("countries", [])
            for cc in cc_list:
                if cc not in rec["countries"]:
                    rec["countries"].append(cc)
            rec["methods"].append(method)

agg_df = pd.DataFrame([
    {
        "EID"            : eid,
        "n_segments"     : v["n_segments"],
        "n_matched"      : v["n_matched"],
        "ror_ids"        : ";".join(v["ror_ids"]),
        "match_methods"  : ";".join(v["methods"]),
        "match_countries": ";".join(v["countries"]),
    }
    for eid, v in eid_agg.items()
])
log.info(f"  Aggregated {len(agg_df):,} EIDs")


# ──────────────────────────────────────────────────────────────────────────
# STEP 7 – Chunked merge → standardised.csv
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 7 – Merging with deduplicated.csv (chunked) ...")

total_written = 0
header_written = False

for chunk in tqdm(
    pd.read_csv(DEDUP_CSV, dtype=str, encoding="utf-8-sig",
                chunksize=CHUNK_SIZE, low_memory=False),
    desc="merging", unit="chunk", ncols=72,
):
    merged = chunk.merge(agg_df, on="EID", how="left")
    for col in ("n_segments", "n_matched", "ror_ids", "match_methods", "match_countries"):
        if col not in merged.columns:
            merged[col] = ""
    merged.to_csv(
        STD_CSV,
        mode="a" if header_written else "w",
        index=False,
        header=not header_written,
        encoding="utf-8",
    )
    header_written = True
    total_written += len(merged)

log.info(f"  Written: {STD_CSV.name}  ({total_written:,} rows)")


# ──────────────────────────────────────────────────────────────────────────
# STEP 8 – Manual review file (unresolved segments, freq >= REVIEW_MIN_FREQ)
# ──────────────────────────────────────────────────────────────────────────
log.info(f"Step 8 – Building manual review for unresolved segments (freq>={REVIEW_MIN_FREQ}) ...")

unresolved_segs = [
    (seg, cnt)
    for seg, cnt in seg_counter.most_common()
    if seg_results.get(seg, ("",))[0] == ""
    and cnt >= REVIEW_MIN_FREQ
]
log.info(f"  Unresolved segments (freq>={REVIEW_MIN_FREQ}) : {len(unresolved_segs):,}")

review_fields = [
    "segment_raw", "frequency",
    "top1_ror_id", "top1_display", "top1_score",
    "top2_ror_id", "top2_display", "top2_score",
    "top3_ror_id", "top3_display", "top3_score",
]

# For suggestions: use token_set_ratio against all AU54 display names
all_ror_names   = [c[1] for c in all_candidates]
all_ror_ids     = [c[0] for c in all_candidates]
all_ror_display = [c[1] for c in all_candidates]   # already display

with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=review_fields)
    writer.writeheader()
    for seg, cnt in tqdm(unresolved_segs, desc="review", unit="seg", ncols=72):
        norm_seg = normalize(seg)
        hints    = extract_country_hints(seg)
        if hints:
            cands = [(c[0], c[1], c[2]) for c in all_candidates
                     if any(cc in ror_metadata.get(c[0], {}).get("countries", [])
                            for cc in hints)]
        else:
            cands = all_candidates

        if not cands:
            top3 = []
        else:
            cand_names = [c[2] for c in cands]
            matches = rfprocess.extract(
                norm_seg, cand_names,
                scorer=fuzz.partial_ratio,
                limit=3,
                score_cutoff=0,
            )
            top3 = [
                (cands[idx][0],
                 ror_metadata.get(cands[idx][0], {}).get("display", ""),
                 score)
                for _name, score, idx in matches
            ]

        row_out = {"segment_raw": seg, "frequency": cnt}
        for i, label in enumerate(["top1", "top2", "top3"]):
            if i < len(top3):
                row_out[f"{label}_ror_id"]  = top3[i][0]
                row_out[f"{label}_display"] = top3[i][1]
                row_out[f"{label}_score"]   = f"{top3[i][2]:.1f}"
            else:
                row_out[f"{label}_ror_id"]  = ""
                row_out[f"{label}_display"] = ""
                row_out[f"{label}_score"]   = ""
        writer.writerow(row_out)

log.info(f"  Written: {REVIEW_CSV.name}")


# ──────────────────────────────────────────────────────────────────────────
# STEP 9 – Provenance affiliation log (same content as slim_affil)
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 9 – Writing provenance affiliation log ...")

import shutil
shutil.copy2(SLIM_CSV, AFFIL_LOG)
log.info(f"  Copied slim_affil.csv -> {AFFIL_LOG.name}")


# ──────────────────────────────────────────────────────────────────────────
# STEP 10 – Summary results CSV
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 10 – Writing summary results ...")

total_segs    = sum(seg_counter.values())
unique_segs   = len(seg_counter)
total_matched = sum(
    1 for seg, _ in seg_counter.items()
    if seg_results.get(seg, ("",))[0] != ""
)
n_manual_override    = method_counts["manual_override"]
n_manual_unresolvable = method_counts["manual_unresolvable"]
n_exact              = method_counts["exact"]
n_exact_stripped     = method_counts["exact_stripped"]
n_acronym            = method_counts["acronym"]
n_fuzzy              = method_counts["fuzzy"]
n_fuzzy_tiebreak     = method_counts["fuzzy_tiebreak"]
n_fuzzy_tiebreak_first = method_counts["fuzzy_tiebreak_first"]
n_unresolved         = method_counts["unresolved"]
pct_matched = 100 * total_matched / unique_segs if unique_segs else 0

results_rows = [
    {"metric": "total_eid_seg_pairs",           "value": total_segs},
    {"metric": "unique_segments",               "value": unique_segs},
    {"metric": "unique_matched",                "value": total_matched},
    {"metric": "unique_unresolved",             "value": unique_segs - total_matched},
    {"metric": "pct_matched",                   "value": f"{pct_matched:.2f}"},
    {"metric": "method_manual_override",        "value": n_manual_override},
    {"metric": "method_manual_unresolvable",    "value": n_manual_unresolvable},
    {"metric": "method_exact",                  "value": n_exact},
    {"metric": "method_exact_stripped",         "value": n_exact_stripped},
    {"metric": "method_acronym",                "value": n_acronym},
    {"metric": "method_fuzzy",                  "value": n_fuzzy},
    {"metric": "method_fuzzy_tiebreak",         "value": n_fuzzy_tiebreak},
    {"metric": "method_fuzzy_tiebreak_first",   "value": n_fuzzy_tiebreak_first},
    {"metric": "method_unresolved",             "value": n_unresolved},
    {"metric": "review_candidates",             "value": len(unresolved_segs)},
    {"metric": "fuzzy_threshold",               "value": FUZZY_THRESHOLD},
    {"metric": "fuzzy_gap",                     "value": FUZZY_GAP},
]

with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=["metric", "value"])
    writer.writeheader()
    writer.writerows(results_rows)

log.info(f"  Written: {RESULTS_CSV.name}")


# ──────────────────────────────────────────────────────────────────────────
# TERMINAL REPORT
# ──────────────────────────────────────────────────────────────────────────
print(f"\n{SEP2}")
print(" REPORT")
print(SEP2)

print(f"\n{SEP}\nA. INPUT\n{SEP}")
print(f"   Corpus records       : {len(slim_df):,}")
print(f"   EID-segment pairs    : {total_segs:,}")
print(f"   Unique segments      : {unique_segs:,}")

print(f"\n{SEP}\nB. MATCHING RESULTS (unique segments)\n{SEP}")
print(f"   manual_override     : {n_manual_override:,}  ({100*n_manual_override/unique_segs:.1f}%)")
print(f"   manual_unresolvable : {n_manual_unresolvable:,}  ({100*n_manual_unresolvable/unique_segs:.1f}%)")
print(f"   exact               : {n_exact:,}  ({100*n_exact/unique_segs:.1f}%)")
print(f"   exact_stripped      : {n_exact_stripped:,}  ({100*n_exact_stripped/unique_segs:.1f}%)")
print(f"   acronym             : {n_acronym:,}  ({100*n_acronym/unique_segs:.1f}%)")
print(f"   fuzzy               : {n_fuzzy:,}  ({100*n_fuzzy/unique_segs:.1f}%)")
print(f"   fuzzy_tiebreak      : {n_fuzzy_tiebreak:,}  ({100*n_fuzzy_tiebreak/unique_segs:.1f}%)")
print(f"   fuzzy_tiebreak_first: {n_fuzzy_tiebreak_first:,}  ({100*n_fuzzy_tiebreak_first/unique_segs:.1f}%)")
print(f"   Unresolved          : {n_unresolved:,}  ({100*n_unresolved/unique_segs:.1f}%)")
print(f"   Total matched       : {total_matched:,}  ({pct_matched:.1f}%)")

# EID-level stats
n_eids_any_match = sum(1 for v in eid_agg.values() if v["n_matched"] > 0)
print(f"\n{SEP}\nC. EID-LEVEL COVERAGE\n{SEP}")
print(f"   EIDs with >=1 match  : {n_eids_any_match:,}  ({100*n_eids_any_match/len(eid_agg):.1f}%)")
print(f"   EIDs with 0 matches  : {len(eid_agg)-n_eids_any_match:,}")

# Country distribution of matched institutions
cc_dist: Counter = Counter()
for v in eid_agg.values():
    for cc in v["countries"]:
        cc_dist[cc] += 1

print(f"\n{SEP}\nD. TOP 10 MATCHED COUNTRIES\n{SEP}")
print(f"   {'ISO2':<6}  {'EIDs with match':>15}")
for cc, cnt in cc_dist.most_common(10):
    print(f"   {cc:<6}  {cnt:>15,}")

print(f"\n{SEP}\nE. FILES WRITTEN\n{SEP}")
print(f"   data/interim/slim_affil.csv")
print(f"   data/interim/standardised.csv")
print(f"   provenance/stage3_affiliation_log.csv")
print(f"   provenance/stage3_manual_review.csv")
print(f"   results/stage3_affiliation_results.csv")

print(f"\n{SEP2}")
print(" STAGE 3C COMPLETE – DO NOT COMMIT YET")
print(SEP2)
