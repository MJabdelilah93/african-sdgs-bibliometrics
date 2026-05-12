# Africa's Scientific Contribution to the Sustainable Development Goals (2015–2025)

## An Auditable Bibliometric Analysis of Research Output, Thematic Coverage, and Collaboration Across 54 Countries

---

## Overview

This repository contains the full replication package for the article:

> El Majjaoui, A. (2026). Africa's Scientific Contribution to the
> Sustainable Development Goals (2015–2025): An Auditable Bibliometric
> Analysis of Research Output, Thematic Coverage, and Collaboration
> Across 54 Countries. *Journal of Cleaner Production* (under review).

The study covers all 54 African Union member states, all 17 SDGs,
and 338,409 unique publications retrieved from Scopus (2015–2025).

---

## Repository Structure

```
article08/
├── code/                    # All analysis scripts
│   ├── 01_deduplication.py
│   ├── 02_affiliation_standardisation.py
│   ├── 03_keyword_harmonisation.py
│   ├── 04_performance_indicators.py
│   ├── 05a_thematic_map_F6.R
│   ├── 05b_thematic_evolution_F7.R
│   ├── 05c_three_field_F8_fixed.R
│   ├── 05d_three_field_F8_python.py
│   ├── 06_alignment_analysis.py
│   ├── 07_provenance_report.py
│   └── utils/
│       ├── logger.py
│       ├── scopus_query_clean.py
│       └── download_ror.py
├── country_lists/           # AU-54 country reference files
├── figures/                 # All manuscript figures (F1-F12)
├── results/                 # Summary tables (T1-T6, RQ5 outputs)
├── provenance/              # Pipeline audit trail
├── config.yaml              # Project configuration
├── requirements.txt         # Python dependencies
└── README.md
```

---

## Data Availability

Raw Scopus exports cannot be shared due to Elsevier's terms of use.
The analysis can be replicated by:

1. Running the 16 Aurora Network SDG queries (v5.0.3;
   Vanderfeesten et al., 2020; DOI: 10.5281/zenodo.4883250)
   in Scopus with AFFILCOUNTRY filters for all 54 AU member states.
2. Exporting results as CSV files to `data/raw/`
3. Running the pipeline scripts in order (01 through 07).

The SDG Index 2025 data (Sachs et al., 2025) must be downloaded
separately from: https://dashboards.sdgindex.org/downloads

---

## Pipeline

The analysis follows the six-stage auditable pipeline published in:

> El Majjaoui, A. (2026). An auditable bibliometric pipeline.
> *Journal of Informetrics*.

Stages:
1. Query specification → `provenance/queries/`
2. Data acquisition → `data/raw/` (not included)
3. Cleaning → `code/01_deduplication.py`, `02_affiliation_standardisation.py`
4. Enrichment → `code/03_keyword_harmonisation.py`
5. Analysis → `code/04-06`
6. Reporting → `code/07_provenance_report.py`

---

## Requirements

### Python
```bash
pip install -r requirements.txt
```

### R
```r
install.packages(c("bibliometrix", "ggplot2", "ggalluvial",
                   "data.table", "htmlwidgets", "webshot2"))
```

---

## Key Findings

- CAGR of 16.3% (2015–2024), exceeding the global SDG research average
- Five countries account for 223,590 full-counted country-publication records
- SDG 3 (Health) dominates at 16.2%; SDG 7 (Energy) ranks 11th at 3.9%
- Intra-African co-authorship: 17.4% of Africa-involved link strength
- Median Spearman rho = −0.296 across 47 countries (42/47 negative):
  research portfolios systematically misaligned with implementation deficits
- SDG 7 is the most underserved goal relative to implementation need

---

## Citation

If you use this code or findings, please cite:

El Majjaoui, A. (2026). Africa's Scientific Contribution to the
Sustainable Development Goals (2015–2025): An Auditable Bibliometric
Analysis. *Journal of Cleaner Production*. [Under review]

---

## License

Code: MIT License  
Figures and manuscript text: CC BY 4.0

---

## Contact

Abdelilah El Majjaoui  
ENSAH, Abdelmalek Essaâdi University, Morocco  
0009-0008-1414-5602
