# Africa's Scientific Contribution to the Sustainable Development Goals (2015–2025)

## An Auditable Bibliometric Analysis of Research Output, Thematic Coverage, and Collaboration Across 54 Countries

**Zenodo DOI:** [ZENODO DOI TO BE ADDED]  
**Related article DOI:** [JOURNAL DOI TO BE ADDED]  
**Licence:** CC BY 4.0

---

## Authors

**Abdelilah El Majjaoui**  
ENSAH, Abdelmalek Essaâdi University, Morocco  
ORCID: [0009-0008-1414-5602](https://orcid.org/0009-0008-1414-5602)

---

## Abstract

This replication package provides all queries, code, provenance records, and aggregated results for a fully auditable bibliometric analysis of African scientific output across all 17 UN Sustainable Development Goals (SDGs) and all 54 African Union member states (Scopus, 2015–2025). The study covers 338,409 unique deduplicated publications and examines growth trends, thematic coverage, international collaboration, and alignment between research portfolios and implementation deficits.

---

## Article Reference

> El Majjaoui, A. (2026). Africa's Scientific Contribution to the
> Sustainable Development Goals (2015–2025): An Auditable Bibliometric
> Analysis of Research Output, Thematic Coverage, and Collaboration
> Across 54 Countries. *Journal of Cleaner Production* (under review).

---

## Key Findings

- CAGR of 16.3% (2015–2024), exceeding the global SDG research average
- Five countries (South Africa, Egypt, Nigeria, Ethiopia, Kenya) account for the majority of output
- SDG 3 (Health) dominates at 16.2%; SDG 7 (Energy) ranks 11th at 3.9%
- Intra-African co-authorship represents 17.4% of Africa-involved link strength
- Median Spearman ρ = −0.296 across 47 countries (42/47 negative): research portfolios are systematically misaligned with implementation deficits
- SDG 7 is the most underserved goal relative to implementation need

---

## Data Availability

**Raw Scopus exports are not included** in this package due to Elsevier's terms of use for Scopus data. The analysis can be replicated by:

1. Running the 17 Aurora Network SDG queries (v5.0.3; Vanderfeesten et al., 2020; DOI: [10.5281/zenodo.4883250](https://doi.org/10.5281/zenodo.4883250)) in Scopus Advanced Search with `AFFILCOUNTRY` filters for all 54 AU member states (see `country_lists/au54_countries.csv`).
2. Exporting results as CSV files to `data/raw/` following the naming convention in `provenance/stage2_acquisition_manifest.csv`.
3. Verifying file integrity against `provenance/stage2_checksums.txt`.
4. Running the pipeline scripts in order (01 through 07).

The SDG Index 2025 data (Sachs et al., 2025) is included at `data/external/sdg_index/sdg_index_2025.xlsx`. It can also be downloaded from the [Sustainable Development Report](https://dashboards.sdgindex.org/downloads).

ROR affiliation data (v2.6, April 2026; DOI: [10.5281/zenodo.19576723](https://doi.org/10.5281/zenodo.19576723)) — the Africa-filtered subset is included at `data/external/ror/ror_africa_v2.json`.

---

## Repository Structure

```
article08/
├── code/                         # All analysis scripts
│   ├── 00_clean_composed_queries.py    # Stage 1: wildcard cleaning (Rules A-G)
│   ├── 00_year_split_queries.py        # Stage 1: year-range splitting
│   ├── 01_deduplication.py             # Stage 3a: DOI + fuzzy-title dedup
│   ├── 01_stage2_acquisition_manifest.py # Stage 2: manifest builder
│   ├── 02_affiliation_standardisation.py # Stage 3c: ROR-based affiliation
│   ├── 03_keyword_harmonisation.py     # Stage 4: thesaurus harmonisation
│   ├── 04_performance_indicators.py    # Stage 5a: output/growth/collab metrics
│   ├── 05_thematic_analysis.R          # Stage 5b: bibliometrix co-word analysis
│   ├── 05a_thematic_map_F6.R           # Figure F6: thematic map
│   ├── 05b_thematic_evolution_F7.R     # Figure F7: thematic evolution
│   ├── 05c_three_field_F8_fixed.R      # Figure F8: three-field (R version)
│   ├── 05d_three_field_F8_python.py    # Figure F8: three-field (Python version)
│   ├── 06_alignment_analysis.py        # Stage 5c: RQ5 Spearman alignment
│   ├── 07_provenance_report.py         # Stage 6: full audit report [TODO]
│   ├── compose_aurora.py               # Utility: compose Aurora XML → text queries
│   └── utils/
│       ├── checksums.py                # SHA-256 file hashing
│       ├── config.py                   # Config loader
│       ├── download_ror.py             # ROR data downloader
│       ├── logger.py                   # Structured logging
│       ├── scopus_query_clean.py       # Wildcard cleaning rules A-G
│       └── year_split_query.py         # Year-range splitter
├── country_lists/
│   ├── au54_countries.csv              # 54 African Union member states
│   └── sdg_names.csv                   # SDG number-to-name mapping
├── data/
│   ├── raw/                            # Scopus CSVs (NOT included — see above)
│   ├── interim/                        # Intermediate cleaning files (NOT included)
│   ├── processed/                      # Final analysis-ready corpus (NOT included)
│   └── external/
│       ├── ror/ror_africa_v2.json      # Africa ROR institutions (CC0)
│       └── sdg_index/sdg_index_2025.xlsx  # Bertelsmann SDG Index 2025
├── figures/                            # All manuscript figures (F2–F12, PNG + SVG)
├── provenance/                         # Full pipeline audit trail
│   ├── stage1_query_cleaning_log.csv   # Query cleaning statistics per SDG
│   ├── stage2_acquisition_manifest.csv # Retrieval date, record counts, file names
│   ├── stage2_checksums.txt            # SHA-256 checksums of raw CSV files
│   ├── stage3_dedup_log.csv            # Deduplication removals log
│   ├── stage3_affiliation_log.csv      # Affiliation standardisation log
│   ├── stage3_manual_overrides.csv     # Manual affiliation corrections
│   ├── stage3_ror_snapshot.txt         # ROR data version record
│   ├── stage4_thesaurus.csv            # Keyword harmonisation thesaurus
│   └── logs/                           # Per-stage execution logs
├── results/                            # Aggregated outputs (tables T1–T6, RQ5)
├── sdg_queries/
│   ├── aurora/                         # 17 Aurora XML source files
│   └── composed/                       # 17 cleaned text queries + year-splits
├── config.yaml                         # Project-level configuration
├── requirements.txt                    # Python 3.12 dependencies (pinned)
└── README.md
```

---

## How to Run

### Prerequisites

- Python 3.12.x
- R 4.4.x

### Python setup

```bash
pip install -r requirements.txt
```

### R setup

```r
install.packages(c("bibliometrix", "ggplot2", "ggalluvial",
                   "data.table", "htmlwidgets", "webshot2"))
```

### Pipeline execution

From the project root, run scripts in order after placing Scopus CSVs in `data/raw/`:

```bash
python code/01_deduplication.py
python code/02_affiliation_standardisation.py
python code/03_keyword_harmonisation.py
python code/04_performance_indicators.py
Rscript code/05a_thematic_map_F6.R
Rscript code/05b_thematic_evolution_F7.R
Rscript code/05c_three_field_F8_fixed.R
python code/06_alignment_analysis.py
python code/07_provenance_report.py
```

All scripts read paths from `config.yaml` and write a provenance log to `provenance/logs/`.

---

## SDG Query Framework

This study uses the **Aurora Network SDG Queries v5.0.3** (Vanderfeesten et al., 2020), DOI: [10.5281/zenodo.4883250](https://doi.org/10.5281/zenodo.4883250). The Elsevier 2025 framework was evaluated but rejected because several queries (SDGs 2, 4, 5, 17) use deeply nested `W/n` proximity operators designed for SciVal and are incompatible with standard Scopus Advanced Search.

Aurora queries (XML format) are parsed by `code/compose_aurora.py` and cleaned by `code/utils/scopus_query_clean.py` (Rules A–G). Cleaning rules and transformation counts are logged in `provenance/stage1_query_cleaning_log.csv`.

---

## Provenance

All Scopus exports were retrieved on **2026-05-08**. SHA-256 checksums are recorded in `provenance/stage2_checksums.txt`. ROR data snapshot details are in `provenance/stage3_ror_snapshot.txt`.

---

## Citation

If you use this code or data, please cite:

```
El Majjaoui, A. (2026). Africa's Scientific Contribution to the
Sustainable Development Goals (2015–2025): An Auditable Bibliometric
Analysis. Journal of Cleaner Production. [ZENODO DOI TO BE ADDED]
```

---

## Licence

This replication package is released under the **Creative Commons Attribution 4.0 International (CC BY 4.0)** licence. You are free to share and adapt the material for any purpose, provided appropriate credit is given.

See: [https://creativecommons.org/licenses/by/4.0/](https://creativecommons.org/licenses/by/4.0/)

---

## Contact

Abdelilah El Majjaoui  
ENSAH, Abdelmalek Essaâdi University, Morocco  
Email: [CONTACT EMAIL TO BE ADDED]  
ORCID: [0009-0008-1414-5602](https://orcid.org/0009-0008-1414-5602)
