# VOSviewer settings for Figures 8–10

Figures 8–10 were drawn in VOSviewer 1.6.21 from the map and network files written by
`code/08_network_collaboration.py` (`results/vosviewer/`). Counting is done in Python; VOSviewer is used only for
normalisation, layout, clustering and drawing. Settings common to the three figures:

| Setting | Value |
|---|---|
| VOSviewer version | 1.6.21 |
| Input | "Create a map based on network data": VOSviewer map file + VOSviewer network file |
| Counting | Full counting, pre-computed in the network file |
| Normalisation | Association strength |
| Clustering | Resolution 1.00, minimum cluster size 1, random seed 0 |
| Manual node moves | None |
| Exports | PNG (`figures/`) and VOSviewer JSON (`results/vosviewer/*.json`) |

The JSON exports store the items, item weights, coordinates, clusters and links of the final maps. They do not
store the layout or clustering parameters, which are therefore listed below. Layout parameters (attraction,
repulsion) affect only the positions of the items; they do not change items, links, weights or clusters of the
network input. `code/09_validate_release.py` checks that each JSON export contains exactly the items, item weights,
labels, links and link weights of its input files.

## Figure 8 — keyword co-occurrence network

| Setting | Value |
|---|---|
| Input | `F8_keyword_min1000_map.txt` + `F8_keyword_min1000_network.txt` |
| Unit | Harmonised author keywords (Stage 03), after removal of the 67 geographic terms of Stage 05 |
| Occurrence / co-occurrence | Number of records containing the keyword / both keywords (keywords deduplicated within a record) |
| Threshold | At least 1,000 occurrences (pre-selected in the input files; 67 keywords) |
| Item size | `weight<Occurrences>` |
| Layout | Attraction 2, repulsion −1 |
| Result | 67 items, 1,648 links, total link strength 37,318, 5 clusters |

Candidate thresholds (`results/keyword_threshold_candidates.csv`):

| Minimum occurrences | Keywords | Links among them |
|---|---|---|
| 250 | 498 | 37,602 |
| 500 | 189 | 9,325 |
| 750 | 104 | 3,543 |
| **1,000** | **67** | **1,648** |
| 1,250 | 47 | 822 |
| 1,500 | 34 | 433 |
| 2,000 | 18 | 118 |

The threshold is a readability choice (about 60–70 legible labels). Network files for 500 and 1,500 occurrences
are included as alternatives (`F8_keyword_min500_*`, `F8_keyword_min1500_*`).

## Figure 9 — country co-authorship network

| Setting | Value |
|---|---|
| Input | `F9_country_africa_involved_top50_map.txt` + `F9_country_africa_involved_top50_network.txt` |
| Unit | Countries (direct affiliation-text attribution); links with at least one AU member state as endpoint (AU–AU and AU–non-AU co-authorship) |
| Selection | Top 50 countries by link strength in this Africa-involved network (full network: `F9_country_africa_involved_full_*`) |
| Item size | `weight<Documents>` |
| Layout | Attraction 2, repulsion 0 |
| Result | 50 items, 994 links, total link strength 523,013, 5 clusters |

## Figure 10 — African-institution co-authorship network

| Setting | Value |
|---|---|
| Scientific input | `F10_institution_ror_top50_map.txt` + `F10_institution_ror_top50_network.txt` |
| Map loaded for display | `F10_institution_ror_top50_map_shortlabels.txt`: identical to the scientific map except for the `label` field; label mapping in `F10_institution_display_labels.csv` (ROR ID, full ROR name, short label) |
| Unit | African institutions identified by ROR ID (Stage 02; ROR v2.6-2026-04) |
| Selection | Top 50 institutions by total link strength (full network: 2,942 institutions and 74,942 links, `F10_institution_ror_full_*`) |
| Item size | `weight<Documents>` |
| Layout | Attraction 4, repulsion −1 |
| Result | 50 items, 1,211 links, total link strength 88,190, 5 clusters |

Cluster membership is descriptive and depends on the clustering settings above.
