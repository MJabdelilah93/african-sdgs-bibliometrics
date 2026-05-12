# =============================================================================
# Stage 5d — Figure F8: Three-Field Plot (Countries → Keywords → Journals)
# Input : data/processed/bibliometrix_input.csv
#         data/interim/standardised.csv  (country join key)
# Output: figures/F8_three_field.html
#         figures/F8_three_field_static.png
# Run from: article08/
# NOTE: does NOT call metaTagExtraction() — avoids 338k-record hang
# =============================================================================

options(timeout = 300)   # global operation timeout guard

# ── 0. Packages ───────────────────────────────────────────────────────────────
for (pkg in c("bibliometrix", "ggplot2", "htmlwidgets", "data.table")) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    install.packages(pkg, repos = "https://cloud.r-project.org")
  }
}
library(bibliometrix)
library(ggplot2)
library(htmlwidgets)
library(data.table)

# ── 1. Load bibliometrix_input.csv ───────────────────────────────────────────
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
M$PY        <- suppressWarnings(as.integer(M$PY))

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

M$DE <- vapply(M$DE, remove_geo, character(1))

cat(sprintf("  Records with keywords after geo-filter: %s\n",
            format(sum(!is.na(M$DE)), big.mark = ",")))

# ── 5. Load country data from standardised.csv (two columns only) ─────────────
cat("Loading standardised_countries from standardised.csv ...\n")
t1 <- proc.time()

# Find actual column names first (header scan only)
hdr      <- fread("data/interim/standardised.csv", nrows = 0L)
all_cols <- names(hdr)

eid_col <- all_cols[grepl("^eid$", all_cols, ignore.case = TRUE)][1]
cc_col  <- all_cols[grepl("standardised_countries", all_cols,
                           ignore.case = TRUE)][1]

if (is.na(eid_col) || is.na(cc_col)) {
  cat(sprintf("  Available columns: %s\n",
              paste(head(all_cols, 30), collapse = ", ")))
  stop(sprintf("Could not find required columns. EID='%s', countries='%s'",
               eid_col, cc_col))
}

cat(sprintf("  Using columns: '%s' and '%s'\n", eid_col, cc_col))

country_data <- fread(
  "data/interim/standardised.csv",
  select       = c(eid_col, cc_col),
  showProgress = TRUE,
  encoding     = "UTF-8"
)
setnames(country_data, c(eid_col, cc_col), c("EID", "countries_raw"))

cat(sprintf("  Loaded %s rows  (%.1f s)\n",
            format(nrow(country_data), big.mark = ","),
            (proc.time() - t1)["elapsed"]))

# ── 6. ISO-2 → full country name lookup ──────────────────────────────────────
ISO2_NAMES <- c(
  ZA = "South Africa",    NG = "Nigeria",         EG = "Egypt",
  ET = "Ethiopia",        GH = "Ghana",            KE = "Kenya",
  UG = "Uganda",          TZ = "Tanzania",         TN = "Tunisia",
  MA = "Morocco",         CM = "Cameroon",         SN = "Senegal",
  ZW = "Zimbabwe",        ZM = "Zambia",           RW = "Rwanda",
  MW = "Malawi",          BW = "Botswana",         MZ = "Mozambique",
  DZ = "Algeria",         SD = "Sudan",            ML = "Mali",
  BF = "Burkina Faso",    BJ = "Benin",            TG = "Togo",
  GN = "Guinea",          AO = "Angola",           NE = "Niger",
  SL = "Sierra Leone",    LR = "Liberia",          SO = "Somalia",
  ER = "Eritrea",         BI = "Burundi",          CI = "Cote d'Ivoire",
  MG = "Madagascar",      CD = "Dem. Rep. Congo",  CG = "Congo",
  GA = "Gabon",           CF = "Central African Republic",
  TD = "Chad",            DJ = "Djibouti",         KM = "Comoros",
  MU = "Mauritius",       SC = "Seychelles",       GM = "Gambia",
  CV = "Cabo Verde",      GQ = "Equatorial Guinea",SS = "South Sudan",
  LY = "Libya",           LS = "Lesotho",          SZ = "Eswatini",
  ST = "Sao Tome and Principe"
)

expand_iso2 <- function(cell) {
  if (is.na(cell) || nchar(trimws(cell)) == 0) return(NA_character_)
  codes <- trimws(strsplit(cell, ";", fixed = TRUE)[[1]])
  codes <- codes[nchar(codes) > 0]
  names_out <- ISO2_NAMES[codes]
  names_out <- names_out[!is.na(names_out)]
  if (length(names_out) == 0) return(NA_character_)
  paste(unique(names_out), collapse = ";")
}

cat("Converting ISO-2 codes to country names ...\n")
country_data[, AU_CO := vapply(countries_raw, expand_iso2, character(1))]

# ── 7. Join AU_CO into M via EID/UT ──────────────────────────────────────────
cat("Joining country data into M ...\n")

co_map <- setNames(country_data$AU_CO, country_data$EID)
M$AU_CO <- co_map[M$UT]

n_with_co <- sum(!is.na(M$AU_CO) & nchar(trimws(M$AU_CO)) > 0)
cat(sprintf("  Records with AU_CO after join: %s / %s (%.1f%%)\n",
            format(n_with_co, big.mark = ","),
            format(nrow(M), big.mark = ","),
            100 * n_with_co / nrow(M)))

# Top 15 countries (for report — before threeFieldsPlot)
all_countries <- unlist(strsplit(
  paste(na.omit(M$AU_CO), collapse = ";"), ";", fixed = TRUE
))
all_countries <- trimws(all_countries[nchar(trimws(all_countries)) > 0])
top_countries <- sort(table(all_countries), decreasing = TRUE)[1:15]

# ── 8. Build three-field plot ─────────────────────────────────────────────────
cat("Building three-field plot ...\n")

three_field <- tryCatch({
  threeFieldsPlot(
    M,
    fields = c("AU_CO", "DE", "SO"),
    n      = c(15L, 15L, 15L),
    sep    = ";"
  )
}, error = function(e) {
  cat(sprintf("  threeFieldsPlot with sep= failed (%s); retrying without sep.\n",
              conditionMessage(e)))
  threeFieldsPlot(
    M,
    fields = c("AU_CO", "DE", "SO"),
    n      = c(15L, 15L, 15L)
  )
})

cat("  Three-field plot built.\n")

# ── 9. Save interactive HTML ──────────────────────────────────────────────────
cat("Saving figures/F8_three_field.html ...\n")
dir.create("figures", showWarnings = FALSE)

output_html <- file.path("figures", "F8_three_field.html")

saveWidget(
  widget        = three_field,
  file          = normalizePath(output_html, mustWork = FALSE),
  selfcontained = TRUE
)

html_size <- file.info(output_html)$size
cat(sprintf("  Saved: %.1f MB\n", html_size / 1048576))

# ── 10. Static PNG — webshot2 first, png() fallback ──────────────────────────
cat("Saving figures/F8_three_field_static.png ...\n")

png_path      <- "figures/F8_three_field_static.png"
static_method <- "none"

if (!requireNamespace("webshot2", quietly = TRUE)) {
  tryCatch(
    install.packages("webshot2", repos = "https://cloud.r-project.org"),
    error = function(e) invisible(NULL)
  )
}

if (requireNamespace("webshot2", quietly = TRUE)) {
  webshot_ok <- tryCatch({
    webshot2::webshot(
      url     = normalizePath(output_html, mustWork = FALSE),
      file    = png_path,
      vwidth  = 1400L,
      vheight = 900L,
      zoom    = 2L
    )
    file.exists(png_path) && file.info(png_path)$size > 10000L
  }, error = function(e) {
    cat(sprintf("  webshot2 error: %s\n", conditionMessage(e)))
    FALSE
  })

  if (isTRUE(webshot_ok)) {
    static_method <- "webshot2"
    cat("  webshot2 succeeded.\n")
  } else {
    cat("  webshot2 produced empty file — falling back to png() device.\n")
  }
}

if (static_method == "none") {
  tryCatch({
    png(png_path, width = 4200L, height = 2700L, res = 300L, bg = "white")
    print(three_field)
    dev.off()
    static_method <- "png() device fallback"
    cat("  png() device fallback succeeded.\n")
  }, error = function(e) {
    if (dev.cur() > 1L) dev.off()
    cat(sprintf("  png() device also failed: %s\n", conditionMessage(e)))
    static_method <<- "FAILED"
  })
}

png_size <- if (file.exists(png_path)) file.info(png_path)$size else 0L

# ── 11. Console report ────────────────────────────────────────────────────────
cat("\n")
cat("=============================================================\n")
cat(" FIGURE F8 — THREE-FIELD PLOT REPORT\n")
cat("=============================================================\n")

cat(sprintf("  Records with AU_CO data     : %s / %s\n",
            format(n_with_co, big.mark = ","),
            format(nrow(M),   big.mark = ",")))
cat("\n")

cat("  Top 15 countries (AU_CO):\n")
for (i in seq_along(top_countries)) {
  cat(sprintf("    %2d. %-35s %s\n",
              i, names(top_countries)[i],
              format(as.integer(top_countries[i]), big.mark = ",")))
}
cat("\n")

# Top 15 keywords
all_kw <- unlist(strsplit(
  paste(na.omit(M$DE), collapse = ";"), ";", fixed = TRUE
))
all_kw  <- trimws(all_kw[nchar(trimws(all_kw)) > 0])
top_kw  <- sort(table(all_kw), decreasing = TRUE)[1:15]
cat("  Top 15 keywords (DE after geo-filter):\n")
for (i in seq_along(top_kw)) {
  cat(sprintf("    %2d. %-45s %s\n",
              i, names(top_kw)[i],
              format(as.integer(top_kw[i]), big.mark = ",")))
}
cat("\n")

# Top 15 journals
all_so  <- trimws(M$SO[!is.na(M$SO) & nchar(trimws(M$SO)) > 0])
top_so  <- sort(table(all_so), decreasing = TRUE)[1:15]
cat("  Top 15 journals (SO):\n")
for (i in seq_along(top_so)) {
  cat(sprintf("    %2d. %-55s %s\n",
              i, substr(names(top_so)[i], 1, 55),
              format(as.integer(top_so[i]), big.mark = ",")))
}
cat("\n")

cat(sprintf("  Static PNG method           : %s\n", static_method))
cat(sprintf("  HTML size                   : %.1f MB\n", html_size / 1048576))
cat(sprintf("  PNG size                    : %.1f MB\n", png_size / 1048576))
cat("  HTML output                 : figures/F8_three_field.html\n")
cat("  PNG output                  : figures/F8_three_field_static.png\n")
cat(sprintf("  Total time                  : %.1f s\n",
            (proc.time() - t0)["elapsed"]))
cat("=============================================================\n")
cat(" STAGE 5D COMPLETE\n")
cat("=============================================================\n")
