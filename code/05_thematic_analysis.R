# ============================================================
# Article 8 — Stage 5b: Thematic Analysis
# Produces: F6 (thematic map), F7 (thematic evolution),
#           F8 (three-field plot)
# Run from: RStudio with working directory set to article08/
# ============================================================

# SETUP — install packages if needed (run once)
# install.packages(c("bibliometrix", "ggplot2", "htmlwidgets"))

library(bibliometrix)
library(ggplot2)

# Set working directory to your project root
# Replace the path with your actual article08/ folder path
setwd("C:/Users/AbdelilahElMajjaoui/Downloads/PhD/Article 8/african_sdgs/article08")   # Windows example
# setwd("~/article08")          # Mac/Linux example

# ── LOAD DATA ──────────────────────────────────────────────
cat("Loading bibliometrix_input.csv...\n")
cat("This may take 2-3 minutes for a 338k-record corpus.\n\n")

cat("Loading bibliometrix_input.csv directly...\n")
M <- read.csv(
  "data/processed/bibliometrix_input.csv",
  encoding = "UTF-8",
  stringsAsFactors = FALSE
)

# Add bibliometrix class so all functions work correctly
class(M) <- c("bibliometrixDB", "data.frame")

# Create unique SR field required by bibliometrix functions
M$SR <- paste(
  sub(";.*", "", M$AU),
  M$SO,
  M$PY,
  sep = ", "
)

# Make SR unique by appending UT where duplicates exist
dupes <- duplicated(M$SR) | duplicated(M$SR, fromLast = TRUE)
M$SR[dupes] <- paste(M$SR[dupes], M$UT[dupes], sep = "_")

# Final check — if still duplicates, force unique
if (any(duplicated(M$SR))) {
  M$SR <- make.unique(M$SR, sep = "_")
}

M$SR_FULL <- M$SR
rownames(M) <- M$SR


cat("Records with author keywords:", sum(M$DE != "" & !is.na(M$DE)), "\n")
cat("Sample DE value:", M$DE[which(M$DE != "" & !is.na(M$DE))[1]], "\n")


cat("Records loaded:", nrow(M), "\n")
cat("Expected:       338409\n\n")


if (nrow(M) != 338409) {
  warning("Row count mismatch — check the CSV before proceeding.")
}

# ── QUICK SANITY CHECK ──────────────────────────────────────
cat("\n── SANITY CHECK ──\n")
cat("Total documents:", nrow(M), "\n")
cat("Total citations:", sum(as.numeric(M$TC), na.rm = TRUE), "\n")
cat("Years covered:  ", min(as.numeric(M$PY), na.rm = TRUE),
    "-", max(as.numeric(M$PY), na.rm = TRUE), "\n\n")

# ── FIGURE F6 — THEMATIC MAP (SINGLE PERIOD) ────────────────
cat("Generating F6 — thematic map...\n")

# Filter geographic terms from keywords before thematic analysis
geographic_terms <- c(
  "africa", "sub-saharan africa", "south africa", "nigeria", "ethiopia",
  "kenya", "ghana", "uganda", "tanzania", "egypt", "morocco", "algeria",
  "tunisia", "cameroon", "senegal", "zimbabwe", "zambia", "rwanda",
  "malawi", "mozambique", "botswana", "namibia", "sudan", "mali",
  "burkina faso", "benin", "togo", "guinea", "angola", "niger",
  "sierra leone", "liberia", "somalia", "eritrea", "burundi",
  "cote d'ivoire", "madagascar", "democratic republic of congo",
  "congo", "gabon", "central african republic", "chad", "djibouti",
  "comoros", "mauritius", "seychelles", "gambia", "cabo verde",
  "equatorial guinea", "south sudan", "libya", "lesotho", "eswatini",
  "developing country", "developing countries", "low income country",
  "middle income country", "low-income country", "middle-income country",
  "west africa", "east africa", "north africa", "central africa",
  "southern africa", "sub saharan africa"
)

# Apply geographic filter to DE column
M_thematic <- M
M_thematic$DE <- sapply(M_thematic$DE, function(kw) {
  if (is.na(kw) || kw == "") return(kw)
  terms <- strsplit(kw, "; ")[[1]]
  terms_filtered <- terms[!tolower(trimws(terms)) %in% geographic_terms]
  if (length(terms_filtered) == 0) return(NA)
  paste(terms_filtered, collapse = "; ")
})

cat("Records with keywords after geographic filter:",
    sum(!is.na(M_thematic$DE) & M_thematic$DE != ""), "\n")

# Run thematic map with higher frequency threshold
thematic_map <- thematicMap(
  M_thematic,
  field    = "DE",
  n        = 500,
  minfreq  = 15,
  stemming = FALSE,
  size     = 0.7,
  n.labels = 5,
  repel    = TRUE
)

# Save using png() device to avoid watermark issues
png("figures/F6_thematic_map.png",
    width = 3000, height = 2400, res = 300)
plot(thematic_map$map)
dev.off()

cat("F6 saved: figures/F6_thematic_map.png\n\n")

cat("F6 saved: figures/F6_thematic_map.png + .svg\n\n")

# ── FIGURE F7 — THEMATIC EVOLUTION (3 TIME SLICES) ──────────
cat("Generating F7 — thematic evolution map...\n")
cat("Time slices: 2015-2018 | 2019-2022 | 2023-2025\n")

thematic_evol <- thematicEvolution(
  M,
  field    = "DE",
  years    = c(2018, 2022),  # cut points; creates 3 slices
  n        = 250,
  minFreq  = 10,
  size     = 0.5,
  stemming = FALSE,
  n.labels = 5,
  repel    = TRUE
)

# Save F7 using png device (alluvial diagram does not work with ggsave)
png("figures/F7_thematic_evolution.png",
    width = 4200, height = 2400, res = 300)
plot(thematic_evol$alluvial_diagram)
dev.off()

cat("F7 saved: figures/F7_thematic_evolution.png\n\n")

cat("F7 saved: figures/F7_thematic_evolution.png + .svg\n\n")

# ── FIGURE F8 — THREE-FIELD PLOT ────────────────────────────
cat("Generating F8 — three-field plot...\n")
cat("Fields: Countries → Author Keywords → Journals\n")

# htmlwidgets is needed for saveWidget
if (!requireNamespace("htmlwidgets", quietly = TRUE)) {
  install.packages("htmlwidgets")
}
library(htmlwidgets)

three_field <- threeFieldsPlot(
  M,
  fields = c("AU_CO", "DE", "SO"),
  n      = c(20, 20, 20)
)

saveWidget(
  widget = three_field,
  file   = normalizePath("figures/F8_three_field.html",
                          mustWork = FALSE),
  selfcontained = TRUE
)

cat("F8 saved: figures/F8_three_field.html\n")
cat("Open this file in a browser to view the interactive plot.\n\n")

# ── SAVE BIBLIOMETRIX OBJECT ────────────────────────────────
cat("Saving M object for future sessions...\n")
saveRDS(M,       "data/processed/bibliometrix_M.rds")
saveRDS(results, "data/processed/bibliometrix_results.rds")

# ── SAVE R SESSION INFO FOR PROVENANCE ──────────────────────
sink("provenance/stage5_r_session.txt")
cat("Article 8 — Stage 5b Thematic Analysis\n")
cat("Run date:", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "\n\n")
sessionInfo()
sink()

cat("R session info saved: provenance/stage5_r_session.txt\n\n")

# ── COMPLETION SUMMARY ──────────────────────────────────────
cat("══════════════════════════════════════════\n")
cat("Stage 5b complete.\n")
cat("Files saved:\n")
cat("  figures/F6_thematic_map.png\n")
cat("  figures/F6_thematic_map.svg\n")
cat("  figures/F7_thematic_evolution.png\n")
cat("  figures/F7_thematic_evolution.svg\n")
cat("  figures/F8_three_field.html\n")
cat("  data/processed/bibliometrix_M.rds\n")
cat("  data/processed/bibliometrix_results.rds\n")
cat("  provenance/stage5_r_session.txt\n")
cat("══════════════════════════════════════════\n")
cat("Next step: run VOSviewer for F9, F10, F11\n")