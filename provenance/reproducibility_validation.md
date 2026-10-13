# Reproducibility validation — version 2.0.0

Validation of this package, run on 13 October 2026 on Windows 11 with Python 3.12.6 and R 4.4.3
(`provenance/software_environment.txt`). Restricted inputs (Scopus exports, SDG Index workbook) were used from an
authorised local copy and are not part of the package.

## 1. Query specification

`compose_aurora.py` → `00_clean_composed_queries.py` → `00_year_split_queries.py`, run in an empty copy of the
package from the Aurora XML files (`sdg_queries/aurora/`):

| Output | Result |
|---|---|
| 17 composed and cleaned full queries (`SDG{nn}_full.txt`) | byte-identical |
| 36 publication-year split queries | byte-identical |
| `sdg_queries/composed/_query_lengths.csv` | byte-identical |
| `provenance/stage1_query_cleaning_log.csv` | byte-identical |
| `sdg_queries/composed/_aurora_provenance.txt` | identical except the composition date and the name of the XML parser (identical parse results) |

## 2. Data acquisition

The 43 exports are identified by SHA-256 in `provenance/query_manifest.csv` (41 exports of 8 May 2026, 599,370
records; 2 SDG 2 exports of 7 October 2026, 31,198 records). All 43 matched their recorded SHA-256 in the
validation run.

## 3. Cleaning — corpus construction from the raw exports

| Step | Result |
|---|---|
| `01_deduplication.py` on the 41 exports of 8 May 2026 | `data/interim/deduplicated.csv`: 338,409 records, SHA-256 `c6977ca7…0001b` = reference (`provenance/corpus_validation.json`) |
| `01a_consolidate_corpus.py --check-only` (complete consolidation; output streamed and digested, nothing written) | 345,069 consolidated records; field digest `f8b746b2…8c67` = reference; decision digest `ededc4a1…9979`; 6,654 records added from the SDG 2 exports, 2 removed, 8 kept separate; 31,190 records tagged SDG 2; 345,025 eligible records; all 40 checks PASS, including SHA-256 of all 43 exports and two complete in-memory runs being identical |
| Eligibility step: `eligibility()` of `01b_scope_2015_2025.py`, applied in 20,000-record chunks to the consolidated corpus with field digest `f8b746b2…8c67`; retained records written and read back with the Stage 01b / `01c_validate_corpus.py` CSV settings | 345,025 records (44 excluded: 43 exported year outside 2015–2025, 1 document type); 312,276 articles, 32,749 reviews; field digest `3544243b…cd1b` = reference; records per SDG = reference; EIDs unique |

## 4. Enrichment and 5. Analysis

| Stage | Validation |
|---|---|
| Stages 02–05 and 08 (affiliations, keywords, indicators, thematic analysis, networks) | Not re-executed for this release. The released result tables, figures, thematic tables and network files of these stages are the outputs of the analysis run and match the SHA-256 recorded at their generation (in the Figure 11 provenance record, two descriptive fields follow the released `08c_three_field_F11.py`). The released scripts are behaviour-equivalent to the scripts of that run for all released outputs: comparison of Python syntax trees (docstrings excluded) and R parse trees shows differences only in comments, documentation, log messages, descriptive fields of run records, default paths, removal of code that produced no released output, and the ROR download pinned to the archived release v2.6-2026-04 |
| Stage 06 / RQ5 (`06_alignment_analysis.py`, `rq5_manuscript_prep.py`, `06_render_F12_F13.py`) | Re-executed with the released scripts on the enriched corpus of the analysis and the SDG Index 2025 workbook: internal validation PASS; all 21 outputs byte-identical to the released files (11 `results/rq5_*.csv`; Figure 12 data, PNG and SVG; Figure 13 PNG and SVG; 4 sensitivity / bootstrap tables and the country crosswalk in `provenance/v2/`) |
| `04b_export_annual_tables.py` | Annual tables written from the Stage 04 run record; totals sum to 345,025 |
| Unit tests (`code/tests/`) | 26/26 PASS (country normalisation 11, collaboration methods 6, RQ5 methods 9) |

## 6. Reporting

| Item | Validation |
|---|---|
| Figure 1 (`07_render_figure1.py`) | Re-rendered byte-identically (PNG and SVG) from `provenance/corpus_flow.json` |
| Figures 8–10 (VOSviewer) | The JSON exports contain exactly the items, item weights, labels, links and link weights of the network input files (Figure 8: 67 items, 1,648 links; Figure 9: 50 items, 994 links; Figure 10: 50 items, 1,211 links); the Figure 10 display map differs from the scientific map only in the label field |
| Figure and data files | No content-credential or provider metadata (PNG chunks and SVG metadata inspected) |
| `09_validate_release.py` | 34/34 checks PASS: headline results below, VOSviewer networks of Figures 8–10, and SHA-256 of the 182 released outputs, queries, inputs and provenance files in `provenance/output_checksums.sha256` |

## Headline results checked by `code/09_validate_release.py`

| Result | Value |
|---|---|
| Publications / source titles / citations / citations per paper | 345,025 / 18,269 / 7,132,248 / 20.67 |
| Annual output 2015 / 2025; CAGR 2015–2024 | 12,697 / 60,917; 16.2% |
| SDG shares (fractional) | SDG 3 15.82%, SDG 12 9.88%, SDG 15 9.32%, SDG 13 9.26%, SDG 2 4.27%, SDG 7 3.79% |
| Alignment | 50 countries; median Spearman rho −0.251; 44 negative / 6 positive; bootstrap 95% CI entirely below zero only for Botswana and Comoros |
| Excluding 2025 publications | median rho −0.231; 44 negative |
| Low-research / high-deficit counts | median split: SDG 9 15, SDG 7 12; equal-allocation benchmark: SDG 9 42, SDG 7 38 |
| Collaboration | international 58.0%; at least two AU countries 12.3%; AU and non-AU countries 53.9%; intra-African link share 14.41% (full) / 12.73% (fractional) |
