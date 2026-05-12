# =============================================================================
# Stage 5b — Figure F6: Thematic Map
# Input : data/processed/bibliometrix_input.csv
# Output: figures/F6_thematic_map.png
#         figures/F6_thematic_map_data.csv
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
  encoding        = "UTF-8",
  stringsAsFactors = FALSE,
  na.strings      = ""
)

cat(sprintf("  Loaded: %s rows x %s cols  (%.1f s)\n",
            format(nrow(M), big.mark = ","),
            ncol(M),
            (proc.time() - t0)["elapsed"]))

# ── 2. Add required bibliometrix fields manually ──────────────────────────────
cat("Adding bibliometrix metadata fields ...\n")

# SR: short reference used as row identifier
M$SR <- make.unique(
  paste(sub(";.*", "", M$AU), M$SO, M$PY, sep = ", "),
  sep = "_"
)
M$SR_FULL    <- M$SR
rownames(M)  <- M$SR
class(M)     <- c("bibliometrixDB", "data.frame")

# ── 3. Fix keyword separator: "; " → ";" ──────────────────────────────────────
cat("Normalising keyword separator ...\n")
M$DE <- gsub("; ", ";", M$DE, fixed = TRUE)
M$ID <- gsub("; ", ";", M$ID, fixed = TRUE)

# ── 4. Remove geographic terms from DE before thematic analysis ───────────────
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
  terms   <- trimws(strsplit(kw_cell, ";", fixed = TRUE)[[1]])
  terms   <- terms[nchar(terms) > 0]
  keep    <- terms[!tolower(terms) %in% GEO_TERMS]
  if (length(keep) == 0) return(NA_character_)
  paste(keep, collapse = ";")
}

M_thematic     <- M
M_thematic$DE  <- vapply(M$DE, remove_geo, character(1))

n_with_kw  <- sum(!is.na(M_thematic$DE))
all_kw     <- unlist(strsplit(
  paste(na.omit(M_thematic$DE), collapse = ";"), ";", fixed = TRUE
))
all_kw     <- trimws(all_kw[nchar(trimws(all_kw)) > 0])
n_unique   <- length(unique(tolower(all_kw)))

cat(sprintf("  Records with keywords after geo-filter : %s\n",
            format(n_with_kw, big.mark = ",")))
cat(sprintf("  Unique keywords available for clustering: %s\n",
            format(n_unique, big.mark = ",")))

# ── 5. Build thematic map ─────────────────────────────────────────────────────
cat("Building thematic map (n=250, minfreq=5) ...\n")

run_map <- function(mf) {
  thematicMap(
    M_thematic,
    field    = "DE",
    n        = 250,
    minfreq  = mf,
    stemming = FALSE,
    size     = 0.7,
    n.labels = 5,
    repel    = TRUE
  )
}

# Verify DE separator before clustering
sample_de <- head(M_thematic$DE[!is.na(M_thematic$DE)], 3)
cat("DE sample after processing:\n")
print(sample_de)

thematic_map <- tryCatch(
  run_map(5),
  error = function(e) {
    cat(sprintf("  thematicMap(minfreq=5) failed: %s\n", conditionMessage(e)))
    cat("  Retrying with minfreq=3 ...\n")
    tryCatch(
      run_map(3),
      error = function(e2) {
        cat(sprintf("  thematicMap(minfreq=3) also failed: %s\n",
                    conditionMessage(e2)))
        cat("DIAGNOSTIC: check that DE column is not all NA after geo-filter.\n")
        cat(sprintf("  NA count in DE: %s / %s\n",
                    sum(is.na(M_thematic$DE)), nrow(M_thematic)))
        stop("Thematic map could not be produced. See diagnostics above.")
      }
    )
  }
)

# ── 6. Save figure (png device — no watermark) ───────────────────────────────
cat("Saving figures/F6_thematic_map.png ...\n")
dir.create("figures", showWarnings = FALSE)

png("figures/F6_thematic_map.png",
    width  = 3000,
    height = 2400,
    res    = 300,
    bg     = "white")
plot(thematic_map$map)
dev.off()

png_size <- file.info("figures/F6_thematic_map.png")$size
cat(sprintf("  Saved: %.1f MB\n", png_size / 1048576))

# ── 7. Export cluster data ────────────────────────────────────────────────────
cat("Writing figures/F6_thematic_map_data.csv ...\n")

map_data <- thematic_map$map$data

# Standardise column names defensively
names(map_data) <- tolower(names(map_data))

wanted <- c("label", "rcentrality", "rdensity", "cluster", "freq",
            "centrality", "density", "words")
export_cols <- intersect(wanted, names(map_data))
if (length(export_cols) == 0) export_cols <- names(map_data)

write.csv(
  map_data[, export_cols, drop = FALSE],
  "figures/F6_thematic_map_data.csv",
  row.names = FALSE,
  fileEncoding = "UTF-8"
)
cat(sprintf("  Written: %s rows, columns: %s\n",
            nrow(map_data),
            paste(export_cols, collapse = ", ")))

# ── 8. Console report ─────────────────────────────────────────────────────────
cat("\n")
cat("=============================================================\n")
cat(" FIGURE F6 — THEMATIC MAP REPORT\n")
cat("=============================================================\n")
cat(sprintf("  Records with keywords (post geo-filter) : %s\n",
            format(n_with_kw, big.mark = ",")))
cat(sprintf("  Unique keywords for clustering          : %s\n",
            format(n_unique, big.mark = ",")))

clusters <- sort(unique(map_data$cluster))
cat(sprintf("  Clusters produced                       : %s\n",
            length(clusters)))
cat("\n")

for (cl in clusters) {
  rows  <- map_data[map_data$cluster == cl, ]
  # keyword column may be 'label' or 'words'
  kw_col <- if ("label" %in% names(rows)) "label" else names(rows)[1]
  kws   <- if (is.list(rows[[kw_col]])) {
    unlist(rows[[kw_col]])
  } else {
    as.character(rows[[kw_col]])
  }
  # determine quadrant from centrality/density if present
  quad <- ""
  if (all(c("rcentrality", "rdensity") %in% names(rows))) {
    rc <- mean(rows$rcentrality, na.rm = TRUE)
    rd <- mean(rows$rdensity,    na.rm = TRUE)
    quad <- if (rc >= 0 && rd >= 0) "(Motor Themes)" else
            if (rc <  0 && rd >= 0) "(Niche Themes)" else
            if (rc >= 0 && rd <  0) "(Basic Themes)" else
                                    "(Emerging or Declining)"
  }
  cat(sprintf("  Cluster %s %s — %s keywords:\n", cl, quad, length(kws)))
  for (k in kws) cat(sprintf("    %s\n", k))
  cat("\n")
}

cat(sprintf("  F6 PNG size : %.1f MB\n", png_size / 1048576))
cat("  F6 CSV      : figures/F6_thematic_map_data.csv\n")
cat(sprintf("  Total time  : %.1f s\n",
            (proc.time() - t0)["elapsed"]))
cat("=============================================================\n")
cat(" STAGE 5B COMPLETE\n")
cat("=============================================================\n")
