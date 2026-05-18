# Pipeline Provenance Report

**Generated:** 2026-05-18 13:40:29 UTC
**Article:** Africa's Scientific Contribution to the Sustainable Development Goals (2015–2025): An Auditable Bibliometric Analysis of Research Output, Thematic Coverage, and Collaboration Across 54 Countries
**Lead author:** El Majjaoui, Abdelilah (ENSAH, Abdelmalek Essaâdi University, Morocco)
**Pipeline framework:** Six-stage auditable bibliometric pipeline

---

## Section 1 — Pipeline Overview

| Stage | Label | Primary script | Key output |
|-------|-------|---------------|------------|
| 1 | Query specification | `00_clean_composed_queries.py` | `sdg_queries/composed/` |
| 2 | Data acquisition | `01_stage2_acquisition_manifest.py` | `data/raw/` + manifest |
| 3a | Deduplication | `01_deduplication.py` | `data/interim/deduplicated.csv` |
| 3c | Affiliation standardisation | `02_affiliation_standardisation.py` | `data/interim/standardised.csv` |
| 4 | Keyword harmonisation | `03_keyword_harmonisation.py` | `data/processed/enriched.csv` |
| 5a | Performance indicators | `04_performance_indicators.py` | `results/table_T*.csv` |
| 5b | Thematic analysis | `05a–05c.R` | `figures/F6–F8` |
| 5c | Alignment analysis | `06_alignment_analysis.py` | `results/rq5_*.csv` |
| 6 | Provenance report | `07_provenance_report.py` | this file |

---

## Section 2 — Stage 1: Query Specification

**Query framework:** Aurora Network SDG Queries v5.0.3 (Vanderfeesten et al., 2020; DOI: 10.5281/zenodo.4883250)

Wildcard cleaning rules applied before Scopus submission:

| Rule | Description |
|------|-------------|
| A | Remove quotes around single-word wildcards: `"child*"` → `child*` |
| B | Remove wildcard from quoted multi-word phrases: `"poverty line*"` → `"poverty line"` |
| C | Remove wildcard from curly-brace exact phrases: `{phrase*}` → `{phrase}` |
| D | Remove leading wildcards: `*poverty` → `poverty` |
| E | Whitespace normalisation |
| F | Replace `W/n` proximity with `AND` when either group contains a wildcard |
| G | Complex `W/n`+wildcard → `AND` for compound operand groups |

| SDG | Query file | Original length (chars) | Cleaned length (chars) | Transformations |
|-----|-----------|------------------------|------------------------|-----------------|
|  1 | `SDG01_full.txt` | 3,414 | 3,338 | 64 |
|  2 | `SDG02_full.txt` | 3,638 | 3,524 | 77 |
|  3 | `SDG03_full.txt` | 6,412 | 6,246 | 133 |
|  4 | `SDG04_full.txt` | 3,860 | 3,797 | 56 |
|  5 | `SDG05_full.txt` | 4,827 | 4,701 | 81 |
|  6 | `SDG06_full.txt` | 3,244 | 3,173 | 65 |
|  7 | `SDG07_full.txt` | 2,914 | 2,893 | 21 |
|  8 | `SDG08_full.txt` | 4,461 | 4,407 | 83 |
|  9 | `SDG09_full.txt` | 4,595 | 4,496 | 89 |
| 10 | `SDG10_full.txt` | 3,877 | 3,767 | 86 |
| 11 | `SDG11_full.txt` | 3,964 | 3,897 | 63 |
| 12 | `SDG12_full.txt` | 3,684 | 3,585 | 74 |
| 13 | `SDG13_full.txt` | 3,951 | 3,832 | 80 |
| 14 | `SDG14_full.txt` | 4,313 | 4,155 | 101 |
| 15 | `SDG15_full.txt` | 5,186 | 5,017 | 109 |
| 16 | `SDG16_full.txt` | 5,162 | 4,986 | 131 |
| 17 | `SDG17_full.txt` | 6,917 | 6,711 | 194 |
| **Total** | | **74,419** | **72,525** | **1507** |

---

## Section 3 — Stage 2: Data Acquisition

All records retrieved from **Scopus** via Advanced Search on **2026-05-08**.
Queries were restricted to 54 African Union member states via `AFFILCOUNTRY` filter.
Exports exceeding 20,000 records were split by year range (see `provenance/stage2_acquisition_manifest.csv`).

### Record counts per SDG

| SDG | Name | Export parts | Record count |
|-----|------|-------------|-------------|
|  1 | No Poverty | 2 | 23,941 |
|  2 | Zero Hunger | 2 | 23,941 |
|  3 | Good Health and Well-being | 4 | 69,360 |
|  4 | Quality Education | 2 | 27,604 |
|  5 | Gender Equality | 1 | 14,857 |
|  6 | Clean Water and Sanitation | 3 | 45,369 |
|  7 | Affordable and Clean Energy | 1 | 19,932 |
|  8 | Decent Work and Economic Growth | 1 | 18,189 |
|  9 | Industry, Innovation and Infrastructure | 3 | 37,538 |
| 10 | Reduced Inequalities | 1 | 14,160 |
| 11 | Sustainable Cities and Communities | 2 | 27,412 |
| 12 | Responsible Consumption and Production | 5 | 69,448 |
| 13 | Climate Action | 4 | 54,190 |
| 14 | Life Below Water | 1 | 18,187 |
| 15 | Life on Land | 4 | 64,130 |
| 16 | Peace, Justice and Strong Institutions | 2 | 30,486 |
| 17 | Partnerships for the Goals | 3 | 40,626 |
| **Total** | | | **599,370** |

### SHA-256 checksums of raw CSV files

```
706dddf6239872ea907e707a4fc8d77cd4770d6f58e5b31b732b40855a554c44  SDG01_AU54_2026-05-08_2015-2020.csv
dc4d33bf6084c265a6b9fbb9b629f2771d5b6c4192f14ef1cbfd9592b3d499c7  SDG01_AU54_2026-05-08_2021-2025.csv
878451cb417340f02b41da2b2aeb3a37d9409378148930d65211ffd6115e00cb  SDG02_AU54_2026-05-08_2015-2021.csv
8272eb55be49ae3baa428cc9c235a73049ecbfcd619649e1d883101f6426d123  SDG02_AU54_2026-05-08_2022-2025.csv
cafaf199cdde878f04fdd79db7df819d2286da5409d60b89941d3ce5522dd56d  SDG03_AU54_2026-05-08_2015-2018.csv
f0de2ebe7692ef125ea108b758e7c980e7e2a6d08487243e00d883c14a127fda  SDG03_AU54_2026-05-08_2019-2021.csv
d066621958c658c7fa22e8085e110c50604a03dc4d77c5643a224548f52c280e  SDG03_AU54_2026-05-08_2022-2023.csv
0b833d9a2050c2cb1478eb20253ff98d17ae5a1ad5cfe2e3dd41c2c37462f9f2  SDG03_AU54_2026-05-08_2024-2025.csv
6d749e60cead62563b3a7d5090e379f55b5a601c3d090c0b3fad12cc04ad274a  SDG04_AU54_2026-05-08_2015-2020.csv
11ef0bde2937df32701da670483a04d1078e02179163cff003d5ba3a406d1ebd  SDG04_AU54_2026-05-08_2021-2025.csv
3473f886cfea0a66524c0e7e8667dc8ac7fdd909d6f02372352a22a1f997c8cf  SDG05_AU54_2026-05-08.csv
950185a532a266a0a3f8d6c2fdf4479c59c43a666a6821c2ed7b5a9bc830d4e5  SDG06_AU54_2026-05-08_2015-2020.csv
0ad5179df415b2eb06bc68d1a26def2dee2cfa692f728582b3938f89a649af03  SDG06_AU54_2026-05-08_2021-2023.csv
3aebd970445a9fd57410484512038cff62cdb51fc643658438a437cb901f260e  SDG06_AU54_2026-05-08_2024-2025.csv
ad08b74f623fff4f35a3b746bb976bc8803f1cad740bef06b318aad6374ce1fb  SDG07_AU54_2026-05-08.csv
4f836f980e1781a89801740c4b85eda5b7ca0f98040efce3644f82e01aa3d3e0  SDG08_AU54_2026-05-08.csv
b61ed64864c1e0b4167093ef2b5de6dad97f449d0ad17c9dff77147762ad2686  SDG09_AU54_2026-05-08_2015-2020.csv
41aa697bb2cab646f422d8565c9bc9aa23327dd6a33ea4c4199282c44d4060da  SDG09_AU54_2026-05-08_2021-2023.csv
a7f437c593541060729f22b8eb3141c813a7b9383f236f8dd27d2b70d0db0c97  SDG09_AU54_2026-05-08_2024-2025.csv
6655966ce4394eef5b7b6351a945fbfb24d343f00a2fa70e96843738c4a321b0  SDG10_AU54_2026-05-08.csv
3d37b62e89b141ba628ad23e1b4c71fc288cd4ad4c18793d53aee6187fa32f4b  SDG11_AU54_2026-05-08_2015-2020.csv
a220cc89ff92e6ef6087bbc8799e347dadd06657648e68bbf39b0c1edd003774  SDG11_AU54_2026-05-08_2021-2025.csv
8dedf8d2af6070f42b8fb25d735df3ddbb49016d7d85134dcd3dd99c3dbae1d7  SDG12_AU54_2026-05-08_2015-2020.csv
55af53c5f13433169856db4cd0079591c4002f00159cfb17c1eea203b8a7297f  SDG12_AU54_2026-05-08_2021-2022.csv
740298fd831d34fb513bd76c2f5ac541b9eccdd24b2122576087db5b2ece5405  SDG12_AU54_2026-05-08_2023-2023.csv
cf0743a19c485c454e237b17cf71fbccdeba6f48b62d35cd0c8f79b08680928f  SDG12_AU54_2026-05-08_2024-2024.csv
b3646b65d5412414ab1f7df51348226a4eafb6f0e257b3b9b747304346bc540b  SDG12_AU54_2026-05-08_2025-2025.csv
ca1c513730ca760d4f14862355e068b24aa3d859a8d00f47e70684a865bd6900  SDG13_AU54_2026-05-08_2015-2018.csv
f4a723d519ea8b25cdd4787600d9079a6f3cd11bd766472f1321cffb6ed5214f  SDG13_AU54_2026-05-08_2019-2022.csv
c1c961bfaa6721933890be8082fb88e5ac5eba3d72802ee047b183a1529ba5cc  SDG13_AU54_2026-05-08_2023-2024.csv
82d73f9880384a4188ada5cee2e9e75ccb1dbb70e8b70f81ff97b522c0175d19  SDG13_AU54_2026-05-08_2025-2025.csv
bb543294f13383a0aef357941368917c43f107b3a43102ce3fae484d57f773ff  SDG14_AU54_2026-05-08.csv
b72cbd48876b8d97948b3e60980767fca62144956aeba751850a0834a5cea35e  SDG15_AU54_2026-05-08_2015-2020.csv
1c6057bf9344f9eaa14321db600bdeb768a406b8e53d7a133c351e2ea2cc1385  SDG15_AU54_2026-05-08_2021-2022.csv
4b40dbb901afeb5770bcce4f394e4a3f18da38b85f43e694cbf1b21871a80902  SDG15_AU54_2026-05-08_2023-2024.csv
57268e2d0872048a8b6fc6a89bcd8f5058adbc22664cffab0857c95588fc6655  SDG15_AU54_2026-05-08_2025-2025.csv
ac2cd3ead4e775d8bc1741d2e531b760330ce41ae63be850f4a80c98ff149503  SDG16_AU54_2026-05-08_2015-2020.csv
a80dd2cc6b42f0a836505b8c359c357d313032284843b83a548d2fde25be997a  SDG16_AU54_2026-05-08_2021-2025.csv
ad70f95bd2e31f23c3990b936cded12b0df0e020da1831425e7557534ac59e4f  SDG17_AU54_2026-05-08_2015-2020.csv
f749338995917e44a5e9f6feff7515ff31ed8f552dd9b3bebe8e776eda70fed4  SDG17_AU54_2026-05-08_2021-2023.csv
5bfebc24e545bf2025d003aea386413a0c734b6f39e49110b8695f33b61fcfb3  SDG17_AU54_2026-05-08_2024-2025.csv
475adc989098c55dc03c3ecd427eb18721301458eb31bb0a174e1bfa45f45f29  deduplicated.csv
```

---

## Section 4 — Stage 3: Cleaning

### Deduplication (Stage 3a)

| Metric | Value |
|--------|-------|
| Total raw records (all exports combined) | 599,370 |
| Removed — DOI exact-match (Pass 1) | 254,171 (42.41%) |
| Removed — fuzzy title-match (Pass 2) | 6,790 (1.13%) |
| **Total removed** | **260,961 (43.54%)** |
| **Unique records retained** | **338,409** |

**Deduplication parameters** (from `config.yaml`):

- Primary key: DOI (lowercase, exact match) — `dedup_doi_lowercase: True`
- Fuzzy-title similarity threshold: `0.95` (rapidfuzz `token_sort_ratio`, Pass 2 applied to no-DOI records only)
- Year window for fuzzy matching: ±`1` year

---

## Section 5 — Stage 4: Enrichment (Keyword Harmonisation)

| Metric | Value |
|--------|-------|
| Thesaurus entries total | 169 |
| Keywords flagged as potentially multi-SDG | 8 |

Rule-type breakdown:

| Rule type | Count |
|-----------|-------|
| case_fold | 93 |
| plural_singular | 27 |
| hyphen | 18 |
| acronym_expansion | 16 |
| synonym_map | 12 |
| british_american | 3 |

---

## Section 6 — Software Environment

### Python

Python `3.12.6` on `win32`

Pinned package versions (`requirements.txt`):

| Package | Version |
|---------|---------|
| `pandas` | `2.2.2` |
| `numpy` | `1.26.4` |
| `scipy` | `1.13.1` |
| `matplotlib` | `3.9.2` |
| `seaborn` | `0.13.2` |
| `plotly` | `5.24.1` |
| `kaleido` | `0.2.1` |
| `rapidfuzz` | `3.10.1` |
| `openpyxl` | `3.1.5` |
| `requests` | `2.32.3` |
| `pyyaml` | `6.0.2` |
| `tqdm` | `4.66.5` |
| `adjustText` | `1.3.0` |

### R

R version: **not detected**
bibliometrix version: **not detected**

R packages used: `bibliometrix`, `ggplot2`, `ggalluvial`, `data.table`, `htmlwidgets`, `webshot2`

### External reference data

| Resource | Version | DOI / Source |
|----------|---------|-------------|
| ROR data dump | v2.6-2026-04 (released 2026-04-14, downloaded 2026-05-08) | 10.5281/zenodo.19576723 |
| Aurora Network SDG Queries | v5.0.3 | 10.5281/zenodo.4883250 |
| SDG Index | 2025 | Sachs et al., 2025 — dashboards.sdgindex.org |
| Scopus | — | Retrieved 2026-05-08 (institutional access) |

---

## Section 7 — Reproducibility Statement

With authorised Scopus access and the versioned rule sets archived in this
repository, the deterministic stages of this pipeline are designed to produce
identical outputs. All cleaning rules — deduplication thresholds, affiliation
fuzzy-match parameters, and keyword thesaurus mappings — are fixed in
`config.yaml` and `provenance/stage3_manual_overrides.csv`. Stage 5 statistical
analysis (Spearman ρ with bootstrap 95% CI, 1,000 resamples) uses
`scipy.stats.spearmanr` with a fixed random seed in `code/06_alignment_analysis.py`,
ensuring full computational reproducibility.

**Non-deterministic element:** Scopus search results are subject to database
updates after the retrieval date. Results are anchored to the snapshot of
**2026-05-08** via SHA-256 checksums recorded in `provenance/stage2_checksums.txt`.

---

*Report generated by `code/07_provenance_report.py` — 2026-05-18 13:40:29 UTC*