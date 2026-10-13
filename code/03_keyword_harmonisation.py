"""03_keyword_harmonisation.py
Stage 03 – build the keyword thesaurus and produce enriched.csv.

Extracts the Aurora SDG query vocabulary (standard-library ElementTree), combines it with the 500 most
frequent author keywords of the corpus, applies case, singular/plural, spelling, acronym and synonym rules,
and writes enriched.csv with harmonised author and index keywords and the thesaurus
(provenance/stage4_thesaurus.csv). Paths can be overridden on the command line; inputs and rule inputs are
hashed; outputs are written to .tmp files and promoted only after internal validation; a log, summary and
manifest are written to provenance/v2/; the run is refused outside a virtual environment.

Run from the repository root:
    python code/03_keyword_harmonisation.py
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
import xml.etree.ElementTree as etree
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from time import perf_counter

import pandas as pd
import tqdm as _tqdm_pkg
from tqdm import tqdm

# ── bootstrap ──────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parent
sys.path.insert(0, str(HERE))

from utils.config import cfg
from utils.checksums import sha256_file

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── config ─────────────────────────────────────────────────────────────────
CHUNK_SIZE = 50_000
TOP_KW     = 500
SCRIPT_VERSION = "2.0.0"

# ── paths ──────────────────────────────────────────────────────────────────
PROV    = ARTICLE / cfg["paths"]["provenance"]
V2_PROV = PROV / "v2"

_ap = argparse.ArgumentParser(description="Stage 03 / pipeline Stage 4 – keyword harmonisation")
_ap.add_argument("--input",      type=Path, default=ARTICLE / "data" / "interim" / "standardised.csv")
_ap.add_argument("--output",     type=Path, default=ARTICLE / "data" / "processed" / "enriched.csv")
_ap.add_argument("--aurora-dir", type=Path, default=ARTICLE / "sdg_queries" / "aurora")
_ap.add_argument("--thesaurus-out", type=Path, default=PROV / "stage4_thesaurus.csv")
_ap.add_argument("--summary",    type=Path, default=V2_PROV / "stage3_keyword_summary.json")
_ap.add_argument("--manifest",   type=Path, default=V2_PROV / "stage3_keyword_manifest.csv")
_ap.add_argument("--log",        type=Path, default=V2_PROV / "logs" / "03_keyword_harmonisation.log")
_ap.add_argument("--overwrite",  action="store_true", help="replace an existing enriched output (default: refuse)")
_ap.add_argument("--allow-global-python", action="store_true",
                 help="run outside a virtual environment (default: refuse; use .venv)")
ARGS = _ap.parse_args()

AURORA_DIR    = ARGS.aurora_dir
STD_CSV       = ARGS.input
ENRICHED_CSV  = ARGS.output
THESAURUS_CSV = ARGS.thesaurus_out


def _rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ARTICLE).as_posix()
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
log = logging.getLogger("03_keyword_harmonisation")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
for _h in (logging.FileHandler(ARGS.log, mode="w", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
    _h.setFormatter(_fmt)
    log.addHandler(_h)

RUN_START = datetime.now()
IN_VENV = sys.prefix != sys.base_prefix
VERSIONS = {"python": platform.python_version(), "pandas": pd.__version__, "tqdm": _tqdm_pkg.__version__,
            "xml_parser": "xml.etree.ElementTree (stdlib)"}
GIT_HEAD = _git("rev-parse", "HEAD")
GIT_DIRTY = bool(_git("status", "--porcelain", "--untracked-files=no"))

log.info("=" * 62)
log.info(f"STAGE 03 / pipeline Stage 4 – script v{SCRIPT_VERSION}")
log.info(f"Git HEAD   : {GIT_HEAD} (tracked changes: {GIT_DIRTY})")
log.info(f"Python     : {VERSIONS['python']}  (virtual environment: {IN_VENV})")
for _pkg in ("pandas", "tqdm"):
    log.info(f"{_pkg:<10} : {VERSIONS[_pkg]}  (requirements.txt pin: {_pinned(_pkg)})")
    if _pinned(_pkg) and VERSIONS[_pkg] != _pinned(_pkg):
        log.warning(f"{_pkg} {VERSIONS[_pkg]} differs from the pinned {_pinned(_pkg)}")
if not IN_VENV and not ARGS.allow_global_python:
    log.error("Not running inside a virtual environment – use .venv\\Scripts\\python.exe "
              "(or pass --allow-global-python deliberately).")
    sys.exit(2)
if not STD_CSV.exists() or not AURORA_DIR.is_dir():
    log.error(f"Required input missing: {_rel(STD_CSV)} or {_rel(AURORA_DIR)}")
    sys.exit(2)
if STD_CSV.resolve() in {ENRICHED_CSV.resolve(), THESAURUS_CSV.resolve()}:
    log.error("An output path equals the input path – refusing to run.")
    sys.exit(2)
if ENRICHED_CSV.exists() and not ARGS.overwrite:
    log.error(f"Output already exists: {_rel(ENRICHED_CSV)} (use --overwrite to replace).")
    sys.exit(2)

INPUT_SHA = sha256_file(STD_CSV)
SCRIPT_SHA = sha256_file(Path(__file__))
AURORA_SHA = {p.name: sha256_file(p) for p in sorted(AURORA_DIR.glob("query_SDG*.xml"))}
log.info(f"Input      : {_rel(STD_CSV)}  SHA-256 {INPUT_SHA}")
log.info(f"Rule tables: hard-coded in this script (SHA-256 {SCRIPT_SHA}); TOP_KW = {TOP_KW}")
log.info(f"Aurora XML : {_rel(AURORA_DIR)} ({len(AURORA_SHA)} files)")
for _n, _d in AURORA_SHA.items():
    log.info(f"  {_n:<20} {_d}")

ENRICHED_CSV.parent.mkdir(parents=True, exist_ok=True)
for _p in (THESAURUS_CSV, ARGS.summary, ARGS.manifest):
    _p.parent.mkdir(parents=True, exist_ok=True)

SEP  = "-" * 62
SEP2 = "=" * 62

# ── Aurora XML namespace ───────────────────────────────────────────────────
NS = {
    "aqd": "http://aurora-network.global/queries/namespace/",
    "dc":  "http://dublincore.org/documents/dcmi-namespace/",
}

# ── hard-coded rule tables ─────────────────────────────────────────────────
BA_MAP = {
    "behavior":           "behaviour",
    "behaviors":          "behaviours",
    "analyze":            "analyse",
    "analyzes":           "analyses",
    "analysis":           "analysis",     # already British, no-op placeholder
    "organization":       "organisation",
    "organizations":      "organisations",
    "urbanization":       "urbanisation",
    "urbanizations":      "urbanisations",
    "industrialization":  "industrialisation",
    "industrializations": "industrialisations",
    "fertilizer":         "fertiliser",
    "fertilizers":        "fertilisers",
    "labor":              "labour",
    "colour":             "colour",       # no-op: already British
    "color":              "colour",
    "colors":             "colours",
    "center":             "centre",
    "centers":            "centres",
    "meter":              "metre",
    "meters":             "metres",
    "catalog":            "catalogue",
    "catalogs":           "catalogues",
    "program":            "programme",
    "programs":           "programmes",
}
# Remove no-op entries
BA_MAP = {k: v for k, v in BA_MAP.items() if k != v}

ACRONYM_MAP = {
    "sdg":   "sustainable development goal",
    "sdgs":  "sustainable development goals",
    "ghg":   "greenhouse gas",
    "gdp":   "gross domestic product",
    "hiv":   "human immunodeficiency virus",
    "aids":  "acquired immunodeficiency syndrome",
    "tb":    "tuberculosis",
    "wash":  "water sanitation and hygiene",
    "ndc":   "nationally determined contribution",
    "fdi":   "foreign direct investment",
    "sme":   "small and medium enterprise",
    "ict":   "information and communication technology",
    "ngo":   "non-governmental organisation",
    "who":   "world health organization",
    "fao":   "food and agriculture organization",
    "cop":   "conference of the parties",
}

SYNONYM_MAP = {
    "climate crisis":       "climate change",
    "global warming":       "climate change",
    "food insecurity":      "food security",
    "undernourishment":     "malnutrition",
    "gender gap":           "gender inequality",
    "gender disparity":     "gender inequality",
    "clean energy":         "renewable energy",
    "green energy":         "renewable energy",
    "solar power":          "solar energy",
    "deforestation":        "forest loss",
    "desertification":      "land degradation",
    "rural electrification": "energy access",
}

# ── helpers ────────────────────────────────────────────────────────────────
_QUERY_OPERATORS = frozenset({
    "and", "or", "not", "near", "with", "the", "of", "by",
    "in", "to", "a", "an", "is", "are", "as", "at", "be",
    "do", "if", "it", "no", "so", "up", "us",
})


def norm_token(s: str) -> str:
    """Lowercase, strip punctuation (keep hyphens), collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^\w\s-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokenize_query_line(text: str) -> list[str]:
    """Extract vocabulary terms from an Aurora/Scopus query-line string."""
    tokens = []
    # Quoted phrases: strip quotes and trailing wildcards
    for m in re.finditer(r'"([^"]+)"', text):
        phrase = m.group(1).strip().rstrip("*").strip()
        phrase = norm_token(phrase)
        if phrase and len(phrase) >= 3:
            tokens.append(phrase)
    # Unquoted alphabetic tokens (not operators, not proximity markers)
    bare = re.sub(r'"[^"]*"', " ", text)
    for tok in re.split(r"[\s()/,\[\]]+", bare):
        tok = tok.strip()
        if not tok or not tok.isalpha():
            continue
        tok_l = tok.lower()
        if len(tok_l) >= 3 and tok_l not in _QUERY_OPERATORS:
            tokens.append(tok_l)
    return tokens


def harmonise_cell(cell: str, lookup: dict) -> tuple[str, int]:
    """Harmonise a '; '-delimited keyword string.

    Returns (harmonised_string, n_remapped) where n_remapped counts
    keywords where the preferred term differs from the lowercase input.
    """
    if not isinstance(cell, str) or not cell.strip():
        return "", 0
    parts = [p.strip() for p in cell.split("; ") if p.strip()]
    out, n = [], 0
    for kw in parts:
        kw_l = kw.lower()
        pref = lookup.get(kw_l, kw_l)
        out.append(pref)
        if pref != kw_l:
            n += 1
    return "; ".join(out), n


# ══════════════════════════════════════════════════════════════════════════
# STEP 1 – Extract Aurora vocabulary
# ══════════════════════════════════════════════════════════════════════════
t0 = perf_counter()
log.info(SEP2)
log.info("STAGE 4 – KEYWORD HARMONISATION")
log.info(SEP2)
log.info("Step 1 – Extracting Aurora vocabulary from 17 XML files ...")

# aurora_vocab[term] = set of SDG numbers (1-17) the term appears in
aurora_vocab: dict[str, set[int]] = defaultdict(set)

xml_files = sorted(AURORA_DIR.glob("query_SDG*.xml"))
for xml_path in xml_files:
    m = re.search(r"SDG(\d+)", xml_path.name)
    sdg_num = int(m.group(1)) if m else 0
    tree = etree.parse(str(xml_path))
    query_lines = tree.findall(".//aqd:query-line", NS)
    sdg_terms: set[str] = set()
    for el in query_lines:
        for tok in tokenize_query_line(el.text or ""):
            sdg_terms.add(tok)
    for tok in sdg_terms:
        aurora_vocab[tok].add(sdg_num)
    log.info(f"  SDG{sdg_num:02d}: {len(query_lines):3d} query-lines  "
             f"→ {len(sdg_terms):,} unique terms")

n_aurora = len(aurora_vocab)
log.info(f"  Total Aurora vocabulary terms : {n_aurora:,}")

t_step1 = perf_counter() - t0

# ══════════════════════════════════════════════════════════════════════════
# STEP 2 – Extract top 500 author keywords from corpus
# ══════════════════════════════════════════════════════════════════════════
t2 = perf_counter()
log.info("Step 2 – Extracting top 500 author keywords from corpus ...")

all_cols = pd.read_csv(STD_CSV, nrows=0, encoding="utf-8-sig").columns.tolist()

def find_col(cols: list[str], *patterns: str) -> str | None:
    for pat in patterns:
        for c in cols:
            if re.fullmatch(pat, c, re.IGNORECASE):
                return c
    return None

kw_col  = find_col(all_cols, r"author.keywords", r"author keywords", r"de")
idx_col = find_col(all_cols, r"index.keywords",  r"index keywords",  r"id")
log.info(f"  Author Keywords column : {kw_col!r}")
log.info(f"  Index Keywords column  : {idx_col!r}")

kw_counter:   Counter = Counter()   # lowercase → frequency
kw_raw_forms: dict    = {}          # lowercase → first raw form seen

if kw_col:
    cols_to_read = [kw_col]
    for chunk in pd.read_csv(
        STD_CSV, usecols=cols_to_read, dtype=str,
        chunksize=CHUNK_SIZE, low_memory=False, keep_default_na=False,
    ):
        for cell in chunk[kw_col]:
            if not cell:
                continue
            for kw in cell.split("; "):
                kw = kw.strip()
                if not kw:
                    continue
                kw_l = kw.lower()
                kw_counter[kw_l] += 1
                if kw_l not in kw_raw_forms:
                    kw_raw_forms[kw_l] = kw

top500_kw: dict[str, int] = dict(kw_counter.most_common(TOP_KW))
log.info(f"  Unique lowercase keywords in corpus : {len(kw_counter):,}")
log.info(f"  Top {TOP_KW} selected.")

t_step2 = perf_counter() - t2

# ══════════════════════════════════════════════════════════════════════════
# STEP 3 – Build thesaurus
# ══════════════════════════════════════════════════════════════════════════
t3 = perf_counter()
log.info("Step 3 – Building thesaurus ...")

vocab_set: set[str] = set(aurora_vocab.keys()) | set(top500_kw.keys())
n_combined_before = len(aurora_vocab) + len(top500_kw)
n_combined_after  = len(vocab_set)

log.info(f"  Aurora vocab              : {len(aurora_vocab):,}")
log.info(f"  Top-{TOP_KW} author kw        : {len(top500_kw):,}")
log.info(f"  Combined before dedup     : {n_combined_before:,}")
log.info(f"  Combined after dedup      : {n_combined_after:,}")

thesaurus_rows: list[dict] = []
apply_lookup:   dict       = {}    # lowercase_source → preferred_term
rule_counts:    Counter    = Counter()


def _add(source: str, preferred: str, rule: str, just: str) -> None:
    """Register a thesaurus mapping."""
    if source == preferred:
        return
    sdg_n = len(aurora_vocab.get(source, set()))
    thesaurus_rows.append({
        "source_term":          source,
        "preferred_term":       preferred,
        "rule_type":            rule,
        "justification":        just,
        "multi_sdg_query_count": sdg_n,
        "potentially_multi_sdg": sdg_n >= 2,
    })
    apply_lookup[source] = preferred
    rule_counts[rule] += 1


# ── Vocabulary-dependent rules (iterate vocab, first match wins) ───────────
for term in sorted(vocab_set):
    # british_american
    if term in BA_MAP:
        _add(term, BA_MAP[term], "british_american",
             f"American → British spelling")
        continue

    # plural_singular
    if term.endswith("ies"):
        singular = term[:-3] + "y"
        if singular in vocab_set:
            _add(term, singular, "plural_singular",
                 f"Plural 'ies' → singular")
            continue
    elif (term.endswith("s") and not term.isupper()
          and len(term) - 1 >= 5):
        singular = term[:-1]
        if singular in vocab_set:
            _add(term, singular, "plural_singular",
                 f"Plural 's' → singular")
            continue

    # hyphen: prefer unhyphenated if both exist in vocab
    if "-" in term:
        dehyph = term.replace("-", "")
        if dehyph in vocab_set:
            _add(term, dehyph, "hyphen",
                 f"Hyphenated → unhyphenated form")
            continue

    # acronym_expansion
    if term in ACRONYM_MAP:
        _add(term, ACRONYM_MAP[term], "acronym_expansion",
             f"Acronym expansion")
        continue

    # synonym_map
    if term in SYNONYM_MAP:
        _add(term, SYNONYM_MAP[term], "synonym_map",
             f"Synonym → preferred term")
        continue

# ── Always-apply hard-coded rules (add if not already mapped) ─────────────
for src, pref in ACRONYM_MAP.items():
    if src not in apply_lookup:
        _add(src, pref, "acronym_expansion", "Acronym expansion (always-apply)")

for src, pref in SYNONYM_MAP.items():
    if src not in apply_lookup:
        _add(src, pref, "synonym_map", "Synonym mapping (always-apply)")

# ── case_fold: document raw author keyword forms that need lowercasing ─────
for kw_l, raw in kw_raw_forms.items():
    if kw_l in top500_kw and raw != kw_l:
        # Record original mixed-case → lowercase (does not modify apply_lookup;
        # lowercasing is applied before any lookup during harmonisation)
        sdg_n = len(aurora_vocab.get(kw_l, set()))
        thesaurus_rows.append({
            "source_term":           raw,
            "preferred_term":        kw_l,
            "rule_type":             "case_fold",
            "justification":         "Normalise to lowercase",
            "multi_sdg_query_count": sdg_n,
            "potentially_multi_sdg": sdg_n >= 2,
        })
        rule_counts["case_fold"] += 1

n_multi_sdg = sum(1 for r in thesaurus_rows if r["potentially_multi_sdg"])
log.info(f"  Thesaurus mappings total  : {len(thesaurus_rows):,}")
log.info(f"    case_fold               : {rule_counts['case_fold']:,}")
log.info(f"    british_american        : {rule_counts['british_american']:,}")
log.info(f"    plural_singular         : {rule_counts['plural_singular']:,}")
log.info(f"    hyphen                  : {rule_counts['hyphen']:,}")
log.info(f"    acronym_expansion       : {rule_counts['acronym_expansion']:,}")
log.info(f"    synonym_map             : {rule_counts['synonym_map']:,}")
log.info(f"  Potentially multi-SDG     : {n_multi_sdg:,}")

t_step3 = perf_counter() - t3

# ══════════════════════════════════════════════════════════════════════════
# STEP 4 – Apply thesaurus to corpus (chunked)
# ══════════════════════════════════════════════════════════════════════════
t4 = perf_counter()
log.info("Step 4 – Applying thesaurus to corpus (chunked) ...")
log.info(f"  Input  : {STD_CSV.name}")
log.info(f"  Output : {ENRICHED_CSV.name}")

# Stats accumulators
n_author_records_changed = 0
n_index_records_changed  = 0
n_total_harmonisations   = 0
total_written            = 0
header_written           = False

# For top-20 harmonised keywords
post_kw_counter: Counter = Counter()

# bookkeeping (statistics and validation only; outputs unaffected)
input_rows = 0
enr_eids: list[str] = []
in_columns: list[str] = []
n_author_records_with_kw = 0
n_index_records_with_kw = 0
n_author_tokens = 0
n_index_tokens = 0
n_index_harmonisations = 0
post_idx_counter: Counter = Counter()

for chunk in tqdm(
    pd.read_csv(
        STD_CSV, dtype=str, chunksize=CHUNK_SIZE,
        low_memory=False, keep_default_na=False, encoding="utf-8-sig",
    ),
    desc="harmonising", unit="chunk", ncols=72,
):
    if not in_columns:
        in_columns = chunk.columns.tolist()
    input_rows += len(chunk)
    # ── Author Keywords ────────────────────────────────────────────────────
    if kw_col and kw_col in chunk.columns:
        results = chunk[kw_col].apply(
            lambda c: harmonise_cell(c, apply_lookup)
        )
        chunk["keywords_harmonised"] = [r[0] for r in results]
        n_changed = sum(1 for r in results if r[1] > 0)
        n_author_records_changed += n_changed
        n_total_harmonisations   += sum(r[1] for r in results)
        # Collect post-harmonisation keyword frequencies
        for r in results:
            if r[0]:
                n_author_records_with_kw += 1
                for kw in r[0].split("; "):
                    if kw:
                        post_kw_counter[kw] += 1
                        n_author_tokens += 1
    else:
        chunk["keywords_harmonised"] = ""

    # ── Index Keywords ─────────────────────────────────────────────────────
    if idx_col and idx_col in chunk.columns:
        idx_results = chunk[idx_col].apply(
            lambda c: harmonise_cell(c, apply_lookup)
        )
        chunk["index_keywords_harmonised"] = [r[0] for r in idx_results]
        n_idx_changed = sum(1 for r in idx_results if r[1] > 0)
        n_index_records_changed += n_idx_changed
        n_index_harmonisations  += sum(r[1] for r in idx_results)
        for r in idx_results:
            if r[0]:
                n_index_records_with_kw += 1
                for kw in r[0].split("; "):
                    if kw:
                        post_idx_counter[kw] += 1
                        n_index_tokens += 1
    else:
        chunk["index_keywords_harmonised"] = ""

    # ── Write chunk ────────────────────────────────────────────────────────
    chunk.to_csv(
        _tmp(ENRICHED_CSV),
        mode="a" if header_written else "w",
        index=False,
        header=not header_written,
        encoding="utf-8",
    )
    header_written = True
    total_written += len(chunk)
    enr_eids.extend(chunk["EID"])

log.info(f"  Records written (temporary) : {total_written:,}")

t_step4 = perf_counter() - t4

# ══════════════════════════════════════════════════════════════════════════
# STEP 5 – Write thesaurus CSV
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 5 – Writing thesaurus CSV ...")

thesaurus_fields = [
    "source_term", "preferred_term", "rule_type", "justification",
    "multi_sdg_query_count", "potentially_multi_sdg",
]
with open(_tmp(THESAURUS_CSV), "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=thesaurus_fields)
    writer.writeheader()
    writer.writerows(thesaurus_rows)

log.info(f"  Written (temporary) : {THESAURUS_CSV.name}  ({len(thesaurus_rows):,} rows)")

# ══════════════════════════════════════════════════════════════════════════
# STEP 6 – Internal validation, promote outputs, manifest and summary
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 6 – Internal validation ...")
_out_header = pd.read_csv(_tmp(ENRICHED_CSV), nrows=0, encoding="utf-8").columns.tolist()
_eid_set = set(enr_eids)
checks = {
    "rows written == rows read":                  total_written == input_rows,
    "output EIDs unique":                         len(_eid_set) == len(enr_eids),
    "no blank EIDs":                              all(e.strip() for e in enr_eids),
    "output columns == input columns + 2 added":  _out_header == in_columns + ["keywords_harmonised",
                                                                              "index_keywords_harmonised"],
    "input unchanged (SHA-256)":                  sha256_file(STD_CSV) == INPUT_SHA,
    "Aurora XML unchanged (SHA-256)":             {p.name: sha256_file(p) for p in
                                                   sorted(AURORA_DIR.glob("query_SDG*.xml"))} == AURORA_SHA,
    "script unchanged during run (SHA-256)":      sha256_file(Path(__file__)) == SCRIPT_SHA,
}
for _name, _ok in checks.items():
    log.info(f"  [{'PASS' if _ok else 'FAIL'}] {_name}")
if not all(checks.values()):
    log.error("Validation FAILED – temporary (.tmp) outputs kept for inspection; final paths untouched.")
    sys.exit(4)
for _final in (ENRICHED_CSV, THESAURUS_CSV):
    os.replace(_tmp(_final), _final)
    log.info(f"  Promoted : {_rel(_final)}")

log.info("Hashing outputs and writing manifest ...")
ENRICHED_SHA = sha256_file(ENRICHED_CSV)
THESAURUS_SHA = sha256_file(THESAURUS_CSV)
_manifest = [("input_standardised", STD_CSV, input_rows, len(_eid_set), INPUT_SHA),
             ("rule_tables_in_script", Path(__file__), None, None, SCRIPT_SHA)]
_manifest += [(f"rule_input_aurora_{p.stem}", p, None, None, AURORA_SHA[p.name])
              for p in sorted(AURORA_DIR.glob("query_SDG*.xml"))]
_manifest += [("output_enriched", ENRICHED_CSV, total_written, len(_eid_set), ENRICHED_SHA),
              ("output_thesaurus", THESAURUS_CSV, len(thesaurus_rows), None, THESAURUS_SHA)]
with open(ARGS.manifest, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(["role", "relative_path", "size_bytes", "row_count", "unique_eids", "sha256"])
    for role, path, nrow, neid, digest in _manifest:
        w.writerow([role, _rel(path), path.stat().st_size,
                    "" if nrow is None else nrow, "" if neid is None else neid, digest])
log.info(f"  output_enriched  {_rel(ENRICHED_CSV)}  {ENRICHED_CSV.stat().st_size:,} bytes  {ENRICHED_SHA}")
log.info(f"  output_thesaurus {_rel(THESAURUS_CSV)}  {THESAURUS_CSV.stat().st_size:,} bytes  {THESAURUS_SHA}")

# Top-N boundary diagnostics (descriptive only; selection itself unchanged)
_ranked = kw_counter.most_common()
_cut = _ranked[TOP_KW - 1][1] if len(_ranked) >= TOP_KW else None
_boundary = {
    "frequency_at_rank_top_kw": _cut,
    "frequency_at_rank_top_kw_plus_1": _ranked[TOP_KW][1] if len(_ranked) > TOP_KW else None,
    "keywords_with_cutoff_frequency_total": sum(1 for _k, f in _ranked if f == _cut),
    "keywords_with_cutoff_frequency_selected": sum(1 for _k, f in _ranked[:TOP_KW] if f == _cut),
    "selection_tie_break": "Counter.most_common order (first-seen order in the input corpus)",
}
summary = {
    "stage": "03_keyword_harmonisation; pipeline-internal name Stage 4",
    "script_version": SCRIPT_VERSION,
    "input_path": _rel(STD_CSV), "output_path": _rel(ENRICHED_CSV), "thesaurus_path": _rel(THESAURUS_CSV),
    "input_rows": input_rows, "output_rows": total_written,
    "input_unique_eids": len(_eid_set), "output_unique_eids": len(_eid_set),
    "keyword_source_fields": {"author": kw_col, "index": idx_col},
    "aurora_xml_files": len(AURORA_SHA), "aurora_vocabulary_terms": n_aurora,
    "author_keyword_vocabulary_lowercase": len(kw_counter),
    "top_kw_parameter": TOP_KW, "top_kw_selected": len(top500_kw), "top_kw_boundary": _boundary,
    "combined_vocabulary_before_dedup": n_combined_before, "combined_vocabulary_after_dedup": n_combined_after,
    "thesaurus_rows": len(thesaurus_rows), "thesaurus_rule_counts": dict(sorted(rule_counts.items())),
    "apply_lookup_mappings": len(apply_lookup), "potentially_multi_sdg_rows": n_multi_sdg,
    "author_keywords": {"records_with_keywords": n_author_records_with_kw,
                        "records_without_keywords": total_written - n_author_records_with_kw,
                        "tokens_processed": n_author_tokens,
                        "tokens_changed_by_lookup": n_total_harmonisations,
                        "tokens_unchanged_by_lookup": n_author_tokens - n_total_harmonisations,
                        "records_with_any_change": n_author_records_changed,
                        "harmonised_vocabulary": len(post_kw_counter)},
    "index_keywords": {"records_with_keywords": n_index_records_with_kw,
                       "records_without_keywords": total_written - n_index_records_with_kw,
                       "tokens_processed": n_index_tokens,
                       "tokens_changed_by_lookup": n_index_harmonisations,
                       "tokens_unchanged_by_lookup": n_index_tokens - n_index_harmonisations,
                       "records_with_any_change": n_index_records_changed,
                       "harmonised_vocabulary": len(post_idx_counter)},
    "note_tokens": "all output tokens are lowercased; 'changed_by_lookup' counts tokens whose preferred term "
                   "differs from the lowercased input (the pipeline's own n_remapped definition)",
    "input_sha256": INPUT_SHA, "output_sha256": ENRICHED_SHA, "thesaurus_sha256": THESAURUS_SHA,
    "rule_tables_script_sha256": SCRIPT_SHA, "aurora_sha256": AURORA_SHA,
    "validation": {k: bool(v) for k, v in checks.items()},
    "versions": VERSIONS, "python_in_virtualenv": IN_VENV,
    "git_commit_at_start": GIT_HEAD, "git_tracked_changes_at_start": GIT_DIRTY,
    "run_started": RUN_START.isoformat(timespec="seconds"),
    "run_finished": datetime.now().isoformat(timespec="seconds"),
}
ARGS.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
log.info(f"Summary    : {_rel(ARGS.summary)}")
log.info(f"RESULT     : rows {total_written:,} | author kw vocab {len(kw_counter):,} -> {len(post_kw_counter):,} "
         f"| thesaurus {len(thesaurus_rows):,} | author tokens changed {n_total_harmonisations:,} "
         f"| index tokens changed {n_index_harmonisations:,}")
log.info(f"Top-{TOP_KW} boundary: {_boundary}")
log.info("VALIDATION : PASS")

# ══════════════════════════════════════════════════════════════════════════
# TERMINAL REPORT
# ══════════════════════════════════════════════════════════════════════════
t_total = perf_counter() - t0

std_rows  = input_rows      # counted while streaming
enr_rows  = total_written
enr_size  = ENRICHED_CSV.stat().st_size / 1e9

print(f"\n{SEP2}")
print(" STAGE 4 – KEYWORD HARMONISATION REPORT")
print(SEP2)

print(f"\n{SEP}\nA. VOCABULARY SUMMARY\n{SEP}")
print(f"   Aurora vocabulary terms extracted : {n_aurora:,}")
print(f"   Top {TOP_KW} author keywords selected")
print(f"   Combined before dedup             : {n_combined_before:,}")
print(f"   Combined after dedup              : {n_combined_after:,}")

print(f"\n   Top 20 author keywords (frequency):")
print(f"   {'Rank':<5} {'Keyword':<45} {'Freq':>8}")
print(f"   {'-'*5} {'-'*45} {'-'*8}")
for i, (kw, freq) in enumerate(kw_counter.most_common(20), 1):
    print(f"   {i:<5} {kw:<45} {freq:>8,}")

print(f"\n{SEP}\nB. THESAURUS SUMMARY\n{SEP}")
print(f"   Total mappings created : {len(thesaurus_rows):,}")
print(f"   By rule type:")
print(f"     case_fold            : {rule_counts['case_fold']:,}")
print(f"     british_american     : {rule_counts['british_american']:,}")
print(f"     plural_singular      : {rule_counts['plural_singular']:,}")
print(f"     hyphen               : {rule_counts['hyphen']:,}")
print(f"     acronym_expansion    : {rule_counts['acronym_expansion']:,}")
print(f"     synonym_map          : {rule_counts['synonym_map']:,}")
pct_multi = 100 * n_multi_sdg / len(thesaurus_rows) if thesaurus_rows else 0
print(f"   Potentially multi-SDG  : {n_multi_sdg:,}  ({pct_multi:.1f}%)")

print(f"\n{SEP}\nC. HARMONISATION EFFECT ON CORPUS\n{SEP}")
pct_ak = 100 * n_author_records_changed / total_written if total_written else 0
pct_ik = 100 * n_index_records_changed  / total_written if total_written else 0
print(f"   Records with >=1 Author KW harmonised : "
      f"{n_author_records_changed:,}  ({pct_ak:.1f}%)")
print(f"   Records with >=1 Index KW harmonised  : "
      f"{n_index_records_changed:,}  ({pct_ik:.1f}%)")
print(f"   Total individual harmonisations applied: {n_total_harmonisations:,}")

print(f"\n{SEP}\nD. TOP 20 HARMONISED KEYWORDS (post-harmonisation)\n{SEP}")
print(f"   {'Rank':<5} {'Keyword':<45} {'Freq':>8}")
print(f"   {'-'*5} {'-'*45} {'-'*8}")
for i, (kw, freq) in enumerate(post_kw_counter.most_common(20), 1):
    print(f"   {i:<5} {kw:<45} {freq:>8,}")

print(f"\n{SEP}\nE. OUTPUT FILES\n{SEP}")
print(f"   data/processed/enriched.csv         : "
      f"{enr_size:.3f} GB   {enr_rows:,} rows")
print(f"   provenance/stage4_thesaurus.csv     : {len(thesaurus_rows):,} rows")
row_match = "✓ MATCH" if enr_rows == std_rows else f"✗ MISMATCH (standardised={std_rows:,})"
print(f"   enriched.csv row count vs standardised.csv : {row_match}")

print(f"\n{SEP}\nF. TIMING\n{SEP}")
print(f"   Step 1  Aurora vocab extraction    : {t_step1:>6.1f} s")
print(f"   Step 2  Top-500 keyword scan       : {t_step2:>6.1f} s")
print(f"   Step 3  Thesaurus build            : {t_step3:>6.1f} s")
print(f"   Step 4  Corpus harmonisation       : {t_step4:>6.1f} s")
print(f"   Total                              : {t_total:>6.1f} s  "
      f"({t_total/60:.1f} min)")

print(f"\n{SEP2}")
print(" STAGE 4 COMPLETE – DO NOT COMMIT YET")
print(SEP2)
