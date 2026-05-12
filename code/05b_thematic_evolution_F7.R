# =============================================================================
# Stage 5c — Figure F7: Thematic Evolution Map
# Input : data/processed/bibliometrix_input.csv
# Output: figures/F7_thematic_evolution.png
#         figures/F7_thematic_evolution_data.csv
# Run from: article08/
# =============================================================================

# ── 0. Packages ───────────────────────────────────────────────────────────────
for (pkg in c("bibliometrix", "ggplot2", "svglite")) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    install.packages(pkg, repos = "https://cloud.r-project.org")
  }
}
library(bibliometrix)
library(ggplot2)

# ── 1. Load CSV (do NOT use convert2df) ──────────────────────────────────────
cat("Loading bibliometrix_input.csv ...\n")
t0 <- proc.time()

M <- read.csv(
  "data/processed/bibliometrix_input.csv",
  encoding         = "UTF-8",
  stringsAsFactors = FALSE,
  na.strings       = ""
)

cat(sprintf("  Loaded: %s rows x %s cols  (%.1f s)\n",
            format(nrow(M), big.mark = ","),
            ncol(M),
            (proc.time() - t0)["elapsed"]))

# ── 2. Add required bibliometrix fields manually ──────────────────────────────
cat("Adding bibliometrix metadata fields ...\n")

M$SR <- make.unique(
  paste(sub(";.*", "", M$AU), M$SO, M$PY, sep = ", "),
  sep = "_"
)
M$SR_FULL   <- M$SR
rownames(M) <- M$SR
class(M)    <- c("bibliometrixDB", "data.frame")

# Ensure PY is numeric for slice filtering
M$PY <- suppressWarnings(as.integer(M$PY))

# ── 3. Fix keyword separator: "; " → ";" ──────────────────────────────────────
cat("Normalising keyword separator ...\n")
M$DE <- gsub("; ", ";", M$DE, fixed = TRUE)
M$ID <- gsub("; ", ";", M$ID, fixed = TRUE)

# ── 4. Remove geographic terms from DE ───────────────────────────────────────
cat("Removing geographic terms from DE ...\n")

GEO_TERMS <- tolower(c(
  "africa", "sub-saharan africa", "south africa", "nigeria", "ethiopia",
  "kenya", "ghana", "uganda", "tanzania", "egypt", "morocco", "algeria",
  "tunisia", "cameroon", "senegal", "zimbabwe", "zambia", "rwanda",
  "malawi", "mozambique", "botswana", "namibia", "sudan", "mali",
  "burkina faso", "benin", "togo", "guinea", "angola", "niger",
  "sierra leone", "liberia", "somalia", "eritrea", "burundi",
  "cote d'ivoire", "madagascar", "democratic republic of congo", "congo",
  "gabon", "central african republic", "chad", "djibouti", "comoros",
  "mauritius", "seychelles", "gambia", "cabo verde", "equatorial guinea",
  "south sudan", "libya", "lesotho", "eswatini",
  "developing country", "developing countries",
  "low income country", "middle income country",
  "low-income country", "middle-income country",
  "west africa", "east africa", "north africa", "central africa",
  "southern africa", "sub saharan africa",
  "developed country", "developed countries"
))

remove_geo <- function(kw_cell) {
  if (is.na(kw_cell) || nchar(trimws(kw_cell)) == 0) return(NA_character_)
  terms <- trimws(strsplit(kw_cell, ";", fixed = TRUE)[[1]])
  terms <- terms[nchar(terms) > 0]
  keep  <- terms[!tolower(terms) %in% GEO_TERMS]
  if (length(keep) == 0) return(NA_character_)
  paste(keep, collapse = ";")
}

M_thematic    <- M
M_thematic$DE <- vapply(M$DE, remove_geo, character(1))

# ── 5. Verify time slices ─────────────────────────────────────────────────────
cat("\n--- Time slice diagnostics ---\n")

slice_defs <- list(
  s1 = list(label = "2015-2018", lo = 2015L, hi = 2018L),
  s2 = list(label = "2019-2022", lo = 2019L, hi = 2022L),
  s3 = list(label = "2023-2025", lo = 2023L, hi = 2025L)
)

slice_ok <- TRUE
for (s in slice_defs) {
  rows    <- M_thematic[!is.na(M_thematic$PY) &
                        M_thematic$PY >= s$lo &
                        M_thematic$PY <= s$hi, ]
  n_total <- nrow(rows)
  n_kw    <- sum(!is.na(rows$DE))
  warn    <- if (n_kw < 1000) " <-- WARNING: fewer than 1000 records with keywords" else ""
  cat(sprintf("  Slice %s : %s total records, %s with keywords%s\n",
              s$label,
              format(n_total, big.mark = ","),
              format(n_kw,    big.mark = ","),
              warn))
  if (n_kw < 1000) slice_ok <- FALSE
}
cat("\n")

# ── 6. Build thematic evolution map ──────────────────────────────────────────
cat("Building thematic evolution map ...\n")

fallback_used <- "none"

run_evol <- function(yr_breaks, mf) {
  thematicEvolution(
    M_thematic,
    field    = "DE",
    years    = yr_breaks,
    n        = 250,
    minFreq  = mf,
    size     = 0.5,
    stemming = FALSE,
    n.labels = 3,
    repel    = TRUE
  )
}

# Verify DE separator before clustering
sample_de <- head(M_thematic$DE[!is.na(M_thematic$DE)], 3)
cat("DE sample after processing:\n")
print(sample_de)

thematic_evol <- tryCatch({
  cat("  Attempt 1: years=c(2018,2022), minFreq=5 ...\n")
  run_evol(c(2018L, 2022L), 5L)
}, error = function(e) {
  cat(sprintf("  Attempt 1 failed: %s\n", conditionMessage(e)))
  cat("  Attempt 2: years=c(2018,2022), minFreq=3 ...\n")
  tryCatch({
    result <- run_evol(c(2018L, 2022L), 3L)
    fallback_used <<- "minFreq=3 (3-slice)"
    result
  }, error = function(e2) {
    cat(sprintf("  Attempt 2 failed: %s\n", conditionMessage(e2)))
    cat("  Attempt 3: years=c(2020), 2 slices, minFreq=3 ...\n")
    tryCatch({
      result <- run_evol(c(2020L), 3L)
      fallback_used <<- "years=c(2020), minFreq=3 (2-slice fallback)"
      result
    }, error = function(e3) {
      cat(sprintf("  Attempt 3 failed: %s\n", conditionMessage(e3)))
      cat("\nDIAGNOSTIC — DE column summary:\n")
      cat(sprintf("  NA count in DE : %s / %s\n",
                  sum(is.na(M_thematic$DE)), nrow(M_thematic)))
      cat(sprintf("  PY range       : %s – %s\n",
                  min(M_thematic$PY, na.rm = TRUE),
                  max(M_thematic$PY, na.rm = TRUE)))
      cat("  First 10 DE values (non-NA):\n")
      print(head(na.omit(M_thematic$DE), 10))
      stop("thematicEvolution failed on all three attempts. See diagnostics above.")
    })
  })
})

if (fallback_used == "none") {
  cat("  Succeeded with primary parameters.\n")
} else {
  cat(sprintf("  Succeeded with fallback: %s\n", fallback_used))
}

# ── 7. Install ggalluvial ─────────────────────────────────────────────────────
if (!requireNamespace("ggalluvial", quietly = TRUE)) {
  install.packages("ggalluvial", repos = "https://cloud.r-project.org")
}
library(ggalluvial)

# ── 8. Build alluvial diagram manually from Nodes + Edges ────────────────────
cat("\nBuilding alluvial diagram from thematic_evol$Nodes and $Edges ...\n")

nodes_df <- thematic_evol$Nodes
edges_df  <- thematic_evol$Edges

SLICE_LABELS <- c("1" = "2015–2018", "2" = "2019–2022", "3" = "2023–2025")

nodes_df$period <- SLICE_LABELS[as.character(nodes_df$slice)]

cat(sprintf("  Nodes: %s rows, slices: %s\n",
            nrow(nodes_df), paste(sort(unique(nodes_df$slice)), collapse = ", ")))
cat(sprintf("  Edges: %s rows\n", nrow(edges_df)))

plot_method <- "none"
p           <- NULL

# ── Approach A: ggalluvial Sankey ─────────────────────────────────────────────
p <- tryCatch({
  # Keep only edges with positive flow that cross time slices
  flows <- edges_df[edges_df$Inc_Weighted > 0, ]

  # Attach period labels for from/to nodes
  from_info <- nodes_df[, c("name", "label", "slice", "period", "group")]
  names(from_info) <- c("from", "from_label", "from_slice", "from_period", "from_group")
  to_info   <- nodes_df[, c("name", "label", "slice", "period")]
  names(to_info) <- c("to", "to_label", "to_slice", "to_period")

  flows <- merge(flows, from_info, by = "from", all.x = TRUE)
  flows <- merge(flows, to_info,   by = "to",   all.x = TRUE)
  flows <- flows[!is.na(flows$from_period) & !is.na(flows$to_period), ]

  if (nrow(flows) == 0) stop("No cross-slice edges with positive weight found.")

  # Build long format: one row per flow, two time points each
  mk_long <- function(flows) {
    rbind(
      data.frame(
        alluvium = seq_len(nrow(flows)),
        period   = flows$from_period,
        theme    = flows$from_label,
        weight   = flows$Inc_Weighted,
        group    = as.character(flows$from_group),
        stringsAsFactors = FALSE
      ),
      data.frame(
        alluvium = seq_len(nrow(flows)),
        period   = flows$to_period,
        theme    = flows$to_label,
        weight   = flows$Inc_Weighted,
        group    = as.character(flows$from_group),
        stringsAsFactors = FALSE
      )
    )
  }
  long_df <- mk_long(flows)
  long_df$period <- factor(long_df$period,
                           levels = unname(SLICE_LABELS))

  ggplot(long_df,
         aes(x        = period,
             stratum  = theme,
             alluvium = alluvium,
             y        = weight,
             fill     = theme,
             label    = theme)) +
    geom_alluvium(alpha = 0.55, width = 1/4) +
    geom_stratum(alpha = 0.80, width = 1/4, colour = "grey30", size = 0.3) +
    geom_text(stat = "stratum", size = 2.6, fontface = "bold") +
    scale_x_discrete(limits = unname(SLICE_LABELS)) +
    scale_fill_manual(
      values = setNames(
        scales::hue_pal()(length(unique(long_df$theme))),
        unique(long_df$theme)
      )
    ) +
    theme_minimal(base_size = 12) +
    theme(legend.position = "none",
          panel.grid      = element_blank(),
          axis.text.y     = element_blank(),
          axis.ticks.y    = element_blank()) +
    labs(x = NULL, y = "Keyword frequency weight")
}, error = function(e) {
  cat(sprintf("  ggalluvial approach failed: %s\n", conditionMessage(e)))
  NULL
})

if (!is.null(p)) {
  plot_method <- "ggalluvial Sankey (Approach A)"
  cat(sprintf("  %s\n", plot_method))
}

# ── Approach B: bubble chart fallback ────────────────────────────────────────
if (is.null(p)) {
  cat("  Falling back to bubble chart (Approach B) ...\n")
  p <- tryCatch({
    bdf <- nodes_df
    # Issue 1 — strip "--YYYY-YYYY" period suffix from labels
    bdf$label  <- trimws(gsub("--\\d{4}-\\d{4}$", "", bdf$label))
    bdf$period <- factor(bdf$period, levels = unname(SLICE_LABELS))
    # Issue 2 — dynamic title using actual year range (cap 2025)
    yr_min     <- min(as.numeric(M$PY), na.rm = TRUE)
    yr_max     <- 2025L
    plot_title <- paste0("Thematic evolution ", yr_min, "–", yr_max)
    ggplot(bdf,
           aes(x      = period,
               y      = factor(seq_along(label)),   # Issue 4
               size   = freq,
               colour = factor(group))) +
      geom_point(alpha = 0.70) +
      geom_text(aes(label = label), hjust = -0.15, size = 2.8) +
      scale_size_continuous(range = c(3, 14)) +
      theme_minimal(base_size = 12) +
      theme(legend.position  = "none",
            panel.grid.major.x = element_blank(),
            axis.text.y      = element_blank(),     # Issue 3
            axis.ticks.y     = element_blank()) +   # Issue 3
      labs(x = NULL, y = NULL, title = plot_title)
  }, error = function(e) {
    cat(sprintf("  Bubble chart also failed: %s\n", conditionMessage(e)))
    NULL
  })

  if (!is.null(p)) {
    plot_method <- "bubble chart (Approach B fallback)"
    cat(sprintf("  %s\n", plot_method))
  }
}

if (is.null(p)) stop("Both plot approaches failed. Check Nodes/Edges structure.")

# ── 9. Save figure ────────────────────────────────────────────────────────────
cat("Saving figures/F7_thematic_evolution.png ...\n")
dir.create("figures", showWarnings = FALSE)

png("figures/F7_thematic_evolution.png",
    width  = 4200,
    height = 2400,
    res    = 300,
    bg     = "white")
print(p)
dev.off()

png_size <- file.info("figures/F7_thematic_evolution.png")$size
cat(sprintf("  Saved: %.1f MB\n", png_size / 1048576))

# ── 10a. Export Nodes and Edges CSVs ──────────────────────────────────────────
cat("Writing figures/F7_nodes_data.csv and F7_edges_data.csv ...\n")

write.csv(nodes_df, "figures/F7_nodes_data.csv",
          row.names = FALSE, fileEncoding = "UTF-8")
write.csv(edges_df, "figures/F7_edges_data.csv",
          row.names = FALSE, fileEncoding = "UTF-8")

cat(sprintf("  Nodes: %s rows x %s cols\n", nrow(nodes_df), ncol(nodes_df)))
cat(sprintf("  Edges: %s rows x %s cols\n", nrow(edges_df), ncol(edges_df)))

# ── 11. Console report ───────────────────────────────────────────────────────
cat("\n")
cat("=============================================================\n")
cat(" FIGURE F7 — THEMATIC EVOLUTION REPORT\n")
cat("=============================================================\n")

# Records per slice (from corpus)
cat("  Records per time slice (with keywords):\n")
for (s in slice_defs) {
  rows <- M_thematic[!is.na(M_thematic$PY) &
                     M_thematic$PY >= s$lo &
                     M_thematic$PY <= s$hi, ]
  n_kw <- sum(!is.na(rows$DE))
  cat(sprintf("    %s : %s\n", s$label, format(n_kw, big.mark = ",")))
}
cat("\n")

# Themes per slice from Nodes dataframe
for (sl in sort(unique(nodes_df$slice))) {
  sl_themes <- nodes_df$label[nodes_df$slice == sl]
  sl_label  <- SLICE_LABELS[as.character(sl)]
  cat(sprintf("  Themes in slice %s — %s (%s themes):\n",
              sl, sl_label, length(sl_themes)))
  for (th in sl_themes) cat(sprintf("    %s\n", th))
  cat("\n")
}

# Persistence and emergence
themes_by_slice <- lapply(sort(unique(nodes_df$slice)), function(sl) {
  nodes_df$label[nodes_df$slice == sl]
})
n_slices <- length(themes_by_slice)

if (n_slices >= 2) {
  persistent <- Reduce(intersect, themes_by_slice)
  cat(sprintf("  Themes persisting across all %s slices (%s):\n",
              n_slices, length(persistent)))
  for (th in persistent) cat(sprintf("    %s\n", th))
  cat("\n")

  if (n_slices == 3) {
    emerging    <- setdiff(themes_by_slice[[3]], themes_by_slice[[1]])
    disappearing <- setdiff(themes_by_slice[[1]], themes_by_slice[[3]])
    cat(sprintf("  Emerging themes (new in 2023–2025, %s):\n", length(emerging)))
    for (th in emerging) cat(sprintf("    %s\n", th))
    cat(sprintf("  Disappearing themes (gone by 2023–2025, %s):\n",
                length(disappearing)))
    for (th in disappearing) cat(sprintf("    %s\n", th))
    cat("\n")
  }
}

cat(sprintf("  Plot method              : %s\n", plot_method))
cat(sprintf("  thematicEvolution params : %s\n", fallback_used))
cat(sprintf("  F7 PNG size              : %.1f MB\n", png_size / 1048576))
cat("  F7 Nodes CSV             : figures/F7_nodes_data.csv\n")
cat("  F7 Edges CSV             : figures/F7_edges_data.csv\n")
cat(sprintf("  Total time               : %.1f s\n",
            (proc.time() - t0)["elapsed"]))
cat("=============================================================\n")
cat(" STAGE 5C COMPLETE\n")
cat("=============================================================\n")
