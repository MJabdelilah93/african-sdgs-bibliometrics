# African SDG Bibliometric Analysis (2015–2025): Reproducibility Package

Version 2.0.0

## Scope

Bibliometric and scientometric analysis of research related to the Sustainable Development Goals (SDGs) with
authors affiliated in Africa:

- all 54 African Union (AU) member states;
- all 17 SDGs (Aurora SDG Queries v5.0.3);
- publication years 2015–2025;
- Scopus articles and reviews;
- final analytical corpus: **345,025 publications**.

## Reproducibility package

| Folder / file | Content |
|---|---|
| `sdg_queries/aurora/` | Aurora SDG query definitions (XML, v5.0.3) |
| `sdg_queries/composed/` | Scopus queries for the 17 SDGs restricted to the AU member states, including the publication-year splits used for export |
| `code/` | Processing, analysis, rendering and validation code (Python and R); `code/utils/` shared modules; `code/tests/` unit tests |
| `config.yaml` | Paths, study window, document types, deduplication and matching thresholds |
| `country_lists/` | AU member states (ISO codes, sub-regions), country-name reference, SDG names |
| `data/external/ror/ror_africa_v2.json` | ROR v2.6-2026-04 subset for organisations located in AU member states |
| `provenance/` | Query and export manifest, curated inputs (manual ROR overrides, keyword thesaurus), corpus record flow, analysis parameters, software environment, validation reference values and output checksums |
| `provenance/v2/` | Intermediate analysis tables used by the thematic, alignment and three-field scripts, and the sensitivity outputs |
| `results/` | Result tables (CSV); `results/vosviewer/` network files and VOSviewer exports |
| `figures/` | Figures 1–13 (PNG, SVG where available) and their data tables |
| `docs/` | Figure and table index (`figures_and_tables.csv`), VOSviewer settings (`vosviewer_settings.md`) |

## Workflow

| Stage | Steps | Code |
|---|---|---|
| 1. Query specification | Aurora SDG queries composed for Scopus, restricted to the 54 AU member states, 2015–2025, articles and reviews; Scopus syntax normalisation; publication-year splits for the 20,000-record export limit | `compose_aurora.py`, `00_clean_composed_queries.py`, `00_year_split_queries.py` |
| 2. Data acquisition | Scopus CSV exports (41 files of 8 May 2026; 2 SDG 2 files of 7 October 2026), file manifest and checksums | `01_stage2_acquisition_manifest.py`; `provenance/query_manifest.csv` |
| 3. Cleaning | Deduplication (EID, DOI, fuzzy title), consolidation with the SDG 2 assignment, eligibility screening (2015–2025, articles and reviews), corpus validation; country attribution from the affiliation text and ROR institution matching | `01_deduplication.py`, `01a_consolidate_corpus.py`, `01b_scope_2015_2025.py`, `01c_validate_corpus.py`, `utils/download_ror.py`, `02_affiliation_standardisation.py` |
| 4. Enrichment | Keyword harmonisation (keyword thesaurus) and the enriched record file with the consolidated SDG tags | `03_keyword_harmonisation.py` |
| 5. Analysis | Performance indicators; thematic map and evolution; research–implementation alignment (RQ5); collaboration networks; three-field plot; sensitivity analyses and independent validators | `04_performance_indicators.py`, `04b_export_annual_tables.py`, `05a_*.R`, `05b_*.R`, `05e_*.R`, `06_alignment_analysis.py`, `06b_alignment_validation.py`, `rq5_manuscript_prep.py`, `08_network_collaboration.py`, `08d_network_validation.py`, `08c_three_field_F11.py` |
| 6. Reporting | Production figures, VOSviewer maps, release validation | `05b_render_F7.R`, `06_render_F12_F13.py`, `08f_render_F11.py`, `07_render_figure1.py`, VOSviewer (`docs/vosviewer_settings.md`), `09_validate_release.py` |

Record flow (`provenance/corpus_flow.json`): 599,370 records in the 41 exports of 8 May 2026 and 31,198 records in
the two SDG 2 exports of 7 October 2026; 338,409 records after deduplication; 345,069 records after consolidation,
before eligibility screening; 44 records excluded (43 outside 2015–2025, 1 document type); **345,025** records in
the final analytical corpus (312,276 articles, 32,749 reviews), of which 344,020 have at least one affiliation
resolved to an AU member state.

## Software

| Software | Version |
|---|---|
| Python | 3.12.6 (packages pinned in `requirements.txt`) |
| R | 4.4.3 |
| bibliometrix | 5.4.0 |
| VOSviewer | 1.6.21 |
| ROR data dump | v2.6-2026-04 (Zenodo record 19576723) |
| Aurora SDG Queries | v5.0.3 |

Other R packages: ggplot2 4.0.3, ggalluvial 0.12.6, svglite 2.2.2, scales 1.4.0, openssl 2.4.0, jsonlite 2.0.0,
yaml 2.3.12. The complete environment is listed in `provenance/software_environment.txt`. The analysis was run on
Windows 11.

## Reproduction

Run all commands from the repository root. Several scripts refuse to run outside a Python virtual environment.

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt        # Windows; on Linux/macOS: .venv/bin/python
```

R 4.4.3 with the packages listed above is needed for Stage 05. Stage 01a holds the corpus in memory and needs about
20 GB of RAM (or RAM plus page file); the other stages process the corpus in chunks.

**Inputs that are not distributed** (see *Data availability*):

- Scopus exports in `data/raw/` (41 files) and `data/raw/sdg2_2026-10-07/` (2 files), named and identified by
  SHA-256 in `provenance/query_manifest.csv`. Scopus content changes over time; the published counts are reproduced
  only from these exports.
- Sustainable Development Report 2025 database (SDG Index goal scores) as
  `data/external/sdg_index/sdg_index_2025.xlsx`; its SHA-256 is checked by Stage 06.
- Full ROR v2.6-2026-04 data dump, downloaded by `code/utils/download_ror.py` (needed by Stage 02 for override
  targets outside Africa).

**Order of execution** (Python scripts with the virtual-environment interpreter; R scripts with `Rscript`):

1. Queries (optional; the composed queries are included): `compose_aurora.py`, `00_clean_composed_queries.py`,
   `00_year_split_queries.py`.
2. Acquisition: run each query in Scopus Advanced Search and export all records as CSV into `data/raw/`;
   `01_stage2_acquisition_manifest.py`.
3. Cleaning: `01_deduplication.py` → `01a_consolidate_corpus.py` → `01b_scope_2015_2025.py` →
   `01c_validate_corpus.py`; `utils/download_ror.py` → `02_affiliation_standardisation.py`.
4. Enrichment: `03_keyword_harmonisation.py`.
5. Analysis: `04_performance_indicators.py` → `04b_export_annual_tables.py`; `Rscript code/05a_thematic_map_F6.R`,
   `Rscript code/05b_thematic_evolution_F7.R`; `06_alignment_analysis.py` → `06b_alignment_validation.py` →
   `rq5_manuscript_prep.py`; `08_network_collaboration.py` → `08d_network_validation.py` →
   `08c_three_field_F11.py`.
6. Reporting: `Rscript code/05b_render_F7.R` → `Rscript code/05e_thematic_2025_sensitivity.R`;
   `06_render_F12_F13.py`; `08f_render_F11.py`; `07_render_figure1.py`; Figures 8–10 in VOSviewer with the settings
   in `docs/vosviewer_settings.md`; `09_validate_release.py`.

Unit tests: `code/tests/test_country_normalisation.py`, `code/tests/test_collab_methods.py`,
`code/tests/test_rq5_methods.py`.

Without the restricted inputs, the released outputs can still be inspected and checked:
`python code/09_validate_release.py` verifies the headline results, the VOSviewer exports of Figures 8–10 and the
SHA-256 of every released output (`provenance/output_checksums.sha256`).

## Data availability

Raw Scopus exports are not redistributed because of third-party licensing restrictions. The repository provides the queries, processing code, configuration files, analytical parameters, derived outputs and reproducibility documentation needed to inspect and reproduce the workflow using authorised source data.

## Validation

`provenance/reproducibility_validation.md` documents the validation of this package:

- the query stage regenerates all composed and year-split queries byte for byte from the Aurora XML files;
- corpus building from the raw exports reproduces the Stage 01 output and the record-level digests of the
  consolidated (345,069 records) and analytical (345,025 records) corpora (`provenance/corpus_validation.json`);
- the alignment analysis reproduces all RQ5 result tables and the Figure 12/13 data;
- `code/09_validate_release.py` checks the headline results (corpus, SDG distribution, alignment, sensitivity
  analyses, collaboration), the VOSviewer networks and the output checksums.

## Licence

Creative Commons Attribution 4.0 International (CC BY 4.0); see `LICENSE`. Third-party material: Aurora SDG
Queries (Vanderfeesten, Otten & Spielberg, 2020; CC BY 4.0) and ROR data (CC0 1.0).

## Citation

EL MAJJAOUI, A. (2026). *African SDG Bibliometric Analysis (2015–2025): Reproducibility Package* (Version 2.0.0)
[Software]. Zenodo. https://doi.org/10.5281/zenodo.23346426

Concept DOI (all versions): https://doi.org/10.5281/zenodo.20272149. Citation metadata: `CITATION.cff`.

References for the reused resources:

- Vanderfeesten, M., Otten, R., & Spielberg, E. (2020). Search queries for "mapping research output to the SDGs"
  (v5.0.3). Zenodo. https://doi.org/10.5281/zenodo.3817445
- Research Organization Registry (ROR). ROR data dump v2.6-2026-04. Zenodo. https://doi.org/10.5281/zenodo.19576723
