# =============================================================================
# Accidents and Union Branches: REGION (RD) LEVEL ANALYSIS
# =============================================================================
# Unit: Registration District (RD)
# DV: has_union = 1 if region has at least one union branch
# IV: has_accident = 1 if region had at least one accident
# Q: If a region had an accident, is it more likely to have a union branch?
#
# Controls: log(area+1), log(stations+1), [optional] log(factories+1)
# Fixed effects: County (R_CTY) or Division (R_DIV)
#
# Usage: source("Accidents_Unions_Regression_RD_Level.R")
# =============================================================================

library(tidyverse)
library(sf)
library(fixest)
library(modelsummary)

base_path <- "C:/Users/Keitaro Ninomiya/Box/Research Notes (keitaro2@illinois.edu)/RailwayUnions/Processed_Data"
rd_shp   <- file.path(base_path, "7. 1851 England and Wales Census Registration Districts/1851EngWalesRegistrationDistrict.shp")

# Optional: census CSV with rd_name, population
census_csv <- NULL

# Optional: factory/industry CSV with rd_name and factory count
# Expected columns: rd_name, and one of factory_count, n_factories, factories
factory_csv <- NULL  # e.g. file.path(base_path, "factories_by_rd1851.csv")

# Railway line fixed effects: compare RDs on the SAME line (accident randomness is on the line)
# Build rd_line_mapping.csv first: python build_rd_line_mapping.py
# Requires: 1861 Rail Lines shapefile from UK Data Service https://reshare.ukdataservice.ac.uk/852992/
rd_line_csv <- file.path(base_path, "rd_line_mapping.csv")

# -----------------------------------------------------------------------------
# 1. Load RD-level data
# -----------------------------------------------------------------------------
rd_agg <- read_csv(file.path(base_path, "rd1851_aggregates.csv"), show_col_types = FALSE) %>%
  mutate(
    rd_name = as.character(rd_name),
    has_accident = as.integer(accident_count > 0),
    has_union = as.integer(branch_count > 0),
    log_stations = log(pmax(station_count, 0) + 1)
  )

# RD hierarchy (county, division) from shapefile
rds <- st_read(rd_shp, quiet = TRUE) %>%
  st_drop_geometry() %>%
  select(CEN1, R_CTY, R_DIV) %>%
  distinct() %>%
  mutate(rd_name = as.character(CEN1))

# Population: area proxy or census
if (!is.null(census_csv) && file.exists(census_csv)) {
  pop_df <- read_csv(census_csv, show_col_types = FALSE) %>%
    mutate(rd_name = as.character(rd_name), log_pop = log(pmax(population, 1)))
} else {
  rds_geo <- st_read(rd_shp, quiet = TRUE) %>% st_transform(27700)
  rds_geo$area_km2 <- st_area(rds_geo) %>% as.numeric() / 1e6
  pop_df <- rds_geo %>%
    st_drop_geometry() %>%
    group_by(CEN1) %>%
    summarise(area_km2 = sum(area_km2), .groups = "drop") %>%
    mutate(rd_name = as.character(CEN1), log_pop = log(pmax(area_km2, 0.1) + 1))
}

# Factory count by RD (industry structure control)
if (!is.null(factory_csv) && file.exists(factory_csv)) {
  factory_df <- read_csv(factory_csv, show_col_types = FALSE) %>%
    mutate(rd_name = as.character(rd_name))
  fc_col <- intersect(c("factory_count", "n_factories", "factories"), names(factory_df))[1]
  if (is.na(fc_col)) stop("Factory CSV must have column: factory_count, n_factories, or factories")
  factory_df <- factory_df %>%
    mutate(log_factories = log(pmax(!!sym(fc_col), 0) + 1)) %>%
    select(rd_name, log_factories)
  message("Factory control: loaded ", nrow(factory_df), " RDs from ", basename(factory_csv))
} else {
  factory_df <- NULL
}

# Railway line mapping (for line FE: identify RDs on same line)
if (!is.null(rd_line_csv) && file.exists(rd_line_csv)) {
  rd_line <- read_csv(rd_line_csv, show_col_types = FALSE) %>%
    mutate(rd_name = as.character(rd_name), line_id = as.character(line_id))
  message("Line FE: loaded ", nrow(rd_line), " RDs from rd_line_mapping.csv")
} else {
  rd_line <- NULL
}

df <- rd_agg %>%
  left_join(select(rds, rd_name, R_CTY, R_DIV), by = "rd_name") %>%
  left_join(select(pop_df, rd_name, log_pop), by = "rd_name") %>%
  { if (!is.null(factory_df)) left_join(., factory_df, by = "rd_name") else . } %>%
  { if (!is.null(rd_line)) left_join(., rd_line, by = "rd_name") else . } %>%
  filter(!is.na(log_pop), !is.na(R_CTY))

if (!is.null(factory_df)) {
  df <- df %>% filter(!is.na(log_factories))
  message("RDs with factory data: ", nrow(df))
}

# Drop RDs with no variation in outcome (all union or no union within FE group)
message("RDs (with rail stations): ", nrow(df))
message("RDs with accident: ", sum(df$has_accident), " (", round(100 * mean(df$has_accident), 1), "%)")
message("RDs with union branch: ", sum(df$has_union), " (", round(100 * mean(df$has_union), 1), "%)")
message("Counties: ", n_distinct(df$R_CTY), " | Divisions: ", n_distinct(df$R_DIV))

# -----------------------------------------------------------------------------
# 2. Run regressions (LPM at RD level) — 4 columns: intensive by FE, extensive
# -----------------------------------------------------------------------------
rhs_ext <- if (!is.null(factory_df)) "has_accident + log_pop + log_stations + log_factories" else "has_accident + log_pop + log_stations"
rhs_int <- if (!is.null(factory_df)) "accident_count + log_pop + log_stations + log_factories" else "accident_count + log_pop + log_stations"

df_line <- NULL
if (!is.null(rd_line)) {
  df_line <- df %>% filter(!is.na(line_id))
  if (nrow(df_line) == 0 || n_distinct(df_line$line_id) <= 1) df_line <- NULL
}
if (!is.null(df_line)) message("Line FE sample: ", nrow(df_line), " RDs, ", n_distinct(df_line$line_id), " lines")

# Col 1: Intensive (No. accidents), Line FE
# Col 2: Intensive, Line FE + Division FE
# Col 3: Intensive, Line FE + County FE
# Col 4: Extensive (has accident), Line FE
mod_1 <- mod_2 <- mod_3 <- mod_4 <- NULL
if (!is.null(df_line)) {
  mod_1 <- feols(as.formula(paste0("has_union ~ ", rhs_int, " | line_id")), data = df_line, vcov = "HC1")
  mod_2 <- feols(as.formula(paste0("has_union ~ ", rhs_int, " | line_id + R_DIV")), data = df_line, vcov = "HC1")
  mod_3 <- feols(as.formula(paste0("has_union ~ ", rhs_int, " | line_id + R_CTY")), data = df_line, vcov = "HC1")
  mod_4 <- feols(as.formula(paste0("has_union ~ ", rhs_ext, " | line_id")), data = df_line, vcov = "HC1")
}

# -----------------------------------------------------------------------------
# 3. Table (4 columns)
# -----------------------------------------------------------------------------
notes_vec <- c(
  "Unit: Registration District (1851). Sample: RDs with rail stations, assigned to railway line.",
  "DV: has_union = 1 if RD has union branch. Cols 1--3: intensive (No. accidents). Col 4: extensive (has accident).",
  if (!is.null(factory_df)) "Controls: log(area+1), log(stations+1), log(factories+1)." else "Controls: log(area+1), log(stations+1).",
  "All specifications include Line FE. Accident randomness is on the line.",
  "HC1 robust SE."
)

mod_list <- list(
  "(1) Line FE" = mod_1,
  "(2) Line + Division FE" = mod_2,
  "(3) Line + County FE" = mod_3,
  "(4) Extensive (Line FE)" = mod_4
)
mod_list <- mod_list[!sapply(mod_list, is.null)]

if (length(mod_list) > 0) {
  modelsummary(
    mod_list,
    coef_map = c("(Intercept)" = "Constant", "has_accident" = "Has accident", "accident_count" = "No. accidents",
                 "log_pop" = "Log(area+1)", "log_stations" = "Log(stations+1)", "log_factories" = "Log(factories+1)"),
    stars = c("*" = 0.1, "**" = 0.05, "***" = 0.01),
    title = "Accidents and Union Branches",
    notes = notes_vec
  )
}

# Save results for LaTeX
res_rows <- list()
if (!is.null(mod_1)) res_rows[[1]] <- tibble(col = 1, fe = "Line", margin = "Intensive", beta = as.numeric(coef(mod_1)["accident_count"]), se = sqrt(vcov(mod_1)["accident_count", "accident_count"]))
if (!is.null(mod_2)) res_rows[[2]] <- tibble(col = 2, fe = "Line+Division", margin = "Intensive", beta = as.numeric(coef(mod_2)["accident_count"]), se = sqrt(vcov(mod_2)["accident_count", "accident_count"]))
if (!is.null(mod_3)) res_rows[[3]] <- tibble(col = 3, fe = "Line+County", margin = "Intensive", beta = as.numeric(coef(mod_3)["accident_count"]), se = sqrt(vcov(mod_3)["accident_count", "accident_count"]))
if (!is.null(mod_4)) res_rows[[4]] <- tibble(col = 4, fe = "Line", margin = "Extensive", beta = as.numeric(coef(mod_4)["has_accident"]), se = sqrt(vcov(mod_4)["has_accident", "has_accident"]))
res_rd <- bind_rows(res_rows)
if (nrow(res_rd) > 0) {
  write_csv(res_rd, file.path(base_path, "regression_RD_level.csv"))
  message("\nSaved: regression_RD_level.csv")
}
