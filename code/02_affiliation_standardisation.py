"""02_affiliation_standardisation.py
Stage 02 – country attribution and ROR institution matching of Scopus affiliations.

Country attribution is independent of ROR: every record gets `affiliation_countries` / `au_countries`
(ISO2) parsed directly from the Scopus `Affiliations` text by utils/country_normalisation.py. Segments are
split after HTML-entity decoding. A segment naming more than one distinct country after the text-only
collapse rules (Congo forms; '<US state>, United States') is country-ambiguous: it gets no segment country,
contributes nothing to au_countries and abstains from every ROR step (method ambiguous_country). Resolved
segments restrict ROR candidates to exactly their one country; ROR is never used to choose a country.
`match_countries` (AU countries of the matched ROR institutions) is recorded for reference; country-level
analyses use `au_countries`.

ROR matching per segment:
  * exact – normalised comma-prefix walk against all ROR name variants; exact keys from
    utils/institution_core.exact_key (both sides: accent-folded, the article 'the' optional, center == centre);
    lookups hold CANDIDATE SETS, and exact / exact_stripped (unit prefix removed) / acronym matches are
    restricted to the segment's explicit countries and accepted only when exactly one candidate remains;
    with no explicit country the name must be unique in the ROR subset; otherwise the segment abstains;
  * exact_component – before fuzzy matching, a single comma-component (or its bracket-free variant) that
    exactly names a ROR institution (country-restricted, unique) is accepted; a component may also equal a
    ROR name qualified by that record's registered city/country ('University of Nigeria Nsukka'); several
    organisations sharing the exact name are separated only by their registered city named as a component
    of the segment; when several components each name one organisation, the right-most is taken
    (exact_component_rightmost, Scopus unit -> institution order); any ambiguous component abstains;
  * acronym – all-caps token matched against a country-restricted acronym dictionary;
  * fuzzy – country-restricted partial_ratio >= threshold with a gap >= 5 between the best and second-best
    candidate, scored without country-only components; several perfect candidates abstain; every fuzzy
    winner must pass the institutional gates A-E (utils/institution_core.CoreGates) or the segment abstains.
Reviewed manual overrides (provenance/stage3_manual_overrides.csv) whose ROR country contradicts the
segment's explicit country stop the run.

Input defaults to the 2015–2025 scoped corpus; every path can be overridden on the command line; outputs
are written to .tmp files and promoted only after internal validation (--hold keeps them as .tmp for
inspection, --promote-held promotes them after re-checking their hashes); the run is refused outside a
virtual environment.

Run from the repository root:
    python code/02_affiliation_standardisation.py
"""

import argparse
import csv
import json
import logging
import os
import platform
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import rapidfuzz
from rapidfuzz import fuzz, process as rfprocess
from tqdm import tqdm

# ── bootstrap ──────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent       # code/
ARTICLE = HERE.parent                           # repository root
sys.path.insert(0, str(HERE))

from utils.config import cfg
from utils.checksums import sha256_file
from utils.country_normalisation import CountryNormaliser, split_segments
from utils.institution_core import CoreGates, exact_key

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── config ─────────────────────────────────────────────────────────────────
FUZZY_THRESHOLD  = int(cfg["cleaning"]["affiliation_fuzzy_threshold"] * 100)  # 92
FUZZY_GAP        = 5
REVIEW_MIN_FREQ  = 5
CHUNK_SIZE       = 50_000
SCRIPT_VERSION   = "3.2.0"   # + deterministic exact keys / component matching; gated fuzzy institution matching

# ── paths ──────────────────────────────────────────────────────────────────
PROV    = ARTICLE / cfg["paths"]["provenance"]
RESULTS = ARTICLE / cfg["paths"]["results"]
V2_PROV = PROV / "v2"
CLIST   = ARTICLE / cfg["paths"]["country_list"]

_ap = argparse.ArgumentParser(description="Stage 02 / pipeline Stage 3C – affiliation standardisation")
_ap.add_argument("--input",      type=Path, default=ARTICLE / "data" / "interim" / "scoped_2015_2025.csv")
_ap.add_argument("--ror",        type=Path, default=ARTICLE / "data" / "external" / "ror" / "ror_africa_v2.json")
_ap.add_argument("--overrides",  type=Path, default=PROV / "stage3_manual_overrides.csv")
_ap.add_argument("--ror-global", type=Path, default=ARTICLE / "data" / "external" / "ror" / "ror_data_v2_latest.json",
                 help="global ROR dump, used only to look up countries of override targets outside the Africa subset")
_ap.add_argument("--country-reference", type=Path, default=ARTICLE / "country_lists" / "country_names_iso2.csv")
_ap.add_argument("--slim-out",   type=Path, default=ARTICLE / "data" / "interim" / "slim_affil.csv")
_ap.add_argument("--std-out",    type=Path, default=ARTICLE / "data" / "interim" / "standardised.csv")
_ap.add_argument("--affil-log",  type=Path, default=PROV / "stage3_affiliation_log.csv")
_ap.add_argument("--review-out", type=Path, default=PROV / "stage3_manual_review.csv")
_ap.add_argument("--results-out", type=Path, default=RESULTS / "stage3_affiliation_results.csv")
_ap.add_argument("--summary",    type=Path, default=V2_PROV / "stage2_affiliation_summary.json")
_ap.add_argument("--manifest",   type=Path, default=V2_PROV / "stage2_affiliation_manifest.csv")
_ap.add_argument("--log",        type=Path, default=V2_PROV / "logs" / "02_affiliation_standardisation.log")
_ap.add_argument("--overwrite",  action="store_true",
                 help="replace existing standardised.csv / slim_affil.csv (default: refuse)")
_ap.add_argument("--hold", action="store_true",
                 help="after validation keep outputs as .tmp (hashes recorded) for inspection before promotion")
_ap.add_argument("--promote-held", action="store_true",
                 help="promote held .tmp outputs after re-verifying their hashes against the manifest, then exit")
_ap.add_argument("--allow-global-python", action="store_true",
                 help="run outside a virtual environment (default: refuse; use .venv)")
ARGS = _ap.parse_args()

ROR_JSON      = ARGS.ror
INPUT_CSV     = ARGS.input
SLIM_CSV      = ARGS.slim_out
STD_CSV       = ARGS.std_out
AFFIL_LOG     = ARGS.affil_log
REVIEW_CSV    = ARGS.review_out
OVERRIDES_CSV = ARGS.overrides
RESULTS_CSV   = ARGS.results_out


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(ARTICLE).as_posix()
    except ValueError:
        return str(p)


def _tmp(p: Path) -> Path:
    return p.with_name(p.name + ".tmp")


def _pinned(package: str) -> str | None:
    req = ARTICLE / "requirements.txt"
    if not req.exists():
        return None
    for line in req.read_text(encoding="utf-8").splitlines():
        name, _, ver = line.split("#")[0].strip().partition("==")
        if name.strip().lower() == package:
            return ver.strip()
    return None


def _git(*args) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ARTICLE, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


ARGS.log.parent.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("02_affiliation_standardisation")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
for _h in (logging.FileHandler(ARGS.log, mode="a" if ARGS.promote_held else "w", encoding="utf-8"),
           logging.StreamHandler(sys.stdout)):
    _h.setFormatter(_fmt)
    log.addHandler(_h)

RUN_START = datetime.now()

if ARGS.promote_held:
    # promotion of outputs held by a previous --hold run (no recomputation)
    with open(ARGS.manifest, encoding="utf-8") as _f:
        _rows = [r for r in csv.DictReader(_f) if r["role"].startswith("output_")]
    _paths = [(ARTICLE / r["relative_path"], r["sha256"]) for r in _rows]
    for _p, _d in _paths:
        _t = _p.with_name(_p.name + ".tmp")
        if not _t.exists() or sha256_file(_t) != _d:
            log.error(f"Held output missing or hash differs: {_rel(_t)}")
            sys.exit(5)
    for _p, _d in _paths:
        os.replace(_p.with_name(_p.name + ".tmp"), _p)
        log.info(f"  Promoted held output: {_rel(_p)}  {_d}")
    _summ = json.loads(ARGS.summary.read_text(encoding="utf-8"))
    _summ["promotion"] = {"status": "promoted", "promoted_at": RUN_START.isoformat(timespec="seconds"),
                          "hashes_reverified": True}
    ARGS.summary.write_text(json.dumps(_summ, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("PROMOTION : PASS")
    sys.exit(0)
IN_VENV = sys.prefix != sys.base_prefix
VERSIONS = {"python": platform.python_version(), "pandas": pd.__version__,
            "rapidfuzz": rapidfuzz.__version__}
GIT_HEAD = _git("rev-parse", "HEAD")
GIT_DIRTY = bool(_git("status", "--porcelain", "--untracked-files=no"))

log.info("=" * 62)
log.info(f"STAGE 02 / pipeline Stage 3C – script v{SCRIPT_VERSION}")
log.info(f"Git HEAD   : {GIT_HEAD} (tracked changes: {GIT_DIRTY})")
log.info(f"Python     : {VERSIONS['python']}  (virtual environment: {IN_VENV})")
for _pkg in ("pandas", "rapidfuzz"):
    log.info(f"{_pkg:<10} : {VERSIONS[_pkg]}  (requirements.txt pin: {_pinned(_pkg)})")
    if _pinned(_pkg) and VERSIONS[_pkg] != _pinned(_pkg):
        log.warning(f"{_pkg} {VERSIONS[_pkg]} differs from the pinned {_pinned(_pkg)}")
if not IN_VENV and not ARGS.allow_global_python:
    log.error("Not running inside a virtual environment – use .venv\\Scripts\\python.exe "
              "(or pass --allow-global-python deliberately).")
    sys.exit(2)
for _need in (INPUT_CSV, ROR_JSON, OVERRIDES_CSV, CLIST, ARGS.ror_global, ARGS.country_reference):
    if not _need.exists():
        log.error(f"Required input missing: {_rel(_need)}")
        sys.exit(2)
if INPUT_CSV.resolve() in {p.resolve() for p in (SLIM_CSV, STD_CSV, AFFIL_LOG, REVIEW_CSV, RESULTS_CSV)}:
    log.error("An output path equals the input path – refusing to run.")
    sys.exit(2)
for _big in (SLIM_CSV, STD_CSV):
    if _big.exists() and not ARGS.overwrite:
        log.error(f"Output already exists: {_rel(_big)} (use --overwrite to replace).")
        sys.exit(2)

log.info(f"Input      : {_rel(INPUT_CSV)}")
INPUT_SHA = sha256_file(INPUT_CSV)
ROR_SHA = sha256_file(ROR_JSON)
OVERRIDES_SHA = sha256_file(OVERRIDES_CSV)
log.info(f"  SHA-256  : {INPUT_SHA}")
log.info(f"ROR        : {_rel(ROR_JSON)}  SHA-256 {ROR_SHA}")
log.info(f"Overrides  : {_rel(OVERRIDES_CSV)}  SHA-256 {OVERRIDES_SHA}")
REF_SHA = sha256_file(ARGS.country_reference)
CLIST_SHA = sha256_file(CLIST)
ROR_GLOBAL_SHA = sha256_file(ARGS.ror_global)
log.info(f"Countries  : {_rel(ARGS.country_reference)}  SHA-256 {REF_SHA}")
log.info(f"AU-54      : {_rel(CLIST)}  SHA-256 {CLIST_SHA}")
log.info(f"ROR global : {_rel(ARGS.ror_global)}  SHA-256 {ROR_GLOBAL_SHA}")
NORM = CountryNormaliser(ARGS.country_reference, CLIST)
GATES = CoreGates(NORM.alias.keys())
log.info(f"Fuzzy      : partial_ratio >= {FUZZY_THRESHOLD}, gap >= {FUZZY_GAP}")

for _p in (SLIM_CSV, STD_CSV, AFFIL_LOG, REVIEW_CSV, RESULTS_CSV, ARGS.summary, ARGS.manifest):
    _p.parent.mkdir(parents=True, exist_ok=True)

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


# Unit-prefix labels that precede the institution name
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

# candidate sets — every ROR record sharing a key is kept
exact_cands   : dict[str, set]             = defaultdict(set)   # norm_name -> {ror_id}
acronym_cands : dict[str, set]             = defaultdict(set)   # acronym -> {ror_id}
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
            if countries:
                acronym_cands[val].add(ror_id)
        else:
            key = exact_key(val)
            if key:
                exact_cands[key].add(ror_id)

# registered-location qualified name variants ('University of Nigeria Nsukka', 'Mohammed V University
# in Rabat', 'University of Sfax-Tunisia', 'Botswana Ministry of Health'): every non-acronym ROR name combined
# with the record's OWN ROR location city and/or country name. Built once for all records, independent of any
# affiliation; a variant key that equals a real ROR name key is never added (real names take precedence).
_cc_aliases = defaultdict(set)
for _a, _cc in NORM.alias.items():
    _cc_aliases[_cc].add(_a)
qual_cands: dict[str, set] = defaultdict(set)
ror_city_keys: dict[str, set] = {}      # ror_id -> exact keys of its registered (ROR) location cities
for rec in ror_records:
    ror_city_keys[rec["id"]] = {exact_key((l.get("geonames_details") or {}).get("name", ""))
                                for l in rec.get("locations", [])} - {""}
    _cities = {(l.get("geonames_details") or {}).get("name", "") for l in rec.get("locations", [])} - {""}
    _ctry = {a for c in ror_metadata[rec["id"]]["countries"] for a in _cc_aliases[c]}
    for n in rec.get("names", []):
        if "acronym" in n.get("types", []):
            continue
        v = n["value"]
        if len(exact_key(v).split()) < 2:     # names lost in ASCII folding (non-Latin script) or one-word names
            continue
        forms = [f"{v} {c}" for c in _cities] + [f"{v} in {c}" for c in _cities] + [f"{v} of {c}" for c in _cities]
        forms += [f"{f} {k}" for f in list(forms) for k in _ctry]
        forms += [f"{v} {k}" for k in _ctry] + [f"{v} of {k}" for k in _ctry] + [f"{k} {v}" for k in _ctry]
        for f_ in forms:
            key = exact_key(f_)
            if key and key not in exact_cands:
                qual_cands[key].add(rec["id"])

# flat list of all candidates (for no-hint fuzzy fallback)
all_candidates = [(ror_id, meta["display"], normalize(meta["display"]))
                  for ror_id, meta in ror_metadata.items()]


def _n_countries(cands) -> int:
    return len({cc for r in cands for cc in ror_metadata[r]["countries"]})


LOOKUP_STATS = {
    "exact_keys": len(exact_cands),
    "exact_keys_multi_record": sum(len(v) > 1 for v in exact_cands.values()),
    "exact_keys_multi_country": sum(_n_countries(v) > 1 for v in exact_cands.values()),
    "acronyms": len(acronym_cands),
    "acronyms_multi_record": sum(len(v) > 1 for v in acronym_cands.values()),
    "acronyms_multi_country": sum(_n_countries(v) > 1 for v in acronym_cands.values()),
    "qualified_keys": len(qual_cands),
    "qualified_keys_multi_record": sum(len(v) > 1 for v in qual_cands.values()),
}
log.info(f"  ROR records loaded : {len(ror_records):,}")
log.info(f"  Lookup ambiguity   : {LOOKUP_STATS}")
log.info(f"  Countries covered  : {len(ror_by_country)}")

# ──────────────────────────────────────────────────────────────────────────
# STEP 2 – Build country-name → ISO2 map (for hint extraction)
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 2 – Country context from utils/country_normalisation.py (all countries) ...")
log.info(f"  Country aliases : {len(NORM.alias)}  (reference entities {len(NORM.name)}, AU {len(NORM.au)})")
if NORM.au != AU54_ISO2:
    log.error("AU-54 ISO2 set of the normaliser differs from this script's ISO3->ISO2 table")
    sys.exit(2)


def extract_country_hints(segment: str) -> list[str]:
    """AU countries explicitly named in the segment's last three comma-parts (fuzzy restriction).

    Uses the shared all-country normaliser (accent/apostrophe/variant aware)."""
    return sorted(NORM.segment(segment).explicit & AU54_ISO2)


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

# override safety — target ROR country (all locations) vs the override string's explicit country
_ov_targets = {r for r, _ in override_lookup.values() if r}
override_target_cc: dict[str, set] = {}
with open(ARGS.ror_global, encoding="utf-8") as _f:
    for _rec in json.load(_f):
        if _rec["id"] in _ov_targets:
            override_target_cc[_rec["id"]] = {(l.get("geonames_details") or {}).get("country_code", "")
                                              for l in _rec.get("locations", [])}
_missing_targets = sorted(_ov_targets - set(override_target_cc))
if _missing_targets:
    log.error(f"Override ROR IDs not found in the global ROR dump: {_missing_targets}")
    sys.exit(3)
OVERRIDE_CONFLICTS = []
with open(OVERRIDES_CSV, encoding="utf-8") as _f:
    for _row in csv.DictReader(_f):
        _raw, _ror = _row.get("raw_string", "").strip(), _row.get("ror_id", "").strip()
        if not _raw or not _ror:
            continue
        _sc = NORM.segment(_raw)
        if _sc.primary and _sc.primary not in override_target_cc[_ror]:
            OVERRIDE_CONFLICTS.append({"raw_string": _raw, "ror_id": _ror, "parsed_country": _sc.primary,
                                       "target_countries": ";".join(sorted(override_target_cc[_ror]))})
log.info(f"  Override country conflicts: {len(OVERRIDE_CONFLICTS)} (strict: no exception mechanism)")
with open(OVERRIDES_CSV, encoding="utf-8") as _f:
    _ov_ambig = [r["raw_string"] for r in csv.DictReader(_f)
                 if r.get("raw_string") and NORM.segment(r["raw_string"]).status == "country_ambiguous"]
log.info(f"  Override strings that are country-ambiguous (will abstain): {len(_ov_ambig)}")
if OVERRIDE_CONFLICTS:
    for _c in OVERRIDE_CONFLICTS:
        log.error(f"  CONFLICT: {_c}")
    log.error("Manual override(s) contradict the explicit affiliation country — review required "
              "(provenance/v2/stage2_manual_override_country_conflicts.csv). Nothing written.")
    sys.exit(3)


# ──────────────────────────────────────────────────────────────────────────
# STEP 3 – Load input corpus (slim: EID + Affiliations)
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 3 – Loading slim corpus (EID + Affiliations) ...")

all_cols   = pd.read_csv(INPUT_CSV, nrows=0, encoding="utf-8-sig").columns.tolist()
eid_col    = next((c for c in all_cols if c.upper() == "EID"), "EID")
affil_col  = next((c for c in all_cols
                   if c.lower() in ("affiliations", "affiliation")), "Affiliations")

# keep_default_na=False: text such as "NA" (Namibia) must never become missing
slim_df = pd.read_csv(
    INPUT_CSV,
    usecols=[eid_col, affil_col],
    dtype=str,
    encoding="utf-8-sig",
    low_memory=False,
    keep_default_na=False,
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

# segments are split AFTER HTML-entity decoding; direct country attribution per record
record_countries: dict[str, object] = {}
for eid, raw in zip(slim_df["EID"], slim_df["Affiliations"]):
    record_countries[eid] = NORM.record(raw)
    if not raw:
        continue
    for seg in split_segments(raw):
        eid_seg_pairs.append((eid, seg))
        seg_counter[seg] += 1

log.info(f"  Total (EID, segment) pairs : {len(eid_seg_pairs):,}")
log.info(f"  Unique segments            : {len(seg_counter):,}")


seg_notes: dict[str, str] = {}   # segment -> 'country_rejected_<method>' when candidates existed but none matched the country


def _restrict(cands, explicit) -> set:
    """Keep ROR candidates located in one of the segment's explicit countries (all if none named)."""
    if explicit:
        return {c for c in cands if set(ror_metadata[c]["countries"]) & explicit}
    return set(cands)


def _exact_walk(raw_seg: str, parts: list[str], explicit, method: str):
    """Longest comma-prefix whose key has country-compatible candidates; accept only a unique one."""
    for n in range(len(parts), 0, -1):
        cands = exact_cands.get(exact_key(", ".join(parts[:n])))
        if not cands:
            continue
        ok = _restrict(cands, explicit)
        if not ok:
            seg_notes.setdefault(raw_seg, f"country_rejected_{method}")
            continue
        if len(ok) == 1:
            return next(iter(ok)), method
        return "", f"ambiguous_{method}"
    return None, None


def _gated(raw_seg: str, rid: str, method: str, score: float):
    """A fuzzy winner is accepted only if it passes the institutional gates A-E."""
    ok, failed = GATES.gates(raw_seg, ror_metadata[rid]["display"])
    if ok:
        return rid, method, score
    seg_notes[raw_seg] = f"fuzzy_gate_failed:{';'.join(failed)}|{ror_metadata[rid]['display']}"
    return "", "fuzzy_rejected", score


def match_segment(raw_seg: str) -> tuple[str, str, float]:
    """
    Returns (ror_id, method, score) or ("", <unresolved|ambiguous_*|manual_unresolvable>, score).
    method: manual_override | manual_unresolvable |
            exact | exact_stripped | acronym | fuzzy |
            fuzzy_tiebreak | fuzzy_country_preferred |
            ambiguous_exact | ambiguous_exact_stripped | ambiguous_acronym | ambiguous_fuzzy_tie |
            ambiguous_country | exact_component | exact_component_rightmost | ambiguous_exact_component |
            fuzzy_rejected | unresolved
    """
    parts    = [p.strip() for p in raw_seg.split(",")]
    sc       = NORM.segment(raw_seg)
    # A segment naming several distinct countries (after text-only collapse rules) is
    # country-ambiguous: no ROR match of any kind (no override, no unique-name fallback).
    if sc.status == "country_ambiguous":
        return "", "ambiguous_country", 0.0
    # a segment ending in a bare US state has non-African location evidence but no country: abstain
    if sc.status == "us_state_terminated":
        return "", "unresolved", 0.0
    explicit = {sc.primary} if sc.primary else set()          # restriction = the ONE resolved country
    hints    = [sc.primary] if sc.primary in AU54_ISO2 else []
    norm_seg = normalize(raw_seg)

    # ── Step 0: Manual override (country conflicts were gated at start-up) ─
    _ov = override_lookup.get(norm_seg)
    if _ov is not None:
        _ov_ror, _ = _ov
        if _ov_ror:
            return _ov_ror, "manual_override", 1.0
        else:
            return "", "manual_unresolvable", 0.0

    # ── Step A: Exact – article-normalised comma-prefix walk (country-restricted, unique) ─
    # An AMBIGUOUS exact walk is held and returned only if the component step below cannot
    #   resolve the segment to exactly one organisation (it can when the registered city is named)
    pending_ambiguous = None
    rid, m = _exact_walk(raw_seg, parts, explicit, "exact")
    if m and rid:
        return rid, m, 100.0
    if m:
        pending_ambiguous = m

    # ── Step A1b: Exact with unit-prefix stripped ──────────────────
    fallback = strip_unit_prefix(raw_seg)
    if fallback is not None:
        fb_parts = [p.strip() for p in fallback.split(",")]
        if pending_ambiguous is None:
            rid, m = _exact_walk(raw_seg, fb_parts, explicit, "exact_stripped")
            if m and rid:
                return rid, m, 100.0
            if m:
                pending_ambiguous = m

    # ── Step A1c: exact match of one institution-bearing comma-component ─
    #   (a real ROR name, else a registered-location qualified variant of one)
    comp_hits, comp_hit = [], False
    seg_comp_keys = {exact_key(c) for c in parts if c.strip()}
    for comp in parts:
        if not comp.strip() or GATES.is_country_component(comp):
            continue
        ids = set()
        for variant in {comp, re.sub(r"\([^)]*\)", " ", comp)}:
            k = exact_key(variant)
            cands = exact_cands.get(k) or qual_cands.get(k)
            if cands:
                comp_hit = True
                ids |= _restrict(cands, explicit)
        if len(ids) > 1:
            # same exact name, several organisations ('Obafemi Awolowo University' is also an alias of two other
            # Nigerian records): keep the one whose registered ROR city is itself a component of the segment
            by_city = {i for i in ids if ror_city_keys[i] & seg_comp_keys}
            if len(by_city) == 1:
                ids = by_city
                seg_notes.setdefault(raw_seg, "exact_component_city_disambiguated")
        if ids:
            comp_hits.append(ids)
    comp_ids = set().union(*comp_hits) if comp_hits else set()
    if comp_ids:
        if len(comp_ids) == 1:
            return next(iter(comp_ids)), "exact_component", 100.0
        # several components each name exactly ONE organisation ('Mohammadia School of Engineers, Mohammed V
        # University, Rabat'): Scopus orders an affiliation from the smallest unit to the institution, so the
        # right-most uniquely named organisation is taken; any component that is itself ambiguous -> abstain
        if all(len(ids) == 1 for ids in comp_hits):
            return next(iter(comp_hits[-1])), "exact_component_rightmost", 100.0
        return "", pending_ambiguous or "ambiguous_exact_component", 0.0
    if pending_ambiguous:
        return "", pending_ambiguous, 0.0
    if comp_hit:
        seg_notes.setdefault(raw_seg, "country_rejected_exact_component")

    # ── Step B: Acronym – all-caps token in first comma-part (country-restricted, unique) ─
    first = parts[0].strip()
    if re.match(r"^[A-Z]{2,10}$", first) and first in acronym_cands:
        ok = _restrict(acronym_cands[first], explicit)
        if len(ok) == 1:
            return next(iter(ok)), "acronym", 100.0
        if len(ok) > 1:
            return "", "ambiguous_acronym", 0.0
        seg_notes.setdefault(raw_seg, "country_rejected_acronym")

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
    score_seg = normalize(GATES.scoring_text(raw_seg))      # country-only components ignored
    top2 = rfprocess.extract(
        score_seg, cand_names,
        scorer=fuzz.partial_ratio,
        limit=2,
        score_cutoff=0,
    )

    if not top2 or top2[0][1] < FUZZY_THRESHOLD:
        return "", "unresolved", float(top2[0][1]) if top2 else 0.0

    _best_name, best_score, best_idx = top2[0]
    gap = best_score - (top2[1][1] if len(top2) > 1 else 0)

    if gap >= FUZZY_GAP:
        return _gated(raw_seg, candidates[best_idx][0], "fuzzy", float(best_score))

    # Gap too small — check for a perfect-score tie-break
    if best_score == 100.0:
        perfect_all = rfprocess.extract(
            score_seg, cand_names,
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
            return _gated(raw_seg, country_filtered[0][0], "fuzzy_tiebreak", 100.0)
        elif len(country_filtered) > 1:
            # several perfect candidates: abstain
            return "", "ambiguous_fuzzy_tie", 100.0

    # Imperfect gap, non-perfect score — check whether the top candidate has the wrong country
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
            return _gated(raw_seg, candidates[t2_idx][0], "fuzzy_country_preferred", float(t2_score))

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
log.info(f"  fuzzy_country_preferred : {method_counts['fuzzy_country_preferred']:,}")
for _m in ("exact_component", "exact_component_rightmost", "ambiguous_exact_component", "fuzzy_rejected", "ambiguous_country", "ambiguous_exact",
           "ambiguous_exact_stripped", "ambiguous_acronym", "ambiguous_fuzzy_tie"):
    log.info(f"  {_m:<24}: {method_counts[_m]:,}")
log.info(f"  unresolved              : {method_counts['unresolved']:,}")
log.info(f"  segment notes (types)   : {dict(Counter(v.split(':')[0] for v in seg_notes.values()))}")


# ──────────────────────────────────────────────────────────────────────────
# STEP 5 – Write slim_affil.csv  (one row per EID-segment)
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 5 – Writing slim_affil.csv ...")

slim_fields = ["eid", "segment_raw", "segment_norm",
               "ror_id", "ror_display", "country_code", "method", "score",
               "segment_country", "segment_explicit_countries", "segment_country_status",
               "ror_country_consistency", "match_note"]

seg_country = {seg: NORM.segment(seg) for seg in seg_counter}
consistency_counts: Counter = Counter()
with open(_tmp(SLIM_CSV), "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=slim_fields)
    writer.writeheader()
    buf = []
    for eid, raw_seg in tqdm(eid_seg_pairs, desc="writing slim", unit="row", ncols=72):
        ror_id, method, score = seg_results.get(raw_seg, ("", "unresolved", 0.0))
        meta     = ror_metadata.get(ror_id, {})
        display  = meta.get("display", "")
        cc_list  = meta.get("countries", [])
        cc       = cc_list[0] if cc_list else ""
        _sc      = seg_country[raw_seg]
        if not ror_id:
            _cons = ""
        elif _sc.primary is None:
            _cons = "no_segment_country"
        else:
            _tgt = set(cc_list) if ror_id in ror_metadata else override_target_cc.get(ror_id, set())
            _cons = "consistent" if _sc.primary in _tgt else "CONTRADICTORY"
        buf.append({
            "eid"          : eid,
            "segment_raw"  : raw_seg,
            "segment_norm" : normalize(raw_seg),
            "ror_id"       : ror_id,
            "ror_display"  : display,
            "country_code" : cc,
            "method"       : method,
            "score"        : f"{score:.2f}",
            "segment_country": _sc.primary or "",
            "segment_explicit_countries": ";".join(sorted(_sc.explicit)),
            "segment_country_status": _sc.status,
            "ror_country_consistency": _cons,
            "match_note"   : seg_notes.get(raw_seg, ""),
        })
        consistency_counts[(method, _cons)] += 1
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

# Counts are stored as text so records without segments (no agg row) merge to
# blank rather than turning the whole chunk's counts into floats ("3.0").
agg_df = pd.DataFrame([
    {
        "EID"            : eid,
        "n_segments"     : str(v["n_segments"]),
        "n_matched"      : str(v["n_matched"]),
        "ror_ids"        : ";".join(v["ror_ids"]),
        "match_methods"  : ";".join(v["methods"]),
        "match_countries": ";".join(v["countries"]),
    }
    for eid, v in eid_agg.items()
])
log.info(f"  Aggregated {len(agg_df):,} EIDs")
# direct, ROR-independent country attribution for EVERY record (ISO2, sorted)
country_df = pd.DataFrame([
    {"EID": eid, "affiliation_countries": ";".join(sorted(rc.countries)), "au_countries": ";".join(sorted(rc.au)),
     "n_country_unresolved_segments": str(rc.n_unresolved)}
    for eid, rc in record_countries.items()
])
_n_direct_au = int((country_df["au_countries"] != "").sum())
log.info(f"  Direct country attribution: {len(country_df):,} records; with >=1 AU country {_n_direct_au:,}; "
         f"with any country {int((country_df['affiliation_countries'] != '').sum()):,}")


# ──────────────────────────────────────────────────────────────────────────
# STEP 7 – Chunked merge → standardised.csv
# ──────────────────────────────────────────────────────────────────────────
log.info(f"Step 7 – Merging with {INPUT_CSV.name} (chunked) ...")

total_written = 0
header_written = False
input_rows = 0
std_eids: list[str] = []
src_columns: list[str] = []

for chunk in tqdm(
    pd.read_csv(INPUT_CSV, dtype=str, encoding="utf-8-sig",
                chunksize=CHUNK_SIZE, low_memory=False, keep_default_na=False),
    desc="merging", unit="chunk", ncols=72,
):
    if not src_columns:
        src_columns = chunk.columns.tolist()
    input_rows += len(chunk)
    merged = chunk.merge(agg_df, on="EID", how="left").merge(country_df, on="EID", how="left")
    for col in ("n_segments", "n_matched", "ror_ids", "match_methods", "match_countries",
                "affiliation_countries", "au_countries", "n_country_unresolved_segments"):
        if col not in merged.columns:
            merged[col] = ""
    merged.to_csv(
        _tmp(STD_CSV),
        mode="a" if header_written else "w",
        index=False,
        header=not header_written,
        encoding="utf-8",
    )
    header_written = True
    total_written += len(merged)
    std_eids.extend(merged["EID"])

log.info(f"  Written (temporary): {STD_CSV.name}  ({total_written:,} rows)")


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

with open(_tmp(REVIEW_CSV), "w", newline="", encoding="utf-8") as fh:
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
shutil.copy2(_tmp(SLIM_CSV), _tmp(AFFIL_LOG))
log.info(f"  Copied slim_affil.csv -> {AFFIL_LOG.name} (temporary)")


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
n_ambiguous           = {m: method_counts[m] for m in ("fuzzy_rejected", "ambiguous_exact_component", "ambiguous_country", "ambiguous_exact", "ambiguous_exact_stripped",
                                                           "ambiguous_acronym", "ambiguous_fuzzy_tie")}
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
    {"metric": "method_fuzzy_country_preferred", "value": method_counts["fuzzy_country_preferred"]},
    {"metric": "method_exact_component",        "value": method_counts["exact_component"]},
    {"metric": "method_exact_component_rightmost", "value": method_counts["exact_component_rightmost"]},
    *[{"metric": f"method_{m}", "value": v} for m, v in n_ambiguous.items()],
    {"metric": "method_unresolved",             "value": n_unresolved},
    {"metric": "review_candidates",             "value": len(unresolved_segs)},
    {"metric": "fuzzy_threshold",               "value": FUZZY_THRESHOLD},
    {"metric": "fuzzy_gap",                     "value": FUZZY_GAP},
]

with open(_tmp(RESULTS_CSV), "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=["metric", "value"])
    writer.writeheader()
    writer.writerows(results_rows)

log.info(f"  Written (temporary): {RESULTS_CSV.name}")


# ──────────────────────────────────────────────────────────────────────────
# STEP 11 – Internal validation, then promote temporary outputs
# ──────────────────────────────────────────────────────────────────────────
log.info("Step 11 – Internal validation ...")

def _count_csv_records(path: Path) -> int:
    with open(path, encoding="utf-8", newline="") as _fh:
        return sum(1 for _ in csv.reader(_fh)) - 1   # minus header


_input_eids = set(slim_df["EID"])
_std_eid_set = set(std_eids)
_n_eids_au = sum(1 for v in eid_agg.values() if v["countries"])   # ROR-institution AU countries (provenance)
_contradictory = {k: v for k, v in consistency_counts.items() if k[1] == "CONTRADICTORY"}
_codes_valid = all(c in NORM.name for rc in record_countries.values() for c in rc.countries)
checks = {
    "no accepted ROR match contradicts the explicit segment country": not _contradictory,
    "no arbitrary multi-candidate selection (fuzzy_tiebreak_first absent)": method_counts["fuzzy_tiebreak_first"] == 0,
    "manual overrides country-consistent": not OVERRIDE_CONFLICTS,
    "direct country codes valid": _codes_valid,
    "direct AU countries subset of AU-54": all(rc.au <= AU54_ISO2 for rc in record_countries.values()),
    "every input EID has a direct-country row": set(record_countries) == set(slim_df["EID"]),
    "standardised rows == input rows":          total_written == input_rows == len(slim_df),
    "standardised EIDs unique":                 len(_std_eid_set) == len(std_eids),
    "standardised EID set == input EID set":    _std_eid_set == _input_eids,
    "no blank EIDs":                            all(e.strip() for e in std_eids),
    "slim rows == EID-segment pairs":           _count_csv_records(_tmp(SLIM_CSV)) == len(eid_seg_pairs),
    "aggregated EIDs subset of input":          set(eid_agg) <= _input_eids,
    "input unchanged (SHA-256)":                sha256_file(INPUT_CSV) == INPUT_SHA,
    "overrides unchanged (SHA-256)":            sha256_file(OVERRIDES_CSV) == OVERRIDES_SHA,
    "ROR unchanged (SHA-256)":                  sha256_file(ROR_JSON) == ROR_SHA,
}
for _name, _ok in checks.items():
    log.info(f"  [{'PASS' if _ok else 'FAIL'}] {_name}")
if not all(checks.values()):
    log.error("Validation FAILED – temporary (.tmp) outputs kept for inspection; final paths untouched.")
    sys.exit(4)

for _final in (SLIM_CSV, STD_CSV, AFFIL_LOG, REVIEW_CSV, RESULTS_CSV):
    if ARGS.hold:
        log.info(f"  Held (not promoted): {_rel(_tmp(_final))}")
        continue
    os.replace(_tmp(_final), _final)
    log.info(f"  Promoted : {_rel(_final)}")

# ── Manifest and summary ────────────────────────────────────────────────────
log.info("Hashing outputs and writing manifest ...")
_n_records_with_segments = len(eid_agg)
_manifest = [
    ("input_scoped_corpus", INPUT_CSV,     input_rows,         len(_input_eids), INPUT_SHA),
    ("input_ror",           ROR_JSON,      len(ror_records),   None,             ROR_SHA),
    ("input_overrides",     OVERRIDES_CSV, None,               None,             OVERRIDES_SHA),
    ("input_country_reference", ARGS.country_reference, len(NORM.name), None,    REF_SHA),
    ("input_au54",          CLIST,         54,                 None,             CLIST_SHA),
    ("input_ror_global",    ARGS.ror_global, None,             None,             ROR_GLOBAL_SHA),
    ("output_standardised", STD_CSV,       total_written,      len(_std_eid_set), None),
    ("output_slim_affil",   SLIM_CSV,      len(eid_seg_pairs), len(eid_agg),     None),
    ("output_affil_log",    AFFIL_LOG,     len(eid_seg_pairs), len(eid_agg),     None),
    ("output_manual_review", REVIEW_CSV,   len(unresolved_segs), None,           None),
    ("output_results",      RESULTS_CSV,   len(results_rows),  None,             None),
]
with open(OVERRIDES_CSV, encoding="utf-8") as _f:
    _override_rows = sum(1 for _ in csv.DictReader(_f))
_hashes = {}
with open(ARGS.manifest, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(["role", "relative_path", "size_bytes", "row_count", "unique_eids", "sha256"])
    for role, path, nrow, neid, digest in _manifest:
        if ARGS.hold and role.startswith("output_"):
            path = _tmp(path)
        digest = digest or sha256_file(path)
        _hashes[role] = digest
        if role == "input_overrides":
            nrow = _override_rows
        w.writerow([role, _rel(path).removesuffix(".tmp"), path.stat().st_size,
                    "" if nrow is None else nrow, "" if neid is None else neid, digest])
        log.info(f"  {role:<22} {_rel(path)}  {path.stat().st_size:,} bytes  {digest}")

_pairs_by_method = Counter(seg_results[s][1] for _e, s in eid_seg_pairs)
_n_records = len(_input_eids)
summary = {
    "stage": "02_affiliation_standardisation; pipeline-internal name Stage 3C",
    "script_version": SCRIPT_VERSION,
    "input_path": _rel(INPUT_CSV),
    "input_rows": input_rows,
    "output_rows": total_written,
    "input_unique_eids": len(_input_eids),
    "output_unique_eids": len(_std_eid_set),
    "records_with_affiliation_segments": _n_records_with_segments,
    "records_without_affiliation_segments": _n_records - _n_records_with_segments,
    "eid_segment_pairs": len(eid_seg_pairs),
    "unique_segments": unique_segs,
    "unique_segments_matched": total_matched,
    "unique_segments_unmatched": unique_segs - total_matched,
    "unique_segment_counts_by_method": dict(sorted(method_counts.items())),
    "eid_segment_pair_counts_by_method": dict(sorted(_pairs_by_method.items())),
    "records_with_matched_ror": sum(1 for v in eid_agg.values() if v["n_matched"] > 0),
    "records_with_ror_institution_au_country (match_countries, provenance only)": _n_eids_au,
    "records_with_direct_au_country (au_countries)": _n_direct_au,
    "records_without_direct_au_country": _n_records - _n_direct_au,
    "records_with_any_direct_country": int((country_df["affiliation_countries"] != "").sum()),
    "direct_country_frequencies_au": dict(sorted(Counter(c for rc in record_countries.values() for c in rc.au).items())),
    "segments_without_direct_country": sum(rc.n_unresolved for rc in record_countries.values()),
    "segments_us_state_terminated": sum(rc.n_us_state_terminated for rc in record_countries.values()),
    "segments_country_ambiguous": sum(rc.n_country_ambiguous for rc in record_countries.values()),
    "accepted_matches_by_method_and_country_consistency": {f"{m}|{c}": v for (m, c), v in sorted(consistency_counts.items())},
    "segment_note_types": dict(Counter(v.split(":")[0] for v in seg_notes.values())),
    "fuzzy_gate_failures": dict(Counter(g for v in seg_notes.values() if v.startswith("fuzzy_gate_failed")
                                        for g in v.split(":", 1)[1].split("|")[0].split(";"))),
    "lookup_ambiguity": LOOKUP_STATS,
    "override_country_conflicts": OVERRIDE_CONFLICTS,
    "country_attribution_rule": "utils/country_normalisation.py: whole comma-part aliases, last 3 parts scanned from the end; US-state-terminated segments unresolved",
    "country_reference_sha256": REF_SHA, "au54_sha256": CLIST_SHA, "ror_global_sha256": ROR_GLOBAL_SHA,
    "manual_override_entries_loaded": len(override_lookup),
    "manual_override_file_rows": _override_rows,
    "unique_segments_resolved_by_manual_override": method_counts["manual_override"],
    "unique_segments_marked_manual_unresolvable": method_counts["manual_unresolvable"],
    "eid_segment_pairs_manual_override": _pairs_by_method["manual_override"],
    "eid_segment_pairs_manual_unresolvable": _pairs_by_method["manual_unresolvable"],
    "review_candidates_freq_ge_min": len(unresolved_segs),
    "review_min_freq": REVIEW_MIN_FREQ,
    "fuzzy_threshold": FUZZY_THRESHOLD,
    "fuzzy_gap": FUZZY_GAP,
    "ror_input": _rel(ROR_JSON),
    "ror_records": len(ror_records),
    "ror_sha256": ROR_SHA,
    "overrides_input": _rel(OVERRIDES_CSV),
    "overrides_sha256": OVERRIDES_SHA,
    "input_sha256": INPUT_SHA,
    "output_sha256": {k: v for k, v in _hashes.items() if k.startswith("output_")},
    "validation": {k: bool(v) for k, v in checks.items()},
    "versions": VERSIONS,
    "python_in_virtualenv": IN_VENV,
    "git_commit_at_start": GIT_HEAD,
    "git_tracked_changes_at_start": GIT_DIRTY,
    "run_started": RUN_START.isoformat(timespec="seconds"),
    "run_finished": datetime.now().isoformat(timespec="seconds"),
}
summary["promotion"] = {"status": "held_for_review" if ARGS.hold else "promoted"}
ARGS.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
log.info(f"Summary    : {_rel(ARGS.summary)}")
log.info(f"RESULT     : records {input_rows:,} | pairs {len(eid_seg_pairs):,} | unique segments "
         f"{unique_segs:,} | matched {total_matched:,} ({pct_matched:.2f}%) | records with AU country "
         f"{_n_eids_au:,} (ROR) | direct AU country {_n_direct_au:,}")
log.info("VALIDATION : PASS")
log.info(f"Finished in {(datetime.now() - RUN_START).total_seconds():.0f}s")


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
print(f"   ambiguous (abstained): {sum(n_ambiguous.values()):,}  {n_ambiguous}")
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
