"""01_deduplication.py
Stage 3A – Deduplicate the raw Scopus corpus.

Three-pass cascade:
  Pass 1: EID exact match  (Scopus Electronic Item Identifier, vectorised).
  Pass 2: DOI exact match  (records not resolved by Pass 1, vectorised).
  Pass 3: Fuzzy title match (records with neither EID nor DOI, rapidfuzz).

Run from article08/:
    python code/01_deduplication.py
"""

import re
import sys
import time
import random
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.process import cdist as rf_cdist

# ── bootstrap path so "from utils.x" works ───────────────────────────────────
HERE    = Path(__file__).resolve().parent   # article08/code/
ARTICLE = HERE.parent                       # article08/
sys.path.insert(0, str(HERE))

from utils.config    import cfg
from utils.logger    import get_logger
from utils.checksums import sha256_file

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# pandas 3.x defaults to Arrow-backed strings; revert to numpy object dtype
# to avoid ArrowMemoryError on large corpora and stay compatible with 2.x code.
pd.options.future.infer_string = False

# ── logging ───────────────────────────────────────────────────────────────────
TODAY  = date.today().isoformat()
logger = get_logger(f"stage3a_dedup_{TODAY}")
log    = logger.info
warn   = logger.warning

# ── paths ─────────────────────────────────────────────────────────────────────
RAW     = ARTICLE / cfg["paths"]["raw_data"]
INTERIM = ARTICLE / cfg["paths"]["interim_data"]
PROV    = ARTICLE / cfg["paths"]["provenance"]
INTERIM.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = PROV  / "stage2_acquisition_manifest.csv"
DEDUP_OUT     = INTERIM / "deduplicated.csv"
DEDUP_LOG     = PROV  / "stage3_dedup_log.csv"
CHECKSUMS_TXT = PROV  / "stage2_checksums.txt"

# ── thresholds ────────────────────────────────────────────────────────────────
FUZZY_THRESHOLD = float(cfg["cleaning"]["dedup_title_threshold"])   # 0.95
YEAR_WINDOW     = int(cfg["cleaning"]["dedup_year_window"])          # 1
FUZZY_SCORE_CUT = FUZZY_THRESHOLD * 100                             # 95.0

FILE_RE = re.compile(r"^SDG(\d{2})_AU54_.*\.csv$")

# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def find_col(columns, *candidates):
    lc = {c.lower(): c for c in columns}
    for cand in candidates:
        hit = lc.get(cand.lower())
        if hit:
            return hit
    return None


def clean_title(s):
    if not isinstance(s, str) or not s.strip():
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def merge_sdg_tags(*tag_strings):
    """Merge one or more comma-separated SDG-number strings into a sorted string."""
    nums = set()
    for ts in tag_strings:
        if pd.notna(ts):
            for part in str(ts).split(","):
                p = part.strip()
                if p.isdigit():
                    nums.add(int(p))
    return ",".join(str(n) for n in sorted(nums))


# Union-Find with path compression + rank
class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank   = [0] * n

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x, y):
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1

    def clusters(self):
        groups = defaultdict(list)
        for i in range(len(self.parent)):
            groups[self.find(i)].append(i)
        return groups


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – CONCATENATION
# ─────────────────────────────────────────────────────────────────────────────
log("=" * 62)
log("STAGE 3A – DEDUPLICATION  (three-pass: EID → DOI → fuzzy)")
log("=" * 62)
t0_total = time.time()

csv_files = sorted(f for f in RAW.iterdir() if FILE_RE.match(f.name))
log(f"CSV files found: {len(csv_files)}")

manifest = pd.read_csv(MANIFEST_PATH)
manifest_total = int(manifest["raw_record_count"].sum())
log(f"Manifest total : {manifest_total:,}")

# Discover key column names from the first file (all Scopus exports share the same schema)
_first_f = csv_files[0]
for _enc in ("utf-8-sig", "utf-8", "latin-1"):
    try:
        _hdr = pd.read_csv(_first_f, nrows=0, encoding=_enc, dtype=object)
        break
    except Exception:
        continue
_all_hdr_cols = _hdr.columns.tolist()
del _hdr
_doi_key   = find_col(_all_hdr_cols, "doi",   "DOI")
_title_key = find_col(_all_hdr_cols, "title", "Title")
_year_key  = find_col(_all_hdr_cols, "year",  "Year")
_eid_key   = find_col(_all_hdr_cols, "eid",   "EID", "Scopus EID")
_usecols   = [c for c in [_eid_key, _doi_key, _title_key, _year_key] if c]
log(f"Phase 1 key columns ({len(_usecols)}): {_usecols}")

frames          = []
partial_dfs     = []
BATCH_SIZE      = 8          # concat every 8 files to cap peak memory
per_file_counts = {}
row_id_start    = 0          # global row counter for Phase 2 cross-reference

for f in csv_files:
    m = FILE_RE.match(f.name)
    sdg_num = int(m.group(1))
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df_f = pd.read_csv(f, encoding=enc, dtype=object, usecols=_usecols)
            break
        except Exception:
            continue
    else:
        log(f"ERROR: cannot decode {f.name}")
        sys.exit(1)

    n_f = len(df_f)
    df_f["sdg_number"]  = str(sdg_num)
    df_f["source_file"] = f.name
    df_f["_row_id"]     = list(range(row_id_start, row_id_start + n_f))
    row_id_start += n_f
    per_file_counts[f.name] = n_f
    frames.append(df_f)
    log(f"  {f.name:<55} {n_f:>7,}")
    if len(frames) >= BATCH_SIZE:
        partial_dfs.append(pd.concat(frames, ignore_index=True, sort=False))
        frames = []

if frames:
    partial_dfs.append(pd.concat(frames, ignore_index=True, sort=False))

df = pd.concat(partial_dfs, ignore_index=True, sort=False)
del partial_dfs, frames
total_raw = len(df)
log(f"\nTotal concatenated : {total_raw:,}  (manifest {manifest_total:,})")
if total_raw != manifest_total:
    warn(f"  Row count mismatch: {total_raw} vs {manifest_total}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – COLUMN DISCOVERY, DOI STANDARDISATION & EID STANDARDISATION
# ─────────────────────────────────────────────────────────────────────────────
doi_col   = find_col(df.columns, "doi", "DOI")
title_col = find_col(df.columns, "title", "Title")
year_col  = find_col(df.columns, "year", "Year")
eid_col   = find_col(df.columns, "eid", "EID", "Scopus EID")

if not doi_col:
    log("ERROR: DOI column not found"); sys.exit(1)
if not title_col:
    log("ERROR: Title column not found"); sys.exit(1)

log(f"\nColumns: DOI='{doi_col}'  Title='{title_col}'  "
    f"Year='{year_col}'  EID='{eid_col}'")

# DOI standardisation
doi_std = (
    df[doi_col]
    .astype(str)
    .str.lower()
    .str.strip()
    .str.replace(r"^https?://doi\.org/", "", regex=True)
    .str.replace(r"^doi:\s*", "",         regex=True)
)
doi_std = doi_std.replace({"": pd.NA, "-": pd.NA, "none": pd.NA,
                            "nan": pd.NA, "n/a": pd.NA, "#name?": pd.NA})
df["_doi_std"] = doi_std

# EID standardisation (format: "2-s2.0-XXXXXXXXXX")
if eid_col:
    eid_std = (
        df[eid_col]
        .astype(str)
        .str.strip()
    )
    eid_std = eid_std.replace({"": pd.NA, "-": pd.NA, "none": pd.NA,
                               "nan": pd.NA, "n/a": pd.NA})
else:
    warn("EID column not found – Pass 1 will be skipped")
    eid_std = pd.Series(pd.NA, index=df.index, dtype=object)

df["_eid_std"] = eid_std

valid_doi = df["_doi_std"].notna()
valid_eid = df["_eid_std"].notna()

n_valid_doi  = int(valid_doi.sum())
n_missing_doi = int((~valid_doi).sum())
n_valid_eid  = int(valid_eid.sum())
n_missing_eid = int((~valid_eid).sum())

log(f"\nDOI valid   : {n_valid_doi:,}  ({100*n_valid_doi/total_raw:.1f}%)")
log(f"DOI missing : {n_missing_doi:,} ({100*n_missing_doi/total_raw:.1f}%)")
log(f"EID valid   : {n_valid_eid:,}  ({100*n_valid_eid/total_raw:.1f}%)")
log(f"EID missing : {n_missing_eid:,} ({100*n_missing_eid/total_raw:.1f}%)")

# Initial sdg_tags = single sdg_number as string
df["sdg_tags"] = df["sdg_number"].astype(str)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – PASS 1: EID EXACT DEDUPLICATION  (vectorised)
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "-" * 62)
log("PASS 1 – EID exact deduplication")
log("-" * 62)
t0_p1 = time.time()

eid_df = df[valid_eid].copy()

# Merge sdg_tags per EID group (use existing sdg_tags, which are single ints here)
sdg_by_eid = (
    eid_df.groupby("_eid_std", sort=False)["sdg_tags"]
    .apply(lambda tags: merge_sdg_tags(*tags.tolist()))
)
eid_df["sdg_tags"] = eid_df["_eid_std"].map(sdg_by_eid)

# Non-null count for tie-breaking
eid_df["_nonnull"] = eid_df.notna().sum(axis=1)
eid_df["_pos"]     = range(len(eid_df))

# Sort: eid_std asc, _nonnull desc, _pos asc → first row per group = best
eid_sorted = eid_df.sort_values(
    ["_eid_std", "_nonnull", "_pos"],
    ascending=[True, False, True],
)
is_eid_keeper = ~eid_sorted.duplicated(subset="_eid_std", keep="first")
eid_kept      = eid_sorted[is_eid_keeper].copy()
eid_dropped   = eid_sorted[~is_eid_keeper].copy()

eid_dup_groups = int(eid_df[eid_df["_eid_std"].duplicated(keep=False)]["_eid_std"].nunique())
n_p1_removed   = len(eid_dropped)
log(f"Duplicate EID groups    : {eid_dup_groups:,}")
log(f"Rows removed (EID)      : {n_p1_removed:,}  ({100*n_p1_removed/total_raw:.2f}% of raw)")
log(f"Rows retained after P1  : {len(eid_kept):,}")
log(f"Pass 1 time             : {time.time()-t0_p1:.1f}s")

# Lookup: EID → kept record's EID and DOI (for log)
eid_to_kept_doi = eid_kept.set_index("_eid_std")["_doi_std"].to_dict()

# Build dedup log for Pass 1
ts = datetime.now().isoformat()
p1_log = eid_dropped[[title_col, "_eid_std", "_doi_std", "sdg_tags"]].copy()
p1_log.columns = ["_t", "_eid", "_doi", "_sdg"]
p1_log["pass_number"]        = 1
p1_log["removed_title"]      = p1_log["_t"].fillna("").str[:80]
p1_log["removed_eid"]        = p1_log["_eid"]
p1_log["removed_doi"]        = p1_log["_doi"]
p1_log["kept_eid"]           = p1_log["_eid"]   # same EID = exact match
p1_log["kept_doi"]           = p1_log["_eid"].map(eid_to_kept_doi)
p1_log["reason"]             = "eid_exact_match"
p1_log["sdg_numbers_merged"] = p1_log["_sdg"]
p1_log["timestamp"]          = ts
dedup_log_p1 = p1_log[["pass_number", "removed_title", "removed_eid", "removed_doi",
                         "kept_eid", "kept_doi", "reason", "sdg_numbers_merged", "timestamp"]]

# ─────────────────────────────────────────────────────────────────────────────
# Pool entering Pass 2: EID keepers + records that had no EID
# ─────────────────────────────────────────────────────────────────────────────
no_eid_df = df[~valid_eid].copy()
pool_p2 = pd.concat([eid_kept, no_eid_df], ignore_index=True, sort=False)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – PASS 2: DOI EXACT DEDUPLICATION  (vectorised, on pool_p2)
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "-" * 62)
log("PASS 2 – DOI exact deduplication")
log("-" * 62)
t0_p2 = time.time()

valid_doi_p2 = pool_p2["_doi_std"].notna()
n_valid_p2   = int(valid_doi_p2.sum())
n_missing_p2 = int((~valid_doi_p2).sum())
log(f"DOI valid in pool   : {n_valid_p2:,}")
log(f"DOI missing in pool : {n_missing_p2:,}")

doi_df = pool_p2[valid_doi_p2].copy()

# Merge sdg_tags per DOI group, preserving any already-merged tags from P1
sdg_by_doi = (
    doi_df.groupby("_doi_std", sort=False)["sdg_tags"]
    .apply(lambda tags: merge_sdg_tags(*tags.tolist()))
)
doi_df["sdg_tags"] = doi_df["_doi_std"].map(sdg_by_doi)

# Non-null count for tie-breaking
doi_df["_nonnull"] = doi_df.notna().sum(axis=1)
doi_df["_pos"]     = range(len(doi_df))

# Sort: doi_std asc, _nonnull desc, _pos asc → first row per group = best
doi_sorted = doi_df.sort_values(
    ["_doi_std", "_nonnull", "_pos"],
    ascending=[True, False, True],
)
is_doi_keeper = ~doi_sorted.duplicated(subset="_doi_std", keep="first")
doi_kept      = doi_sorted[is_doi_keeper].copy()
doi_dropped   = doi_sorted[~is_doi_keeper].copy()

doi_dup_groups = int(doi_df[doi_df["_doi_std"].duplicated(keep=False)]["_doi_std"].nunique())
n_p2_removed   = len(doi_dropped)
log(f"Duplicate DOI groups    : {doi_dup_groups:,}")
log(f"Rows removed (DOI)      : {n_p2_removed:,}  ({100*n_p2_removed/total_raw:.2f}% of raw)")
log(f"Rows retained after P2  : {len(doi_kept):,}")
log(f"Pass 2 time             : {time.time()-t0_p2:.1f}s")

# Lookup: DOI → kept record's EID and DOI (for log)
doi_to_kept_eid = doi_kept.set_index("_doi_std")["_eid_std"].to_dict()

# Build dedup log for Pass 2
ts = datetime.now().isoformat()
p2_log = doi_dropped[[title_col, "_eid_std", "_doi_std", "sdg_tags"]].copy()
p2_log.columns = ["_t", "_eid", "_doi", "_sdg"]
p2_log["pass_number"]        = 2
p2_log["removed_title"]      = p2_log["_t"].fillna("").str[:80]
p2_log["removed_eid"]        = p2_log["_eid"]
p2_log["removed_doi"]        = p2_log["_doi"]
p2_log["kept_eid"]           = p2_log["_doi"].map(doi_to_kept_eid)
p2_log["kept_doi"]           = p2_log["_doi"]   # same DOI = exact match
p2_log["reason"]             = "doi_exact_match"
p2_log["sdg_numbers_merged"] = p2_log["_sdg"]
p2_log["timestamp"]          = ts
dedup_log_p2 = p2_log[["pass_number", "removed_title", "removed_eid", "removed_doi",
                         "kept_eid", "kept_doi", "reason", "sdg_numbers_merged", "timestamp"]]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 – PASS 3: FUZZY TITLE DEDUP ON NO-DOI RECORDS
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "-" * 62)
log("PASS 3 – Fuzzy title dedup (no-DOI records)")
log("-" * 62)
t0_p3 = time.time()

no_doi_df = pool_p2[~valid_doi_p2].copy().reset_index(drop=True)
no_doi_df["_title_clean"] = no_doi_df[title_col].apply(clean_title)
no_doi_df["_year"] = (
    pd.to_numeric(no_doi_df[year_col], errors="coerce")
    if year_col else pd.Series(dtype=float, index=no_doi_df.index)
)

has_title   = no_doi_df["_title_clean"].str.len() > 0
matchable   = no_doi_df[has_title].reset_index(drop=True)
unmatchable = no_doi_df[~has_title]

n_match = len(matchable)
log(f"No-DOI total          : {len(no_doi_df):,}")
log(f"  with title (matchable): {n_match:,}")
log(f"  no title (pass-through): {len(unmatchable):,}")

uf = UnionFind(n_match)

# Group by year
year_to_idx = defaultdict(list)
for i, yr in enumerate(matchable["_year"].values):
    if pd.notna(yr):
        year_to_idx[int(yr)].append(i)

years_sorted  = sorted(year_to_idx.keys())
total_pairs   = 0
matched_pairs = 0

# ---- 5a. Same-year comparisons ----
log(f"\nSame-year comparisons (threshold={FUZZY_THRESHOLD}):")
for yr in years_sorted:
    idxs = year_to_idx[yr]
    if len(idxs) <= 1:
        continue
    titles = matchable.iloc[idxs]["_title_clean"].tolist()
    scores = rf_cdist(titles, titles,
                      scorer=fuzz.token_set_ratio,
                      score_cutoff=FUZZY_SCORE_CUT)
    np.fill_diagonal(scores, 0)
    ri, ci = np.where(scores > 0)
    pairs_found = int((ri < ci).sum())
    for r, c in zip(ri, ci):
        if r < c:
            uf.union(idxs[r], idxs[c])
            matched_pairs += 1
    total_pairs += len(idxs) * (len(idxs) - 1) // 2
    if pairs_found:
        log(f"  {yr}: {len(idxs):,} records → {pairs_found:,} match pairs")

# ---- 5b. Cross-year comparisons (Y vs Y+1 only) ----
log(f"\nCross-year comparisons (window={YEAR_WINDOW}):")
for i in range(len(years_sorted) - 1):
    yr_a, yr_b = years_sorted[i], years_sorted[i + 1]
    if yr_b - yr_a > YEAR_WINDOW:
        continue
    idxs_a = year_to_idx[yr_a]
    idxs_b = year_to_idx[yr_b]
    titles_a = matchable.iloc[idxs_a]["_title_clean"].tolist()
    titles_b = matchable.iloc[idxs_b]["_title_clean"].tolist()
    scores = rf_cdist(titles_a, titles_b,
                      scorer=fuzz.token_set_ratio,
                      score_cutoff=FUZZY_SCORE_CUT)
    ri, ci = np.where(scores > 0)
    for r, c in zip(ri, ci):
        uf.union(idxs_a[r], idxs_b[c])
        matched_pairs += 1
    total_pairs += len(idxs_a) * len(idxs_b)
    if len(ri):
        log(f"  {yr_a}-{yr_b}: {len(ri):,} cross-year match pairs")

# ---- 5c. Determine keepers via clusters ----
nonnull_counts = matchable.notna().sum(axis=1).values
sdg_tags_arr   = matchable["sdg_tags"].values
eid_arr        = matchable["_eid_std"].values if "_eid_std" in matchable.columns else None

fuzzy_keeper_idxs  = []
fuzzy_dropped_idxs = []
fuzzy_kept_map     = {}   # dropped_local_idx -> kept_local_idx
fuzzy_merged_tags  = {}   # kept_local_idx -> merged sdg_tags string

for members in uf.clusters().values():
    if len(members) == 1:
        fuzzy_keeper_idxs.append(members[0])
        continue
    best = max(members, key=lambda p: (nonnull_counts[p], -p))
    fuzzy_keeper_idxs.append(best)
    merged = merge_sdg_tags(*[sdg_tags_arr[m] for m in members])
    fuzzy_merged_tags[best] = merged
    for m in members:
        if m != best:
            fuzzy_dropped_idxs.append(m)
            fuzzy_kept_map[m] = best

# Apply merged sdg_tags to keepers
for ki, mtags in fuzzy_merged_tags.items():
    matchable.at[ki, "sdg_tags"] = mtags

fuzzy_kept    = matchable.iloc[sorted(fuzzy_keeper_idxs)].copy()
fuzzy_dropped = matchable.iloc[sorted(fuzzy_dropped_idxs)].copy()

n_p3_removed = len(fuzzy_dropped_idxs)
elapsed_p3   = time.time() - t0_p3
log(f"\nFuzzy pairs matched     : {matched_pairs:,}  (of {total_pairs:,} checked)")
log(f"Rows removed (fuzzy)    : {n_p3_removed:,}  ({100*n_p3_removed/total_raw:.2f}% of raw)")
log(f"Pass 3 time             : {elapsed_p3:.1f}s")

# Build dedup log for Pass 3
ts = datetime.now().isoformat()
p3_log_rows = []
for di in fuzzy_dropped_idxs:
    ki         = fuzzy_kept_map[di]
    merged     = fuzzy_merged_tags.get(ki, sdg_tags_arr[ki])
    dropped_row = matchable.iloc[di]
    kept_row    = matchable.iloc[ki]
    p3_log_rows.append({
        "pass_number":        3,
        "removed_title":      str(dropped_row[title_col])[:80] if pd.notna(dropped_row[title_col]) else "",
        "removed_eid":        dropped_row.get("_eid_std", pd.NA),
        "removed_doi":        pd.NA,
        "kept_eid":           kept_row.get("_eid_std", pd.NA),
        "kept_doi":           pd.NA,
        "reason":             "fuzzy_title_match",
        "sdg_numbers_merged": merged,
        "timestamp":          ts,
    })

LOG_COLS = ["pass_number", "removed_title", "removed_eid", "removed_doi",
            "kept_eid", "kept_doi", "reason", "sdg_numbers_merged", "timestamp"]

dedup_log_p3 = (
    pd.DataFrame(p3_log_rows, columns=LOG_COLS)
    if p3_log_rows else
    pd.DataFrame(columns=LOG_COLS)
)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 – FINALISE
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "-" * 62)
log("FINALISE")
log("-" * 62)

final_df = pd.concat(
    [doi_kept, fuzzy_kept, unmatchable],
    ignore_index=True, sort=False,
)

# Compute sdg_tag_count on lightweight frame (used for reporting)
final_df["sdg_tag_count"] = (
    final_df["sdg_tags"].fillna("").str.split(",").apply(len)
)

# Extract dedup decisions before dropping helper columns
kept_row_ids       = set(final_df["_row_id"].values)
sdg_tags_by_row_id = dict(zip(final_df["_row_id"].values,
                               final_df["sdg_tags"].values))

# Drop all helper columns (_xxx) from lightweight frame
helper_cols = [c for c in final_df.columns if c.startswith("_")]
final_df.drop(columns=helper_cols, inplace=True)

n_unique    = len(final_df)
n_removed   = total_raw - n_unique
pct_removed = 100 * n_removed / total_raw
log(f"Unique records after dedup : {n_unique:,}")
log(f"Total removed              : {n_removed:,}  ({pct_removed:.2f}% of raw)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6b – PHASE 2: RE-READ SOURCE FILES WITH FULL COLUMNS
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "-" * 62)
log("PHASE 2 – re-reading with full columns (one file at a time)")
log("-" * 62)
t0_p2io     = time.time()
_row_start2 = 0
_out_frames = []
for f in csv_files:
    _sdg_num = int(FILE_RE.match(f.name).group(1))
    for _enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            _df_f = pd.read_csv(f, encoding=_enc, dtype=object, low_memory=False)
            break
        except Exception:
            continue
    else:
        log(f"ERROR (Phase 2): cannot decode {f.name}")
        sys.exit(1)
    _n = len(_df_f)
    _df_f["sdg_number"]  = str(_sdg_num)
    _df_f["source_file"] = f.name
    _df_f["_row_id"]     = list(range(_row_start2, _row_start2 + _n))
    _row_start2 += _n
    _df_kept = _df_f[_df_f["_row_id"].isin(kept_row_ids)].copy()
    del _df_f
    _df_kept["sdg_tags"]      = _df_kept["_row_id"].map(sdg_tags_by_row_id)
    _df_kept["sdg_tag_count"] = (
        _df_kept["sdg_tags"].fillna("").str.split(",").apply(len)
    )
    _out_frames.append(_df_kept)

final_output = pd.concat(_out_frames, ignore_index=True, sort=False)
del _out_frames
_p2_helpers = [c for c in final_output.columns if c.startswith("_")]
final_output.drop(columns=_p2_helpers, inplace=True)
log(f"Phase 2 time : {time.time()-t0_p2io:.1f}s")

# Write deduplicated CSV
log(f"\nWriting {DEDUP_OUT} ...")
final_output.to_csv(DEDUP_OUT, index=False, encoding="utf-8-sig")
log(f"Written: {n_unique:,} rows")

# SHA-256 and append to checksums
cksum = sha256_file(DEDUP_OUT)
with open(CHECKSUMS_TXT, "a", encoding="utf-8") as fh:
    fh.write(f"{cksum}  {DEDUP_OUT.name}\n")
log(f"SHA-256 appended to {CHECKSUMS_TXT.name}")

# Write combined dedup log (all three passes)
dedup_log = pd.concat([dedup_log_p1, dedup_log_p2, dedup_log_p3], ignore_index=True)
dedup_log.to_csv(DEDUP_LOG, index=False, encoding="utf-8-sig")
log(f"Dedup log written : {len(dedup_log):,} rows → {DEDUP_LOG.name}")

# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL REPORT
# ─────────────────────────────────────────────────────────────────────────────
SEP  = "-" * 62
SEP2 = "=" * 62
print(f"\n{SEP2}")
print(" STAGE 3A – DEDUPLICATION REPORT  (three-pass: EID / DOI / fuzzy)")
print(SEP2)

# A. Concatenation
print(f"\n{SEP}\nA. CONCATENATION\n{SEP}")
print(f"   Total rows loaded   : {total_raw:,}  (manifest {manifest_total:,})")
files_sorted = sorted(per_file_counts.items())
print("   First 5 files:")
for fn, ct in files_sorted[:5]:
    print(f"     {ct:>7,}   {fn}")
print("   Last 5 files:")
for fn, ct in files_sorted[-5:]:
    print(f"     {ct:>7,}   {fn}")

# B. Key identifier stats
print(f"\n{SEP}\nB. KEY IDENTIFIER STATISTICS\n{SEP}")
print(f"   EID valid   : {n_valid_eid:,}  ({100*n_valid_eid/total_raw:.1f}%)")
print(f"   EID missing : {n_missing_eid:,} ({100*n_missing_eid/total_raw:.1f}%)")
print(f"   DOI valid   : {n_valid_doi:,}  ({100*n_valid_doi/total_raw:.1f}%)")
print(f"   DOI missing : {n_missing_doi:,} ({100*n_missing_doi/total_raw:.1f}%)")

# C. Pass 1 – EID
print(f"\n{SEP}\nC. PASS 1 – EID EXACT MATCH\n{SEP}")
print(f"   Duplicate EID groups : {eid_dup_groups:,}")
print(f"   Rows removed         : {n_p1_removed:,}  ({100*n_p1_removed/total_raw:.2f}% of raw)")
print(f"   Rows retained        : {len(eid_kept):,}")

# D. Pass 2 – DOI
print(f"\n{SEP}\nD. PASS 2 – DOI EXACT MATCH\n{SEP}")
print(f"   Pool entering P2     : {len(pool_p2):,}")
print(f"   Duplicate DOI groups : {doi_dup_groups:,}")
print(f"   Rows removed         : {n_p2_removed:,}  ({100*n_p2_removed/total_raw:.2f}% of raw)")
print(f"   Rows retained        : {len(doi_kept):,}")

# E. Pass 3 – Fuzzy
print(f"\n{SEP}\nE. PASS 3 – FUZZY TITLE MATCH\n{SEP}")
print(f"   No-DOI eligible      : {n_match:,}")
print(f"   Fuzzy pairs found    : {matched_pairs:,}")
print(f"   Rows removed         : {n_p3_removed:,}  ({100*n_p3_removed/total_raw:.2f}% of raw)")
print(f"   Fuzzy time           : {elapsed_p3:.1f}s")

# F. Final
print(f"\n{SEP}\nF. FINAL DEDUP OUTPUT\n{SEP}")
print(f"   Unique records       : {n_unique:,}")
print(f"   Total reduction      : {n_removed:,}  ({pct_removed:.2f}% of {total_raw:,} raw)")
print(f"                          P1 (EID)   : {n_p1_removed:,}")
print(f"                          P2 (DOI)   : {n_p2_removed:,}")
print(f"                          P3 (fuzzy) : {n_p3_removed:,}")

# G. sdg_tags distribution
print(f"\n{SEP}\nG. SDG_TAGS DISTRIBUTION\n{SEP}")
tag_counts = final_df["sdg_tag_count"]
for k in [1, 2, 3]:
    ct = int((tag_counts == k).sum())
    print(f"   Tagged to {k} SDG{'s' if k>1 else ' '} : {ct:>7,}  ({100*ct/n_unique:.1f}%)")
ct4 = int((tag_counts >= 4).sum())
print(f"   Tagged to 4+ SDGs : {ct4:>7,}  ({100*ct4/n_unique:.1f}%)")
print(f"   Max tag count     : {int(tag_counts.max())}")

print(f"\n   Top 10 most common sdg_tag combinations:")
combo_counts = final_df["sdg_tags"].value_counts().head(10)
for combo, ct in combo_counts.items():
    print(f"     {combo:<25}  {ct:>7,}")

# H. Dedup log sample
print(f"\n{SEP}\nH. DEDUP LOG SAMPLE\n{SEP}")

def trunc(s, n=55):
    s = str(s) if pd.notna(s) else "(missing)"
    return s[:n] + "..." if len(s) > n else s

# 5 random EID-duplicate removals
if len(eid_dropped) > 0:
    print("   EID duplicate removals (5 random):")
    sample_eid = eid_dropped.sample(min(5, len(eid_dropped)), random_state=42)
    for _, row in sample_eid.iterrows():
        kept_rows = eid_kept[eid_kept["_eid_std"] == row["_eid_std"]] if "_eid_std" in eid_kept.columns else pd.DataFrame()
        kept_title = trunc(kept_rows.iloc[0][title_col]) if len(kept_rows) > 0 else "(unknown)"
        print(f"     REMOVED : {trunc(row[title_col])}")
        print(f"     KEPT    : {kept_title}")
        print(f"     REASON  : eid_exact_match  ({row['_eid_std']})")
        print()
else:
    print("   No EID duplicates found.")

# 5 random DOI-duplicate removals (Pass 2)
if len(doi_dropped) > 0:
    print("   DOI duplicate removals (5 random):")
    sample_doi = doi_dropped.sample(min(5, len(doi_dropped)), random_state=42)
    for _, row in sample_doi.iterrows():
        kept_rows = doi_kept[doi_kept["_doi_std"] == row["_doi_std"]] if "_doi_std" in doi_kept.columns else pd.DataFrame()
        kept_title = trunc(kept_rows.iloc[0][title_col]) if len(kept_rows) > 0 else "(unknown)"
        print(f"     REMOVED : {trunc(row[title_col])}")
        print(f"     KEPT    : {kept_title}")
        print(f"     REASON  : doi_exact_match  ({row['_doi_std']})")
        print()
else:
    print("   No DOI duplicates found after Pass 1.")

# 5 random fuzzy-match removals (Pass 3)
if fuzzy_dropped_idxs:
    print("   Fuzzy-match removals (5 random):")
    random.seed(42)
    sample_idxs = random.sample(fuzzy_dropped_idxs, min(5, len(fuzzy_dropped_idxs)))
    for di in sample_idxs:
        ki = fuzzy_kept_map[di]
        drec = matchable.iloc[di]
        krec = matchable.iloc[ki]
        print(f"     REMOVED : {trunc(drec[title_col])}")
        print(f"     KEPT    : {trunc(krec[title_col])}")
        print(f"     REASON  : fuzzy_title_match")
        print()
else:
    print("   No fuzzy duplicates found.")

print(f"\n{SEP}\nFILES WRITTEN\n{SEP}")
print(f"   {DEDUP_OUT.relative_to(ARTICLE)}")
print(f"   {DEDUP_LOG.relative_to(ARTICLE)}")
print(f"   SHA-256 appended to {CHECKSUMS_TXT.relative_to(ARTICLE)}")
print(f"\n   Total runtime: {time.time()-t0_total:.1f}s")
print(f"\n{SEP2}")
print(" STAGE 3A COMPLETE")
print(f"{SEP2}\n")
