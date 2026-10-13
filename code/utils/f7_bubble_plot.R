# =============================================================================
# Figure F7 (manuscript Figure 7) — bubble-chart rendering and export only.
# Shared by code/05b_thematic_evolution_F7.R (Approach B fallback) and the
# render-only script code/05b_render_F7.R. No scientific logic here: the input is
# the thematicEvolution Nodes table (figures/F7_nodes_data.csv).
#
# Encoding: x = period, one row per node in stored order, colour = period group
# (default ggplot2 hue palette), bubble area from freq via scale_size_continuous
# with a 3:14 size ratio, alpha 0.70.
# Production layout:
#   - no internal title (the figure caption carries it);
#   - 180 x 120 mm canvas with labels at 10.5 pt and period labels at 11.5 pt
#     (about 10 pt when placed at 170 mm text width);
#   - bubble size range scaled to the canvas, ratio 3:14;
#   - labels left-aligned just beyond each bubble's edge;
#   - tight margins and axis expansion;
#   - PNG at 600 dpi plus SVG (svglite).
# =============================================================================

F7_WIDTH_MM  <- 180
F7_HEIGHT_MM <- 120
F7_SIZE_RANGE <- c(3, 14) * 0.6        # size ratio 3:14, uniformly scaled
F7_LABEL_PT  <- 10.5
F7_PERIOD_PT <- 11.5
F7_X_EXPAND  <- c(0.30, 0.95)          # discrete-axis expansion (left, right), in period units
F7_MARGIN_MM <- c(2, 2, 1, 2)          # top, right, bottom, left

f7_bubble_plot <- function(nodes_df) {
  slice_labels <- c("1" = "2015–2018", "2" = "2019–2022", "3" = "2023–2025")
  bdf <- nodes_df
  bdf$label  <- trimws(gsub("--\\d{4}-\\d{4}$", "", bdf$label))
  bdf$period <- factor(bdf$period, levels = unname(slice_labels))
  # Rendered bubble diameter (mm) as ggplot2 draws it: scale_size_continuous
  # (area palette) on freq, shape 19 with the default stroke of 0.5.
  sz <- scales::rescale(sqrt(scales::rescale(bdf$freq)), F7_SIZE_RANGE, c(0, 1))
  diam_mm <- (sz * ggplot2::.pt + 0.5 * ggplot2::.stroke / 2) * 25.4 / 72.27
  panel_w_mm <- F7_WIDTH_MM - F7_MARGIN_MM[2] - F7_MARGIN_MM[4]
  mm_per_unit <- panel_w_mm / (2 + sum(F7_X_EXPAND))
  nudge <- (diam_mm / 2 + 1.2) / mm_per_unit      # label starts 1.2 mm beyond the bubble edge
  ggplot(bdf,
         aes(x      = period,
             y      = factor(seq_along(label)),
             size   = freq,
             colour = factor(group))) +
    geom_point(alpha = 0.70) +
    geom_text(aes(label = label), hjust = 0, size = F7_LABEL_PT / .pt, colour = "grey10",
              position = position_nudge(x = nudge)) +
    scale_size_continuous(range = F7_SIZE_RANGE) +
    scale_x_discrete(expand = expansion(add = F7_X_EXPAND)) +
    scale_y_discrete(expand = expansion(add = 0.6)) +
    theme_minimal(base_size = F7_PERIOD_PT) +
    theme(legend.position    = "none",
          panel.grid.major.x = element_blank(),
          axis.text.y        = element_blank(),
          axis.ticks.y       = element_blank(),
          axis.text.x        = element_text(size = F7_PERIOD_PT, colour = "grey10",
                                            margin = margin(t = 1.5, unit = "mm")),
          plot.margin        = margin(F7_MARGIN_MM[1], F7_MARGIN_MM[2], F7_MARGIN_MM[3],
                                      F7_MARGIN_MM[4], unit = "mm"),
          plot.background    = element_rect(fill = "white", colour = NA)) +
    labs(x = NULL, y = NULL)
}

f7_save <- function(p, png_path, svg_path) {
  png(png_path, width = F7_WIDTH_MM, height = F7_HEIGHT_MM, units = "mm", res = 600, bg = "white")
  print(p)
  dev.off()
  svglite::svglite(svg_path, width = F7_WIDTH_MM / 25.4, height = F7_HEIGHT_MM / 25.4, bg = "white")
  print(p)
  dev.off()
  invisible(c(png_path, svg_path))
}
