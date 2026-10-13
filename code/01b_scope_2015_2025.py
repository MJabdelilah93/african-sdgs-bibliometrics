"""01b_scope_2015_2025.py
Stage 01b – post-retrieval eligibility screening (study window + document type).

Exported metadata are authoritative. A record is kept only when BOTH hold:
    1. corpus.year_min <= exported Year <= corpus.year_max   (config.yaml; 2015–2025)
    2. exported Document Type is one of the labels for corpus.doc_types
       (config.yaml; ar -> "Article", re -> "Review")
Every other record is written to an exclusion log with exactly one reason.
Precedence (first failing rule wins): year rules, then document-type rules.
Only the row population changes: all columns, column order and cell text of
retained rows are passed through unchanged. Article-in-press records are kept
whenever their exported Year and Document Type are eligible.

Inputs  : data/interim/consolidated.csv              (Stage 01a)
Outputs : data/interim/scoped_2015_2025.csv          (written via .tmp, renamed on success)
          provenance/v2/stage1b_scope_exclusions.csv
          provenance/v2/stage1b_scope_summary.json
          provenance/v2/stage1b_scope_manifest.csv
          provenance/v2/logs/01b_scope_2015_2025.log

Run from the repository root:
    python code/01b_scope_2015_2025.py
"""
import argparse
import csv
import json
import logging
import os
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parent
sys.path.insert(0, str(HERE))

from utils.config import cfg
from utils.checksums import sha256_file

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_VERSION = "1.1.0"
CHUNK_SIZE     = 50_000
ENCODING_IN    = "utf-8-sig"   # source carries a UTF-8 BOM
LINE_END       = "\r\n"        # source records are CRLF-terminated

YEAR_COL  = "Year"
EID_COL   = "EID"
DT_COL    = "Document Type"
STAGE_COL = "Publication Stage"
# Scopus DOCTYPE search codes (as used in the queries / config) -> exported Document Type labels
DOCTYPE_LABELS = {"ar": "Article", "re": "Review"}
AIP_VALUE = "Article in press"
LOG_COLS  = ["EID", "Year", "Document Type", "Publication Stage",
             "source_file", "sdg_number", "sdg_tags", "DOI", "Title"]

REASON_ABOVE   = "year_above_study_window"
REASON_BELOW   = "year_below_study_window"
REASON_INVALID = "missing_or_invalid_year"
REASON_DOCTYPE = "document_type_not_article_or_review"
REASON_DT_MISSING = "missing_or_invalid_document_type"

V2_PROV = ARTICLE / "provenance" / "v2"
DEFAULTS = {
    "input":      ARTICLE / "data" / "interim" / "consolidated.csv",
    "output":     ARTICLE / "data" / "interim" / "scoped_2015_2025.csv",
    "exclusions": V2_PROV / "stage1b_scope_exclusions.csv",
    "summary":    V2_PROV / "stage1b_scope_summary.json",
    "manifest":   V2_PROV / "stage1b_scope_manifest.csv",
    "log":        V2_PROV / "logs" / "01b_scope_2015_2025.log",
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    for key, default in DEFAULTS.items():
        ap.add_argument(f"--{key}", type=Path, default=default)
    ap.add_argument("--year-min", type=int, default=int(cfg["corpus"]["year_min"]))
    ap.add_argument("--year-max", type=int, default=int(cfg["corpus"]["year_max"]))
    ap.add_argument("--doc-types", nargs="+", default=list(cfg["corpus"]["doc_types"]),
                    help="eligible Scopus DOCTYPE codes (default: config corpus.doc_types)")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace an existing scoped output (default: refuse)")
    ap.add_argument("--allow-global-python", action="store_true",
                    help="run outside a virtual environment (default: refuse; use .venv)")
    return ap.parse_args()


def pinned_version(package: str) -> str | None:
    req = ARTICLE / "requirements.txt"
    if not req.exists():
        return None
    for line in req.read_text(encoding="utf-8").splitlines():
        name, _, ver = line.split("#")[0].strip().partition("==")
        if name.strip().lower() == package:
            return ver.strip()
    return None


def get_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("01b_scope")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    for handler in (logging.FileHandler(path, mode="w", encoding="utf-8"),
                    logging.StreamHandler(sys.stdout)):
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ARTICLE).as_posix()
    except ValueError:
        return str(path)


def git_state() -> dict:
    def run(*args):
        return subprocess.run(["git", *args], cwd=ARTICLE, capture_output=True,
                              text=True, check=True).stdout.strip()
    try:
        return {"commit": run("rev-parse", "HEAD"),
                "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
                "tracked_changes": bool(run("status", "--porcelain", "--untracked-files=no"))}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "branch": None, "tracked_changes": None}


def classify(years: pd.Series, year_min: int, year_max: int) -> pd.Series:
    """Return '' for in-window rows, otherwise the year exclusion reason."""
    stripped = years.str.strip()
    numeric = pd.to_numeric(stripped.where(stripped.str.fullmatch(r"\d{4}")), errors="coerce")
    reason = pd.Series("", index=years.index, dtype=object)
    reason[numeric.isna()] = REASON_INVALID
    reason[numeric > year_max] = REASON_ABOVE
    reason[numeric < year_min] = REASON_BELOW
    return reason


def classify_doctype(doctypes: pd.Series, allowed: set[str]) -> pd.Series:
    """Return '' for eligible exported Document Types, otherwise the document-type reason.
    Exact match on the exported label (no case folding or inference)."""
    reason = pd.Series("", index=doctypes.index, dtype=object)
    reason[~doctypes.isin(allowed)] = REASON_DOCTYPE
    reason[doctypes.str.strip() == ""] = REASON_DT_MISSING
    return reason


def eligibility(chunk: pd.DataFrame, year_min: int, year_max: int, allowed: set[str]) -> pd.Series:
    """One reason per record; precedence: year rules first, then document-type rules."""
    reason = classify(chunk[YEAR_COL], year_min, year_max)
    dt_reason = classify_doctype(chunk[DT_COL], allowed)
    return reason.where(reason != "", dt_reason)


def main() -> int:
    a = parse_args()
    log = get_logger(a.log)
    t0 = datetime.now()
    log.info("=" * 62)
    log.info(f"STAGE 1B – ELIGIBILITY SCOPE: STUDY WINDOW + DOCUMENT TYPE  (v{SCRIPT_VERSION})")
    log.info("=" * 62)
    log.info(f"Input      : {rel(a.input)}")
    log.info(f"Output     : {rel(a.output)}")
    log.info(f"Window     : {a.year_min} <= {YEAR_COL} <= {a.year_max}")
    unknown = [c for c in a.doc_types if c not in DOCTYPE_LABELS]
    if unknown:
        log.error(f"No exported-label mapping for DOCTYPE code(s): {unknown}")
        return 2
    allowed = {DOCTYPE_LABELS[c] for c in a.doc_types}
    log.info(f"Doc types  : codes {a.doc_types} -> exported '{DT_COL}' in {sorted(allowed)}")
    log.info(f"Precedence : year rules, then document-type rules (one reason per excluded record)")

    in_venv = sys.prefix != sys.base_prefix
    pandas_pin = pinned_version("pandas")
    log.info(f"Python     : {platform.python_version()}  (virtual environment: {in_venv})")
    log.info(f"pandas     : {pd.__version__}  (requirements.txt pin: {pandas_pin})")
    if not in_venv and not a.allow_global_python:
        log.error("Not running inside a virtual environment – use .venv\\Scripts\\python.exe "
                  "(or pass --allow-global-python deliberately).")
        return 2
    if pandas_pin and pd.__version__ != pandas_pin:
        log.warning(f"pandas {pd.__version__} differs from the pinned {pandas_pin}.")

    if a.input.resolve() == a.output.resolve():
        log.error("Output path equals input path – refusing to run.")
        return 2
    if not a.input.exists():
        log.error(f"Input not found: {a.input}")
        return 2
    if a.output.exists() and not a.overwrite:
        log.error(f"Output already exists: {rel(a.output)} (use --overwrite to replace).")
        return 2

    git = git_state()
    log.info(f"Git        : {git['branch']} @ {git['commit']} (tracked changes: {git['tracked_changes']})")
    log.info("Hashing input ...")
    input_sha_before = sha256_file(a.input)
    log.info(f"Input SHA-256 : {input_sha_before}")

    header = pd.read_csv(a.input, nrows=0, encoding=ENCODING_IN).columns.tolist()
    missing = [c for c in (YEAR_COL, EID_COL, DT_COL) if c not in header]
    if missing:
        log.error(f"Required columns missing from input: {missing}")
        return 2
    log_cols = [c for c in LOG_COLS if c in header]
    log.info(f"Columns    : {len(header)}")

    tmp_out = a.output.with_name(a.output.name + ".tmp")
    tmp_exc = a.exclusions.with_name(a.exclusions.name + ".tmp")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.exclusions.parent.mkdir(parents=True, exist_ok=True)

    rows_in = rows_out = rows_exc = n_chunks = 0
    in_eids: set[str] = set()
    out_eids: set[str] = set()
    exc_eids: set[str] = set()
    blank_eids = 0
    dup_out = 0
    years_kept: Counter = Counter()
    exc_by_year: Counter = Counter()
    exc_by_reason: Counter = Counter()
    exc_by_doctype: Counter = Counter()
    doctypes_kept: Counter = Counter()
    aip_kept = 0

    with open(tmp_out, "w", encoding="utf-8-sig", newline="") as fo, \
         open(tmp_exc, "w", encoding="utf-8", newline="") as fe:
        for i, chunk in enumerate(pd.read_csv(a.input, dtype=str, keep_default_na=False,
                                              chunksize=CHUNK_SIZE, encoding=ENCODING_IN,
                                              low_memory=False)):
            n_chunks += 1
            if chunk.columns.tolist() != header:
                log.error(f"Chunk {i}: column mismatch with header")
                return 3
            rows_in += len(chunk)
            eid = chunk[EID_COL]
            blank_eids += int((eid.str.strip() == "").sum())
            in_eids.update(eid)

            reason = eligibility(chunk, a.year_min, a.year_max, allowed)
            keep = reason == ""
            kept, excluded = chunk[keep], chunk[~keep]

            dup_out += sum(1 for e in kept[EID_COL] if e in out_eids)
            out_eids.update(kept[EID_COL])
            exc_eids.update(excluded[EID_COL])
            years_kept.update(kept[YEAR_COL].str.strip())
            doctypes_kept.update(kept[DT_COL])
            if STAGE_COL in kept:
                aip_kept += int((kept[STAGE_COL] == AIP_VALUE).sum())

            kept.to_csv(fo, index=False, header=(i == 0), lineterminator=LINE_END)
            rows_out += len(kept)

            if len(excluded):
                exc = excluded[log_cols].copy()
                exc["exclusion_reason"] = reason[~keep].values
                exc.to_csv(fe, index=False, header=(rows_exc == 0), lineterminator=LINE_END)
                rows_exc += len(exc)
                exc_by_year.update(excluded[YEAR_COL].str.strip().replace("", "<blank>"))
                exc_by_reason.update(reason[~keep])
                exc_by_doctype.update(excluded[DT_COL].replace("", "<blank>"))
                for r, y, d, e in zip(reason[~keep], excluded[YEAR_COL], excluded[DT_COL], excluded[EID_COL]):
                    log.info(f"  excluded  {e}  Year={y!r}  DocType={d!r}  {r}")
            log.info(f"Chunk {n_chunks:>3}: read {rows_in:>9,}  kept {rows_out:>9,}  excluded {rows_exc:>4,}")
        if rows_exc == 0:
            pd.DataFrame(columns=log_cols + ["exclusion_reason"]).to_csv(fe, index=False,
                                                                       lineterminator=LINE_END)

    # ── Internal validation (before the temporary output is promoted) ──────────
    checks = {
        "rows_in == rows_out + rows_excluded":   rows_in == rows_out + rows_exc,
        "no blank EIDs in input":                blank_eids == 0,
        "input EIDs unique":                     len(in_eids) == rows_in,
        "output EIDs unique":                    dup_out == 0 and len(out_eids) == rows_out,
        "output and excluded EIDs disjoint":     not (out_eids & exc_eids),
        "output ∪ excluded == input EIDs":       (out_eids | exc_eids) == in_eids,
        "retained years inside window":          all(a.year_min <= int(y) <= a.year_max for y in years_kept),
        "retained document types eligible":      set(doctypes_kept) <= allowed,
        "input unchanged (SHA-256)":             sha256_file(a.input) == input_sha_before,
    }
    for name, ok in checks.items():
        log.info(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not all(checks.values()):
        log.error("Validation FAILED – temporary outputs kept for inspection, final paths untouched.")
        return 4

    os.replace(tmp_out, a.output)
    os.replace(tmp_exc, a.exclusions)
    log.info(f"Promoted   : {rel(a.output)}")
    log.info(f"Exclusions : {rel(a.exclusions)} ({rows_exc} rows)")

    # ── Manifest ───────────────────────────────────────────────────────────────
    log.info("Hashing outputs ...")
    manifest = [
        ("input",      a.input,      rows_in,  len(in_eids),  input_sha_before),
        ("output",     a.output,     rows_out, len(out_eids), sha256_file(a.output)),
        ("exclusions", a.exclusions, rows_exc, len(exc_eids), sha256_file(a.exclusions)),
    ]
    a.manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(a.manifest, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["role", "relative_path", "size_bytes", "row_count", "unique_eids", "sha256"])
        for role, path, nrow, neid, digest in manifest:
            w.writerow([role, rel(path), path.stat().st_size, nrow, neid, digest])
            log.info(f"  {role:<10} {rel(path)}  {path.stat().st_size:,} bytes  {digest}")

    # ── Summary ────────────────────────────────────────────────────────────────
    kept_years = sorted(int(y) for y in years_kept)
    summary = {
        "stage": "01b_scope_2015_2025",
        "script_version": SCRIPT_VERSION,
        "rule": f"{a.year_min} <= exported '{YEAR_COL}' <= {a.year_max} AND exported '{DT_COL}' in "
                f"{sorted(allowed)} (DOCTYPE codes {a.doc_types}); Article in press retained when both hold",
        "reason_precedence": [REASON_INVALID, REASON_ABOVE, REASON_BELOW, REASON_DT_MISSING, REASON_DOCTYPE],
        "eligible_document_types": sorted(allowed),
        "retained_counts_by_document_type": dict(sorted(doctypes_kept.items())),
        "excluded_counts_by_document_type": dict(sorted(exc_by_doctype.items())),
        "input_path": rel(a.input),
        "output_path": rel(a.output),
        "exclusions_path": rel(a.exclusions),
        "input_rows": rows_in,
        "output_rows": rows_out,
        "excluded_rows": rows_exc,
        "retained_year_min": kept_years[0] if kept_years else None,
        "retained_year_max": kept_years[-1] if kept_years else None,
        "retained_counts_by_year": dict(sorted(years_kept.items())),
        "excluded_counts_by_year": dict(sorted(exc_by_year.items())),
        "excluded_counts_by_reason": dict(sorted(exc_by_reason.items())),
        "retained_article_in_press": aip_kept if STAGE_COL in header else None,
        "input_unique_eids": len(in_eids),
        "output_unique_eids": len(out_eids),
        "output_duplicate_eids": dup_out,
        "missing_eids": blank_eids,
        "chunks": n_chunks,
        "chunk_size": CHUNK_SIZE,
        "input_sha256": input_sha_before,
        "output_sha256": manifest[1][4],
        "validation": {k: bool(v) for k, v in checks.items()},
        "run_started": t0.isoformat(timespec="seconds"),
        "run_finished": datetime.now().isoformat(timespec="seconds"),
        "git_commit_before_run": git["commit"],
        "git_branch": git["branch"],
        "git_tracked_changes_at_run": git["tracked_changes"],
        "python_version": platform.python_version(),
        "python_in_virtualenv": in_venv,
        "pandas_version": pd.__version__,
        "pandas_matches_requirements_pin": pd.__version__ == pandas_pin,
    }
    a.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info(f"Summary    : {rel(a.summary)}")
    log.info(f"RESULT     : read {rows_in:,} | retained {rows_out:,} | excluded {rows_exc:,} "
             f"| years {summary['retained_year_min']}–{summary['retained_year_max']}")
    log.info("VALIDATION : PASS")
    log.info(f"Finished in {(datetime.now() - t0).total_seconds():.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
