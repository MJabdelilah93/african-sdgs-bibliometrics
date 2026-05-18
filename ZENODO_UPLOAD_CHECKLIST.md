# Zenodo Upload Checklist — Article 08

Prepared: 2026-05-18  
Zenodo DOI: [ZENODO DOI TO BE ADDED]

---

## 1. Files to INCLUDE in the Zenodo deposit

### Root-level files

| File | Status | Notes |
|------|--------|-------|
| `README.md` | Present | Update DOI placeholder before upload |
| `config.yaml` | Present | |
| `requirements.txt` | Present | Pinned Python 3.12 versions |
| `ZENODO_UPLOAD_CHECKLIST.md` | Present | This file — include for transparency |
| `.gitignore` | Present | Optional but harmless |

### code/

| File | Status | Notes |
|------|--------|-------|
| `code/00_clean_composed_queries.py` | Present | |
| `code/00_year_split_queries.py` | Present | |
| `code/01_deduplication.py` | Present | |
| `code/01_stage2_acquisition_manifest.py` | Present | |
| `code/02_affiliation_standardisation.py` | Present | |
| `code/03_keyword_harmonisation.py` | Present | |
| `code/04_performance_indicators.py` | Present | |
| `code/05_thematic_analysis.R` | Present | |
| `code/05a_thematic_map_F6.R` | Present | |
| `code/05b_thematic_evolution_F7.R` | Present | |
| `code/05c_three_field_F8_fixed.R` | Present | |
| `code/05d_three_field_F8_python.py` | Present | |
| `code/06_alignment_analysis.py` | Present | |
| `code/07_provenance_report.py` | **MISSING** | Must be created before upload |
| `code/compose_aurora.py` | Present | |
| `code/utils/checksums.py` | Present | |
| `code/utils/config.py` | Present | |
| `code/utils/download_ror.py` | Present | |
| `code/utils/logger.py` | Present | |
| `code/utils/scopus_query_clean.py` | Present | |
| `code/utils/year_split_query.py` | Present | |

### country_lists/

| File | Status | Notes |
|------|--------|-------|
| `country_lists/au54_countries.csv` | Present | |
| `country_lists/sdg_names.csv` | Present | |

### sdg_queries/

| File | Status | Notes |
|------|--------|-------|
| `sdg_queries/aurora/query_SDG1.xml` … `query_SDG17.xml` | Present (17 files) | Aurora Network source XML |
| `sdg_queries/composed/SDG01_full.txt` … `SDG17_full.txt` | Present (17+ files) | Cleaned text queries |
| `sdg_queries/composed/SDG*_full_YYYY-YYYY.txt` | Present (year-split variants) | |
| `sdg_queries/composed/_aurora_provenance.txt` | Present | |
| `sdg_queries/composed/_query_lengths.csv` | Present | |
| `sdg_queries/composed/_pre_clean_archive/` | Present | Original pre-cleaning queries |

### provenance/

| File | Status | Notes |
|------|--------|-------|
| `provenance/stage1_query_cleaning_log.csv` | Present | |
| `provenance/stage2_acquisition_manifest.csv` | Present | Retrieval dates, record counts |
| `provenance/stage2_checksums.txt` | Present | SHA-256 of all raw CSVs |
| `provenance/stage3_dedup_log.csv` | Present | |
| `provenance/stage3_affiliation_log.csv` | Present | |
| `provenance/stage3_manual_overrides.csv` | Present | Manual affiliation corrections |
| `provenance/stage3_manual_review.csv` | Present | |
| `provenance/stage3_african_affiliations_to_review.csv` | Present | |
| `provenance/stage3_institutions_to_review.csv` | Present | |
| `provenance/stage3_ror_country_counts.csv` | Present | |
| `provenance/stage3_ror_snapshot.txt` | Present | ROR data version record |
| `provenance/stage4_thesaurus.csv` | Present | |
| `provenance/vosviewer_country_thesaurus.txt` | Present | |
| `provenance/logs/06_alignment_analysis.log` | Present | |
| `provenance/logs/stage2_verification.md` | Present | |
| `provenance/logs/stage3a_dedup_2026-05-08.log` | Present | |
| `provenance/logs/stage3c_affiliation.log` | Present | |
| `provenance/logs/stage4_keyword_2026-05-10.log` | Present | |
| `provenance/logs/stage5a_indicators.log` | Present | |

### results/

| File | Status | Notes |
|------|--------|-------|
| `results/table_T1_corpus_overview.csv` | Present | |
| `results/table_T2_publications_by_SDG.csv` | Present | |
| `results/table_T3_top_countries.csv` | Present | |
| `results/table_T4_top_institutions.csv` | Present | |
| `results/table_T5_top_journals.csv` | Present | |
| `results/table_T6_subregional_summary.csv` | Present | |
| `results/rq5_country_correlations.csv` | Present | |
| `results/rq5_inclusion_table.csv` | Present | |
| `results/rq5_quadrant_assignments.csv` | Present | |
| `results/rq5_sensitivity_absolute.csv` | Present | |
| `results/rq5_sensitivity_tertiles.csv` | Present | |
| `results/stage3_affiliation_results.csv` | Present | Derived institution-level data |

### figures/

Include only final static figure files. Exclude browser widget dependencies.

| File | Status | Notes |
|------|--------|-------|
| `figures/F2_annual_growth_subregion.png` | Present | |
| `figures/F2_annual_growth_subregion.svg` | Present | |
| `figures/F3_sdg_country_heatmap.png` | Present | |
| `figures/F3_sdg_country_heatmap.svg` | Present | |
| `figures/F4_top_countries_bar.png` | Present | |
| `figures/F4_top_countries_bar.svg` | Present | |
| `figures/F5_subregional_share.png` | Present | |
| `figures/F5_subregional_share.svg` | Present | |
| `figures/F6_thematic_map.png` | Present | |
| `figures/F6_thematic_map_data.csv` | Present | Source data for F6 |
| `figures/F7_thematic_evolution.png` | Present | |
| `figures/F7_edges_data.csv` | Present | Source data for F7 |
| `figures/F7_nodes_data.csv` | Present | Source data for F7 |
| `figures/F8_three_field_static.png` | Present | |
| `figures/F9_country_coauthorship.png` | Present | |
| `figures/F10_institution_coauthorship.png` | Present | |
| `figures/F11_keyword_cooccurrence.png` | Present | |
| `figures/F12_alignment_quadrant.png` | Present | |
| `figures/F12_alignment_quadrant.svg` | Present | |
| `figures/network_country_map.json` | Present | Network layout data |
| `figures/network_country_map.txt` | Present | |
| `figures/network_country_network.txt` | Present | |
| `figures/network_institution_map.txt` | Present | |
| `figures/network_institution_map_clean.txt` | Present | |
| `figures/network_institution_network.txt` | Present | |
| `figures/network_institution_network_clean.txt` | Present | |
| `figures/network_keyword_map.json` | Present | |
| `figures/network_keyword_map.txt` | Present | |
| `figures/network_keyword_network.txt` | Present | |

### data/external/ (redistributable reference data)

| File | Status | Notes |
|------|--------|-------|
| `data/external/ror/ror_africa_v2.json` | Present | Africa-filtered ROR subset (CC0) |
| `data/external/sdg_index/sdg_index_2025.xlsx` | Present | Bertelsmann SDG Index 2025 |

---

## 2. Files to EXCLUDE from the Zenodo deposit

| Path | Reason |
|------|--------|
| `data/raw/SDG*.csv` (41 files) | **Scopus data — Elsevier terms of use prohibit redistribution** |
| `data/interim/deduplicated.csv` | Derived from Scopus raw data — same licensing constraint |
| `data/interim/slim_affil.csv` | Derived from Scopus raw data |
| `data/interim/standardised.csv` | Derived from Scopus raw data |
| `data/processed/bibliometrix_input.csv` | Derived from Scopus raw data |
| `data/processed/bibliometrix_M.rds` | Derived from Scopus raw data |
| `data/processed/enriched.csv` | Derived from Scopus raw data |
| `data/processed/vosviewer_input.csv` | Derived from Scopus raw data |
| `data/external/ror/raw/v2.6-2026-04-14-ror-data.zip` | 32 MB — too large; reference via DOI instead |
| `data/external/ror/ror_data_v2_latest.json` | 280 MB — too large; reference via DOI instead |
| `figures/F8_three_field.html` | Interactive widget (bundled JS/CSS); static PNG is included |
| `figures/F8_three_field_files/` | Browser JS/CSS dependencies for F8 widget |
| `code/utils/__pycache__/` | Python compiled bytecode |
| `.Rhistory` | R session history — internal |
| `memory/` | Internal Claude Code working notes |
| `instructions/` | Internal Claude Code session prompts |
| `skills/` | Internal Claude Code prompts |
| `.git/` | Git repository history |
| `code/_edit_institution_map.py` | Internal utility — not part of main pipeline |
| `code/_shorten_labels.py` | Internal utility — not part of main pipeline |
| `code/utils/analyse_review.py` | Internal utility |
| `code/utils/classify_stubs.py` | Internal utility |
| `code/utils/measure_fixes.py` | Internal utility |

---

## 3. Action items before upload

- [ ] Write `code/07_provenance_report.py` (final pipeline script — currently missing)
- [ ] Fill in `[ZENODO DOI TO BE ADDED]` placeholder in `README.md` (available after first upload)
- [ ] Fill in `[JOURNAL DOI TO BE ADDED]` in `README.md`
- [ ] Add ORCID and contact email in `README.md`
- [ ] Verify SHA-256 checksums in `provenance/stage2_checksums.txt` still match `data/raw/` files
- [ ] Confirm R package versions and add an `renv.lock` or `session_info.txt` for R reproducibility

---

## 4. Recommended Zenodo metadata

| Field | Value |
|-------|-------|
| **Title** | Africa's Scientific Contribution to the Sustainable Development Goals (2015–2025): Replication Package |
| **Authors** | El Majjaoui, Abdelilah (ENSAH, Abdelmalek Essaâdi University, Morocco; ORCID: 0009-0008-1414-5602) |
| **Description** | Full replication package for the bibliometric analysis of African scientific output across all 17 SDGs and 54 AU member states. Includes Aurora SDG queries (v5.0.3), all analysis scripts (Python 3.12 / R 4.4), provenance audit trail, aggregated results tables (T1–T6), and all manuscript figures (F2–F12). Raw Scopus data is not included due to Elsevier licensing. |
| **Keywords** | bibliometrics; sustainable development goals; SDGs; Africa; scientometrics; research output; Scopus; Aurora queries; alignment analysis; Spearman correlation |
| **Licence** | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| **Resource type** | Software / Dataset |
| **Related publication DOI** | [JOURNAL DOI TO BE ADDED] |
| **Related dataset** | Aurora Network SDG Queries v5.0.3 — DOI: 10.5281/zenodo.4883250 |
| **Related dataset** | ROR Data Dump v2.6 (2026-04) — DOI: 10.5281/zenodo.19576723 |
| **Version** | 1.0.0 |
| **Language** | English |

---

## 5. Pre-upload verification commands

```bash
# Verify SHA-256 checksums of raw CSVs (run from project root)
python -c "
import hashlib, csv, pathlib
errors = []
with open('provenance/stage2_checksums.txt') as f:
    for line in f:
        line = line.strip()
        if not line: continue
        expected_hash, fname = line.split('  ', 1)
        fpath = pathlib.Path('data/raw') / fname
        if not fpath.exists():
            errors.append(f'MISSING: {fname}')
            continue
        actual = hashlib.sha256(fpath.read_bytes()).hexdigest()
        if actual != expected_hash:
            errors.append(f'MISMATCH: {fname}')
[print(e) for e in errors] or print('All checksums OK')
"
```
