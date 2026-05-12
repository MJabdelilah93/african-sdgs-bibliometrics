"""03_keyword_harmonisation.py
Stage 4 – Build domain thesaurus and produce enriched.csv.

Extracts Aurora SDG vocabulary, combines with top-500 corpus author
keywords, applies spelling / synonym rules, writes enriched.csv.

Run from article08/:
    python code/03_keyword_harmonisation.py
"""

import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from time import perf_counter

import pandas as pd
from lxml import etree
from tqdm import tqdm

# ── bootstrap ──────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parent
sys.path.insert(0, str(HERE))

from utils.config import cfg
from utils.logger import get_logger

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATE_STR = datetime.now().strftime("%Y-%m-%d")
log      = get_logger(f"stage4_keyword_{DATE_STR}")

# ── config ─────────────────────────────────────────────────────────────────
CHUNK_SIZE = 50_000
TOP_KW     = 500

# ── paths ──────────────────────────────────────────────────────────────────
AURORA_DIR    = ARTICLE / "sdg_queries" / "aurora"
STD_CSV       = ARTICLE / "data" / "interim" / "standardised.csv"
ENRICHED_CSV  = ARTICLE / "data" / "processed" / "enriched.csv"
PROV          = ARTICLE / cfg["paths"]["provenance"]
THESAURUS_CSV = PROV / "stage4_thesaurus.csv"

ENRICHED_CSV.parent.mkdir(parents=True, exist_ok=True)

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

all_cols = pd.read_csv(STD_CSV, nrows=0).columns.tolist()

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

for chunk in tqdm(
    pd.read_csv(
        STD_CSV, dtype=str, chunksize=CHUNK_SIZE,
        low_memory=False, keep_default_na=False,
    ),
    desc="harmonising", unit="chunk", ncols=72,
):
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
                for kw in r[0].split("; "):
                    if kw:
                        post_kw_counter[kw] += 1
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
    else:
        chunk["index_keywords_harmonised"] = ""

    # ── Write chunk ────────────────────────────────────────────────────────
    chunk.to_csv(
        ENRICHED_CSV,
        mode="a" if header_written else "w",
        index=False,
        header=not header_written,
        encoding="utf-8",
    )
    header_written = True
    total_written += len(chunk)

log.info(f"  Records written : {total_written:,}")

t_step4 = perf_counter() - t4

# ══════════════════════════════════════════════════════════════════════════
# STEP 5 – Write thesaurus CSV
# ══════════════════════════════════════════════════════════════════════════
log.info("Step 5 – Writing thesaurus CSV ...")

thesaurus_fields = [
    "source_term", "preferred_term", "rule_type", "justification",
    "multi_sdg_query_count", "potentially_multi_sdg",
]
with open(THESAURUS_CSV, "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=thesaurus_fields)
    writer.writeheader()
    writer.writerows(thesaurus_rows)

log.info(f"  Written : {THESAURUS_CSV.name}  ({len(thesaurus_rows):,} rows)")

# ══════════════════════════════════════════════════════════════════════════
# TERMINAL REPORT
# ══════════════════════════════════════════════════════════════════════════
t_total = perf_counter() - t0

std_rows  = sum(1 for _ in open(STD_CSV,      encoding="utf-8")) - 1
enr_rows  = sum(1 for _ in open(ENRICHED_CSV, encoding="utf-8")) - 1
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
