# =============================================================================
# Stage 05e — sensitivity analysis: thematic evolution (Figure 7) without 2025 publications.
# Input : data/processed/bibliometrix_input.csv (frozen; SHA-256 checked against the Stage 04 manifest)
# Output: provenance/v2/thematic_2025_sensitivity/  (sensitivity-only; frozen Figure 7 untouched)
#
# Identical to code/05b_thematic_evolution_F7.R in preprocessing (SR construction, keyword separator,
# 67-term geographic filter evaluated from 05b's own source lines) and in thematicEvolution parameters
# (field DE, years c(2018, 2022), n 250, minFreq 5, size 0.5, stemming FALSE, n.labels 3, repel TRUE,
# Louvain, seed 1234). The only change is the corpus restriction PY <= 2024.
# Gates (nothing is written unless all pass):
#   G1 the full-corpus run with this code path reproduces the frozen F7 nodes, edges and slice clusters;
#   G2 the restricted corpus removes exactly the PY == 2025 records and no earlier record;
#   G3 slices 2015-2018 / 2019-2022 contain identical records and DE strings in both corpora;
#   G4 frozen Figure 7 / Stage 05 files unchanged (SHA-256 before == after == Stage 05 manifest);
#   G5 environment = pinned (R 4.4.3, bibliometrix 5.4.0); same parameters; seeds 1234 (primary), 1, 2024.
# Run from the repository root:  Rscript code/05e_thematic_2025_sensitivity.R
# =============================================================================
source("code/utils/stage5_guard.R")
s5_require(c("bibliometrix", "jsonlite", "openssl"))
suppressPackageStartupMessages(library(bibliometrix))
run <- s5_start("05e")                                        # R / bibliometrix versions + input SHA-256 gate
OUT <- "provenance/v2/thematic_2025_sensitivity"
FROZEN <- c("figures/F7_nodes_data.csv", "figures/F7_edges_data.csv", "figures/F7_thematic_evolution.png",
            "figures/F7_thematic_evolution.svg", "provenance/v2/stage5_F7_periods.csv",
            "provenance/v2/stage5_F7_slice_clusters.csv", "provenance/v2/stage5_F7_params.csv")
frozen_before <- vapply(FROZEN, s5_sha, character(1))
man5 <- utils::read.csv("provenance/v2/stage5_thematic_manifest.csv", stringsAsFactors = FALSE, colClasses = "character")
gate <- list()
gate$G4_frozen_match_stage5_manifest <- all(vapply(FROZEN, function(f) {
  e <- man5$sha256[man5$path == f]; length(e) == 1 && e == frozen_before[[f]] }, logical(1)))

# ── preprocessing: identical to 05b steps 1-4 ─────────────────────────────────
M <- read.csv(S5_INPUT, encoding = "UTF-8", stringsAsFactors = FALSE, na.strings = "")
run <- s5_check_corpus(run, M)
M$SR <- make.unique(paste(sub(";.*", "", M$AU), M$SO, M$PY, sep = ", "), sep = "_")
M$SR_FULL   <- M$SR
rownames(M) <- M$SR
class(M)    <- c("bibliometrixDB", "data.frame")
M$PY <- suppressWarnings(as.integer(M$PY))
M$DE <- gsub("; ", ";", M$DE, fixed = TRUE)
M$ID <- gsub("; ", ";", M$ID, fixed = TRUE)
src <- readLines("code/05b_thematic_evolution_F7.R", encoding = "UTF-8")
i <- grep("GEO_TERMS <- tolower(c(", src, fixed = TRUE)
j <- grep("M_thematic    <- M", src, fixed = TRUE)
stopifnot(length(i) == 1, length(j) == 1, j > i)
eval(parse(text = src[i:(j - 1)], encoding = "UTF-8"))      # GEO_TERMS + remove_geo exactly as in 05b
gate$G5_geo_terms_67 <- length(GEO_TERMS) == 67 && !anyDuplicated(GEO_TERMS)
M_thematic    <- M
M_thematic$DE <- vapply(M$DE, remove_geo, character(1))

M_sens <- M_thematic[M_thematic$PY <= 2024L, ]
class(M_sens) <- class(M_thematic)
n_full <- nrow(M_thematic); n_sens <- nrow(M_sens); n_2025 <- sum(M_thematic$PY == 2025L)
gate$G2_only_2025_removed <- (n_full - n_sens == n_2025) && max(M_sens$PY) == 2024L &&
  identical(table(M_sens$PY), table(M_thematic$PY[M_thematic$PY <= 2024L]))

YEARS <- c(2018L, 2022L)
ts_full <- timeslice(M_thematic, breaks = YEARS)
ts_sens <- timeslice(M_sens, breaks = YEARS)
gate$G3_slices_1_2_identical <- all(vapply(1:2, function(k)
  identical(rownames(ts_full[[k]]), rownames(ts_sens[[k]])) && identical(ts_full[[k]]$DE, ts_sens[[k]]$DE), logical(1)))
periods <- function(ts) data.frame(slice = seq_along(ts), interval = names(ts),
  py_min = vapply(ts, function(d) as.integer(min(d$PY)), integer(1)),
  py_max = vapply(ts, function(d) as.integer(max(d$PY)), integer(1)),
  records = vapply(ts, nrow, integer(1)), records_with_DE = vapply(ts, function(d) sum(!is.na(d$DE)), integer(1)))
per_full <- periods(ts_full); per_sens <- periods(ts_sens)
gate$G2b_sens_periods_2015_2018_2019_2022_2023_2024 <- nrow(per_sens) == 3 &&
  all(per_sens$py_min == c(2015L, 2019L, 2023L)) && all(per_sens$py_max == c(2018L, 2022L, 2024L))

run_evol <- function(MM, seed) thematicEvolution(MM, field = "DE", years = YEARS, n = 250, minFreq = 5L, size = 0.5,
                                                stemming = FALSE, n.labels = 3, repel = TRUE, seed = seed)
cat("Running thematicEvolution: full corpus (gate G1), seed 1234 ...\n"); te_full <- run_evol(M_thematic, 1234)
cat("Running thematicEvolution: 2015-2024 corpus, seed 1234 (primary) ...\n"); te_s1234 <- run_evol(M_sens, 1234)
cat("Running thematicEvolution: 2015-2024 corpus, seed 1 ...\n");    te_s1 <- run_evol(M_sens, 1)
cat("Running thematicEvolution: 2015-2024 corpus, seed 2024 ...\n"); te_s2024 <- run_evol(M_sens, 2024)

# ── G1: this code path reproduces the frozen Figure 7 result exactly ───────────
fn <- utils::read.csv("figures/F7_nodes_data.csv", stringsAsFactors = FALSE, encoding = "UTF-8")
fe <- utils::read.csv("figures/F7_edges_data.csv", stringsAsFactors = FALSE, encoding = "UTF-8")
fsc <- utils::read.csv("provenance/v2/stage5_F7_slice_clusters.csv", stringsAsFactors = FALSE, encoding = "UTF-8")
rn <- te_full$Nodes; re <- te_full$Edges
same_num <- function(a, b) length(a) == length(b) && all(abs(as.numeric(a) - as.numeric(b)) < 1e-9)
g1_nodes <- nrow(rn) == nrow(fn) && identical(as.character(rn$name), fn$name) && identical(as.integer(rn$slice), fn$slice) &&
  same_num(rn$freq, fn$freq) && same_num(rn$sum, fn$sum)
g1_edges <- nrow(re) == nrow(fe) && same_num(re$from, fe$from) && same_num(re$to, fe$to) && same_num(re$Inclusion, fe$Inclusion) &&
  same_num(re$Inc_Weighted, fe$Inc_Weighted)
rsc <- do.call(rbind, lapply(seq_along(te_full$TM), function(k) cbind(slice = k, s5_flat(te_full$TM[[k]]$clusters))))
g1_clusters <- nrow(rsc) == nrow(fsc) && identical(as.character(rsc$name), fsc$name) && same_num(rsc$freq, fsc$freq) &&
  same_num(rsc$centrality, fsc$centrality) && same_num(rsc$density, fsc$density)
gate$G1_full_run_reproduces_frozen_nodes <- g1_nodes
gate$G1_full_run_reproduces_frozen_edges <- g1_edges
gate$G1_full_run_reproduces_frozen_slice_clusters <- g1_clusters
gate$G5_environment <- run$r_version == "R version 4.4.3 (2025-02-28 ucrt)" && run$bibliometrix == "5.4.0"

frozen_after <- vapply(FROZEN, s5_sha, character(1))
gate$G4_frozen_unchanged_during_run <- identical(frozen_before, frozen_after)
for (k in names(gate)) cat(sprintf("  [%s] %s\n", if (isTRUE(gate[[k]])) "PASS" else "FAIL", k))
if (!all(vapply(gate, isTRUE, logical(1)))) stop("VALIDATION GATE FAILED — no sensitivity output written.")

# ── outputs (only after every gate passed) ────────────────────────────────────
dir.create(OUT, showWarnings = FALSE, recursive = TRUE)
slice_label <- function(per) setNames(sprintf("%d-%d", per$py_min, per$py_max), per$slice)
theme_tab <- function(te, per, corpus, seed) {
  do.call(rbind, lapply(seq_along(te$TM), function(k) {
    cl <- s5_flat(te$TM[[k]]$clusters); w <- s5_flat(te$TM[[k]]$words)
    members <- vapply(cl$name, function(nm) paste(w$Words[w$Cluster_Label == nm], collapse = ";"), character(1))
    data.frame(corpus = corpus, seed = seed, slice = k, period = slice_label(per)[[as.character(k)]],
               theme = cl$name, freq = cl$freq, centrality = cl$centrality, density = cl$density,
               rank_centrality = cl$rcentrality, rank_density = cl$rdensity, n_keywords = cl$n,
               top_words = gsub("\n", "; ", cl$words), member_keywords = members, stringsAsFactors = FALSE)
  }))
}
edge_tab <- function(te, per, corpus, seed) {
  nd <- te$Nodes; ed <- te$Edges; lab <- slice_label(per)
  data.frame(corpus = corpus, seed = seed,
             from_theme = nd$name[match(ed$from, nd$id)], from_period = lab[as.character(nd$slice[match(ed$from, nd$id)])],
             to_theme = nd$name[match(ed$to, nd$id)], to_period = lab[as.character(nd$slice[match(ed$to, nd$id)])],
             inclusion = ed$Inclusion, inc_weighted = ed$Inc_Weighted, stringsAsFactors = FALSE)
}
th_full <- theme_tab(te_full, per_full, "frozen_2015_2025", 1234)
th_sens <- theme_tab(te_s1234, per_sens, "sensitivity_2015_2024", 1234)
th_seed <- rbind(theme_tab(te_s1, per_sens, "sensitivity_2015_2024", 1), theme_tab(te_s2024, per_sens, "sensitivity_2015_2024", 2024))
utils::write.csv(th_sens[th_sens$slice == 3, ], file.path(OUT, "primary_2023_2024_themes.csv"), row.names = FALSE, fileEncoding = "UTF-8")
utils::write.csv(rbind(th_full, th_sens), file.path(OUT, "all_slices_themes_frozen_vs_sensitivity.csv"), row.names = FALSE, fileEncoding = "UTF-8")

# final-slice comparison: keyword-membership overlap between every frozen 2023-2025 theme and every 2023-2024 theme
f3 <- th_full[th_full$slice == 3, ]; s3 <- th_sens[th_sens$slice == 3, ]
cmp <- do.call(rbind, lapply(seq_len(nrow(f3)), function(a) do.call(rbind, lapply(seq_len(nrow(s3)), function(b) {
  A <- strsplit(f3$member_keywords[a], ";", fixed = TRUE)[[1]]; Bk <- strsplit(s3$member_keywords[b], ";", fixed = TRUE)[[1]]
  inter <- length(intersect(A, Bk))
  data.frame(frozen_theme_2023_2025 = f3$theme[a], frozen_freq = f3$freq[a], sensitivity_theme_2023_2024 = s3$theme[b],
             sensitivity_freq = s3$freq[b], shared_keywords = inter,
             share_of_frozen_keywords = round(inter / length(A), 4), share_of_sensitivity_keywords = round(inter / length(Bk), 4),
             jaccard = round(inter / length(union(A, Bk)), 4), same_label = f3$theme[a] == s3$theme[b], stringsAsFactors = FALSE)
}))))
cmp <- cmp[cmp$shared_keywords > 0, ]
utils::write.csv(cmp, file.path(OUT, "final_slice_theme_comparison.csv"), row.names = FALSE, fileEncoding = "UTF-8")
ed_all <- rbind(edge_tab(te_full, per_full, "frozen_2015_2025", 1234), edge_tab(te_s1234, per_sens, "sensitivity_2015_2024", 1234))
utils::write.csv(ed_all, file.path(OUT, "evolution_links_frozen_vs_sensitivity.csv"), row.names = FALSE, fileEncoding = "UTF-8")
utils::write.csv(th_seed[th_seed$slice == 3, ], file.path(OUT, "seed_robustness_2023_2024_themes.csv"), row.names = FALSE, fileEncoding = "UTF-8")
utils::write.csv(rbind(cbind(corpus = "frozen_2015_2025", per_full), cbind(corpus = "sensitivity_2015_2024", per_sens)),
                 file.path(OUT, "periods_frozen_vs_sensitivity.csv"), row.names = FALSE, fileEncoding = "UTF-8")

FIVE <- c("adsorption", "machine learning", "sustainability", "climate change", "covid19")
present <- function(th) setNames(lapply(FIVE, function(t) t %in% th$theme[th$slice == 3]), FIVE)
summary <- list(
  stage = "05e thematic-evolution sensitivity excluding 2025",
  input = S5_INPUT, input_sha256 = run$input_sha256,
  records_full = n_full, records_2015_2024 = n_sens, records_2025_excluded = n_2025,
  parameters = list(field = "DE", years = YEARS, n = 250L, minFreq = 5L, size = 0.5, stemming = FALSE, n.labels = 3L,
                    repel = TRUE, cluster = "louvain", seed_primary = 1234L, seeds_robustness = c(1L, 2024L),
                    geo_filter = "67 terms evaluated from code/05b_thematic_evolution_F7.R"),
  gates = gate, periods_frozen = per_full, periods_sensitivity = per_sens,
  final_slice_themes = list(frozen_2023_2025 = f3$theme, sensitivity_2023_2024_seed1234 = s3$theme,
                            sensitivity_2023_2024_seed1 = th_seed$theme[th_seed$seed == 1 & th_seed$slice == 3],
                            sensitivity_2023_2024_seed2024 = th_seed$theme[th_seed$seed == 2024 & th_seed$slice == 3]),
  five_themes_present = list(frozen_2023_2025 = present(th_full), seed1234 = present(th_sens),
                             seed1 = present(th_seed[th_seed$seed == 1, ]), seed2024 = present(th_seed[th_seed$seed == 2024, ])),
  slices_1_2_nodes_identical_to_frozen = identical(th_sens$theme[th_sens$slice < 3], th_full$theme[th_full$slice < 3]) &&
    same_num(th_sens$freq[th_sens$slice < 3], th_full$freq[th_full$slice < 3]),
  frozen_files_sha256 = as.list(frozen_after),
  r_version = run$r_version, bibliometrix = run$bibliometrix,
  session_info = utils::capture.output(utils::sessionInfo()),
  finished = format(Sys.time(), "%Y-%m-%dT%H:%M:%S"), git_head = run$git_head)
jsonlite::write_json(summary, file.path(OUT, "summary.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA)
outs <- list.files(OUT, full.names = TRUE)
jsonlite::write_json(list(script = "code/05e_thematic_2025_sensitivity.R", started = run$started, git_head = run$git_head,
                          input = S5_INPUT, input_sha256 = run$input_sha256, records_2025_excluded = n_2025,
                          r_version = run$r_version, bibliometrix = run$bibliometrix, parameters = summary$parameters,
                          gates = gate, outputs = as.list(setNames(vapply(outs, s5_sha, character(1)), outs))),
                     file.path(OUT, "run_manifest.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA)
cat("  SENSITIVITY RUN : PASS\n")
