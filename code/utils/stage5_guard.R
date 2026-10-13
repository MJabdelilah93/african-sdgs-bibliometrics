# =============================================================================
# Stage 05 shared guard — environment/input validation, safe outputs and
# run provenance for the thematic scripts (05a, 05b). No scientific logic here.
# Sourced from the project root. No package installation, no network.
# =============================================================================

S5_EXPECTED_R            <- "4.4.3"   # pinned environment (provenance/software_environment.txt)
S5_EXPECTED_BIBLIOMETRIX <- "5.4.0"
S5_INPUT    <- "data/processed/bibliometrix_input.csv"
S5_MANIFEST <- "provenance/v2/stage4_performance_manifest.csv"
S5_DOCTYPE_LABELS <- c(ar = "Article", re = "Review")   # same map as Stage 01b

# Plain-character SHA-256 of a file (openssl hash objects keep a class that jsonlite cannot serialise).
s5_sha <- function(path) paste(as.character(openssl::sha256(file(path))), collapse = "")

s5_require <- function(pkgs) {
  missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing)) stop("Required package(s) not installed (no automatic installation): ",
                            paste(missing, collapse = ", "))
}

s5_git <- function(...) {
  out <- tryCatch(system2("git", c(...), stdout = TRUE, stderr = FALSE), error = function(e) NA_character_)
  if (length(out) == 0) "" else paste(out, collapse = "\n")
}

s5_start <- function(stage) {
  if (!file.exists("config.yaml")) stop("Run from the project root.")
  s5_require(c("openssl", "yaml", "jsonlite"))
  r_ver <- paste(R.version$major, R.version$minor, sep = ".")
  b_ver <- as.character(utils::packageVersion("bibliometrix"))
  if (r_ver != S5_EXPECTED_R) stop("R ", r_ver, " != frozen ", S5_EXPECTED_R)
  if (b_ver != S5_EXPECTED_BIBLIOMETRIX) stop("bibliometrix ", b_ver, " != frozen ", S5_EXPECTED_BIBLIOMETRIX)
  head <- s5_git("rev-parse", "HEAD")
  dirty <- nzchar(s5_git("status", "--porcelain", "--untracked-files=no"))
  cat("=============================================================\n")
  cat(sprintf(" STAGE %s — started %s\n", stage, format(Sys.time(), "%Y-%m-%d %H:%M:%S")))
  cat("=============================================================\n")
  cat(sprintf("  Git HEAD      : %s (tracked changes: %s)\n", head, dirty))
  cat(sprintf("  Rscript       : %s\n", file.path(R.home("bin"), "Rscript.exe")))
  cat(sprintf("  R             : %s\n", R.version.string))
  cat(sprintf("  bibliometrix  : %s\n", b_ver))
  cat(sprintf("  .libPaths()   : %s\n", paste(.libPaths(), collapse = " | ")))
  man <- utils::read.csv(S5_MANIFEST, stringsAsFactors = FALSE, colClasses = "character")
  exp <- man[man$role == "output_bibliometrix_input", ]
  if (nrow(exp) != 1) stop("bibliometrix_input entry not found in ", S5_MANIFEST)
  sha <- s5_sha(S5_INPUT)
  cat(sprintf("  Input         : %s\n  Input SHA-256 : %s\n", S5_INPUT, sha))
  if (sha != exp$sha256) stop("Input SHA-256 does not match the Stage 04 manifest (", exp$sha256, ")")
  list(stage = stage, started = format(Sys.time(), "%Y-%m-%dT%H:%M:%S"), git_head = head,
       git_tracked_changes = dirty, r_version = R.version.string, rscript = file.path(R.home("bin"), "Rscript.exe"),
       bibliometrix = b_ver, lib_paths = .libPaths(), input = S5_INPUT, input_sha256 = sha,
       expected_rows = as.integer(exp$row_count), outputs = character(0))
}

s5_check_corpus <- function(run, M) {
  cfg <- yaml::read_yaml("config.yaml")$corpus
  allowed <- unname(S5_DOCTYPE_LABELS[unlist(cfg$doc_types)])
  py <- suppressWarnings(as.integer(M$PY))
  checks <- c(
    rows_equal_manifest  = nrow(M) == run$expected_rows,
    ut_unique            = !anyDuplicated(M$UT),
    ut_nonblank          = all(!is.na(M$UT) & nzchar(M$UT)),
    py_numeric           = !anyNA(py),
    py_min_is_year_min   = min(py) == cfg$year_min,
    py_max_is_year_max   = max(py) == cfg$year_max,
    doctype_article_review = all(M$DT %in% allowed)
  )
  for (k in names(checks)) cat(sprintf("  [%s] %s\n", if (checks[[k]]) "PASS" else "FAIL", k))
  if (!all(checks)) stop("Input corpus validation failed.")
  run$input_checks <- as.list(checks)
  run$input_rows <- nrow(M); run$py_range <- range(py); run$doctypes <- as.list(table(M$DT))
  run
}

.s5 <- new.env()
.s5$pending <- character(0)

# Register a final output path; returns the temporary path to write instead.
s5_out <- function(path) {
  .s5$pending <- unique(c(.s5$pending, path))
  paste0(path, ".tmp")
}

# Promote every registered .tmp output only after the whole analysis succeeded.
s5_promote <- function(run) {
  for (p in .s5$pending) {
    tmp <- paste0(p, ".tmp")
    if (!file.exists(tmp) || file.info(tmp)$size == 0) stop("Temporary output missing/empty: ", tmp)
  }
  for (p in .s5$pending) {
    if (file.exists(p)) file.remove(p)
    if (!file.rename(paste0(p, ".tmp"), p)) stop("Could not promote ", p)
    cat(sprintf("  Promoted : %s\n", p))
  }
  run$outputs <- vapply(.s5$pending, function(p) s5_sha(p), character(1))
  run
}

s5_finish <- function(run, record_path) {
  if (file.exists(S5_INPUT) && s5_sha(S5_INPUT) != run$input_sha256)
    stop("Input changed during the run.")
  run$finished <- format(Sys.time(), "%Y-%m-%dT%H:%M:%S")
  run$session_info <- utils::capture.output(utils::sessionInfo())
  run$outputs <- as.list(run$outputs)
  dir.create(dirname(record_path), showWarnings = FALSE, recursive = TRUE)
  jsonlite::write_json(run, record_path, auto_unbox = TRUE, pretty = TRUE, digits = NA)
  cat(sprintf("  Run record : %s\n", record_path))
  for (p in names(run$outputs)) cat(sprintf("  %-55s %s\n", p, run$outputs[[p]]))
  cat("  VALIDATION : PASS\n")
}

# Flatten list columns so bibliometrix data frames can be written as CSV.
s5_flat <- function(df) {
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  for (k in names(df)) if (is.list(df[[k]])) df[[k]] <- vapply(df[[k]], function(x) paste(x, collapse = ";"), character(1))
  df
}
