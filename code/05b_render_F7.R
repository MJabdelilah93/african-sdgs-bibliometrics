# =============================================================================
# Stage 05b — render-only production export of manuscript Figure 7
# Input : figures/F7_nodes_data.csv (validated thematicEvolution Nodes; read-only)
# Output: figures/F7_thematic_evolution.png (600 dpi) and figures/F7_thematic_evolution.svg
#         provenance/v2/stage5b_F7_render.json; F7 rows of provenance/v2/stage5_thematic_manifest.csv
# Does NOT run thematicEvolution or read the corpus. The node and edge CSVs must
# match the Stage 05 manifest before and after rendering. Rendering:
# code/utils/f7_bubble_plot.R (also used by code/05b_thematic_evolution_F7.R).
# Run from the repository root:  Rscript code/05b_render_F7.R
# =============================================================================
source("code/utils/stage5_guard.R")
s5_require(c("ggplot2", "svglite", "scales", "openssl", "jsonlite"))
suppressPackageStartupMessages(library(ggplot2))
source("code/utils/f7_bubble_plot.R")
if (paste(R.version$major, R.version$minor, sep = ".") != S5_EXPECTED_R) stop("R version differs from the pinned environment")

MAN_PATH <- "provenance/v2/stage5_thematic_manifest.csv"
DATA <- c("figures/F7_nodes_data.csv", "figures/F7_edges_data.csv")
man <- utils::read.csv(MAN_PATH, stringsAsFactors = FALSE, colClasses = "character")
check_data <- function(when) {
  for (f in DATA) {
    exp <- man$sha256[man$path == f]
    got <- s5_sha(f)
    if (length(exp) != 1 || got != exp) stop(f, " does not match the Stage 05 manifest (", when, ")")
    cat(sprintf("  [PASS] %s unchanged (%s) %s\n", f, when, got))
  }
}
check_data("before")

nodes_df <- utils::read.csv("figures/F7_nodes_data.csv", encoding = "UTF-8", stringsAsFactors = FALSE)
edges_df <- utils::read.csv("figures/F7_edges_data.csv", encoding = "UTF-8", stringsAsFactors = FALSE)
if (nrow(nodes_df) != 14 || nrow(edges_df) != 11) stop("Unexpected node/edge count")

p <- f7_bubble_plot(nodes_df)
PNG <- "figures/F7_thematic_evolution.png"
SVG <- "figures/F7_thematic_evolution.svg"
f7_save(p, s5_out(PNG), s5_out(SVG))
run <- s5_promote(list(outputs = character(0)))
check_data("after")

rec <- list(
  stage = "05b render-only production export (manuscript Figure 7)",
  rendered = format(Sys.time(), "%Y-%m-%dT%H:%M:%S"),
  git_head = s5_git("rev-parse", "HEAD"),
  r_version = R.version.string,
  ggplot2 = as.character(utils::packageVersion("ggplot2")),
  svglite = as.character(utils::packageVersion("svglite")),
  input = "figures/F7_nodes_data.csv (thematicEvolution Nodes; not recomputed)",
  data_sha256 = as.list(setNames(vapply(DATA, s5_sha, character(1)), DATA)),
  nodes = nrow(nodes_df), edges = nrow(edges_df),
  themes_per_period = lapply(split(nodes_df$name, nodes_df$period), as.character),
  settings = c("no internal title", "canvas 180 x 120 mm", "theme labels 10.5 pt; period labels 11.5 pt",
               "bubble size range c(3, 14) scaled by 0.6 (3:14 ratio and freq-to-area mapping)",
               "labels dark grey, left-aligned 1.2 mm beyond each bubble edge", "reduced margins and axis expansion",
               "PNG 600 dpi (4251 x 2834 px) and SVG (svglite)", "period colours (default ggplot2 hue)", "row order as stored"),
  data_note = "node and edge data written by 05b_thematic_evolution_F7.R",
  outputs = as.list(run$outputs))
jsonlite::write_json(rec, "provenance/v2/stage5b_F7_render.json", auto_unbox = TRUE, pretty = TRUE, digits = NA)

upsert <- function(m, role, path, notes = "") {
  row <- data.frame(role = role, path = path, sha256 = s5_sha(path), size_bytes = as.character(file.info(path)$size),
                    row_count = "", notes = notes, stringsAsFactors = FALSE)
  i <- which(m$path == path)
  if (length(i)) {
    row$role <- m$role[i]; row$row_count <- m$row_count[i]
    if (!nzchar(notes)) row$notes <- m$notes[i]        # keep existing notes unless replaced
    m[i, ] <- row
  } else m <- rbind(m, row)
  m
}
man <- upsert(man, "script", "code/05b_thematic_evolution_F7.R")
man <- upsert(man, "script", "code/utils/f7_bubble_plot.R", "F7 rendering/export only (shared)")
man <- upsert(man, "script", "code/05b_render_F7.R", "F7 render-only production export from validated Nodes")
man$notes[man$path == PNG] <- "bubble chart (Approach B); production render"
man <- upsert(man, "output_F7", PNG, "bubble chart (Approach B); production render")
man <- upsert(man, "output_F7", SVG, "vector version of F7 (svglite)")
man <- upsert(man, "run_record", "provenance/v2/stage5b_F7_render.json", "F7 render-only run record")
con <- file(MAN_PATH, "wb")                     # binary: keep LF line endings
utils::write.csv(man, con, row.names = FALSE, quote = FALSE, eol = "\n")
close(con)
cat("  Manifest updated: ", MAN_PATH, "\n  RENDER : PASS\n")
