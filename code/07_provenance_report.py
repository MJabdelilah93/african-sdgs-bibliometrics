"""
Stage 6 — Provenance report generator.

Reads artefacts from stages 1–5 and writes two output files:
  provenance/provenance_report.md          — full human-readable report
  provenance/provenance_report_summary.txt — one-page plain-text version

Usage:
    python code/07_provenance_report.py
"""

import csv
import datetime
import pathlib
import re
import subprocess
import sys

import yaml


ROOT = pathlib.Path(__file__).resolve().parent.parent
NOW = datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    """Load config.yaml from project root."""
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _prov(cfg):
    """Return the provenance directory as a Path."""
    return ROOT / cfg["paths"]["provenance"]


# ---------------------------------------------------------------------------
# Stage 1 — Query specification
# ---------------------------------------------------------------------------

def read_stage1(cfg):
    """Read the query-cleaning log.

    Returns a list of dicts sorted by SDG number, each with keys:
        sdg_number, sdg_int, original_length, cleaned_length,
        total_transformations, query_file
    """
    log_path = _prov(cfg) / "stage1_query_cleaning_log.csv"
    rows = []
    with open(log_path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            sdg_str = rec["sdg_number"]
            rows.append({
                "sdg_number": sdg_str,
                "sdg_int": int(sdg_str.lstrip("0") or "0"),
                "original_length": int(rec["original_length"]),
                "cleaned_length": int(rec["cleaned_length"]),
                "total_transformations": int(rec["total_transformations"]),
                "query_file": f"SDG{sdg_str}_full.txt",
            })
    rows.sort(key=lambda r: r["sdg_int"])
    return rows


# ---------------------------------------------------------------------------
# Stage 2 — Data acquisition
# ---------------------------------------------------------------------------

def read_stage2(cfg):
    """Read the acquisition manifest and checksum file.

    Returns:
        sdg_totals  — dict SDG-int → {sdg_name, count, date, parts}
        total_raw   — int total records across all exports
        checksums   — dict filename → sha256 hex string
    """
    prov = _prov(cfg)
    manifest_path = prov / "stage2_acquisition_manifest.csv"
    checksums_path = prov / "stage2_checksums.txt"

    sdg_totals = {}
    with open(manifest_path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            n = int(rec["sdg_number"])
            if n not in sdg_totals:
                sdg_totals[n] = {
                    "sdg_name": rec["sdg_name"],
                    "date": rec["export_date"],
                    "count": 0,
                    "parts": 0,
                }
            sdg_totals[n]["count"] += int(rec["raw_record_count"])
            sdg_totals[n]["parts"] += 1

    total_raw = sum(v["count"] for v in sdg_totals.values())

    checksums = {}
    if checksums_path.exists():
        with open(checksums_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("  ", 1)
                if len(parts) == 2:
                    checksums[parts[1]] = parts[0]

    return sdg_totals, total_raw, checksums


# ---------------------------------------------------------------------------
# Stage 3 — Cleaning
# ---------------------------------------------------------------------------

def read_stage3(cfg):
    """Count deduplication removals from stage3_dedup_log.csv.

    Returns a dict with keys:
        total_raw, doi_removed, fuzzy_removed, total_removed, retained
    """
    prov = _prov(cfg)

    # Total raw is the authoritative sum from the manifest
    total_raw = 0
    with open(prov / "stage2_acquisition_manifest.csv", newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            total_raw += int(rec["raw_record_count"])

    doi_removed = 0
    fuzzy_removed = 0
    with open(prov / "stage3_dedup_log.csv", newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            if rec.get("reason") == "doi_exact_match":
                doi_removed += 1
            else:
                fuzzy_removed += 1

    total_removed = doi_removed + fuzzy_removed
    retained = total_raw - total_removed
    return {
        "total_raw": total_raw,
        "doi_removed": doi_removed,
        "fuzzy_removed": fuzzy_removed,
        "total_removed": total_removed,
        "retained": retained,
    }


# ---------------------------------------------------------------------------
# Stage 4 — Enrichment
# ---------------------------------------------------------------------------

def read_stage4(cfg):
    """Read the keyword thesaurus for enrichment statistics.

    Returns a dict with keys:
        total_entries, multi_sdg_count, rule_counts
    """
    thesaurus_path = _prov(cfg) / "stage4_thesaurus.csv"
    total = 0
    multi_sdg = 0
    rule_counts = {}

    with open(thesaurus_path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            total += 1
            flag = rec.get("potentially_multi_sdg", "").strip().lower()
            if flag in ("true", "1", "yes"):
                multi_sdg += 1
            rule = rec.get("rule_type", "unknown").strip()
            rule_counts[rule] = rule_counts.get(rule, 0) + 1

    return {"total_entries": total, "multi_sdg_count": multi_sdg, "rule_counts": rule_counts}


# ---------------------------------------------------------------------------
# Software environment
# ---------------------------------------------------------------------------

def read_requirements():
    """Parse requirements.txt and return list of (package, version) tuples."""
    req_path = ROOT / "requirements.txt"
    pkgs = []
    if not req_path.exists():
        return pkgs
    with open(req_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9_\-]+)[=><!]+\s*(.+)$", line)
            if m:
                pkgs.append((m.group(1), m.group(2)))
    return pkgs


def _run_cmd(cmd):
    """Run a subprocess command and return combined stdout+stderr, or ''."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
        )
        return (result.stdout + result.stderr).strip()
    except Exception:
        return ""


def get_r_version():
    """Return the installed R version string, or 'not detected'."""
    out = _run_cmd(["Rscript", "--version"])
    if out:
        m = re.search(r"version\s+(\d+\.\d+\.\d+)", out, re.IGNORECASE)
        if m:
            return m.group(1)
    return "not detected"


def get_bibliometrix_version():
    """Return the installed bibliometrix version, or 'not detected'."""
    out = _run_cmd(
        ["Rscript", "-e", "cat(as.character(packageVersion('bibliometrix')))"]
    )
    if out and re.match(r"\d+\.\d+", out):
        return out.strip()
    return "not detected"


def read_ror_snapshot(cfg):
    """Parse key-value pairs from stage3_ror_snapshot.txt."""
    snapshot_path = _prov(cfg) / "stage3_ror_snapshot.txt"
    info = {}
    if not snapshot_path.exists():
        return info
    with open(snapshot_path, encoding="utf-8") as fh:
        for line in fh:
            if ":" in line:
                k, _, v = line.partition(":")
                info[k.strip()] = v.strip()
    return info


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _n(value):
    """Format an integer with thousands separators."""
    return f"{int(value):,}"


def _pct(part, whole):
    """Return 'NN.NN%' string."""
    return f"{part / whole * 100:.2f}%"


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def build_markdown(stage1, s2_sdg_totals, s2_total_raw, s2_checksums,
                   stage3, stage4, pkgs, r_ver, biblio_ver, ror_info, cfg):
    """Assemble the full Markdown provenance report and return as a string."""

    lines = []
    w = lines.append

    # Header
    w("# Pipeline Provenance Report")
    w("")
    w(f"**Generated:** {NOW.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    w("**Article:** Africa's Scientific Contribution to the Sustainable Development "
      "Goals (2015–2025): An Auditable Bibliometric Analysis of Research Output, "
      "Thematic Coverage, and Collaboration Across 54 Countries")
    w("**Lead author:** El Majjaoui, Abdelilah "
      "(ENSAH, Abdelmalek Essaâdi University, Morocco)")
    w("**Pipeline framework:** Six-stage auditable bibliometric pipeline")
    w("")
    w("---")
    w("")

    # ------------------------------------------------------------------
    # Section 1 — Pipeline overview
    # ------------------------------------------------------------------
    w("## Section 1 — Pipeline Overview")
    w("")
    w("| Stage | Label | Primary script | Key output |")
    w("|-------|-------|---------------|------------|")
    w("| 1 | Query specification | `00_clean_composed_queries.py` | `sdg_queries/composed/` |")
    w("| 2 | Data acquisition | `01_stage2_acquisition_manifest.py` | `data/raw/` + manifest |")
    w("| 3a | Deduplication | `01_deduplication.py` | `data/interim/deduplicated.csv` |")
    w("| 3c | Affiliation standardisation | `02_affiliation_standardisation.py` | `data/interim/standardised.csv` |")
    w("| 4 | Keyword harmonisation | `03_keyword_harmonisation.py` | `data/processed/enriched.csv` |")
    w("| 5a | Performance indicators | `04_performance_indicators.py` | `results/table_T*.csv` |")
    w("| 5b | Thematic analysis | `05a–05c.R` | `figures/F6–F8` |")
    w("| 5c | Alignment analysis | `06_alignment_analysis.py` | `results/rq5_*.csv` |")
    w("| 6 | Provenance report | `07_provenance_report.py` | this file |")
    w("")
    w("---")
    w("")

    # ------------------------------------------------------------------
    # Section 2 — Stage 1: Query specification
    # ------------------------------------------------------------------
    w("## Section 2 — Stage 1: Query Specification")
    w("")
    w("**Query framework:** Aurora Network SDG Queries v5.0.3 "
      "(Vanderfeesten et al., 2020; DOI: 10.5281/zenodo.4883250)")
    w("")
    w("Wildcard cleaning rules applied before Scopus submission:")
    w("")
    w("| Rule | Description |")
    w("|------|-------------|")
    w("| A | Remove quotes around single-word wildcards: `\"child*\"` → `child*` |")
    w("| B | Remove wildcard from quoted multi-word phrases: `\"poverty line*\"` → `\"poverty line\"` |")
    w("| C | Remove wildcard from curly-brace exact phrases: `{phrase*}` → `{phrase}` |")
    w("| D | Remove leading wildcards: `*poverty` → `poverty` |")
    w("| E | Whitespace normalisation |")
    w("| F | Replace `W/n` proximity with `AND` when either group contains a wildcard |")
    w("| G | Complex `W/n`+wildcard → `AND` for compound operand groups |")
    w("")
    w("| SDG | Query file | Original length (chars) | Cleaned length (chars) | Transformations |")
    w("|-----|-----------|------------------------|------------------------|-----------------|")
    for r in stage1:
        w(f"| {r['sdg_int']:2d} | `{r['query_file']}` | "
          f"{_n(r['original_length'])} | {_n(r['cleaned_length'])} | "
          f"{r['total_transformations']} |")
    w(f"| **Total** | | "
      f"**{_n(sum(r['original_length'] for r in stage1))}** | "
      f"**{_n(sum(r['cleaned_length'] for r in stage1))}** | "
      f"**{sum(r['total_transformations'] for r in stage1)}** |")
    w("")
    w("---")
    w("")

    # ------------------------------------------------------------------
    # Section 3 — Stage 2: Data acquisition
    # ------------------------------------------------------------------
    w("## Section 3 — Stage 2: Data Acquisition")
    w("")
    w("All records retrieved from **Scopus** via Advanced Search on **2026-05-08**.")
    w("Queries were restricted to 54 African Union member states via `AFFILCOUNTRY` filter.")
    w("Exports exceeding 20,000 records were split by year range "
      "(see `provenance/stage2_acquisition_manifest.csv`).")
    w("")
    w("### Record counts per SDG")
    w("")
    w("| SDG | Name | Export parts | Record count |")
    w("|-----|------|-------------|-------------|")
    for n in sorted(s2_sdg_totals.keys()):
        v = s2_sdg_totals[n]
        w(f"| {n:2d} | {v['sdg_name']} | {v['parts']} | {_n(v['count'])} |")
    w(f"| **Total** | | | **{_n(s2_total_raw)}** |")
    w("")
    w("### SHA-256 checksums of raw CSV files")
    w("")
    w("```")
    for fname in sorted(k for k in s2_checksums if k.startswith("SDG")):
        w(f"{s2_checksums[fname]}  {fname}")
    if "deduplicated.csv" in s2_checksums:
        w(f"{s2_checksums['deduplicated.csv']}  deduplicated.csv")
    w("```")
    w("")
    w("---")
    w("")

    # ------------------------------------------------------------------
    # Section 4 — Stage 3: Cleaning
    # ------------------------------------------------------------------
    w("## Section 4 — Stage 3: Cleaning")
    w("")
    w("### Deduplication (Stage 3a)")
    w("")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Total raw records (all exports combined) | {_n(stage3['total_raw'])} |")
    w(f"| Removed — DOI exact-match (Pass 1) "
      f"| {_n(stage3['doi_removed'])} ({_pct(stage3['doi_removed'], stage3['total_raw'])}) |")
    w(f"| Removed — fuzzy title-match (Pass 2) "
      f"| {_n(stage3['fuzzy_removed'])} ({_pct(stage3['fuzzy_removed'], stage3['total_raw'])}) |")
    w(f"| **Total removed** "
      f"| **{_n(stage3['total_removed'])} ({_pct(stage3['total_removed'], stage3['total_raw'])})** |")
    w(f"| **Unique records retained** | **{_n(stage3['retained'])}** |")
    w("")
    dedup_cfg = cfg.get("cleaning", {})
    w("**Deduplication parameters** (from `config.yaml`):")
    w("")
    w(f"- Primary key: DOI (lowercase, exact match) — "
      f"`dedup_doi_lowercase: {dedup_cfg.get('dedup_doi_lowercase', True)}`")
    w(f"- Fuzzy-title similarity threshold: "
      f"`{dedup_cfg.get('dedup_title_threshold', 0.95)}` "
      f"(rapidfuzz `token_sort_ratio`, Pass 2 applied to no-DOI records only)")
    w(f"- Year window for fuzzy matching: "
      f"±`{dedup_cfg.get('dedup_year_window', 1)}` year")
    w("")
    w("---")
    w("")

    # ------------------------------------------------------------------
    # Section 5 — Stage 4: Enrichment
    # ------------------------------------------------------------------
    w("## Section 5 — Stage 4: Enrichment (Keyword Harmonisation)")
    w("")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Thesaurus entries total | {_n(stage4['total_entries'])} |")
    w(f"| Keywords flagged as potentially multi-SDG | {stage4['multi_sdg_count']} |")
    w("")
    w("Rule-type breakdown:")
    w("")
    w("| Rule type | Count |")
    w("|-----------|-------|")
    for rule, count in sorted(stage4["rule_counts"].items(), key=lambda x: -x[1]):
        w(f"| {rule} | {count} |")
    w("")
    w("---")
    w("")

    # ------------------------------------------------------------------
    # Section 6 — Software environment
    # ------------------------------------------------------------------
    w("## Section 6 — Software Environment")
    w("")
    w("### Python")
    w("")
    w(f"Python `{sys.version.split()[0]}` on `{sys.platform}`")
    w("")
    w("Pinned package versions (`requirements.txt`):")
    w("")
    w("| Package | Version |")
    w("|---------|---------|")
    for pkg, ver in pkgs:
        w(f"| `{pkg}` | `{ver}` |")
    w("")
    w("### R")
    w("")
    w(f"R version: **{r_ver}**")
    w(f"bibliometrix version: **{biblio_ver}**")
    w("")
    w("R packages used: `bibliometrix`, `ggplot2`, `ggalluvial`, "
      "`data.table`, `htmlwidgets`, `webshot2`")
    w("")
    w("### External reference data")
    w("")
    ror_ver = ror_info.get("ror_version", "v2.6-2026-04")
    ror_doi = ror_info.get("zenodo_doi", "10.5281/zenodo.19576723")
    ror_date = ror_info.get("release_date", "2026-04-14")
    ror_ts = ror_info.get("download_timestamp", "2026-05-08")[:10]
    w("| Resource | Version | DOI / Source |")
    w("|----------|---------|-------------|")
    w(f"| ROR data dump | {ror_ver} (released {ror_date}, downloaded {ror_ts}) | {ror_doi} |")
    w("| Aurora Network SDG Queries | v5.0.3 | 10.5281/zenodo.4883250 |")
    w("| SDG Index | 2025 | Sachs et al., 2025 — dashboards.sdgindex.org |")
    w("| Scopus | — | Retrieved 2026-05-08 (institutional access) |")
    w("")
    w("---")
    w("")

    # ------------------------------------------------------------------
    # Section 7 — Reproducibility statement
    # ------------------------------------------------------------------
    w("## Section 7 — Reproducibility Statement")
    w("")
    w("With authorised Scopus access and the versioned rule sets archived in this")
    w("repository, the deterministic stages of this pipeline are designed to produce")
    w("identical outputs. All cleaning rules — deduplication thresholds, affiliation")
    w("fuzzy-match parameters, and keyword thesaurus mappings — are fixed in")
    w("`config.yaml` and `provenance/stage3_manual_overrides.csv`. Stage 5 statistical")
    w("analysis (Spearman ρ with bootstrap 95% CI, 1,000 resamples) uses")
    w("`scipy.stats.spearmanr` with a fixed random seed in `code/06_alignment_analysis.py`,")
    w("ensuring full computational reproducibility.")
    w("")
    w("**Non-deterministic element:** Scopus search results are subject to database")
    w("updates after the retrieval date. Results are anchored to the snapshot of")
    w("**2026-05-08** via SHA-256 checksums recorded in `provenance/stage2_checksums.txt`.")
    w("")
    w("---")
    w("")
    w(f"*Report generated by `code/07_provenance_report.py` — "
      f"{NOW.strftime('%Y-%m-%d %H:%M:%S UTC')}*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plain-text summary
# ---------------------------------------------------------------------------

def build_summary(stage1, s2_sdg_totals, s2_total_raw,
                  stage3, stage4, pkgs, r_ver, ror_info):
    """Build a one-page plain-text summary for journal supplementary submission."""

    ror_ver = ror_info.get("ror_version", "v2.6-2026-04")
    ror_doi = ror_info.get("zenodo_doi", "10.5281/zenodo.19576723")

    lines = []
    w = lines.append
    sep = "-" * 60

    w("PIPELINE PROVENANCE SUMMARY")
    w("=" * 60)
    w(f"Generated   : {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    w("Article     : Africa's Scientific Contribution to the SDGs (2015-2025)")
    w("Author      : El Majjaoui, A. (ENSAH, Abdelmalek Essaadi University)")
    w("")
    w("STAGE 1 — QUERY SPECIFICATION")
    w(sep)
    w("Framework   : Aurora Network SDG Queries v5.0.3")
    w("              DOI: 10.5281/zenodo.4883250")
    w("17 SDG queries processed with wildcard cleaning rules A-G.")
    w(f"Total characters after cleaning : "
      f"{_n(sum(r['cleaned_length'] for r in stage1))}")
    w(f"Total transformations applied   : "
      f"{sum(r['total_transformations'] for r in stage1)}")
    w("")
    w("STAGE 2 — DATA ACQUISITION")
    w(sep)
    w("Source      : Scopus Advanced Search (institutional access)")
    w("Date        : 2026-05-08 (all 17 SDGs)")
    w("Scope       : 54 African Union member states (AFFILCOUNTRY filter)")
    w(f"Raw records : {_n(s2_total_raw)} across 41 CSV export files")
    w("")
    w("  Per-SDG record counts:")
    for n in sorted(s2_sdg_totals.keys()):
        v = s2_sdg_totals[n]
        w(f"    SDG{n:02d}  {v['sdg_name']:<45} {_n(v['count']):>8}")
    w("")
    w("STAGE 3 — CLEANING")
    w(sep)
    w(f"  Input records             : {_n(stage3['total_raw'])}")
    w(f"  Removed (DOI exact match) : "
      f"{_n(stage3['doi_removed'])} ({_pct(stage3['doi_removed'], stage3['total_raw'])})")
    w(f"  Removed (fuzzy title)     : "
      f"{_n(stage3['fuzzy_removed'])} ({_pct(stage3['fuzzy_removed'], stage3['total_raw'])})")
    w(f"  Unique records retained   : {_n(stage3['retained'])}")
    w("")
    w("STAGE 4 — ENRICHMENT")
    w(sep)
    w(f"  Thesaurus entries total   : {_n(stage4['total_entries'])}")
    w(f"  Multi-SDG keywords flagged: {stage4['multi_sdg_count']}")
    w("")
    w("SOFTWARE ENVIRONMENT")
    w(sep)
    w(f"  Python : {sys.version.split()[0]}")
    for pkg, ver in pkgs:
        w(f"  {pkg:<20}: {ver}")
    w(f"  R      : {r_ver}")
    w(f"  bibliometrix : see session_info()")
    w(f"  ROR data     : {ror_ver} ({ror_doi})")
    w("")
    w("REPRODUCIBILITY STATEMENT")
    w(sep)
    w("With authorised Scopus access and the versioned rule sets archived")
    w("in this repository, the deterministic stages of this pipeline are")
    w("designed to produce identical outputs. SHA-256 checksums for all")
    w("raw data files are recorded in provenance/stage2_checksums.txt.")
    w("")
    w("=" * 60)
    w(f"Generated: {NOW.strftime('%Y-%m-%d %H:%M UTC')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Generate the Stage-6 provenance report and one-page summary."""
    cfg = load_config()
    prov_dir = _prov(cfg)

    print("Reading stage artefacts …")
    stage1 = read_stage1(cfg)
    s2_sdg_totals, s2_total_raw, s2_checksums = read_stage2(cfg)
    print("  Stage 3 dedup log — counting rows (this may take a moment) …")
    stage3 = read_stage3(cfg)
    stage4 = read_stage4(cfg)
    pkgs = read_requirements()
    print("  Detecting R version …")
    r_ver = get_r_version()
    biblio_ver = get_bibliometrix_version()
    ror_info = read_ror_snapshot(cfg)

    md = build_markdown(
        stage1, s2_sdg_totals, s2_total_raw, s2_checksums,
        stage3, stage4, pkgs, r_ver, biblio_ver, ror_info, cfg,
    )
    txt = build_summary(
        stage1, s2_sdg_totals, s2_total_raw, stage3, stage4,
        pkgs, r_ver, ror_info,
    )

    md_path = prov_dir / "provenance_report.md"
    txt_path = prov_dir / "provenance_report_summary.txt"

    md_path.write_text(md, encoding="utf-8")
    txt_path.write_text(txt, encoding="utf-8")

    print(f"Provenance report generated: {md_path.relative_to(ROOT)}")
    print(f"Summary generated          : {txt_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
