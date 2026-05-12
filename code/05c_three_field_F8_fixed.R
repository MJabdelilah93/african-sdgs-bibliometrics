# =============================================================================
# Stage 5c — Figure F8: Three-Field Plot (Countries → Keywords → Journals)
# Input : data/processed/bibliometrix_M.rds
#         data/interim/standardised.csv  (EID + match_countries)
# Output: figures/F8_three_field.html
#         figures/F8_three_field_static.png
# Run from: article08/
# =============================================================================

t0 <- proc.time()

# ── 0. Packages ───────────────────────────────────────────────────────────────
for (pkg in c("bibliometrix", "htmlwidgets", "data.table")) {
  if (!requireNamespace(pkg, quietly = TRUE))
    install.packages(pkg, repos = "https://cloud.r-project.org")
}
library(bibliometrix)
library(htmlwidgets)
library(data.table)

# ── 1. Load M ─────────────────────────────────────────────────────────────────
cat("Loading bibliometrix_M.rds ...\n")
M <- readRDS("data/processed/bibliometrix_M.rds")
cat(sprintf("  Loaded: %s rows x %s cols\n",
            format(nrow(M), big.mark = ","), ncol(M)))

# Confirm required columns
stopifnot("UT" %in% names(M), "DE" %in% names(M), "SO" %in% names(M))

# ── 2. Load country data from standardised.csv ────────────────────────────────
cat("Loading standardised.csv (header scan) ...\n")
hdr     <- fread("data/interim/standardised.csv", nrows = 0L)
all_cols <- names(hdr)

eid_col <- all_cols[grepl("^eid$", all_cols, ignore.case = TRUE)][1]
cc_col  <- all_cols[grepl("match_countries", all_cols, ignore.case = TRUE)][1]

if (is.na(eid_col) || is.na(cc_col)) {
  cat(sprintf("  Available columns: %s\n",
              paste(head(all_cols, 30), collapse = ", ")))
  stop(sprintf("Cannot find required columns. EID='%s', countries='%s'",
               eid_col, cc_col))
}
cat(sprintf("  Using: EID='%s'  countries='%s'\n", eid_col, cc_col))

cat("Loading EID + match_countries ...\n")
t1 <- proc.time()
country_data <- fread(
  "data/interim/standardised.csv",
  select       = c(eid_col, cc_col),
  showProgress = FALSE,
  encoding     = "UTF-8"
)
setnames(country_data, c(eid_col, cc_col), c("EID", "countries_raw"))
cat(sprintf("  Loaded %s rows  (%.1f s)\n",
            format(nrow(country_data), big.mark = ","),
            (proc.time() - t1)["elapsed"]))

# ── 3. ISO-2 → full country name lookup ──────────────────────────────────────
ISO2 <- c(
  ZA = "South Africa",  NG = "Nigeria",    EG = "Egypt",
  ET = "Ethiopia",      GH = "Ghana",      KE = "Kenya",
  UG = "Uganda",        TZ = "Tanzania",   TN = "Tunisia",
  MA = "Morocco",       CM = "Cameroon",   SN = "Senegal",
  ZW = "Zimbabwe",      ZM = "Zambia",     RW = "Rwanda",
  MW = "Malawi",        BW = "Botswana",   MZ = "Mozambique",
  DZ = "Algeria",       SD = "Sudan",      ML = "Mali",
  BF = "Burkina Faso",  BJ = "Benin",      TG = "Togo",
  GN = "Guinea",        AO = "Angola",     NE = "Niger",
  SL = "Sierra Leone",  LR = "Liberia",    SO = "Somalia",
  ER = "Eritrea",       BI = "Burundi",    CI = "Cote d'Ivoire",
  MG = "Madagascar",    CD = "DR Congo",   CG = "Congo",
  GA = "Gabon",         CF = "Cent. Afr. Rep.", TD = "Chad",
  DJ = "Djibouti",      KM = "Comoros",    MU = "Mauritius",
  SC = "Seychelles",    GM = "Gambia",     CV = "Cabo Verde",
  GQ = "Eq. Guinea",    SS = "South Sudan",LY = "Libya",
  LS = "Lesotho",       SZ = "Eswatini",   "NA" = "Namibia",
  ST = "Sao Tome & Pr.",MR = "Mauritania", GW = "Guinea-Bissau",
  # Major non-African partners (for completeness in three-field plot)
  GB = "United Kingdom",US = "United States", CH = "Switzerland",
  FR = "France",        DE = "Germany",    SE = "Sweden",
  NL = "Netherlands",   BE = "Belgium",    AU = "Australia",
  CA = "Canada",        IT = "Italy",      NO = "Norway",
  JP = "Japan",         IN = "India",      BR = "Brazil",
  CN = "China"
)

# Take only the FIRST country code per record → convert to full name
first_country <- function(cell) {
  if (is.na(cell) || nchar(trimws(cell)) == 0) return(NA_character_)
  first_code <- trimws(strsplit(cell, ";", fixed = TRUE)[[1]])[1]
  name <- ISO2[first_code]
  if (is.na(name)) return(NA_character_)
  name
}

cat("Converting first ISO-2 code to country name ...\n")
country_data[, AU_CO := vapply(countries_raw, first_country, character(1))]

n_mapped <- sum(!is.na(country_data$AU_CO))
cat(sprintf("  Mapped: %s / %s records (%.1f%%)\n",
            format(n_mapped, big.mark = ","),
            format(nrow(country_data), big.mark = ","),
            100 * n_mapped / nrow(country_data)))

# ── 4. Join AU_CO into M via UT = EID ─────────────────────────────────────────
cat("Joining AU_CO into M ...\n")
co_map  <- setNames(country_data$AU_CO, country_data$EID)
M$AU_CO <- co_map[M$UT]

n_with_co <- sum(!is.na(M$AU_CO) & nchar(trimws(M$AU_CO)) > 0)
cat(sprintf("  Records with AU_CO: %s / %s (%.1f%%)\n",
            format(n_with_co, big.mark = ","),
            format(nrow(M), big.mark = ","),
            100 * n_with_co / nrow(M)))

# ── 5. Remove geographic keywords from DE ────────────────────────────────────
cat("Filtering geographic keywords from DE ...\n")

GEO_TERMS <- tolower(c(
  "africa", "south africa", "nigeria", "ethiopia", "kenya", "ghana",
  "uganda", "tanzania", "egypt", "morocco", "algeria", "tunisia",
  "sub-saharan africa", "sub saharan africa",
  "west africa", "east africa", "north africa", "southern africa",
  "developing countries", "developing country",
  "cameroon", "senegal", "zimbabwe", "zambia", "rwanda", "malawi",
  "botswana", "mozambique", "sudan", "mali", "burkina faso", "benin",
  "togo", "guinea", "angola", "niger", "sierra leone", "liberia",
  "somalia", "eritrea", "burundi", "cote d'ivoire", "madagascar",
  "gabon", "chad", "djibouti", "comoros", "mauritius", "seychelles",
  "gambia", "cabo verde", "south sudan", "libya", "lesotho", "eswatini",
  "namibia", "low income country", "middle income country",
  "low-income country", "middle-income country",
  "developed country", "developed countries",
  "lmic", "lmics", "low- and middle-income countries",
  "low and middle income countries"
))

filter_geo <- function(kw_cell) {
  if (is.na(kw_cell) || nchar(trimws(kw_cell)) == 0) return(NA_character_)
  terms <- trimws(strsplit(kw_cell, ";", fixed = TRUE)[[1]])
  terms <- terms[nchar(terms) > 0]
  terms <- terms[!tolower(terms) %in% GEO_TERMS]
  if (length(terms) == 0) return(NA_character_)
  paste(terms, collapse = ";")
}

M$DE <- vapply(M$DE, filter_geo, character(1))

n_de <- sum(!is.na(M$DE) & nchar(trimws(M$DE)) > 0)
cat(sprintf("  Records with DE after geo-filter: %s\n",
            format(n_de, big.mark = ",")))

# ── 6. Three-field plot ───────────────────────────────────────────────────────
cat("Building three-field plot (Countries -> Keywords -> Journals) ...\n")

# Verify all three fields have data
cat(sprintf("  AU_CO non-NA: %s\n", format(sum(!is.na(M$AU_CO)), big.mark=",")))
cat(sprintf("  DE    non-NA: %s\n", format(sum(!is.na(M$DE)),    big.mark=",")))
cat(sprintf("  SO    non-NA: %s\n", format(sum(!is.na(M$SO)),    big.mark=",")))

f8 <- threeFieldsPlot(
  M,
  fields = c("AU_CO", "DE", "SO"),
  n      = c(15L, 15L, 15L)
)

cat("  Three-field plot built.\n")

# ── 7. Save HTML ──────────────────────────────────────────────────────────────
cat("Saving figures/F8_three_field.html ...\n")
dir.create("figures", showWarnings = FALSE)
html_out <- "figures/F8_three_field.html"

saveWidget(
  widget        = f8,
  file          = normalizePath(html_out, mustWork = FALSE),
  selfcontained = TRUE
)
html_size <- file.info(html_out)$size
cat(sprintf("  Saved HTML: %.1f MB\n", html_size / 1048576))

# ── 8. Save static PNG via webshot2 ──────────────────────────────────────────
cat("Saving figures/F8_three_field_static.png ...\n")
png_out       <- "figures/F8_three_field_static.png"
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
      url    = normalizePath(html_out, mustWork = FALSE),
      file   = png_out,
      vwidth = 1600L,
      vheight = 1000L,
      zoom   = 2L,
      delay  = 5
    )
    file.exists(png_out) && file.info(png_out)$size > 10000L
  }, error = function(e) {
    cat(sprintf("  webshot2 error: %s\n", conditionMessage(e)))
    FALSE
  })
  if (isTRUE(webshot_ok)) {
    static_method <- "webshot2"
    cat("  webshot2 succeeded.\n")
  } else {
    cat("  webshot2 failed — falling back to png() device.\n")
  }
}

if (static_method == "none") {
  tryCatch({
    png(png_out, width = 4800L, height = 3000L, res = 300L, bg = "white")
    print(f8)
    dev.off()
    static_method <- "png() device"
    cat("  png() device fallback succeeded.\n")
  }, error = function(e) {
    if (dev.cur() > 1L) dev.off()
    cat(sprintf("  png() device failed: %s\n", conditionMessage(e)))
    static_method <<- "FAILED"
  })
}

png_size <- if (file.exists(png_out)) file.info(png_out)$size else 0L

# ── 9. Report ─────────────────────────────────────────────────────────────────
cat("\n")
cat("=============================================================\n")
cat(" FIGURE F8 — THREE-FIELD PLOT REPORT\n")
cat("=============================================================\n")

cat(sprintf("  Records with AU_CO : %s / %s (%.1f%%)\n",
            format(n_with_co, big.mark = ","),
            format(nrow(M),   big.mark = ","),
            100 * n_with_co / nrow(M)))
cat("\n")

# Top 15 countries
all_co   <- unlist(strsplit(paste(na.omit(M$AU_CO), collapse = ";"), ";"))
all_co   <- trimws(all_co[nchar(trimws(all_co)) > 0])
top_co   <- sort(table(all_co), decreasing = TRUE)[seq_len(min(15, length(table(all_co))))]
cat("  Top 15 countries (AU_CO — first-author country):\n")
for (i in seq_along(top_co))
  cat(sprintf("    %2d. %-30s %s\n", i, names(top_co)[i],
              format(as.integer(top_co[i]), big.mark = ",")))
cat("\n")

# Top 15 keywords
all_kw <- unlist(strsplit(paste(na.omit(M$DE), collapse = ";"), ";"))
all_kw <- trimws(all_kw[nchar(trimws(all_kw)) > 0])
top_kw <- sort(table(all_kw), decreasing = TRUE)[seq_len(min(15, length(table(all_kw))))]
cat("  Top 15 keywords (DE after geo-filter):\n")
for (i in seq_along(top_kw))
  cat(sprintf("    %2d. %-40s %s\n", i, names(top_kw)[i],
              format(as.integer(top_kw[i]), big.mark = ",")))
cat("\n")

# Top 15 journals
all_so <- trimws(M$SO[!is.na(M$SO) & nchar(trimws(M$SO)) > 0])
top_so <- sort(table(all_so), decreasing = TRUE)[seq_len(min(15, length(table(all_so))))]
cat("  Top 15 journals (SO):\n")
for (i in seq_along(top_so))
  cat(sprintf("    %2d. %-50s %s\n", i, substr(names(top_so)[i], 1, 50),
              format(as.integer(top_so[i]), big.mark = ",")))
cat("\n")

cat(sprintf("  Three fields confirmed : AU_CO=%s  DE=%s  SO=%s\n",
            "AU_CO" %in% names(M), "DE" %in% names(M), "SO" %in% names(M)))
cat(sprintf("  Static PNG method      : %s\n", static_method))
cat(sprintf("  HTML size              : %.1f MB\n", html_size / 1048576))
cat(sprintf("  PNG size               : %.1f MB\n", png_size  / 1048576))
cat("  HTML: figures/F8_three_field.html\n")
cat("  PNG : figures/F8_three_field_static.png\n")
cat(sprintf("  Total time             : %.1f s\n",
            (proc.time() - t0)["elapsed"]))
cat("=============================================================\n")
cat(" STAGE 5C COMPLETE\n")
cat("=============================================================\n")
